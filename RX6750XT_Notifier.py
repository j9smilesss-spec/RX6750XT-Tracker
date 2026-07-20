"""
RX 6750 XT Price Tracker — Playwright Edition for GitHub Actions
================================================================
Uses a headless browser so stores can't block us as easily.
Falls back to API endpoints where available.
"""

import os
import re
import json
import time
import requests as req
from datetime import datetime
from bs4 import BeautifulSoup

# =========================
# SETTINGS
# =========================
MAX_PRICE = 315
GPU_FLOOR = 240  # filter out accessories

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "")
DATA_FILE = "prices.json"

PRODUCTS = {
    "Newegg":   "https://www.newegg.com/p/pl?d=RX+6750+XT",
    "Best Buy": "https://www.bestbuy.com/site/searchpage.jsp?st=rx+6750+xt",
    "B&H":      "https://www.bhphotovideo.com/c/search?q=RX%206750%20XT",
    "Walmart":  "https://www.walmart.com/search?q=RX+6750+XT",
    "eBay":     "https://www.ebay.com/sch/i.html?_nkw=RX+6750+XT",
}

# =========================
# PRICE MEMORY
# =========================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

old_prices = load_data()

# =========================
# DISCORD
# =========================
def send_discord(store, name, price, old_price, link):
    change = ""
    if old_price:
        diff = old_price - price
        if diff > 0:
            change = f"\n📉 Drop: ${diff:.2f}"

    embed = {
        "title": "🚨 RX 6750 XT DEAL ALERT",
        "color": 65280,
        "fields": [
            {"name": "🏪 Store", "value": store, "inline": False},
            {"name": "🎮 GPU",   "value": name,  "inline": False},
            {"name": "💰 Price", "value": f"${price:.2f}{change}", "inline": True},
            {"name": "🕒 Checked",
             "value": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
             "inline": True},
            {"name": "🔗 Link", "value": link},
        ],
    }
    payload = {"content": f"<@{DISCORD_USER_ID}>", "embeds": [embed]}

    try:
        r = req.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"  📬 Discord: {r.status_code}")
    except Exception as e:
        print(f"  ❌ Discord error: {e}")

# =========================
# HELPERS
# =========================
def extract_price(text):
    """Pull first XXX.XX from text → float or None."""
    if not text:
        return None
    m = re.search(r"[\d,]+\.\d{2}", str(text))
    if m:
        try:
            return float(m.group().replace(",", ""))
        except ValueError:
            pass
    return None

def is_gpu_price(val):
    return val is not None and GPU_FLOOR <= val <= MAX_PRICE

def report_products(store, products):
    if not products:
        print(f"  ❌ No RX 6750 XT deals found.\n")
        return

    best = {}
    for p in products:
        k = p["link"]
        if k not in best or (p["price"] and (best[k]["price"] is None or p["price"] < best[k]["price"])):
            best[k] = p

    for prod in best.values():
        name  = prod["title"]
        price = prod["price"]
        link  = prod["link"]
        key   = f"{store}|{name}"

        print(f"  🎮  {name}")
        print(f"  💰  ${price:.2f}" if price else "  💰  Price not found")
        print(f"  🔗  {link}")

        if price is None:
            print()
            continue

        previous = old_prices.get(key)

        if previous is not None and previous != price:
            print(f"  📬 Price changed! Alerting Discord")
            send_discord(store, name, price, previous, link)
        elif previous is None:
            print(f"  🆕 First time seen — alerting Discord")
            send_discord(store, name, price, None, link)
        else:
            print(f"     No change since last check")
        print()

        old_prices[key] = price

    save_data(old_prices)


