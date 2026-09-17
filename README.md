# collector_ons_business_prices_uk

Standalone collector for official ONS Producer Price Inflation (PPI) and Services Producer Price Inflation (SPPI) CSV releases. The curated raw set has 15 PPI and 12 SPPI CDIDs (27 series), 5,965 observations, and history from 1957-01 through 2026-08. Identifiers retain the 2015 base to make rebasing explicit.

Latest observations use the official publication timestamp. Older values in a current artifact without archived release evidence are `first_seen`, so revisions never inherit an earlier date.

## Install and run (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
Copy-Item .env.example .env
pytest -q
python main.py
```

Set `COLLECTOR_DB_URL` and allow `ons.gov.uk`. Databricks is optional via `.[databricks]`; no sibling repository is used. Source smoke: `python -c "from scripts.extract import collect; x=collect(); print(len(x.catalog), len(x.observations))"`.

See [METHODOLOGY.md](METHODOLOGY.md) and [POINT_IN_TIME.md](POINT_IN_TIME.md).
