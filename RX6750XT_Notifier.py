"""
RX 6750 XT Price Tracker — Playwright Edition
================================================================
- Filters out Refurbished, Open Box, and Scalper listings silently.
- Fixes Best Buy crash by waiting for redirects to settle.
- Only alerts for NEW, IN STOCK items UNDER the max price threshold.
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
MAX_PRICE = 340
GPU_FLOOR = 240

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
# STEALTH JS
# =========================
STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    window.chrome = { runtime: {} };
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    Object.defineProperty(navigator, 'userAgent', {
        get: () => navigator.userAgent.replace('HeadlessChrome/', 'Chrome/')
    });
"""

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
def send_discord(store, name, price, old_price, link, is_restock=False):
    change = ""
    title = "🚨 RX 6750 XT DEAL ALERT"
    
    if is_restock:
        title = "🎉 RX 6750 XT BACK IN STOCK!"
        change = "\n📦 Was out of stock, now available!"
    elif old_price:
        diff = old_price - price
        if diff > 0:
            change = f"\n📉 Drop: ${diff:.2f}"
    else:
        change = "\n🆕 New in-stock item found!"

    embed = {
        "title": title,
        "color": 65280 if not is_restock else 16776960,
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
    if not text:
        return None
    m = re.search(r"[\d,]+\.\d{2}", str(text))
    if m:
        try:
            return float(m.group().replace(",", ""))
        except ValueError:
            pass
    return None

def report_products(store, products):
    if not products:
        print(f"  ❌ No RX 6750 XT deals found.\n")
        return 0

    best = {}
    skipped_oos = 0
    skipped_scalper = 0

    for p in products:
        key = f"{store}|{p['title']}"

        # Silently skip out-of-stock items, but track them for restock alerts
        if not p.get("in_stock", True):
            skipped_oos += 1
            old_prices[key] = {"price": p.get("price"), "in_stock": False}
            continue

        # Silently skip overpriced scalper items
        if p.get("price") is None or p["price"] > MAX_PRICE:
            skipped_scalper += 1
            old_prices[key] = {"price": p.get("price"), "in_stock": True}
            continue

        k = p["link"]
        if k not in best:
            best[k] = p
        elif p["price"] < best[k]["price"]:
            best[k] = p

    if skipped_oos > 0:
        print(f"  📦 Skipped {skipped_oos} out-of-stock items (tracking for restock).")
    if skipped_scalper > 0:
        print(f"  💸 Skipped {skipped_scalper} overpriced/scalper items.")

    alerts_sent = 0
    for prod in best.values():
        name  = prod["title"]
        price = prod["price"]
        link  = prod["link"]
        key   = f"{store}|{name}"

        print(f"  🎮  {name}")
        print(f"  💰  ${price:.2f}")
        print(f"  📦  In Stock")
        print(f"  🔗  {link}")

        prev_data = old_prices.get(key)
        if isinstance(prev_data, (int, float)):
            prev_data = {"price": float(prev_data), "in_stock": True}
        
        prev_price = prev_data.get("price") if prev_data else None
        prev_stock = prev_data.get("in_stock") if prev_data else None

        if prev_price is None:
            print(f"  🆕 First time seen and in stock under ${MAX_PRICE}! Alerting Discord")
            send_discord(store, name, price, None, link, is_restock=False)
            alerts_sent += 1
        elif prev_stock == False:
            print(f"  🎉 BACK IN STOCK at ${price:.2f}! Alerting Discord")
            send_discord(store, name, price, prev_price, link, is_restock=True)
            alerts_sent += 1
        elif price < prev_price:
            print(f"  📬 Price dropped ${prev_price:.2f} → ${price:.2f}! Alerting Discord")
            send_discord(store, name, price, prev_price, link, is_restock=False)
            alerts_sent += 1
        elif price > prev_price:
            print(f"  📈 Price went up ${prev_price:.2f} → ${price:.2f} (no alert)")
        else:
            print(f"     No change: ${price:.2f} (no alert)")
        
        print()
        old_prices[key] = {"price": price, "in_stock": True}

    save_data(old_prices)
    return alerts_sent


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
        self.context.add_init_script(STEALTH_JS)

    def stop(self):
        try:
            if self.browser: self.browser.close()
            if self.pw: self.pw.stop()
        except Exception:
            pass

    def new_page(self):
        return self.context.new_page()

    def fetch(self, url, wait_sel=None, extra_wait=2, timeout=25000, wait_until="domcontentloaded"):
        page = self.new_page()
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
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

    def js(self, url, code, wait_sel=None, extra_wait=2, timeout=25000, wait_until="domcontentloaded"):
        page = self.new_page()
        try:
            page.goto(url, wait_until=wait_until, timeout=timeout)
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

    products = b.js(url, """
        (() => {
            const skip = ['refurbished', 'open box', 'cable', 'adapter', 'bracket', 'riser', 'cooler'];
            const out = [];
            document.querySelectorAll('div.item-cell').forEach(cell => {
                const a = cell.querySelector('a.item-title');
                if (!a) return;
                const title = a.innerText.trim();
                const tl = title.toLowerCase();
                if (!tl.match(/6750\\s*xt/)) return;
                if (skip.some(w => tl.includes(w))) return;
                const link = a.href;
                
                let price = null;
                const pc = cell.querySelector('li.price-current');
                if (pc) {
                    const s = pc.querySelector('strong');
                    const sup = pc.querySelector('sup');
                    if (s && sup) {
                        price = parseFloat(
                            (s.innerText + sup.innerText).replace(/,/g, '')
                        );
                    }
                }
                if (price === null || isNaN(price)) {
                    const m = cell.innerText.match(/[$]?([\\d,]+\\.\\d{2})/);
                    if (m) price = parseFloat(m[1].replace(/,/g, ''));
                }
                
                const hasATC = !!cell.querySelector('a.btn-primary, button.btn-primary');
                const cellText = cell.innerText.toLowerCase();
                const isOOS = cellText.includes('out of stock') || cellText.includes('auto notify') || cellText.includes('sold out');
                
                out.push({title, price, link, in_stock: hasATC || !isOOS});
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
    skip_words = ['refurbished', 'open box', 'cable', 'adapter', 'bracket', 'riser', 'cooler']
    for cell in soup.select("div.item-cell"):
        a = cell.select_one("a.item-title")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        tl = title.lower()
        if not re.search(r'6750\s*xt', tl):
            continue
        if any(w in tl for w in skip_words):
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
                    price = float((strong.get_text(strip=True) + sup.get_text(strip=True)).replace(",", ""))
                except ValueError:
                    pass
            if price is None:
                price = extract_price(pc.get_text())
        if price is None:
            price = extract_price(cell.get_text())

        has_atc = bool(cell.select_one("a.btn-primary, button.btn-primary"))
        cell_text = cell.get_text().lower()
        is_oos = "out of stock" in cell_text or "auto notify" in cell_text or "sold out" in cell_text

        products.append({"title": title, "price": price, "link": link, "in_stock": has_atc or not is_oos})
    return products


# ================================================================
#  BEST BUY
# ================================================================
def scrape_bestbuy(b: Browser):
    print("\n🔍 BEST BUY")
    url = PRODUCTS["Best Buy"]

    # Use networkidle to let Best Buy's aggressive redirects settle
    products = b.js(url, """
        (() => {
            const out = [];
            document.querySelectorAll(
                'li.sku-item, [data-sku-id], div.shop-sku-list-item'
            ).forEach(item => {
                const a = item.querySelector(
                    'h4.sku-title a, a[data-testid="product-title"], a.v-line-clamp-2'
                );
                if (!a) return;
                const title = a.innerText.trim();
                if (!title.toLowerCase().match(/6750\\s*xt/)) return;
                const link = a.href;
                
                let price = null;
                const pe = item.querySelector(
                    'div.priceView-customer-price span, [data-testid="customer-price"] span, ' +
                    '.pricing-price .sr-only, div.priceView-hero-price span'
                );
                if (pe) {
                    const m = pe.innerText.match(/([\\d,]+\\.\\d{2})/);
                    if (m) price = parseFloat(m[1].replace(/,/g, ''));
                }
                if (price === null || isNaN(price)) {
                    const m2 = item.innerText.match(/[$]([\\d,]+\\.\\d{2})/);
                    if (m2) price = parseFloat(m2[1].replace(/,/g, ''));
                }
                
                const hasAddToCart = !!item.querySelector(
                    'button.add-to-cart-button, button[data-testid="add-to-cart-button"]'
                );
                const isSoldOut = !!item.querySelector(
                    'button.sold-out-button, div.fulfillment-sold-out'
                );
                
                let inStock = false;
                if (hasAddToCart) inStock = true;
                else if (isSoldOut) inStock = false;
                
                out.push({title, price, link, in_stock: inStock});
            });
            return out;
        })()
    """, wait_sel="li.sku-item, [data-sku-id]", extra_wait=5, wait_until="networkidle")

    if not products:
        html = b.fetch(url, wait_sel="li.sku-item", extra_wait=5, wait_until="networkidle")
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
        if not re.search(r'6750\s*xt', title.lower()):
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
            
        has_atc = bool(item.select_one("button.add-to-cart-button"))
        is_oos = bool(item.select_one("button.sold-out-button, div.fulfillment-sold-out"))
        in_stock = has_atc or not is_oos
        
        products.append({"title": title, "price": price, "link": link, "in_stock": in_stock})
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
                '[data-selenium="productCard"], .product-card, .cx-item, .item[data-selenium]'
            );
            cards.forEach(card => {
                const titleEl = card.querySelector(
                    'a[data-selenium="itemHeadingLink"], a[href*="/sp/"], .item-heading a, a[itemprop="url"]'
                );
                if (!titleEl) return;
                const title = titleEl.innerText.trim();
                if (!title.toLowerCase().match(/6750\\s*xt/)) return;
                const link = titleEl.href;
                
                let price = null;
                const priceEl = card.querySelector(
                    '[data-selenium="uppedDecimalPrice"], [data-selenium="pricingPrice"], ' +
                    '[itemprop="price"], .price, .cx-item-price'
                );
                if (priceEl) {
                    const m = priceEl.innerText.match(/([\\d,]+\\.\\d{2})/);
                    if (m) price = parseFloat(m[1].replace(/,/g, ''));
                }
                if (price === null || isNaN(price)) {
                    const m2 = card.innerText.match(/[$]([\\d,]+\\.\\d{2})/);
                    if (m2) price = parseFloat(m2[1].replace(/,/g, ''));
                }
                
                const txt = card.innerText.toLowerCase();
                const isOOS = txt.includes('out of stock') || txt.includes('notify me when available') || txt.includes('backorder');
                
                out.push({title, price, link, in_stock: !isOOS});
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
        if not re.search(r'6750\s*xt', title.lower()):
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
            
        txt = card.get_text().lower()
        is_oos = "out of stock" in txt or "notify me" in txt or "backorder" in txt
        
        products.append({"title": title, "price": price, "link": link, "in_stock": not is_oos})
    
    # Fallback Regex for B&H
    if not products:
        link_hits = re.findall(r'href="(/sp/[^"]+)"[^>]*>([^<]*6750[^<]*xt[^<]*)</a>', html, re.I)
        price_hits = set()
        for p_str in re.findall(r"\$([\d,]+\.\d{2})", html):
            try:
                val = float(p_str.replace(",", ""))
                if GPU_FLOOR <= val <= MAX_PRICE:
                    price_hits.add(val)
            except ValueError: pass
            
        for href, t in link_hits:
            products.append({
                "title": t.strip(),
                "price": min(price_hits) if price_hits else None,
                "link": f"https://www.bhphotovideo.com{href}",
                "in_stock": True if price_hits else False
            })
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
            const nd = document.getElementById('__NEXT_DATA__');
            if (nd) {
                try {
                    const data = JSON.parse(nd.textContent);
                    const props = (data.props || {}).pageProps || {};
                    const sc = props.searchContent || {};
                    const items = (sc.itemStacks || [{}])[0].items || props.products || [];
                    items.forEach(item => {
                        const name = item.name || item.title || '';
                        if (!name.toLowerCase().match(/6750\\s*xt/)) return;
                        let link = item.canonicalUrl || item.productPageUrl || '';
                        if (link && !link.startsWith('http'))
                            link = 'https://www.walmart.com' + link;
                        const pm = item.priceMap || item.price || {};
                        let price = pm.price || pm.currentPrice || pm.salePrice || null;
                        if (price !== null) price = parseFloat(price);
                        
                        const status = (item.availabilityStatus || '').toUpperCase();
                        const isOOS = status === 'OUT_OF_STOCK' || status === 'PREORDER';
                        
                        out.push({title: name, price, link, in_stock: !isOOS});
                    });
                } catch(e) {}
            }
            if (out.length === 0) {
                document.querySelectorAll(
                    '[data-item-id], [data-testid="item-card"], div.mb0.ph0.pt0.pb0'
                ).forEach(el => {
                    const te = el.querySelector(
                        'span[data-automation-id="product-title"], [data-testid="product-title"]'
                    );
                    if (!te) return;
                    const title = te.innerText.trim();
                    if (!title.toLowerCase().match(/6750\\s*xt/)) return;
                    const le = el.querySelector('a[href*="/ip/"]');
                    const link = le ? le.href : '';
                    let price = null;
                    const pe = el.querySelector(
                        '[data-automation-id="product-price"], [data-testid="price"], .lh-copy'
                    );
                    if (pe) {
                        const m = pe.innerText.match(/([\\d,]+\\.\\d{2})/);
                        if (m) price = parseFloat(m[1].replace(/,/g, ''));
                    }
                    const txt = el.innerText.toLowerCase();
                    const isOOS = txt.includes('out of stock');
                    out.push({title, price, link, in_stock: !isOOS});
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
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            props = data.get("props", {}).get("pageProps", {})
            sc = props.get("searchContent", {})
            items = (sc.get("itemStacks", [{}])[0].get("items", []) or props.get("products", []))
            for item in items:
                name = item.get("name", "") or item.get("title", "")
                if not re.search(r'6750\s*xt', name.lower()):
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
                status = (item.get("availabilityStatus", "")).upper()
                is_oos = status == "OUT_OF_STOCK"
                products.append({"title": name, "price": price, "link": link, "in_stock": not is_oos})
        except: pass

    if not products:
        price_hits = set()
        for p_str in re.findall(r"\$([\d,]+\.\d{2})", html):
            try:
                val = float(p_str.replace(",", ""))
                if GPU_FLOOR <= val <= MAX_PRICE:
                    price_hits.add(val)
            except ValueError: pass
        for slug in re.findall(r'href="/ip/([^"]*6750[^"]*)"', html, re.I):
            products.append({
                "title": "RX 6750 XT",
                "price": min(price_hits) if price_hits else None,
                "link":  f"https://www.walmart.com/ip/{slug}",
                "in_stock": True
            })
    return products


# ================================================================
#  EBAY
# ================================================================
def scrape_ebay(b: Browser):
    print("\n🔍 EBAY")
    url = PRODUCTS["eBay"]
    SKIP = ['refurbished', 'open box', 'cable','adapter','bracket','riser','power','cooler',
            'thermal','case','fan','holder','support','hdmi',
            'displayport','pcie','backplate','screw','nut']

    products = b.js(url, f"""
        (() => {{
            const skip = {json.dumps(SKIP)};
            const out = [];
            document.querySelectorAll('li.s-item').forEach(item => {{
                const te = item.querySelector('.s-item__title');
                if (!te) return;
                const title = te.innerText.trim();
                const tl = title.toLowerCase();
                if (!tl.match(/6750\\s*xt/)) return;
                if (skip.some(w => tl.includes(w))) return;
                const le = item.querySelector('.s-item__link');
                const link = le ? le.href : '';
                let price = null;
                const pe = item.querySelector('.s-item__price');
                if (pe) {{
                    const m = pe.innerText.match(/([\\d,]+\\.\\d{{2}})/);
                    if (m) price = parseFloat(m[1].replace(/,/g, ''));
                }}
                out.push({{title, price, link, in_stock: true}});
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
    SKIP = ['refurbished', 'open box', 'cable','adapter','bracket','riser','power','cooler',
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
        if not re.search(r'6750\s*xt', tl):
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
        products.append({"title": title, "price": price, "link": link, "in_stock": True})
    
    # Fallback Regex for eBay
    if not products:
        link_hits = re.findall(r'href="(https://www\.ebay\.com/itm/[^"]+)"[^>]*>([^<]*6750[^<]*xt[^<]*)</a>', html, re.I)
        price_hits = set()
        for p_str in re.findall(r"\$([\d,]+\.\d{2})", html):
            try:
                val = float(p_str.replace(",", ""))
                if GPU_FLOOR <= val <= MAX_PRICE:
                    price_hits.add(val)
            except ValueError: pass
        
        for href, t in link_hits:
            tl = t.lower()
            if any(w in tl for w in SKIP): continue
            products.append({
                "title": t.strip(),
                "price": min(price_hits) if price_hits else None,
                "link": href,
                "in_stock": True
            })
    return products


# =========================
# MAIN
# ================================
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

    total_found = 0

    for store, func in SCRAPERS:
        try:
            products = func(browser)
            total_found += len(products)
            report_products(store, products)
        except Exception as e:
            print(f"❌ {store} crashed: {e}\n")
        time.sleep(1)

    browser.stop()

    if total_found == 0:
        print("⚠️ No products found on ANY store. Scrapers might be blocked or broken.")
        try:
            req.post(DISCORD_WEBHOOK, json={
                "content": f"<@{DISCORD_USER_ID}> ⚠️ The RX 6750 XT tracker found 0 results across all stores. It might be blocked or broken! Check the logs.",
            }, timeout=10)
        except: pass

    save_data(old_prices)

    print("✅ Done.")
