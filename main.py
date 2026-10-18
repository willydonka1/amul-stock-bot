import os
import time
import random
import logging
import requests
from playwright.sync_api import sync_playwright

# ================= CONFIGURATION =================
PINCODE = "411046"
TELEGRAM_BOT_TOKEN = "8819700989:AAEI7Tj0bC7zCiehHP9-IQwm3Ylkfe7R3KQ"

# WHITELIST: Only Telegram Chat IDs inside this list receive alerts and can use commands.
# To add future subscribers, just add their numeric ID string to this list!
ALLOWED_USERS = [
    "1003899176",  # Your Admin ID
]

MAX_ALERTS_PER_RESTOCK = 3       # Send at most 3 notifications per restock, then stop
REMINDER_INTERVAL_SECONDS = 240  # Wait 4 minutes (240s) between Alert 1, Alert 2, and Alert 3
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
    """Sends a Telegram message to a single user ID."""
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
    """Sends stock alerts ONLY to whitelisted users in ALLOWED_USERS."""
    for user_id in ALLOWED_USERS:
        send_telegram_to_user(user_id, message, url=url)

def handle_telegram_commands(last_update_id: int, latest_status_summary: str) -> int:
    """
    Checks if anyone messaged the bot.
    - Blocks unauthorized strangers and tells them the bot is private.
    - Replies to whitelisted users when they send /status or /start.
    """
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
            first_name = msg.get("from", {}).get("first_name", "User")

            if not chat_id:
                continue

            # 1. Block strangers who are not in ALLOWED_USERS
            if chat_id not in ALLOWED_USERS:
                log_print(f"[🔒 Blocked Unauthorized User] Name: {first_name} | ID: {chat_id}")
                send_telegram_to_user(
                    chat_id,
                    "🔒 *Private Bot — Access Restricted*\n\n"
                    "This Amul Stock Tracker is private and only sends alerts to authorized subscribers.\n\n"
                    f"🆔 Your Telegram ID is: `{chat_id}`"
                )
                continue

            # 2. Respond to authorized subscribers
            if text in ["/start", "/status", "status"]:
                send_telegram_to_user(
                    chat_id,
                    f"🟢 *Bot is Active & Monitoring Pincode `{PINCODE}`*\n"
                    f"👥 *Authorized Subscribers:* `{len(ALLOWED_USERS)}`\n"
                    f"🔔 *Alert Rule:* Max `{MAX_ALERTS_PER_RESTOCK}` alerts per restock (`{REMINDER_INTERVAL_SECONDS // 60} min` apart)\n\n"
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
            log_print(f"[*] Setting delivery pincode {PINCODE} on Amul...")
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
            log_print(f"[+] Pincode {PINCODE} locked! Reloading product data...")
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
                    # Check if we still have alerts left (under 3) AND 4 minutes have passed since last alert
                    if state["count"] < MAX_ALERTS_PER_RESTOCK:
                        if now - state["last_sent"] >= REMINDER_INTERVAL_SECONDS:
                            state["count"] += 1
                            state["last_sent"] = now
                            alert_num = state["count"]

                            badge = (
                                f"Alert {alert_num}/{MAX_ALERTS_PER_RESTOCK}"
                                if alert_num < MAX_ALERTS_PER_RESTOCK
                                else f"Final Reminder {alert_num}/{MAX_ALERTS_PER_RESTOCK}"
                            )

                            log_print(f"[🎉 IN STOCK | {badge} | Qty: {qty_display}] {name}")
                            alert_msg = (
                                f"🚨 *AMUL WHEY PROTEIN IN STOCK!* `[{badge}]`\n\n"
                                f"📦 *Product:* {name}\n"
                                f"📊 *Stock Available:* `{qty_display}`\n"
                                f"📍 *Pincode:* `{PINCODE}`\n"
                                f"💰 *Price:* {price}"
                            )
                            broadcast_to_subscribers(alert_msg, url=url)
                        else:
                            wait_left = int(REMINDER_INTERVAL_SECONDS - (now - state["last_sent"]))
                            log_print(f"[IN STOCK | Sent {state['count']}/{MAX_ALERTS_PER_RESTOCK} | Next reminder in {wait_left}s] {name}")
                    else:
                        log_print(f"[IN STOCK | Max {MAX_ALERTS_PER_RESTOCK}/{MAX_ALERTS_PER_RESTOCK} alerts already sent — Muted] {name}")

                    status_lines.append(f"✅ *{name}:* `{qty_display}` (Alerts sent: {state['count']}/{MAX_ALERTS_PER_RESTOCK})")

                else:
                    # Product is Sold Out -> Reset counter back to 0 so it's ready for the next restock!
                    if state["count"] > 0:
                        log_print(f"[🔄 Restock Ended] {name} went out of stock. Resetting alert counter to 0/{MAX_ALERTS_PER_RESTOCK}.")
                    state["count"] = 0
                    state["last_sent"] = 0
                    log_print(f"[Sold Out | Qty: 0] {name}")
                    status_lines.append(f"❌ *{name}:* Sold Out")

            except Exception as e:
                log_print(f"[!] Error checking {name}: {e}")
                status_lines.append(f"⚠️ *{name}:* Check error")

        browser.close()

    return "\n".join(status_lines)

def main():
    log_print(f"=== Starting Amul Stock Monitor (3-Alert Cap + Private Whitelist) ===")
    broadcast_to_subscribers(
        f"✅ *Amul Stock Bot Updated!*\n"
        f"📍 *Pincode:* `{PINCODE}`\n"
        f"🔔 *Smart Alerts:* Sends *1 immediate alert + 2 reminders* (4 mins apart), then stops spamming until the next restock.\n"
        f"🔒 *Privacy:* Locked to `{len(ALLOWED_USERS)}` whitelisted user(s). Send `/status` anytime to check live stock."
    )

    alert_tracker = {}
    last_update_id = 0
    latest_summary = "First stock check currently running..."

    while True:
        log_print(f"\n--- Checking stock at {time.strftime('%I:%M:%S %p')} ---")
        latest_summary = check_all_products(alert_tracker)

        # Wait ~2 minutes while checking every 5 seconds for /status commands on Telegram
        sleep_duration = random.randint(115, 135)
        log_print(f"Waiting {sleep_duration} seconds until next check (listening for /status commands)...")
        end_wait = time.time() + sleep_duration
        while time.time() < end_wait:
            last_update_id = handle_telegram_commands(last_update_id, latest_summary)
            time.sleep(5)

if __name__ == "__main__":
    main()
