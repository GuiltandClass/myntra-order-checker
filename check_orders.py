import json
import os
import re
import smtplib
from email.message import EmailMessage
import urllib.request
from playwright.sync_api import sync_playwright

URL = "https://mdirect.myntrainfo.com/Orders/Search"

def send_mobile_notification(message, title="Myntra"):
    # 1. Instant Mobile Push Notification via ntfy.sh
    ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
    if ntfy_topic:
        try:
            req = urllib.request.Request(
                f"https://ntfy.sh/{ntfy_topic}",
                data=message.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": "high",
                    "Click": URL,
                },
            )
            urllib.request.urlopen(req, timeout=15)
            print("Mobile push notification sent via ntfy!")
        except Exception as e:
            print("ntfy error:", e)

    # 2. Email Notification (Optional)
    email_addr = os.environ.get("EMAIL_ADDRESS", "").strip()
    email_pass = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    if email_addr and email_pass:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"{title}: {message}"
            msg["From"] = email_addr
            msg["To"] = email_addr
            msg.set_content(f"{message}\n\nManage orders: {URL}")
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
                smtp.login(email_addr, email_pass)
                smtp.send_message(msg)
            print("Email notification sent!")
        except Exception as e:
            print("Email error:", e)

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
        )

        # Load saved session cookies
        cookies_raw = os.environ.get("MYNTRA_COOKIES", "").strip()
        if cookies_raw:
            try:
                raw_cookies = json.loads(cookies_raw)
                clean_cookies = []
                for c in raw_cookies:
                    if "name" in c and "value" in c and "domain" in c:
                        clean_cookies.append({
                            "name": str(c["name"]),
                            "value": str(c["value"]),
                            "domain": str(c["domain"]),
                            "path": str(c.get("path", "/")),
                        })
                context.add_cookies(clean_cookies)
                print(f"Loaded {len(clean_cookies)} session cookies.")
            except Exception as e:
                print("Cookie load warning:", e)

        page = context.new_page()
        print("Opening Myntra MDirect...")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)

        # If redirected to login page, try logging in with Email + Password
        if "login" in page.url.lower() or page.locator("input[type='password']").count() > 0:
            print("Session cookies redirected to login. Trying email/password...")
            email = os.environ.get("MYNTRA_EMAIL", "").strip()
            password = os.environ.get("MYNTRA_PASSWORD", "").strip()
            if email and password:
                try:
                    page.locator("input[type='email'], input[type='text'], input[name*='user'], input[name*='email']").first.fill(email)
                    page.locator("input[type='password']").first.fill(password)
                    page.locator("button[type='submit'], button:has-text('Login'), button:has-text('Sign')").first.click()
                    page.wait_for_timeout(8000)
                    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(8000)
                except Exception as e:
                    print("Auto-login error:", e)
            else:
                send_mobile_notification(
                    "Session expired. Please refresh MYNTRA_COOKIES in GitHub.",
                    title="Myntra Action Required"
                )
                browser.close()
                return

        body_text = page.inner_text("body")
        match = re.search(r"Open Orders\s*\((\d+)\)", body_text, re.IGNORECASE)

        if match:
            order_count = int(match.group(1))
            print(f"Found Open Orders ({order_count})")
            if order_count == 1:
                send_mobile_notification(
                    "You have 1 new order waiting for fulfillment.",
                    title="Myntra"
                )
            elif order_count > 1:
                send_mobile_notification(
                    f"You have {order_count} new orders waiting for fulfillment.",
                    title="Myntra"
                )
        else:
            print("Currently says 'Open Orders' with 0 new orders.")
            # If triggered manually via button click, send a preview of how a real order notification looks!
            if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
                send_mobile_notification(
                    "You have 1 new order waiting for fulfillment. (Test Preview — 0 actual orders)",
                    title="Myntra"
                )

        browser.close()

if __name__ == "__main__":
    main()