# ================================================================
#  BROWSER MANAGER
# ================================================================
class Browser:
    def __init__(self):
        self.pw = None
        self.browser = None
        self.context = None

    def start(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self.context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        # Hide automation fingerprints
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            window.chrome = {runtime: {}};
        """)

    def stop(self):
        try:
            if self.browser: self.browser.close()
            if self.pw: self.pw.stop()
        except Exception:
            pass

    def new_page(self):
        return self.context.new_page()

    def fetch(self, url, wait_sel=None, extra_wait=2, timeout=25000):
        """Load a page, wait for rendering, return HTML."""
        page = self.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            # Dismiss cookie popups that block rendering
            self._dismiss_cookies(page)
            if wait_sel:
                try:
                    page.wait_for_selector(wait_sel, timeout=8000)
                except Exception:
                    pass
            time.sleep(extra_wait)
            return page.content()
        except Exception as e:
            print(f"  ⚠️  Page load error: {e}")
            return ""
        finally:
            page.close()

    def js(self, url, code, wait_sel=None, extra_wait=2, timeout=25000):
        """Load a page and run JS inside it — returns Python objects."""
        page = self.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            self._dismiss_cookies(page)
            if wait_sel:
                try:
                    page.wait_for_selector(wait_sel, timeout=8000)
                except Exception:
                    pass
            time.sleep(extra_wait)
            return page.evaluate(code)
        except Exception as e:
            print(f"  ⚠️  JS evaluate error: {e}")
            return []
        finally:
            page.close()

    @staticmethod
    def _dismiss_cookies(page):
        """Click common cookie-consent buttons so they don't block content."""
        selectors = [
            "button#onetrust-accept-btn-handler",
            "button[data-testid='cookie-consent-accept']",
            "button[data-testid='consent-accept']",
            "button.cc-accept",
            "button:has-text('Accept All')",
            "button:has-text('Accept all cookies')",
            "button:has-text('I Agree')",
            "#consent-banner button",
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.5)
                    return
            except Exception:
                pass

    def debug_save(self, store, html):
        fname = f"debug_{store}.html"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"  📄 Saved {fname} ({len(html)} chars)")


# ================================================================
#  NEWEGG
# ================================================================
def scrape_newegg(b: Browser):
    print("\n🔍 NEWEGG")
    url = PRODUCTS["Newegg"]

    # --- Method 1: Newegg search API (fast, might work from datacenter) ---
    print("  Trying API…")
    try:
        api_r = req.post(
            "https://www.newegg.com/api/common/search",
            json={"Keyword": "RX 6750 XT", "page": 1},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"
                ),
                "Referer": url,
                "Accept": "application/json",
            },
            timeout=15,
        )
        if api_r.status_code == 200:
            data = api_r.json()
            products = []
            results = []
            # Navigate the API response structure
            if isinstance(data, dict):
                results = (
                    data.get("SearchResults", {})
                    .get("ProductList", [])
                    or data.get("ProductList", [])
                    or data.get("results", [])
                    or data.get("Items", [])
                )
            elif isinstance(data, list):
                results = data

            for item in results:
                title = (
                    item.get("Title", "")
                    or item.get("title", "")
                    or item.get("ProductName", "")
                    or ""
                )
                if "6750" not in title.lower():
                    continue

                link = (
                    item.get("Link", "")
                    or item.get("link", "")
                    or item.get("ProductUrl", "")
                    or ""
                )
                if link and not link.startswith("http"):
                    link = "https://www.newegg.com" + link

                price = None
                for key in ["Price", "price", "SalePrice",
                             "FinalPrice", "CurrentPrice", "finalPrice"]:
                    val = item.get(key)
                    if val:
                        try:
                            price = float(val)
                            break
                        except (ValueError, TypeError):
                            pass

                if is_gpu_price(price):
                    products.append({"title": title, "price": price, "link": link})

            if products:
                print(f"  ✅ API returned {len(products)} product(s)")
                return products
            else:
                print("  API returned no 6750 XT products")
        else:
            print(f"  API status: {api_r.status_code}")
    except Exception as e:
        print(f"  API error: {e}")

    # --- Method 2: Playwright ---
    print("  Trying Playwright…")
    products = b.js(url, """
        (() => {
            const out = [];
            document.querySelectorAll('div.item-cell').forEach(cell => {
                const a = cell.querySelector('a.item-title');
                if (!a) return;
                const title = a.textContent.trim();
                if (!title.toLowerCase().includes('6750')) return;
                const link = a.href;
                let price = null;
                const pc = cell.querySelector('li.price-current');
                if (pc) {
                    const s = pc.querySelector('strong');
                    const sup = pc.querySelector('sup');
                    if (s && sup) {
                        price = parseFloat(
                            (s.textContent + sup.textContent).replace(/,/g, '')
                        );
                    }
                }
                if (price === null || isNaN(price)) {
                    const m = cell.textContent.match(/[$]?([\\d,]+\\.\\d{2})/);
                    if (m) price = parseFloat(m[1].replace(/,/g, ''));
                }
                out.push({title, price, link});
            });
            return out;
        })()
    """, wait_sel="div.item-cell")

    if not products:
        html = b.fetch(url, wait_sel="div.item-cell")
        b.debug_save("newegg", html)
        products = _parse_newegg_html(html)

    return products


