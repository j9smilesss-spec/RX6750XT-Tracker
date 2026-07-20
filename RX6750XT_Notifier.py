import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# =========================
# SETTINGS
# =========================
MAX_PRICE = 315
MIN_PRICE = 150
GPU_FLOOR = 240

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "")
DATA_FILE = "prices.json"

# =========================
# PRODUCTS
# =========================
PRODUCTS = {
    "Best Buy": "https://www.bestbuy.com/site/searchpage.jsp?st=rx+6750+xt",
    "B&H": "https://www.bhphotovideo.com/c/search?q=RX%206750%20XT",
    "Newegg": "https://www.newegg.com/p/pl?d=RX+6750+XT",
    "Walmart": "https://www.walmart.com/search?q=RX+6750+XT",
    "eBay": "https://www.ebay.com/sch/i.html?_nkw=RX+6750+XT",
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
            {"name": "🎮 GPU",   "value": name, "inline": False},
            {"name": "💰 Price", "value": f"${price:.2f}{change}", "inline": True},
            {"name": "🕒 Checked",
             "value": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
             "inline": True},
            {"name": "🔗 Link",  "value": link},
        ],
    }
    payload = {"content": f"<@{DISCORD_USER_ID}>", "embeds": [embed]}

    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        print(f"  Discord status: {r.status_code}")
    except Exception as e:
        print(f"  Discord error: {e}")

