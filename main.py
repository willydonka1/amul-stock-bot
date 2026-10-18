import os
import time
import random
import requests
from playwright.sync_api import sync_playwright

# ================= CONFIGURATION =================
PINCODE = "411046"
TELEGRAM_BOT_TOKEN = "8819700989:AAEI7Tj0bC7zCiehHP9-IQwm3Ylkfe7R3KQ"
TELEGRAM_CHAT_ID = "1003899176"

ALERT_COOLDOWN_SECONDS = 900   # Wait 15 mins before repeating an alert for the same pack
RUN_DURATION_SECONDS = 2700    # Run for 45 minutes per cloud cycle, then let the next cycle take over
STATE_FILE = "amul_session_v2.json"
# =================================================

PRODUCTS = [
    {
        "name": "Amul Chocolate Whey Protein (60 Sachets | 34g)",
        "alias": "amul-chocolate-whey-protein-34-g-or-pack-of-60-sachets",
        "price": "₹4,500",
        "url": "https://shop.amul.com/en/product/amul-chocolate-whey-protein-34-g-or-pack-of-60-sachets"
    },
    {
        "name": "Amul Chocolate Whey Protein (30 Sachets | 34g)",
        "alias": "amul-chocolate-whey-protein-34-g-or-pack-of-30-sachets",
        "price": "₹2,500",
        "url": "https://shop.amul.com/product/amul-chocolate-whey-protein-34-g-or-pack-of-30-sachets"
    },
    {
        "name": "Amul Plain Whey Protein (60 Sachets | 32g)",
        "alias": "amul-whey-protein-32-g-or-pack-of-60-sachets",
        "price": "₹4,200",
        "url": "https://shop.amul.com/product/amul-whey-protein-32-g-or-pack-of-60-sachets"
    },
    {
        "name": "Amul Plain Whey Protein (30 Sachets | 32g)",
        "alias": "amul-whey-protein-32-g-or-pack-of-30-sachets",
        "price": "₹2,400",
        "url": "https://shop.amul.com/product/amul-whey-protein-32-g-or-pack-of-30-sachets"
    }
]

def send_telegram_alert(message: str, url: str = None):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if url:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [
                    {"text": "🛒 Buy Now on Amul", "url": url},
                    {"text": "🔄 Open Amul Shop", "url": "https://shop.amul.com"}
                ]
            ]
        }
    try:
        requests.post(api_url, json=payload, timeout=10)
    except Exception as e:
        print(f"[!] Telegram error: {e}")

def ensure_pincode_set(page, context, current_url: str):
    try:
        pincode_input = page.locator("input[placeholder*='Pincode' i]").first
        header_text = page.locator("header, .header, body").first.inner_text()

        if not pincode_input.is_visible(timeout=2500) and PINCODE not in header_text:
            select_btn = page.locator("text='Select Pincodes'").first
            if select_btn.is_visible(timeout=2000):
                select_btn.click()
                page.wait_for_timeout(1000)

        if pincode_input.is_visible(timeout=2500):
            print(f"[*] Setting delivery pincode {PINCODE} on Amul...")
            pincode_input.click()
            pincode_input.fill("")
            pincode_input.press_sequentially(PINCODE, delay=150)
            page.wait_for_timeout(2500)

            dropdown_item = page.locator(
                f"#search-Toggle a:has-text('{PINCODE}'), "
                f".search-item:has-text('{PINCODE}'), "
                f"[ng-click*='pincode' i]:has-text('{PINCODE}'), "
                f"[ng-click*='Pincode' i]:has-text('{PINCODE}')"
            ).first

            if dropdown_item.is_visible(timeout=4000):
                dropdown_item.click()
            else:
                page.locator(f"text='{PINCODE}'").last.click()

            page.wait_for_timeout(3500)
            page.wait_for_load_state("networkidle", timeout=15000)
            context.storage_state(path=STATE_FILE)
            print(f"[+] Pincode {PINCODE} locked! Reloading product data...")
            page.goto(current_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)
    except Exception as e:
        print(f"[!] Pincode setup note: {e}")

