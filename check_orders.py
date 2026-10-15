import json
import os
import re
import smtplib
from email.message import EmailMessage
import urllib.request
from playwright.sync_api import sync_playwright

MYNTRA_URL = "https://mdirect.myntrainfo.com/Orders/Search"
LOTUS_URL = "https://partners.lotusimall.com/Seller/Orders_new"

def send_mobile_notification(message, title="Order Alert", click_url=MYNTRA_URL):
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
    if ntfy_topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{ntfy_topic}",
                data=message.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": "high",
                    "Click": click_url,
                },
                method="POST"
            )
            urllib.request.urlopen(req, timeout=15)
            print(f"[{title}] Notification sent!")
        except Exception as e:
            print(f"[{title}] ntfy error:", e)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        )

        # 1. Load Myntra Cookies
        myntra_cookies = os.environ.get("MYNTRA_COOKIES", "").strip()
        if myntra_cookies:
            try:
                context.add_cookies([{"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/")} for c in json.loads(myntra_cookies) if "name" in c])
            except Exception as e:
                print("Myntra cookie warning:", e)

        myntra_page = context.new_page()
        lotus_page = context.new_page()

        print("Opening Myntra MDirect and Lotus iMall in parallel...")
        try:
            myntra_page.goto(MYNTRA_URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print("Myntra load warning:", e)

        try:
            lotus_page.goto(LOTUS_URL, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print("Lotus load warning:", e)

        myntra_page.wait_for_timeout(6000)

        # ==========================================
        # CHECK MYNTRA
        # ==========================================
        try:
            m_text = myntra_page.inner_text("body")
            m_match = re.search(r"Open Orders\s*\((\d+)\)", m_text, re.IGNORECASE)
            if m_match:
                m_count = int(m_match.group(1))
                print(f"[Myntra] Open Orders: {m_count}")
                if m_count > 0:
                    send_mobile_notification(f"You have {m_count} new order(s) waiting on Myntra.", title="Myntra", click_url=MYNTRA_URL)
        except Exception as e:
            print("[Myntra] Check error:", e)

        # ==========================================
        # CHECK LOTUS iMALL
        # ==========================================
        try:
            # If redirected to login page, log in automatically using email & password
            if "login" in lotus_page.url.lower() or lotus_page.locator("input[type='password']").count() > 0:
                print("[Lotus iMall] Logging in with credentials...")
                l_email = os.environ.get("LOTUS_EMAIL", "").strip()
                l_pass = os.environ.get("LOTUS_PASSWORD", "").strip()
                if l_email and l_pass:
                    lotus_page.locator("input[type='email'], input[type='text'], input[name*='user'], input[name*='email'], input[name*='id']").first.fill(l_email)
                    lotus_page.locator("input[type='password']").first.fill(l_pass)
                    lotus_page.locator("button[type='submit'], input[type='submit'], button:has-text('Login')").first.click()
                    lotus_page.wait_for_timeout(6000)
                    lotus_page.goto(LOTUS_URL, wait_until="domcontentloaded", timeout=45000)
                    lotus_page.wait_for_timeout(5000)

            l_text = lotus_page.inner_text("body")
            # Matches the pending order count above "PENDING Awaiting acceptance"
            l_match = re.search(r"(\d+)\s+PENDING\s+Awaiting acceptance", l_text, re.IGNORECASE)
            if l_match:
                l_count = int(l_match.group(1))
                print(f"[Lotus iMall] PENDING orders: {l_count}")
                if l_count > 0:
                    send_mobile_notification(f"You have {l_count} new order(s) waiting on Lotus iMall.", title="Lotus iMall", click_url=LOTUS_URL)
            else:
                print("[Lotus iMall] Could not find pending count. Text seen snippet:", l_text[:150].replace("\n", " "))
        except Exception as e:
            print("[Lotus iMall] Check error:", e)

        # Manual test notification if triggered from Actions page
        if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
            send_mobile_notification("Both Myntra and Lotus iMall checked successfully!", title="Checker Test", click_url=MYNTRA_URL)

        browser.close()

if __name__ == "__main__":
    main()
