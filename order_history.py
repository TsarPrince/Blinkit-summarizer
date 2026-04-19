#!/usr/bin/env python3
"""Blinkit order history aggregator - uses Chrome TLS impersonation to bypass Cloudflare."""

import csv
import os
import re
import sys
import time
from curl_cffi import requests

FETCH = 10
CURL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "curl.sh")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def parse_curl_file(path):
    """Parse a 'Copy as cURL' file into headers and cookies dicts."""
    with open(path) as f:
        content = f.read()

    # Join continuation lines
    content = content.replace("\\\n", " ")

    headers = {}
    cookies = {}

    for m in re.finditer(r"-H\s+'([^:]+):\s*(.*?)'", content):
        headers[m.group(1).lower()] = m.group(2)

    # -b or --cookie
    cookie_match = re.search(r"(?:-b|--cookie)\s+'([^']+)'", content)
    if cookie_match:
        for pair in cookie_match.group(1).split("; "):
            if "=" in pair:
                k, v = pair.split("=", 1)
                cookies[k.strip()] = v.strip()

    # Remove content-length (curl_cffi handles it)
    headers.pop("content-length", None)

    return headers, cookies


def fetch_json(url, headers, cookies, retries=2):
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, cookies=cookies, impersonate="chrome")
        except Exception as e:
            print(f"[!] Request failed: {e}")
            return None

        if resp.status_code == 403 and attempt < retries:
            # Refresh cookies from curl.sh and retry
            time.sleep(2)
            _, fresh_cookies = parse_curl_file(CURL_FILE)
            cookies.update(fresh_cookies)
            continue

        if resp.status_code != 200:
            print(f"  [!] HTTP {resp.status_code} for {url.split('?')[0].split('/')[-1]}")
            return None

        try:
            return resp.json()
        except Exception:
            return None
    return None


def extract_price(text):
    """Extract the final price from subtitle3 markdown like '~~<regular-200|{grey-600|₹47}>~~ ₹39'."""
    matches = re.findall(r"₹([\d,.]+)", text or "")
    if matches:
        return matches[-1].replace(",", "")
    return ""


def parse_order_date(text):
    """Parse 'placed on Sun, 29 Mar'26, 7:41 PM' -> datetime."""
    from datetime import datetime
    # Strip "placed on " prefix and day name
    m = re.search(r"(\d{1,2})\s+(\w+)'(\d{2}),\s*(\d{1,2}):(\d{2})\s*(AM|PM)", text or "", re.IGNORECASE)
    if not m:
        return None
    day, mon_str, yr2, hour, minute, ampm = m.groups()
    month_map = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                 "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
    month = month_map.get(mon_str.lower()[:3])
    if not month:
        return None
    year = 2000 + int(yr2)
    h = int(hour)
    if ampm.upper() == "PM" and h != 12:
        h += 12
    elif ampm.upper() == "AM" and h == 12:
        h = 0
    return datetime(year, month, int(day), h, int(minute))


def parse_ddmmyyyy(s):
    from datetime import datetime
    return datetime.strptime(s, "%d%m%Y")