def get_product_stock_data(page, alias: str, captured_api_data: dict) -> dict:
    if alias in captured_api_data:
        return captured_api_data[alias]

    return page.evaluate(
        """async ({ alias }) => {
            if (window.angular && window.angular.element) {
                const elements = document.querySelectorAll('[ng-controller], .product-detail, [ng-if], div, form');
                for (const el of elements) {
                    try {
                        const scope = window.angular.element(el).scope();
                        if (scope && scope.product && scope.product.alias === alias) {
                            return {
                                available: Boolean(scope.product.available),
                                quantity: Number(scope.product.inventory_quantity ?? 0),
                                source: 'StoreHippo Live Scope'
                            };
                        }
                    } catch (e) {}
                }
            }
            try {
                const apiUrl = `/api/1/entity/ms.products?filters[0][field]=alias&filters[0][value]=${encodeURIComponent(alias)}&filters[0][operator]=eq&limit=1`;
                const res = await fetch(apiUrl, { credentials: 'include' });
                if (res.ok) {
                    const data = await res.json();
                    const list = data.data || data.records || [];
                    if (list.length > 0) {
                        const prod = list[0];
                        return {
                            available: Boolean(prod.available),
                            quantity: Number(prod.inventory_quantity ?? 0),
                            source: 'StoreHippo API'
                        };
                    }
                }
            } catch (e) {}
            return { available: false, quantity: 0, source: 'Fallback' };
        }""",
        {"alias": alias}
    )

def check_all_products(last_alerted: dict):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = (
            browser.new_context(storage_state=STATE_FILE)
            if os.path.exists(STATE_FILE)
            else browser.new_context()
        )
        page = context.new_page()
        captured_api_data = {}

        def handle_response(response):
            if "ms.products" in response.url and response.status == 200:
                try:
                    body = response.json()
                    items = body.get("data", []) if isinstance(body, dict) else []
                    if isinstance(body, dict) and "alias" in body:
                        items = [body]
                    for prod in items:
                        if isinstance(prod, dict) and "alias" in prod:
                            captured_api_data[prod["alias"]] = {
                                "available": bool(prod.get("available")),
                                "quantity": int(prod.get("inventory_quantity") or 0),
                                "source": "StoreHippo Network JSON"
                            }
                except Exception:
                    pass

        page.on("response", handle_response)

        for item in PRODUCTS:
            name = item["name"]
            alias = item["alias"]
            url = item["url"]
            price = item["price"]

            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)
                ensure_pincode_set(page, context, url)

                stock_info = get_product_stock_data(page, alias, captured_api_data)
                in_stock = stock_info.get("available", False)
                quantity = stock_info.get("quantity", 0)
                qty_display = f"{quantity} units" if quantity > 0 else "Available"

                if in_stock:
                    now = time.time()
                    if now - last_alerted.get(url, 0) >= ALERT_COOLDOWN_SECONDS:
                        print(f"[IN STOCK | Qty: {qty_display}] {name}")
                        alert_msg = (
                            "🚨 *AMUL WHEY PROTEIN IN STOCK!* 🚨\n\n"
                            f"📦 *Product:* {name}\n"
                            f"📊 *Stock Available:* `{qty_display}`\n"
                            f"📍 *Pincode:* `{PINCODE}`\n"
                            f"💰 *Price:* {price}"
                        )
                        send_telegram_alert(alert_msg, url=url)
                        last_alerted[url] = now
                else:
                    print(f"[Sold Out | Qty: {quantity}] {name}")
            except Exception as e:
                print(f"[!] Error checking {name}: {e}")

        browser.close()

def main():
    start_time = time.time()
    last_alerted = {}

    # Only send the startup message when you manually trigger a test on GitHub
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        send_telegram_alert(
            f"☁️ *Amul Cloud Bot is Live on GitHub!* \n"
            f"📍 Monitoring pincode `{PINCODE}` 24/7—even with your laptop turned off."
        )

    while time.time() - start_time < RUN_DURATION_SECONDS:
        check_all_products(last_alerted)
        sleep_duration = random.randint(110, 150)
        time.sleep(sleep_duration)

if __name__ == "__main__":
    main()
