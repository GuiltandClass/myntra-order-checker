import json
import os
import re
import urllib.request
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

MYNTRA_URL = "https://mdirect.myntrainfo.com/Orders/Search"
LOTUS_URL = "https://partners.lotusimall.com/Seller/Orders_new"

IS_MANUAL = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
# On scheduled runs, failure alerts are sent only if ALERT_ON_FAILURE=1 (avoids a ping every 30 min while debugging)
ALERT_ON_FAILURE = os.environ.get("ALERT_ON_FAILURE", "0") == "1"
DEBUG_CAPTURE = os.environ.get("DEBUG_CAPTURE", "1") == "1"

SAMESITE = {"strict": "Strict", "lax": "Lax", "no_restriction": "None", "none": "None"}


def notify(message, title="Order Alert", click_url=MYNTRA_URL, priority="high"):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority, "Click": click_url},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=15)
        print(f"[{title}] Notification sent!")
    except Exception as e:
        print(f"[{title}] ntfy error:", e)


def print_runner_ip():
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=10) as r:
            d = json.loads(r.read().decode())
        print("[Runner IP]", {k: d.get(k) for k in ("ip", "city", "region", "country", "org")})
    except Exception as e:
        print("[Runner IP] lookup failed:", e)


def load_cookies(context, raw):
    """Add cookies one by one, keeping secure/httpOnly/sameSite/expiry so they behave like the originals."""
    ok, bad = 0, 0
    for c in json.loads(raw):
        if not all(k in c for k in ("name", "value", "domain")):
            continue
        item = {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/")}
        if c.get("secure") is not None:
            item["secure"] = bool(c["secure"])
        if c.get("httpOnly") is not None:
            item["httpOnly"] = bool(c["httpOnly"])
        ss = SAMESITE.get(str(c.get("sameSite", "")).lower())
        if ss:
            item["sameSite"] = ss
        exp = c.get("expirationDate") or c.get("expires")
        if isinstance(exp, (int, float)) and exp > 0:
            item["expires"] = exp
        try:
            context.add_cookies([item])
            ok += 1
        except Exception as e:
            bad += 1
            print(f"[Cookies] skipped '{c['name']}':", str(e)[:100])
    print(f"[Cookies] loaded {ok}, skipped {bad}")


def watch_failures(page, label):
    def on_response(r):
        if r.status >= 400:
            print(f"[{label}] HTTP {r.status} {r.url.split('?')[0][:140]}")
    page.on("response", on_response)


def capture(page, name):
    if not DEBUG_CAPTURE:
        return
    try:
        page.screenshot(path=f"{name}_debug.png", full_page=True)
        with open(f"{name}_debug.html", "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception as e:
        print(f"[{name}] capture error:", e)


def settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)


def generic_login(page, email, password, label):
    try:
        page.locator("input[type='email'], input[type='text'], input[name*='user'], input[name*='email'], input[name*='id']").first.fill(email)
        page.locator("input[type='password']").first.fill(password)
        page.locator("button[type='submit'], input[type='submit'], button:has-text('Login'), button:has-text('Sign in')").first.click()
        page.wait_for_timeout(6000)
    except Exception as e:
        print(f"[{label}] login attempt error:", e)


def check_myntra(context):
    """Returns (state, count). state: ok | error_page | login_failed | unknown"""
    page = context.new_page()
    watch_failures(page, "Myntra")
    try:
        resp = page.goto(MYNTRA_URL, wait_until="domcontentloaded", timeout=45000)
        print("[Myntra] main response status:", resp.status if resp else None)
    except Exception as e:
        print("[Myntra] load warning:", e)
    settle(page)
    print("[Myntra] final URL:", page.url.split("?")[0])

    text = page.inner_text("body")

    # If we were bounced to a login form, try logging in from this runner
    if page.locator("input[type='password']").count() > 0:
        email = os.environ.get("MYNTRA_EMAIL", "").strip()
        password = os.environ.get("MYNTRA_PASSWORD", "").strip()
        if email and password:
            print("[Myntra] Login form detected, trying credentials...")
            generic_login(page, email, password, "Myntra")
            try:
                page.goto(MYNTRA_URL, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                print("[Myntra] reload warning:", e)
            settle(page)
            text = page.inner_text("body")
            if page.locator("input[type='password']").count() > 0:
                capture(page, "myntra")
                return "login_failed", None

    m = re.search(r"Open Orders\s*\((\d+)\)", text, re.IGNORECASE)
    if m:
        count = int(m.group(1))
        print(f"[Myntra] Open Orders: {count}")
        return "ok", count

    snippet = text[:150].replace("\n", " ")
    print("[Myntra] Could not find 'Open Orders'. Text seen:", snippet)
    capture(page, "myntra")
    if "something went wrong" in text.lower():
        return "error_page", None
    return "unknown", None


def check_lotus(context):
    """Returns (state, count). state: ok | maintenance | login_failed | unknown"""
    page = context.new_page()
    watch_failures(page, "Lotus")
    try:
        page.goto(LOTUS_URL, wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print("[Lotus iMall] load warning:", e)
    settle(page)

    text = page.inner_text("body")
    if "scheduled maintenance" in text.lower():
        print("[Lotus iMall] Site is under scheduled maintenance.")
        return "maintenance", None

    if "login" in page.url.lower() or page.locator("input[type='password']").count() > 0:
        email = os.environ.get("LOTUS_EMAIL", "").strip()
        password = os.environ.get("LOTUS_PASSWORD", "").strip()
        if email and password:
            print("[Lotus iMall] Logging in with credentials...")
            generic_login(page, email, password, "Lotus iMall")
            try:
                page.goto(LOTUS_URL, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                print("[Lotus iMall] reload warning:", e)
            settle(page)
            text = page.inner_text("body")
            if "scheduled maintenance" in text.lower():
                return "maintenance", None

    m = re.search(r"(\d+)\s+PENDING\s+Awaiting acceptance", text, re.IGNORECASE)
    if m:
        count = int(m.group(1))
        print(f"[Lotus iMall] PENDING orders: {count}")
        return "ok", count

    print("[Lotus iMall] Could not find pending count. Text seen:", text[:150].replace("\n", " "))
    capture(page, "lotus")
    return "unknown", None


def main():
    print_runner_ip()
    results = {}

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage", "--no-sandbox"],
        )
        # No hardcoded user-agent: a "Mac Chrome 129" UA on a Linux Chromium is itself a mismatch signal
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        raw = os.environ.get("MYNTRA_COOKIES", "").strip()
        if raw:
            try:
                load_cookies(context, raw)
            except Exception as e:
                print("Myntra cookie error:", e)

        for name, fn, url in (("Myntra", check_myntra, MYNTRA_URL), ("Lotus iMall", check_lotus, LOTUS_URL)):
            try:
                results[name] = fn(context)
            except Exception as e:
                print(f"[{name}] Check error:", e)
                results[name] = ("exception", None)

        browser.close()

    urls = {"Myntra": MYNTRA_URL, "Lotus iMall": LOTUS_URL}
    for name, (state, count) in results.items():
        if state == "ok" and count and count > 0:
            notify(f"You have {count} new order(s) waiting on {name}.", title=name, click_url=urls[name])
        elif state == "maintenance":
            if IS_MANUAL:
                notify(f"{name} is under scheduled maintenance.", title=f"{name} maintenance", click_url=urls[name], priority="low")
        elif state != "ok":
            if IS_MANUAL or ALERT_ON_FAILURE:
                notify(
                    f"{name} check could not read orders (state: {state}). Session may be expired or blocked; orders are NOT being monitored.",
                    title=f"{name} check FAILED",
                    click_url=urls[name],
                    priority="default",
                )

    if IS_MANUAL:
        summary = " | ".join(f"{n}: {s}" + (f" ({c})" if c is not None else "") for n, (s, c) in results.items())
        notify(summary, title="Checker Test", click_url=MYNTRA_URL, priority="low")


if __name__ == "__main__":
    main()