def _parse_newegg_html(html):
    products = []
    soup = BeautifulSoup(html, "html.parser")

    # DOM parse
    for cell in soup.select("div.item-cell"):
        a = cell.select_one("a.item-title")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        if "6750" not in title.lower():
            continue
        link = a.get("href", "")
        if link.startswith("/"):
            link = "https://www.newegg.com" + link
        price = None
        pc = cell.select_one("li.price-current")
        if pc:
            strong = pc.find("strong")
            sup = pc.find("sup")
            if strong and sup:
                try:
                    price = float(
                        (strong.get_text(strip=True) + sup.get_text(strip=True)).replace(",", "")
                    )
                except ValueError:
                    pass
            if price is None:
                price = extract_price(pc.get_text())
        if price is None:
            price = extract_price(cell.get_text())
        products.append({"title": title, "price": price, "link": link})

    # Regex fallback on __INITIAL_STATE__
    if not products:
        m = re.search(r"window\.__INITIAL_STATE__\s*=\s*({.*?});", html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                items = []
                # Navigate possible structures
                sr = data.get("SearchResults", data.get("searchResults", {}))
                if isinstance(sr, dict):
                    items = sr.get("ProductList", sr.get("productList", []))
                elif isinstance(sr, list):
                    items = sr

                for item in items:
                    title = item.get("Title", item.get("title", ""))
                    if "6750" not in title.lower():
                        continue
                    link = item.get("Link", item.get("link", ""))
                    if link and link.startswith("/"):
                        link = "https://www.newegg.com" + link
                    price = None
                    for k in ["Price", "SalePrice", "FinalPrice", "price"]:
                        v = item.get(k)
                        if v:
                            try:
                                price = float(v)
                                break
                            except (ValueError, TypeError):
                                pass
                    products.append({"title": title, "price": price, "link": link})
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"  __INITIAL_STATE__ parse error: {e}")

    return products


# ================================================================
#  BEST BUY
# ================================================================
def scrape_bestbuy(b: Browser):
    print("\n🔍 BEST BUY")
    url = PRODUCTS["Best Buy"]

    products = b.js(url, """
        (() => {
            const out = [];
            document.querySelectorAll(
                'li.sku-item, [data-sku-id], div.shop-sku-list-item'
            ).forEach(item => {
                const a = item.querySelector(
                    'h4.sku-title a, a[data-testid="product-title"], ' +
                    'a.v-line-clamp-2'
                );
                if (!a) return;
                const title = a.textContent.trim();
                if (!title.toLowerCase().includes('6750')) return;
                const link = a.href;
                let price = null;
                const pe = item.querySelector(
                    'div.priceView-customer-price span, ' +
                    '[data-testid="customer-price"] span, ' +
                    '.pricing-price .sr-only, ' +
                    'div.priceView-hero-price span'
                );
                if (pe) {
                    const m = pe.textContent.match(/([\\d,]+\\.\\d{2})/);
                    if (m) price = parseFloat(m[1].replace(/,/g, ''));
                }
                if (price === null || isNaN(price)) {
                    const m2 = item.textContent.match(/[$]([\\d,]+\\.\\d{2})/);
                    if (m2) price = parseFloat(m2[1].replace(/,/g, ''));
                }
                out.push({title, price, link});
            });
            return out;
        })()
    """, wait_sel="li.sku-item, [data-sku-id]")

    if not products:
        html = b.fetch(url, wait_sel="li.sku-item")
        b.debug_save("bestbuy", html)
        products = _parse_bestbuy_html(html)

    return products


def _parse_bestbuy_html(html):
    products = []
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select("li.sku-item, [data-sku-id]"):
        a = item.select_one("h4.sku-title a, a[data-testid='product-title']")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        if "6750" not in title.lower():
            continue
        link = a.get("href", "")
        if link.startswith("/"):
            link = "https://www.bestbuy.com" + link
        price = None
        pe = item.select_one("div.priceView-customer-price span")
        if pe:
            price = extract_price(pe.get_text())
        if price is None:
            price = extract_price(item.get_text())
        products.append({"title": title, "price": price, "link": link})
    return products


