import os
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime


# =========================
# SETTINGS
# =========================

MAX_PRICE = 10000
MIN_PRICE = 1

DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK"]
DISCORD_USER_ID = os.environ["DISCORD_USER_ID"]
DATA_FILE = "prices.json"


# =========================
# PRODUCTS
# =========================

PRODUCTS = {
    "AMD Radeon RX 6750 XT": 
    "https://pcpartpicker.com/products/video-card/#c=518"
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


    requests.post(
        DISCORD_WEBHOOK,
        json=payload,
        timeout=10
    )



# =========================
# CHECK PRICE
# =========================

def check_product(name, url):

    print("Checking:", name)


    response = requests.get(
        url,
        headers=HEADERS,
        timeout=20
    )


    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )


text = soup.get_text(" ", strip=True)

print("Status Code:", response.status_code)
print("Downloaded", len(response.text), "characters")

prices = re.findall(r"\$(\d+\.\d{2})", text)

print("Prices found:", len(prices))
print(prices[:30])


    prices = [
        float(p)
        for p in prices
    ]


    valid = [

        p for p in prices

        if MIN_PRICE <= p <= MAX_PRICE

    ]


    if not valid:

        print("No deal found")

        return



    price = min(valid)

    previous = old_prices.get(name)


    if previous != price:

        send_discord(
            name,
            price,
            previous,
            url
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
