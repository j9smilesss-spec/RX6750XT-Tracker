import time
import re
import json
import os
import requests

from bs4 import BeautifulSoup


# =========================
# SETTINGS
# =========================

MAX_PRICE = 300
MIN_PRICE = 250

CHECK_EVERY_HOURS = 2


DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1526324828087390288/0MBP_8KG4kZZJfCRikk8rCUZxeKkuKzCPw8WEViOB57jWaoRdtf9XWoUXR7w_jLXzWcv"
DISCORD_USER_ID = "1396870106834796675"


HISTORY_FILE = "seen_deals.json"



# =========================
# PRODUCTS
# =========================

PRODUCTS = {

    "RX 6750 XT - Amazon":
    "https://www.amazon.com/s?k=rx+6750+xt",


    "RX 6750 XT - Walmart":
    "https://www.walmart.com/search?q=rx+6750+xt",


    "RX 6750 XT - B&H":
    "https://www.bhphotovideo.com/c/search?q=rx%206750%20xt",


    "RX 6750 XT - Best Buy":
    "https://www.bestbuy.com/site/searchpage.jsp?st=rx+6750+xt"

}



# =========================
# HEADERS
# =========================

HEADERS = {

    "User-Agent":
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",

    "Accept":
    "text/html,application/xhtml+xml"

}



# =========================
# HISTORY
# =========================

def load_history():

    if os.path.exists(HISTORY_FILE):

        with open(HISTORY_FILE, "r") as f:

            return json.load(f)

    return []



def save_history(data):

    with open(HISTORY_FILE, "w") as f:

        json.dump(
            data,
            f,
            indent=4
        )


seen = load_history()



# =========================
# DISCORD EMBED
# =========================

def send_discord(name, price, link):


    embed = {

        "title":
        "🚨 RX 6750 XT DEAL FOUND!",


        "color":
        5763719,


        "fields":

        [

            {
                "name": "🎮 Card",
                "value": name,
                "inline": False
            },


            {
                "name": "💰 Price",
                "value": f"${price}",
                "inline": True
            },


            {
                "name": "🔗 Link",
                "value": link,
                "inline": False
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


    try:

        requests.post(

            DISCORD_WEBHOOK,

            json=payload,

            timeout=10

        )


    except Exception as e:

        print(
            "Discord error:",
            e
        )



# =========================
# PRICE FINDER
# =========================

def find_prices(text):

    prices = re.findall(

        r"\$(\d{2,4}(?:\.\d{2})?)",

        text

    )


    return [

        float(p)

        for p in prices

    ]



# =========================
# CHECK WEBSITE
# =========================

def check_site(name, url):


    print(
        "Checking:",
        name
    )


    try:


        response = requests.get(

            url,

            headers=HEADERS,

            timeout=20

        )


        if response.status_code != 200:

            print(
                "Blocked:",
                response.status_code
            )

            return



        soup = BeautifulSoup(

            response.text,

            "html.parser"

        )


        text = soup.get_text(

            " ",

            strip=True

        )


        if "6750" not in text:

            print(
                "No RX 6750 XT"
            )

            return



        prices = find_prices(text)



        good_prices = [

            p

            for p in prices

            if MIN_PRICE <= p <= MAX_PRICE

        ]



        if not good_prices:

            print(
                "No valid prices"
            )

            return



        price = min(good_prices)



        deal_id = (

            name

            +

            str(price)

        )



        if deal_id in seen:

            print(
                "Already alerted"
            )

            return



        seen.append(

            deal_id

        )


        save_history(

            seen

        )


        send_discord(

            name,

            price,

            url

        )


        print(
            "DEAL SENT!"
        )



    except Exception as e:

        print(
            "Error:",
            e
        )



# =========================
# MAIN LOOP
# =========================

while True:


    print(
        "\nChecking RX 6750 XT..."
    )


    for name, url in PRODUCTS.items():

        check_site(

            name,

            url

        )



    print(
        "Finished. Sleeping 2 hours."
    )


    time.sleep(

        CHECK_EVERY_HOURS * 3600

    )