# ================================================================
#  B&H PHOTO
# ================================================================
def scrape_bhphoto(b: Browser):
    print("\n🔍 B&H PHOTO")
    url = PRODUCTS["B&H"]

    products = b.js(url, """
        (() => {
            const out = [];
            const cards = document.querySelectorAll(
                '[data-selenium="productCard"], .product-card, ' +
                '.cx-item, .item[data-selenium]'
            );
            cards.forEach(card => {
                const titleEl = card.querySelector(
                    'a[data-selenium="itemHeadingLink"], ' +
                    'a[href*="/sp/"], .item-heading a, a[itemprop="url"]'
                );
                if (!titleEl) return;
                const title = titleEl.textContent.trim();
                if (!title.toLowerCase().includes('6750')) return;
                const link = titleEl.href;
                let price = null;
                const priceEl = card.querySelector(
                    '[data-selenium="uppedDecimalPrice"], ' +
                    '[data-selenium="pricingPrice"], ' +
                    '[itemprop="price"], .price, .cx-item-price'
                );
                if (priceEl) {
                    const m = priceEl.textContent.match(/([\\d,]+\\.\\d{2})/);
                    if (m) price = parseFloat(m[1].replace(/,/g, ''));
                }
                if (price === null || isNaN(price)) {
                    const m2 = card.textContent.match(/[$]([\\d,]+\\.\\d{2})/);
                    if (m2) price = parseFloat(m2[1].replace(/,/g, ''));
                }
                out.push({title, price, link});
            });
            return out;
        })()
    """, extra_wait=3)

    if not products:
        html = b.fetch(url, extra_wait=3)
        b.debug_save("bhphoto", html)
        products = _parse_bhphoto_html(html)

    return products


def _parse_bhphoto_html(html):
    products = []
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select('[data-selenium="productCard"], .product-card, .cx-item'):
        a = card.select_one('a[data-selenium="itemHeadingLink"], a[href*="/sp/"]')
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        if "6750" not in title.lower():
            continue
        link = a.get("href", "")
        if link.startswith("/"):
            link = "https://www.bhphotovideo.com" + link
        price = None
        pe = card.select_one('[data-selenium="uppedDecimalPrice"], [itemprop="price"]')
        if pe:
            price = extract_price(pe.get_text())
        if price is None:
            price = extract_price(card.get_text())
        products.append({"title": title, "price": price, "link": link})
    return products


# ================================================================
#  WALMART
# ================================================================
def scrape_walmart(b: Browser):
    print("\n🔍 WALMART")
    url = PRODUCTS["Walmart"]

    products = b.js(url, """
        (() => {
            const out = [];
            // Method 1: __NEXT_DATA__ JSON
            const nd = document.getElementById('__NEXT_DATA__');
            if (nd) {
                try {
                    const data = JSON.parse(nd.textContent);
                    const props = (data.props || {}).pageProps || {};
                    const sc = props.searchContent || {};
                    const items = (sc.itemStacks || [{}])[0].items
                                || props.products || [];
                    items.forEach(item => {
                        const name = item.name || item.title || '';
                        if (!name.toLowerCase().includes('6750')) return;
                        let link = item.canonicalUrl || item.productPageUrl || '';
                        if (link && !link.startsWith('http'))
                            link = 'https://www.walmart.com' + link;
                        const pm = item.priceMap || item.price || {};
                        let price = pm.price || pm.currentPrice || pm.salePrice || null;
                        if (price !== null) price = parseFloat(price);
                        out.push({title: name, price, link});
                    });
                } catch(e) {}
            }
            // Method 2: DOM scraping
            if (out.length === 0) {
                document.querySelectorAll(
                    '[data-item-id], [data-testid="item-card"], ' +
                    'div.mb0.ph0.pt0.pb0'
                ).forEach(el => {
                    const te = el.querySelector(
                        'span[data-automation-id="product-title"], ' +
                        '[data-testid="product-title"]'
                    );
                    if (!te) return;
                    const title = te.textContent.trim();
                    if (!title.toLowerCase().includes('6750')) return;
                    const le = el.querySelector('a[href*="/ip/"]');
                    const link = le ? le.href : '';
                    let price = null;
                    const pe = el.querySelector(
                        '[data-automation-id="product-price"], ' +
                        '[data-testid="price"], .lh-copy'
                    );
                    if (pe) {
                        const m = pe.textContent.match(/([\\d,]+\\.\\d{2})/);
                        if (m) price = parseFloat(m[1].replace(/,/g, ''));
                    }
                    out.push({title, price, link});
                });
            }
            return out;
        })()
    """, extra_wait=4)

    if not products:
        html = b.fetch(url, extra_wait=4)
        b.debug_save("walmart", html)
        products = _parse_walmart_html(html)

    return products


