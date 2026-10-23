# netzebw-im

A simple script to download electricity meter measurement data ("Intelligentes Messystem", aka. "IM") from the NetzeBW portal at [meine.netze-bw.de](https://meine.netze-bw.de) as CSV.

Currently, the portal only exposes data up until past midnight, that is, you'll always only get data from yesterday or earlier.

## Prerequisites
* Python >= 3.12
* [uv](https://github.com/astral-sh/uv) package manager (or Poetry)

## Installation
```bash
uv sync
```

## Usage
### Example
```bash
export NETZE_BW_EMAIL=johndoe@example.org
export NETZE_BW_PASSWORD=yoursecretpassword

uv run download_csv.py \
    --imid 504A93108B83002A55E6B6359E606BB3 \
    --start 2026-10-01 \
    --end 2026-10-05 \
    --output out/data.csv
```

### Parameter
All parameters are optional.
- `imid`: ID of your measurement system. Find it from the browser URL bar on the portal page that displays the statistics. If ommitted, defaults to the first IM system found in your account.
- `start`: Start of date range to fetch in format `YYYY-mm-dd` (Germany time zone). Defaults to midnight yesterday.
- `end`: End of date range to fetch in format `YYYY-mm-dd` (Germany time zone). Defaults to midnight today (i.e. last midnight).
- `output`: Output path for the CSV download. Defaults to `out/<start>_<end>.csv`.

You may want to run this on regular basis as a cron job, e.g.:
```
30 0 * * *    uv run download_csv.py
```

## VictoriaMetrics ingest
There's a second script `import_victoriametrics.py`, which allows to backfill the downloaded data into [VictoriaMetrics](https://victoriametrics.com) via its [CSV import endpoint](https://docs.victoriametrics.com/victoriametrics/#how-to-import-csv-data).

### Usage example
```bash
VM_URL=http://localhost:8428 uv run import_victoriametrics.py \
    --consumption-metrics netzebw_consumption_kwh \
    --meter-metrics netzebw_meter_reading_kwh \
    out/data.csv
```

### Grafana / PromQL queries
#### Power draw in kW
```promql
sum by (tarif) (netzebw_consumption_kwh) * 4
```

#### Daily totals in kWh
```promql
sum by (tarif) (sum_over_time(netzebw_consumption_kwh[1d]))
```

Set "Min interval / step" to `1d` in GRafana for this.

#### Total in current range in kWh
```promql
sum by (tarif) sum(increase(netzebw_meter_reading_kwh[$__range]))
```

#### Peak in current range in kW
```promql
sum by (tarif) max(max_over_time(netzebw_consumption_kwh[$__range])) * 4
```
