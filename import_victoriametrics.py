#!/usr/bin/env python3
"""Import a Netze BW smart-meter CSV (download_csv.py output) into VictoriaMetrics.

See https://docs.victoriametrics.com/victoriametrics/#how-to-import-csv-data

Usage:
    ./import_victoriametrics.py [path/to/file.csv]
    VM_URL=http://host:8428 ./import_victoriametrics.py --consumption-metric power_kwh --meter-metric reading_kwh
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx2

VM_URL = os.environ.get("VM_URL", "http://localhost:8428")
TZ = ZoneInfo("Europe/Berlin")

METRICS = [
    # (source column header prefix, default metric name)
    ("Verbrauch", "netzebw_consumption_kwh"),
    ("Zaehlerstand", "netzebw_meter_reading_kwh"),
]


def find_latest_csv(base_path: str = "out") -> Path:
    return max(Path(base_path).glob("*.csv"), key=Path.stat)


def load(path: Path) -> dict[str, list[tuple[int, str, str]]]:
    """Parse the CSV into {column prefix: [(unix_seconds, value, tarif), ...]}."""
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        cols = {
            prefix: next(i for i, h in enumerate(header) if h.startswith(prefix))
            for prefix, _ in METRICS
        }
        series = {prefix: [] for prefix in cols}
        for line in reader:
            if not line or not line[0]:
                continue  # empty line
            ts = int(datetime.strptime(f"{line[0]} {line[1]}", "%d.%m.%Y %H:%M").replace(tzinfo=TZ).timestamp())
            for prefix, col in cols.items():
                value = line[col].replace(",", ".")  # 2,1441 -> 2.1441
                if value:  # e.g. the first row of a window has no consumption value
                    series[prefix].append((ts, value, line[5]))
    return series


def post_metric(name: str, rows: list[tuple[int, str, str]]) -> None:
    # format rules reference 1-based column positions in each POSTed line
    fmt = f"1:time:unix_s,2:metric:{name},3:label:tarif"
    body = "\n".join(f"{ts},{value},{tarif}" for ts, value, tarif in rows)
    r = httpx2.post(f"{VM_URL}/api/v1/import/csv", params={"format": fmt}, content=body.encode())
    r.raise_for_status()
    print(f"imported {len(rows)} rows -> {name} (HTTP {r.status_code})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a Netze BW smart-meter CSV into VictoriaMetrics.")
    parser.add_argument("file", nargs="?", type=Path, help="CSV path (default: newest file in out/)")
    parser.add_argument("--consumption-metric", default="netzebw_consumption_kwh", metavar="NAME", help="metric name for the Verbrauch column")
    parser.add_argument("--meter-metric", default="netzebw_meter_reading_kwh", metavar="NAME", help="metric name for the Zaehlerstand column")
    args = parser.parse_args()

    path = args.file or find_latest_csv("out")
    print(f"importing {path} into {VM_URL}")

    names = {"Verbrauch": args.consumption_metric, "Zaehlerstand": args.meter_metric}
    for prefix, rows in load(path).items():
        name = names[prefix]
        if rows:
            post_metric(name, rows)
        else:
            print(f"{name}: no rows, skipping")


if __name__ == "__main__":
    main()