def main():
    if len(sys.argv) != 3:
        print("Usage: order_history.py <start_date> <end_date>")
        print("  Dates in ddmmyyyy format (both inclusive)")
        print()
        print("Example:")
        print("  .venv/bin/python order_history.py 15012026 19042026")
        sys.exit(1)

    start_dt = sys.argv[1]
    end_dt = sys.argv[2]

    headers, cookies = parse_curl_file(CURL_FILE)
    if not headers:
        print(f"[!] No headers found in {CURL_FILE}. Paste a 'Copy as cURL' command there.")
        sys.exit(1)

    start = parse_ddmmyyyy(start_dt).replace(hour=0, minute=0, second=0)
    end = parse_ddmmyyyy(end_dt).replace(hour=23, minute=59, second=59)
    print(f"[+] {start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}")

    rows = []
    next_page_url = None
    page_num = 0
    stop = False

    while not stop:
        if next_page_url:
            url = next_page_url
        else:
            url = "https://blinkit.com/v1/layout/order_history"

        data = fetch_json(url, headers, cookies)
        if not data:
            break

        snippets = data.get("snippets", []) or data.get("response", {}).get("snippets", [])

        orders = []
        for s in snippets:
            if s.get("widget_type") == "order_history_container_vr":
                attrs = s.get("tracking", {}).get("common_attributes", {})
                order_id = attrs.get("order_id")
                deeplink = attrs.get("deeplink", "")
                m = re.search(r"cart_id=(\d+)", deeplink)
                cart_id = m.group(1) if m else ""
                if order_id:
                    orders.append((order_id, cart_id))

        if not orders:
            break

        for order_id, cart_id in orders:
            detail_url = f"https://blinkit.com/v1/layout/order_details/{order_id}?cart_id={cart_id}"
            details = fetch_json(detail_url, headers, cookies)
            if not details:
                print(f"  [!] detail fetch failed for order {order_id}")
                continue

            detail_snippets = details.get("snippets", []) or details.get("response", {}).get("snippets", [])

            # Extract timestamp from "Order placed" snippet and ORD-style order id
            timestamp_str = ""
            order_dt = None
            display_order_id = order_id
            for s in detail_snippets:
                d = s.get("data", {})
                if d.get("title", {}).get("text") == "Order placed":
                    timestamp_str = d.get("subtitle2", {}).get("text", "")
                    order_dt = parse_order_date(timestamp_str)
                btn = d.get("button", {})
                clipboard = btn.get("click_action", {}).get("copy_to_clipboard", {}).get("text", "")
                if clipboard.startswith("ORD"):
                    display_order_id = clipboard.strip()

            if not order_dt:
                continue

            # Check date range
            if order_dt > end:
                continue
            if order_dt < start:
                print(f"  -- reached {order_dt.strftime('%d %b %Y')}, stopping --")
                stop = True
                break

            formatted_ts = order_dt.strftime("%d %b %Y, %I:%M %p")

            # Extract charges and bill total from cart_bill_item snippets
            # Only include rows after "Item total" (those are actual charges)
            charge_rows = []
            bill_total = ""
            past_item_total = False
            for s in detail_snippets:
                if s.get("widget_type") == "cart_bill_item":
                    d = s.get("data", {})
                    label = d.get("left_header", {}).get("text", "").strip()
                    value_raw = d.get("right_header", {}).get("text", "").strip()
                    vm = re.search(r"₹([\d,.]+)", value_raw)
                    value = vm.group(1).replace(",", "") if vm else ""
                    if label.lower() == "item total":
                        past_item_total = True
                        continue
                    if not past_item_total:
                        continue
                    if label.lower() == "bill total":
                        bill_total = value
                    else:
                        charge_label = label or value_raw.strip()
                        if value:
                            charge_rows.append((charge_label, value))

            item_snippets = [s for s in detail_snippets if s.get("widget_type") == "z_v3_image_text_snippet_type_30"]

            for s in item_snippets:
                d = s.get("data", {})
                name = d.get("title", {}).get("text", "")
                subtitle1 = d.get("subtitle1", {}).get("text", "")
                subtitle3 = d.get("subtitle3", {}).get("text", "")

                pack_match = re.match(r"^(\d+)\s*x\s*([\d.]+)\s*(\S+)\s*x\s*(\d+)$", subtitle1 or "")
                simple_match = re.match(r"^([\d.]+)\s*(\S+)\s*x\s*(\d+)$", subtitle1 or "")
                if pack_match:
                    pack = int(pack_match.group(1))
                    amount = pack_match.group(2)
                    unit = pack_match.group(3)
                    qty = pack * int(pack_match.group(4))
                elif simple_match:
                    amount = simple_match.group(1)
                    unit = simple_match.group(2)
                    qty = int(simple_match.group(3))
                else:
                    amount = ""
                    unit = ""
                    qty = 1

                price = extract_price(subtitle3)

                if name:
                    rows.append((display_order_id, formatted_ts, name, amount, unit, qty, price, bill_total))

            # Add charge rows (with empty amount, unit, qty)
            for label, value in charge_rows:
                rows.append((display_order_id, formatted_ts, label, "", "", "", value, bill_total))

            n_items = len(item_snippets)
            print(f"  {formatted_ts}  {display_order_id}  {n_items} items  ₹{bill_total}")

        if stop:
            break

        # Extract pagination from response.pagination.next_url
        resp_obj = data.get("response", data)
        pagination = resp_obj.get("pagination", {})
        next_url = pagination.get("next_url", "") if isinstance(pagination, dict) else ""

        if next_url:
            next_page_url = f"https://blinkit.com{next_url}"
            page_num += 1
            print(f"--- page {page_num + 1} ---")
        else:
            next_page_url = None

        if not next_page_url:
            break

    # Write CSV
    output_csv = os.path.join(BASE_DIR, f"orders_{start_dt}-{end_dt}.csv")
    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["order_id", "timestamp", "item", "amount", "unit", "qty", "price", "bill_total"])
        writer.writerows(rows)

    print(f"\n[+] {len(rows)} rows -> {os.path.basename(output_csv)}")


if __name__ == "__main__":
    main()
