#!/usr/bin/env python3
"""Log in to meine.netze-bw.de and download the smart-meter (IMS) measurements CSV.

Usage:
    pip install httpx2
    # Credentials: NETZE_BW_EMAIL / NETZE_BW_PASSWORD env vars
    ./netze_bw.py [--imid 504A93108B83002A55E6B6359E606BB3] [--start 2026-09-15] [--end 2026-10-16]

    --imid omits the installation lookup; --start/--end (YYYY-MM-DD or ISO datetimes, naive = UTC) default to "last 30 days".
"""

import argparse
import base64
import getpass
import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import httpx2  # Pydantic-maintained successor of httpx; same API, `import httpx2 as httpx` works too

PORTAL = "https://meine.netze-bw.de"
AUTH0_DOMAIN = "login.netze-bw.de"
CONNECTION = "Username-Password-Authentication"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:156.0) Gecko/20100101 Firefox/156.0"}
API_TIME_FMT = "%Y-%m-%dT%H:%M:%S.000Z"


def login(email: str, password: str) -> httpx2.Client:
    s = httpx2.Client(headers=HEADERS, follow_redirects=True, timeout=30.0)

    r = s.get(f"{PORTAL}/bff/auth/login?returnUrl=/signin?target=%2F", follow_redirects=False)
    authorize_url = r.headers["Location"]
    r = s.get(authorize_url, follow_redirects=False)
    login_page = s.get(urljoin(authorize_url, r.headers["Location"]))  # sets the `_csrf` cookie

    blob = re.search(r'window\.atob\("([^"]+)"\)', login_page.text).group(1)
    cfg = json.loads(base64.b64decode(blob))
    extra = {k: v for k, v in cfg["extraParams"].items() if not k.startswith("x-client")}

    r = s.post(
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

    form_action = re.search(r'<form[^>]*action="([^"]+)"', r.text).group(1)
    fields = {
        m.group(1): html.unescape(m.group(2))
        for m in re.finditer(r'name="([^"]+)"\s+value="([^"]*)"', r.text, re.S)
    }
    s.post(form_action, data=fields)
    return s


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def find_meter(client: httpx2.Client) -> dict:
    installations = client.get(f"{PORTAL}/bff/api/kuposervice/v1/portal/installations").json()["installations"]
    return next(i for i in installations if i.get("type") == "IMS")


def download_csv(client: httpx2.Client, meter_id: str, start: datetime, end: datetime) -> None:
    r = client.get(
        f"{PORTAL}/bff/api/imsservice/v1/meters/{meter_id}/measurements/download",
        params={"startDate": start.strftime(API_TIME_FMT), "endDate": end.strftime(API_TIME_FMT)},
    )
    out = f"{meter_id}.csv"
    with open(out, "wb") as f:
        f.write(r.content)
    print(f"saved {out} ({len(r.content)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the Netze BW smart-meter measurements CSV.")
    parser.add_argument("--imid", help="measuring system (IMS) installation id; auto-discovered when omitted")
    parser.add_argument("--start", help="window start, YYYY-MM-DD or ISO datetime (default: 30 days ago)")
    parser.add_argument("--end", help="window end, YYYY-MM-DD or ISO datetime (default: now)")
    args = parser.parse_args()

    email = os.environ.get("NETZE_BW_EMAIL") or input("email: ")
    password = os.environ.get("NETZE_BW_PASSWORD") or getpass.getpass()

    s = login(email, password)

    if args.imid:
        meter_id = args.imid
    else:
        meter = find_meter(s)
        meter_id = meter["id"]
        print(f"meter: {meter_id} ({meter.get('meterId')}, {meter['address']['postalCode']} {meter['address']['city']})")

    now = datetime.now(timezone.utc)
    download_csv(
        s,
        meter_id,
        parse_ts(args.start) if args.start else now - timedelta(days=30),
        parse_ts(args.end) if args.end else now,
    )


if __name__ == "__main__":
    main()
