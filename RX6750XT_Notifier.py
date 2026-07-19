import os
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime


# =========================
# SETTINGS
# =========================

MAX_PRICE = 315
MIN_PRICE = 150

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
DISCORD_USER_ID = os.environ["DISCORD_USER_ID"]
DATA_FILE = "prices.json"


# =========================
# PRODUCTS
# =========================

PRODUCTS = {
    "Best Buy": "https://www.bestbuy.com/site/searchpage.jsp?st=rx+6750+xt",
    "B&H": "https://www.bhphotovideo.com/c/search?q=RX%206750%20XT",
    "Newegg": "https://www.newegg.com/p/pl?d=RX+6750+XT",
    "Walmart": "https://www.walmart.com/search?q=RX+6750+XT",
    "eBay": "https://www.ebay.com/sch/i.html?_nkw=RX+6750+XT"
}


HEADERS = {
    "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
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
# DISCORD EMBED
# =========================

def send_discord(name, price, old_price, link):

    change = ""

    if old_price:
        difference = old_price - price

        if difference > 0:
            change = f"\n📉 Drop: ${difference:.2f}"


    embed = {

        "title":
        "🚨 RX 6750 XT DEAL ALERT",

        "color":
        65280,

        "fields": [

            {
                "name": "🎮 GPU",
                "value": name,
                "inline": False
            },

            {
                "name": "💰 Price",
                "value": f"${price:.2f}{change}",
                "inline": True
            },

            {
                "name": "🕒 Checked",
                "value": datetime.now().strftime("%m/%d/%Y %I:%M %p"),
                "inline": True
            },

            {
                "name": "🔗 Link",
                "value": link
            }

        ]

    }


    payload = {

        "content":
        f"<@{DISCORD_USER_ID}>",

        "embeds":
        [
            embed
        ]

    }

    response = requests.post(
        DISCORD_WEBHOOK,
        json=payload,
        timeout=10
    )

    print("Discord status:", response.status_code)
    print(response.text)




# =========================
# CHECK PRICE
# =========================

def check_product(name, url):

    print("Checking:", name)

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=60
        )
    except requests.exceptions.RequestException as e:
        print(f"{name} failed: {e}")
        return


    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


    # Find product links
    links = soup.find_all("a", href=True)


    found_product = None

    for link in links:

        href = link["href"]
        title = link.get_text(" ", strip=True)


        if "/p/" in href and "6750" in title.lower():

            found_product = {
                "title": title,
                "link": href
            }

            break


    if not found_product:

        print("No RX 6750 XT product found")
        return


    title = found_product["title"]
    product_link = found_product["link"]


    # Fix relative URLs
    if product_link.startswith("/"):

        product_link = "https://www.newegg.com" + product_link


    print("Found:")
    print(title)
    print(product_link)


    # Load the actual product page for price
    try:
        product_response = requests.get(
            product_link,
            headers=HEADERS,
            timeout=60
        )

        product_soup = BeautifulSoup(
            product_response.text,
            "html.parser"
        )

    except requests.exceptions.RequestException as e:
        print("Product page failed:", e)
        return


    # Find price from Newegg page data
    html = product_response.text

    prices = []

    # Look around common price locations
    matches = re.findall(
        r'.{0,100}(\d{2,3}\.\d{2}).{0,100}',
        html
    )

    for match in matches:
        try:
            value = float(match)

            if MIN_PRICE <= value <= MAX_PRICE:
                prices.append(match)

        except:
            pass


    print("Prices found:", prices[:20])
    print("Using price:", min([float(p) for p in prices]))
    prices = [
        float(p)
        for p in prices
    ]


    valid = [
        p for p in prices
        if MIN_PRICE <= p <= MAX_PRICE
    ]


    if not valid:

        print("No valid price")
    return


    price = min(valid)


    previous = old_prices.get(name)


print("Previous:", previous)
print("Current:", price)

if previous != price:

    print("Sending Discord alert!")

    send_discord(
            title,
            price,
            previous,
            product_link
        )


    old_prices[name] = price

    save_data(old_prices)



# =========================
# RUN
# =========================

for name, url in PRODUCTS.items():

    check_product(
        name,
        url
    )

print("Finished")