# =========================
# HELPER
# =========================
def extract_price_float(text):
    """Pull the first $XXX.XX from a string and return as float, or None."""
    m = re.search(r"\$?([\d,]+\.\d{2})", text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None

def is_valid_gpu_price(val):
    return val is not None and GPU_FLOOR <= val <= MAX_PRICE

def create_session(extra_headers=None):
    session = requests.Session()
    base_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    if extra_headers:
        base_headers.update(extra_headers)
    session.headers.update(base_headers)
    return session

def report_products(store, products):
    """Print results and fire Discord alerts for price changes."""
    if not products:
        print(f"  ❌ No RX 6750 XT products with valid prices found.")
        return

    # Deduplicate by link, keep lowest price
    best = {}
    for p in products:
        key = p["link"]
        if key not in best or p["price"] < best[key]["price"]:
            best[key] = p

    for prod in best.values():
        name  = prod["title"]
        price = prod["price"]
        link  = prod["link"]
        key   = f"{store}|{name}"

        print(f"\n  🎮  {name}")
        print(f"  💰  ${price:.2f}")
        print(f"  🔗  {link}")

        previous = old_prices.get(key)

        if previous is not None and previous != price:
            print(f"  📬  Price changed — alerting Discord")
            send_discord(store, name, price, previous, link)
        elif previous is None:
            print(f"  🆕  First time seen — alerting Discord")
            send_discord(store, name, price, None, link)
        else:
            print(f"     No price change")

        old_prices[key] = price

    save_data(old_prices)


# ================================================================
#  NEWEGG
# ================================================================
def scrape_newegg():
    print("\n🔍 NEWEGG")
    session = create_session({"Referer": "https://www.newegg.com/"})

    # Warm up session — Newegg sets essential cookies
    try:
        session.get("https://www.newegg.com/", timeout=30)
        time.sleep(1)
    except Exception as e:
        print(f"  Homepage warmup failed: {e}")

    url = PRODUCTS["Newegg"]
    try:
        r = session.get(url, timeout=30)
    except Exception as e:
        print(f"  Request failed: {e}")
        return []

    print(f"  HTTP {r.status_code}")

    with open("debug_newegg.html", "w", encoding="utf-8") as f:
        f.write(r.text)

    lower = r.text.lower()
    if "robot" in lower or "captcha" in lower or "just a moment" in lower:
        print("  ⚠️  CAPTCHA / bot-check page detected")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    products = []

    # --- DOM parsing of item-cell containers ---
    for cell in soup.select("div.item-cell"):
        title_tag = cell.select_one("a.item-title")
        if not title_tag:
            continue

        title = title_tag.get_text(" ", strip=True)
        link  = title_tag.get("href", "")

        if "6750" not in title.lower():
            continue
        if link.startswith("/"):
            link = "https://www.newegg.com" + link

        price = None
        pc = cell.select_one("li.price-current")
        if pc:
            strong = pc.find("strong")
            sup    = pc.find("sup")
            if strong and sup:
                raw = strong.get_text(strip=True) + sup.get_text(strip=True)
                try:
                    price = float(raw.replace(",", ""))
                except ValueError:
                    pass
            if price is None:
                price = extract_price_float(pc.get_text())
        if price is None:
            price = extract_price_float(cell.get_text())

        if is_valid_gpu_price(price):
            products.append({"title": title, "price": price, "link": link})

    # --- Regex fallback on raw HTML ---
    if not products:
        print("  DOM empty — trying regex fallback…")
        price_hits = set()
        for p_str in re.findall(r"\$([\d,]+\.\d{2})", r.text):
            try:
                val = float(p_str.replace(",", ""))
                if GPU_FLOOR <= val <= MAX_PRICE:
                    price_hits.add(val)
            except ValueError:
                pass

        link_hits = re.findall(
            r'href="((?:https?://www\.newegg\.com)?/p/[^"]+)"'
            r'[^>]*>([^<]{0,300}6750[^<]{0,300})</a>',
            r.text, re.IGNORECASE,
        )
        for href, t in link_hits:
            full = f"https://www.newegg.com{href}" if href.startswith("/") else href
            if price_hits:
                products.append({
                    "title": t.strip(),
                    "price": min(price_hits),
                    "link":  full,
                })

    return products


# ================================================================
#  BEST BUY
# ================================================================
def scrape_bestbuy():
    print("\n🔍 BEST BUY")
    session = create_session()

    url = PRODUCTS["Best Buy"]
    try:
        r = session.get(url, timeout=30)
    except Exception as e:
        print(f"  Request failed: {e}")
        return []

    print(f"  HTTP {r.status_code}")

    with open("debug_bestbuy.html", "w", encoding="utf-8") as f:
        f.write(r.text)

    soup = BeautifulSoup(r.text, "html.parser")
    products = []

    # Best Buy search results: each item is inside an <li> with data-sku-id
    for item in soup.select("li.sku-item"):
        title_tag = item.select_one("h4.sku-title a")
        if not title_tag:
            continue

        title = title_tag.get_text(" ", strip=True)
        link  = title_tag.get("href", "")

        if "6750" not in title.lower():
            continue
        if link.startswith("/"):
            link = "https://www.bestbuy.com" + link

        price = None
        price_tag = item.select_one("div.priceView-customer-price span")
        if price_tag:
            price = extract_price_float(price_tag.get_text())
        if price is None:
            price = extract_price_float(item.get_text())

        if is_valid_gpu_price(price):
            products.append({"title": title, "price": price, "link": link})

    # Regex fallback
    if not products:
        print("  DOM empty — trying regex fallback…")
        # Best Buy embeds JSON in script tags
        for script in soup.select("script"):
            text = script.string or ""
            if "6750" not in text.lower():
                continue
            # Try to pull prices near 6750 mentions
            for m in re.finditer(r"6750.{0,500}?\$?([\d,]+\.\d{2})", text, re.IGNORECASE):
                try:
                    val = float(m.group(1).replace(",", ""))
                    if GPU_FLOOR <= val <= MAX_PRICE:
                        # Try to find a product link
                        links_found = re.findall(
                            r'href="(/site/[^"]+6750[^"]*)"', r.text, re.IGNORECASE
                        )
                        if links_found:
                            href = links_found[0]
                            products.append({
                                "title": "RX 6750 XT (Best Buy)",
                                "price": val,
                                "link":  f"https://www.bestbuy.com{href}",
                            })
                        break
                except ValueError:
                    pass

    return products


# ================================================================
#  B&H PHOTO
# ================================================================
def scrape_bhphoto():
    print("\n🔍 B&H PHOTO")
    session = create_session()

    url = PRODUCTS["B&H"]
    try:
        r = session.get(url, timeout=30)
    except Exception as e:
        print(f"  Request failed: {e}")
        return []

    print(f"  HTTP {r.status_code}")

    with open("debug_bhphoto.html", "w", encoding="utf-8") as f:
        f.write(r.text)

    soup = BeautifulSoup(r.text, "html.parser")
    products = []

    # B&H product cards
    for item in soup.select("div[data-selenium='productCard']"):
        title_tag = item.select_one("a[data-selenium='itemHeadingLink']")
        if not title_tag:
            # Try broader selector
            title_tag = item.select_one("a[href*='/sp/']")

        if not title_tag:
            continue

        title = title_tag.get_text(" ", strip=True)
        link  = title_tag.get("href", "")

        if "6750" not in title.lower():
            # Also check the item's full text
            if "6750" not in item.get_text().lower():
                continue
            # If 6750 is in the item but not the title, skip (likely accessory)
            continue

        if link.startswith("/"):
            link = "https://www.bhphotovideo.com" + link

        price = None
        price_tag = item.select_one("span[data-selenium='uppedDecimalPrice']")
        if not price_tag:
            price_tag = item.select_one("span[data-selenium='pricingPrice']")
        if not price_tag:
            # Broader: any element with price-like text
            for el in item.select("[data-selenium*='price' i]"):
                p = extract_price_float(el.get_text())
                if p and GPU_FLOOR <= p:
                    price = p
                    break
        if price_tag:
            price = extract_price_float(price_tag.get_text())
        if price is None:
            price = extract_price_float(item.get_text())

        if is_valid_gpu_price(price):
            products.append({"title": title, "price": price, "link": link})

    # Regex fallback
    if not products:
        print("  DOM empty — trying regex fallback…")
        # Find product links mentioning 6750
        link_hits = re.findall(
            r'href="(/sp/[^"]+)"[^>]*>([^<]*6750[^<]*)</a>',
            r.text, re.IGNORECASE,
        )
        price_hits = set()
        for p_str in re.findall(r"\$([\d,]+\.\d{2})", r.text):
            try:
                val = float(p_str.replace(",", ""))
                if GPU_FLOOR <= val <= MAX_PRICE:
                    price_hits.add(val)
            except ValueError:
                pass

        for href, t in link_hits:
            products.append({
                "title": t.strip(),
                "price": min(price_hits) if price_hits else None,
                "link":  f"https://www.bhphotovideo.com{href}",
            })

    return products


# ================================================================
#  WALMART
# ================================================================
def scrape_walmart():
    print("\n🔍 WALMART")
    session = create_session()

    url = PRODUCTS["Walmart"]
    try:
        r = session.get(url, timeout=30)
    except Exception as e:
        print(f"  Request failed: {e}")
        return []

    print(f"  HTTP {r.status_code}")

    with open("debug_walmart.html", "w", encoding="utf-8") as f:
        f.write(r.text)

    soup = BeautifulSoup(r.text, "html.parser")
    products = []

    # Walmart heavily relies on JS rendering, but let's try what we can get

    # Method 1: JSON-LD structured data
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]

            for item in items:
                # Could be an ItemList with itemListElement
                elems = item.get("itemListElement", [])
                if not elems and "name" in item:
                    elems = [item]

                for elem in elems:
                    name = elem.get("name", "")
                    if "6750" not in name.lower():
                        continue

                    link = elem.get("url", "")
                    price = None

                    offers = elem.get("offers", {})
                    if isinstance(offers, dict):
                        price_val = offers.get("price") or offers.get("lowPrice")
                        if price_val:
                            try:
                                price = float(price_val)
                            except ValueError:
                                pass
                    elif isinstance(offers, list):
                        for o in offers:
                            price_val = o.get("price") or o.get("lowPrice")
                            if price_val:
                                try:
                                    price = float(price_val)
                                except ValueError:
                                    break

                    if is_valid_gpu_price(price):
                        products.append({"title": name, "price": price, "link": link})

        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # Method 2: Regex fallback on raw HTML
    if not products:
        print("  JSON-LD empty — trying regex fallback…")

        # Walmart embeds product data in __NEXT_DATA__ JSON
        next_data = re.search(
            r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            r.text, re.DOTALL,
        )
        if next_data:
            try:
                data = json.loads(next_data.group(1))
                # Navigate the structure to find products
                props = data.get("props", {}).get("pageProps", {})
                search = props.get("searchContent", {})
                results = (
                    search.get("itemStacks", [{}])[0].get("items", [])
                    or props.get("products", [])
                )
                for item in results:
                    name = item.get("name", "") or item.get("title", "")
                    if "6750" not in name.lower():
                        continue

                    link = item.get("canonicalUrl", "") or item.get("productPageUrl", "")
                    if link and not link.startswith("http"):
                        link = f"https://www.walmart.com{link}"

                    price_info = item.get("priceMap", {}) or item.get("price", {})
                    if isinstance(price_info, dict):
                        price_val = (
                            price_info.get("price") or
                            price_info.get("currentPrice") or
                            price_info.get("salePrice")
                        )
                    else:
                        price_val = price_info

                    try:
                        price = float(price_val)
                    except (ValueError, TypeError):
                        price = None

                    if is_valid_gpu_price(price):
                        products.append({"title": name, "price": price, "link": link})
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"  __NEXT_DATA__ parse failed: {e}")

    # Method 3: Pure regex
    if not products:
        print("  Trying pure regex…")
        price_hits = set()
        for p_str in re.findall(r"\$([\d,]+\.\d{2})", r.text):
            try:
                val = float(p_str.replace(",", ""))
                if GPU_FLOOR <= val <= MAX_PRICE:
                    price_hits.add(val)
            except ValueError:
                pass

        link_hits = re.findall(
            r'href="/ip/([^"]*6750[^"]*)"',
            r.text, re.IGNORECASE,
        )
        for slug in link_hits:
            products.append({
                "title": f"RX 6750 XT ({slug[:50]})",
                "price": min(price_hits) if price_hits else None,
                "link":  f"https://www.walmart.com/ip/{slug}",
            })

    return products


