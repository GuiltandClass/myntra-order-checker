import json
import os
import re
import smtplib
from email.message import EmailMessage
import urllib.request
from playwright.sync_api import sync_playwright

URL = "https://mdirect.myntrainfo.com/Orders/Search"


def send_mobile_notification(message):
  # 1. Instant Mobile Push Notification via ntfy.sh (100% Free)
  ntfy_topic = os.environ.get("NTFY_TOPIC", "").strip()
  if ntfy_topic:
    req = urllib.request.Request(
        f"https://ntfy.sh/{ntfy_topic}",
        data=message.encode("utf-8"),
        headers={
            "Title": "New Myntra MDirect Order!",
            "Priority": "high",
            "Tags": "shopping_bags,bell",
        },
    )
    urllib.request.urlopen(req)
    print("Mobile push notification sent!")

  # 2. Email Notification (Optional - runs if EMAIL_ADDRESS is added)
  email_addr = os.environ.get("EMAIL_ADDRESS", "").strip()
  email_pass = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
  if email_addr and email_pass:
    msg = EmailMessage()
    msg["Subject"] = f"🚨 Myntra Alert: {message}"
    msg["From"] = email_addr
    msg["To"] = email_addr
    msg.set_content(f"{message}\n\nCheck here: {URL}")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
      smtp.login(email_addr, email_pass)
      smtp.send_message(msg)
    print("Email notification sent!")


def main():
  with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})

    # Load saved session cookies if provided
    cookies_raw = os.environ.get("MYNTRA_COOKIES", "").strip()
    if cookies_raw:
      try:
        raw_cookies = json.loads(cookies_raw)
        clean_cookies = []
        for c in raw_cookies:
          cookie = {
              "name": c["name"],
              "value": c["value"],
              "domain": c["domain"],
              "path": c.get("path", "/"),
          }
          clean_cookies.append(cookie)
        context.add_cookies(clean_cookies)
      except Exception as e:
        print("Cookie load warning:", e)

    page = context.new_page()
    page.goto(URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(5000)

    # If redirected to a login page, log in automatically using Email + Password
    if (
        "login" in page.url.lower()
        or page.locator("input[type='password']").count() > 0
    ):
      print("Session expired, logging in with credentials...")
      email = os.environ.get("MYNTRA_EMAIL", "")
      password = os.environ.get("MYNTRA_PASSWORD", "")
      if email and password:
        page.locator("input[type='email'], input[type='text']").first.fill(
            email
        )
        page.locator("input[type='password']").first.fill(password)
        page.locator("button[type='submit'], button:has-text('Login')").first.click()
        page.wait_for_Load_state("networkidle")
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)
      else:
        send_mobile_notification(
            "⚠️ Myntra session expired! Please refresh MYNTRA_COOKIES."
        )
        return

    # Look for the "Open Orders" button text on the page
    body_text = page.inner_text("body")
    match = re.search(r"Open Orders\s*\((\d+)\)", body_text, re.IGNORECASE)

    if match:
      order_count = int(match.group(1))
      print(f"Found Open Orders ({order_count})")
      if order_count > 0:
        send_mobile_notification(
            f"You have Open Orders ({order_count}) waiting on Myntra MDirect!"
        )
    else:
      print("Currently says 'Open Orders' with no new order count (0 orders).")

    browser.close()


if __name__ == "__main__":
  main()
