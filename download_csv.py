#!/usr/bin/env python3
"""Log in to meine.netze-bw.de and download the smart-meter (IMS) measurements CSV.

Usage:
    pip install httpx2
    # Credentials: NETZE_BW_EMAIL / NETZE_BW_PASSWORD env vars
    ./download_csv.py [--imid 504A93108B83002A55E6B6359E606BB3] [--start 2026-09-15] [--end 2026-10-16] [--imid 504A93108A83006A55E6B6359E606BA1] [--output out/data.csv]
"""

import argparse
import base64
import getpass
import html
import json
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx2

PORTAL = "https://meine.netze-bw.de"
AUTH0_DOMAIN = "login.netze-bw.de"
CONNECTION = "Username-Password-Authentication"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:156.0) Gecko/20100101 Firefox/156.0"}
TZ = ZoneInfo("Europe/Berlin")
API_TIME_FMT = "%Y-%m-%dT%H:%M:%S.000Z"  # the API expects UTC


def login(email: str, password: str) -> httpx2.Client:
    client = httpx2.Client(headers=HEADERS, follow_redirects=True, timeout=30.0)

    r1 = client.get(f"{PORTAL}/bff/auth/login?returnUrl=/signin?target=%2F", follow_redirects=False)
    authorize_url = r1.headers["Location"]
    r2 = client.get(authorize_url, follow_redirects=False)
    r3 = client.get(urljoin(authorize_url, r2.headers["Location"]))  # sets the `_csrf` cookie

    blob = re.search(r'window\.atob\("([^"]+)"\)', r3.text).group(1)
    cfg = json.loads(base64.b64decode(blob))
    extra = {k: v for k, v in cfg["extraParams"].items() if not k.startswith("x-client")}

    r4 = client.post(
        f"https://{AUTH0_DOMAIN}/usernamepassword/login",
        json={
            "client_id": cfg["clientID"],
            "tenant": cfg["auth0Tenant"],
            "redirect_uri": cfg["callbackURL"],
            "connection": cfg.get("connection", CONNECTION),
            "username": email,
            "password": password,
            "popup_options": {},
            "sso": True,
            **extra,
        },
    )

    form_action = re.search(r'<form[^>]*action="([^"]+)"', r4.text).group(1)
    fields = {
        m.group(1): html.unescape(m.group(2))
        for m in re.finditer(r'name="([^"]+)"\s+value="([^"]*)"', r4.text, re.S)
    }
    client.post(form_action, data=fields)
    return client


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=TZ)


def find_meter(client: httpx2.Client) -> dict:
    r = client.get(f"{PORTAL}/bff/api/kuposervice/v1/portal/installations", headers={"x-csrf": "1"})
    r.raise_for_status()
    installations = r.json()["installations"]
    return next(i for i in installations if i.get("type") == "IMS")


def download_csv(client: httpx2.Client, meter_id: str, start: datetime, end: datetime, out_path: str) -> None:
    r = client.get(
        f"{PORTAL}/bff/api/imsservice/v1/meters/{meter_id}/measurements/download",
        params={
            "startDate": start.astimezone(timezone.utc).strftime(API_TIME_FMT),
            "endDate": end.astimezone(timezone.utc).strftime(API_TIME_FMT),
        },
        headers={"x-csrf": "1"},
    )
    r.raise_for_status()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.content)
    print(f"saved {out} ({len(r.content)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the Netze BW smart-meter measurements CSV.")
    parser.add_argument("--imid", help="measuring system (IMS) installation id or auto-discovered when omitted")
    parser.add_argument("--start", help="window start, YYYY-MM-DD or ISO datetime, naive times = Europe/Berlin (default: midnight starting yesterday)")
    parser.add_argument("--end", help="window end, YYYY-MM-DD or ISO datetime, naive times = Europe/Berlin (default: last midnight = end of yesterday)")
    parser.add_argument("-o", "--output", help="output CSV path (default: out/<start>_<end>.csv of the requested window)")
    args = parser.parse_args()

    email = os.environ.get("NETZE_BW_EMAIL") or input("email: ")
    password = os.environ.get("NETZE_BW_PASSWORD") or getpass.getpass()

    client = login(email, password)

    if args.imid:
        meter_id = args.imid
    else:
        meter = find_meter(client)
        meter_id = meter["id"]
        print(f"meter: {meter_id} ({meter.get('meterId')}, {meter['address']['postalCode']} {meter['address']['city']})")

    today = datetime.now(TZ).date()
    start = parse_ts(args.start) if args.start else midnight(today - timedelta(days=1))
    end = parse_ts(args.end) if args.end else midnight(today)
    out = args.output or f"out/{start:%Y-%m-%d}_{end:%Y-%m-%d}.csv"
    download_csv(client, meter_id, start, end, out)


if __name__ == "__main__":
    main()