# ================================================================
#  EBAY
# ================================================================
def scrape_ebay():
    print("\n🔍 EBAY")
    session = create_session()

    url = PRODUCTS["eBay"]
    try:
        r = session.get(url, timeout=30)
    except Exception as e:
        print(f"  Request failed: {e}")
        return []

    print(f"  HTTP {r.status_code}")

    with open("debug_ebay.html", "w", encoding="utf-8") as f:
        f.write(r.text)

    soup = BeautifulSoup(r.text, "html.parser")
    products = []

    # eBay search results
    for item in soup.select("li.s-item"):
        title_tag = item.select_one("div.s-item__title")
        if not title_tag:
            continue

        title = title_tag.get_text(" ", strip=True)

        # Filter for RX 6750 XT, exclude accessories
        if "6750" not in title.lower():
            continue
        # Skip common accessory keywords
        skip_words = ["cable", "adapter", "bracket", "riser", "power", "cooler",
                       "thermal", "case", "fan", "holder", "support"]
        if any(w in title.lower() for w in skip_words):
            continue

        link_tag = item.select_one("a.s-item__link")
        link = link_tag.get("href", "") if link_tag else ""

        price = None
        price_tag = item.select_one("span.s-item__price")
        if price_tag:
            price_text = price_tag.get_text(strip=True)
            # Handle "$299.99 to $349.99" — take the low end
            m = re.search(r"\$?([\d,]+\.\d{2})", price_text)
            if m:
                try:
                    price = float(m.group(1).replace(",", ""))
                except ValueError:
                    pass
        if price is None:
            price = extract_price_float(item.get_text())

        if is_valid_gpu_price(price):
            products.append({"title": title, "price": price, "link": link})

    # Regex fallback
    if not products:
        print("  DOM empty — trying regex fallback…")
        price_hits = set()
        for p_str in re.findall(r"\$([\d,]+\.\d{2})", r.text):
            try:
                val = float(p_str.replace(",", ""))
                if GPU_FLOOR <= val <= MAX_PRICE:
                    price_hits.add(val)
            except ValueError:
                pass

        # eBay item links
        link_hits = re.findall(
            r'href="(https://www\.ebay\.com/itm/[^"]+)"[^>]*>([^<]*6750[^<]*)</a>',
            r.text, re.IGNORECASE,
        )
        for href, t in link_hits:
            if any(w in t.lower() for w in ["cable", "adapter", "bracket", "riser"]):
                continue
            products.append({
                "title": t.strip(),
                "price": min(price_hits) if price_hits else None,
                "link":  href,
            })

    return products


# =========================
# MAIN
# =========================
SCRAPERS = {
    "Newegg":   scrape_newegg,
    "Best Buy": scrape_bestbuy,
    "B&H":      scrape_bhphoto,
    "Walmart":  scrape_walmart,
    "eBay":     scrape_ebay,
}

if __name__ == "__main__":
    for store, scraper in SCRAPERS.items():
        try:
            products = scraper()
            report_products(store, products)
        except Exception as e:
            print(f"\n❌ {store} scraper crashed: {e}")

        # Polite delay between stores
        time.sleep(3)

    print("\n✅ Finished all stores.")
