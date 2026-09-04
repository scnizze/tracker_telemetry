# Tracker Telemetry API

A small service that ingests telemetry from a satellite/LTE GNSS tracker
device (position, battery, satellite count, events) and lets you query it
back. Built as a hands-on DevOps learning project: this app itself is
intentionally simple — the interesting part is everything we do *around*
it (containerize it, add CI/CD, observe it, deploy it).

## Run locally (no Docker yet)

```
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs to try it interactively.

## Example request

```
curl -X POST http://127.0.0.1:8000/telemetry ^
  -H "Content-Type: application/json" ^
  -d "{\"device_id\": \"tracker-01\", \"ts\": \"2026-09-03T09:00:00Z\", \"lat\": 51.169, \"lon\": 71.449, \"battery_pct\": 87.5, \"satellites\": 9}"
```
