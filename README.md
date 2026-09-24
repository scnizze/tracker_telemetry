# Tracker Telemetry API

A small service that ingests telemetry from a satellite/LTE GNSS tracker
device (position, battery, satellite count, events) and lets you query it
back. Built as a hands-on DevOps learning project: this app itself is
intentionally simple — the interesting part is everything we do *around*
it (containerize it, add CI/CD, observe it, deploy it).

It now also has an **end-to-end pipeline for real device data**: Iridium
emails an `.sbd` file every time your NOMAD tracker uplinks → a poller
script decodes it and saves it to the database → a `/map` page shows
where the tracker has been. See "Email → decode → map" below.

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

## Email → decode → map

This is the automated path for real hardware: Iridium's SBD service
emails you the raw uplink as a `.sbd` attachment; `email_poller.py`
watches that inbox, decodes each attachment with `app/sbd_frame.py`
(same wire format as `sbd_decode.py`, the standalone CLI tool for
eyeballing one frame by hand), and writes the result straight into the
database. The API and the map just read what the poller wrote.

```
[NOMAD tracker] --SBD--> [Iridium] --email w/ .sbd attachment--> [Gmail]
                                                                     |
                                                          email_poller.py (polls every 60s)
                                                                     |
                                                                     v
                                                          app/sbd_frame.py decodes it
                                                                     |
                                                                     v
                                                    sbd_messages / sbd_positions tables
                                                                     |
                                        +----------------------------+----------------------------+
                                        v                                                         v
                             app/main.py's /sbd/... endpoints                              /map (Leaflet page)
```

**One-time setup (Gmail):**

1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
   (any name works, e.g. "tracker-telemetry"). This 16-character code is
   what the poller logs in with — never your real Gmail password.
3. Copy `.env.example` to `.env` and fill in `GMAIL_USER` and
   `GMAIL_APP_PASSWORD`. `.env` is git-ignored on purpose; it holds a
   password and must never be committed.

**Run the poller** (in its own terminal, separate from the API):

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then edit .env with real values
python email_poller.py
```

It logs one line per check ("checked mailbox: nothing new" / "N new
message(s)") so you can see it's alive. Leave it running.

**Run the API and open the map** (in a second terminal):

```
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/map — pick a device from the dropdown to see
its position history as a path, newest fix highlighted in red. It
refreshes itself every 30 seconds.

**Useful endpoints while debugging:**

- `GET /sbd/devices` — every IMEI we've decoded a message from
- `GET /sbd/messages/{imei}` — raw decoded messages (battery, flags, msg type), newest first
- `GET /sbd/positions/{imei}` — the position history the map draws, oldest first

