import os
import time
import random
import logging
import requests
from playwright.sync_api import sync_playwright

# ================= CONFIGURATION =================
PINCODE = "411046"

# Read token directly from GitHub Secrets / Environment Variable
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

ALLOWED_USERS = [
    "1003899176",  # Your Admin ID
]

MAX_ALERTS_PER_RESTOCK = 3       
REMINDER_INTERVAL_SECONDS = 240  
STATE_FILE = "amul_session_v2.json"
LOG_FILE = "bot.log"
# =================================================

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

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

def log_print(message: str):
    print(message)
    logging.info(message)

def send_telegram_to_user(chat_id: str, message: str, url: str = None):
    if not TELEGRAM_BOT_TOKEN:
        log_print("[!] Error: TELEGRAM_BOT_TOKEN is empty. Check GitHub Secrets.")
        return

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
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
        response = requests.post(api_url, json=payload, timeout=10)
        if not response.ok:
            log_print(f"[!] Telegram API error for {chat_id}: {response.text}")
    except Exception as e:
        log_print(f"[!] Failed to send Telegram message to {chat_id}: {e}")

def broadcast_to_subscribers(message: str, url: str = None):
    for user_id in ALLOWED_USERS:
        send_telegram_to_user(user_id, message, url=url)

def handle_telegram_commands(last_update_id: int, latest_status_summary: str) -> int:
    if not TELEGRAM_BOT_TOKEN:
        return last_update_id

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {"timeout": 1}
    if last_update_id:
        params["offset"] = last_update_id + 1

    try:
        res = requests.get(api_url, params=params, timeout=5)
        if not res.ok:
            return last_update_id
        updates = res.json().get("result", [])
        for update in updates:
            last_update_id = update["update_id"]
            msg = update.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = (msg.get("text") or "").strip().lower()

            if not chat_id:
                continue

            if chat_id not in ALLOWED_USERS:
                send_telegram_to_user(chat_id, f"🔒 *Access Restricted.*\n🆔 Your ID: `{chat_id}`")
                continue

            if text in ["/start", "/status", "status"]:
                send_telegram_to_user(
                    chat_id,
                    f"🟢 *Cloud Bot is Active & Monitoring Pincode `{PINCODE}`*\n\n"
                    f"*Latest Check Summary:*\n{latest_status_summary}"
                )
    except Exception:
        pass
    return last_update_id

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
            page.goto(current_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)
    except Exception as e:
        log_print(f"[!] Pincode setup note: {e}")

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

def check_all_products(alert_tracker: dict) -> str:
    status_lines = []
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

            if url not in alert_tracker:
                alert_tracker[url] = {"count": 0, "last_sent": 0}

            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)
                ensure_pincode_set(page, context, url)

                stock_info = get_product_stock_data(page, alias, captured_api_data)
                in_stock = stock_info.get("available", False)
                quantity = stock_info.get("quantity", 0)
                qty_display = f"{quantity} units" if quantity > 0 else "Available"

                state = alert_tracker[url]

                if in_stock:
                    now = time.time()
                    if state["count"] < MAX_ALERTS_PER_RESTOCK:
                        if now - state["last_sent"] >= REMINDER_INTERVAL_SECONDS:
                            state["count"] += 1
                            state["last_sent"] = now
                            alert_num = state["count"]
                            badge = f"Alert {alert_num}/{MAX_ALERTS_PER_RESTOCK}"

                            alert_msg = (
                                f"🚨 *AMUL WHEY PROTEIN IN STOCK!* `[{badge}]`\n\n"
                                f"📦 *Product:* {name}\n"
                                f"📊 *Stock Available:* `{qty_display}`\n"
                                f"📍 *Pincode:* `{PINCODE}`\n"
                                f"💰 *Price:* {price}"
                            )
                            broadcast_to_subscribers(alert_msg, url=url)
                    status_lines.append(f"✅ *{name}:* `{qty_display}`")
                else:
                    state["count"] = 0
                    state["last_sent"] = 0
                    status_lines.append(f"❌ *{name}:* Sold Out")
            except Exception as e:
                log_print(f"[!] Error checking {name}: {e}")
                status_lines.append(f"⚠️ *{name}:* Check error")

        browser.close()
    return "\n".join(status_lines)

def main():
    log_print(f"=== Starting Amul Cloud Stock Monitor for {PINCODE} ===")

    if not TELEGRAM_BOT_TOKEN:
        log_print("[!] CRITICAL: TELEGRAM_BOT_TOKEN not found in environment. Check GitHub Secrets.")

    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        broadcast_to_subscribers(
            f"☁️ *Amul Cloud Bot is Live on GitHub!*\n"
            f"📍 *Pincode:* `{PINCODE}`\n"
            f"🔔 Max `{MAX_ALERTS_PER_RESTOCK}` alerts per restock (`{REMINDER_INTERVAL_SECONDS // 60}m` apart)."
        )

    alert_tracker = {}
    last_update_id = 0
    latest_summary = "Initializing first check..."

    # Run for 42 minutes per cloud cycle, well within the 50-minute workflow timeout
    start_time = time.time()
    while time.time() - start_time < 2520:
        log_print(f"\n--- Checking stock at {time.strftime('%I:%M:%S %p')} ---")
        latest_summary = check_all_products(alert_tracker)
        
        sleep_duration = random.randint(115, 135)
        end_wait = time.time() + sleep_duration
        while time.time() < end_wait:
            last_update_id = handle_telegram_commands(last_update_id, latest_summary)
            time.sleep(5)

if __name__ == "__main__":
    main()