def _parse_walmart_html(html):
    products = []
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if m:
        try:
            data = json.loads(m.group(1))
            props = data.get("props", {}).get("pageProps", {})
            sc = props.get("searchContent", {})
            items = (sc.get("itemStacks", [{}])[0].get("items", [])
                     or props.get("products", []))
            for item in items:
                name = item.get("name", "") or item.get("title", "")
                if "6750" not in name.lower():
                    continue
                link = item.get("canonicalUrl", "") or item.get("productPageUrl", "")
                if link and not link.startswith("http"):
                    link = f"https://www.walmart.com{link}"
                pm = item.get("priceMap", {}) or item.get("price", {})
                price_val = pm.get("price") or pm.get("currentPrice") or pm.get("salePrice")
                try:
                    price = float(price_val)
                except (ValueError, TypeError):
                    price = None
                products.append({"title": name, "price": price, "link": link})
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    if not products:
        price_hits = set()
        for p_str in re.findall(r"\$([\d,]+\.\d{2})", html):
            try:
                val = float(p_str.replace(",", ""))
                if GPU_FLOOR <= val <= MAX_PRICE:
                    price_hits.add(val)
            except ValueError:
                pass
        for slug in re.findall(r'href="/ip/([^"]*6750[^"]*)"', html, re.I):
            products.append({
                "title": "RX 6750 XT",
                "price": min(price_hits) if price_hits else None,
                "link":  f"https://www.walmart.com/ip/{slug}",
            })

    return products


# ================================================================
#  EBAY
# ================================================================
def scrape_ebay(b: Browser):
    print("\n🔍 EBAY")
    url = PRODUCTS["eBay"]

    SKIP = ['cable','adapter','bracket','riser','power','cooler',
            'thermal','case','fan','holder','support','hdmi',
            'displayport','pcie','backplate','screw','nut']

    products = b.js(url, f"""
        (() => {{
            const skip = {json.dumps(SKIP)};
            const out = [];
            document.querySelectorAll('li.s-item').forEach(item => {{
                const te = item.querySelector('.s-item__title');
                if (!te) return;
                const title = te.textContent.trim();
                const tl = title.toLowerCase();
                if (!tl.includes('6750')) return;
                if (skip.some(w => tl.includes(w))) return;
                const le = item.querySelector('.s-item__link');
                const link = le ? le.href : '';
                let price = null;
                const pe = item.querySelector('.s-item__price');
                if (pe) {{
                    const m = pe.textContent.match(/([\\d,]+\\.\\d{{2}})/);
                    if (m) price = parseFloat(m[1].replace(/,/g, ''));
                }}
                out.push({{title, price, link}});
            }});
            return out;
        }})()
    """, wait_sel="li.s-item")

    if not products:
        html = b.fetch(url, wait_sel="li.s-item")
        b.debug_save("ebay", html)
        products = _parse_ebay_html(html)

    return products


def _parse_ebay_html(html):
    SKIP = ['cable','adapter','bracket','riser','power','cooler',
            'thermal','case','fan','holder','support','hdmi',
            'displayport','pcie','backplate','screw','nut']
    products = []
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select("li.s-item"):
        te = item.select_one(".s-item__title")
        if not te:
            continue
        title = te.get_text(" ", strip=True)
        tl = title.lower()
        if "6750" not in tl:
            continue
        if any(w in tl for w in SKIP):
            continue
        le = item.select_one(".s-item__link")
        link = le.get("href", "") if le else ""
        price = None
        pe = item.select_one(".s-item__price")
        if pe:
            price = extract_price(pe.get_text())
        if price is None:
            price = extract_price(item.get_text())
        products.append({"title": title, "price": price, "link": link})
    return products


# =========================
# MAIN
# =========================
if __name__ == "__main__":
    browser = Browser()
    print("Launching headless browser…")
    try:
        browser.start()
    except Exception as e:
        print(f"❌ Failed to start browser: {e}")
        print("Make sure Playwright is installed:")
        print("  pip install playwright")
        print("  playwright install --with-deps chromium")
        raise SystemExit(1)

    SCRAPERS = [
        ("Newegg",   scrape_newegg),
        ("Best Buy", scrape_bestbuy),
        ("B&H",      scrape_bhphoto),
        ("Walmart",  scrape_walmart),
        ("eBay",     scrape_ebay),
    ]

    try:
        for store, func in SCRAPERS:
            try:
                products = func(browser)
                report_products(store, products)
            except Exception as e:
                print(f"❌ {store} crashed: {e}\n")
            time.sleep(2)
    finally:
        browser.stop()

    print("✅ Done.")
