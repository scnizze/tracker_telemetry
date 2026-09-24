"""
Telemetry ingestion API.

Modeled on the hybrid satellite/LTE GNSS tracker: a device periodically
reports its position, battery, and satellite count, and occasionally an
event (e.g. leaving a geofence). This service accepts those reports and
lets you query them back.

It now also serves the *decoded SBD side* of the same tracker: positions
that email_poller.py pulled out of Iridium SBD emails and saved via
app/database.py's sbd_messages/sbd_positions tables (see app/sbd_frame.py
for the decoding itself), plus a /map page to look at them.

Run it directly (before/without Docker):

    python -m venv .venv
    .venv\\Scripts\\activate        # Windows
    pip install -r requirements.txt
    uvicorn app.main:app --reload

Or via docker-compose (API + Postgres together):

    docker compose up --build

Then open http://127.0.0.1:8000/docs for the interactive API docs, or
http://127.0.0.1:8000/map for the map.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from typing import List

from app.database import init_db, engine, telemetry, sbd_messages, sbd_positions
from app.models import TelemetryIn, TelemetryOut, PositionOut, SbdMessageOut


app = FastAPI(title="Tracker Telemetry API", version="0.3.0")

# Anything under app/static/ is served as-is at /static/... . map.html
# lives there because it's a static page: plain HTML/JS that calls the
# JSON endpoints below, no server-side templating needed.
app.mount("/static", StaticFiles(directory="app/static"), name="static")



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once before the app starts accepting requests.
    init_db()
    yield
    # (nothing to clean up on shutdown yet)


app = FastAPI(title="Tracker Telemetry API", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health():
    """
    A health check endpoint. This looks trivial, but it's a real DevOps
    building block: load balancers, orchestrators (Kubernetes), and
    monitoring systems all poll something like this to decide whether
    an instance of your app is alive and should keep receiving traffic.
    """
    return {"status": "ok"}


@app.post("/telemetry", response_model=TelemetryOut, status_code=201)
def ingest(reading: TelemetryIn):
    with engine.begin() as conn:
        result = conn.execute(telemetry.insert().values(**reading.model_dump()))
        new_id = result.inserted_primary_key[0]
        row = conn.execute(
            telemetry.select().where(telemetry.c.id == new_id)
        ).mappings().first()
        return dict(row)


@app.get("/telemetry/{device_id}", response_model=List[TelemetryOut])
def list_readings(device_id: str, limit: int = 50):
    with engine.connect() as conn:
        rows = conn.execute(
            telemetry.select()
            .where(telemetry.c.device_id == device_id)
            .order_by(telemetry.c.id.desc())
            .limit(limit)
        ).mappings().all()
        if not rows:
            raise HTTPException(status_code=404, detail="No readings for that device_id")
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------
# SBD side: read-only endpoints over what email_poller.py has decoded.
# The poller does all the writing directly against the database: these
# endpoints exist purely so the map (and you, poking around) can read
# it back over HTTP instead of opening a DB client.
# ---------------------------------------------------------------------

@app.get("/sbd/devices", response_model=List[str])
def sbd_devices():
    """Distinct IMEIs we've ever decoded a message from."""
    with engine.connect() as conn:
        rows = conn.execute(
            sbd_messages.select()
            .with_only_columns(sbd_messages.c.imei)
            .distinct()
            .where(sbd_messages.c.imei.is_not(None))
        ).all()
        return sorted({r[0] for r in rows})


@app.get("/sbd/messages/{imei}", response_model=List[SbdMessageOut])
def sbd_messages_for(imei: str, limit: int = 50):
    """Raw decoded messages for one device, newest first -- useful for
    debugging (e.g. checking battery voltage or flags on the latest
    uplink), separate from the position history used by the map."""
    with engine.connect() as conn:
        rows = conn.execute(
            sbd_messages.select()
            .where(sbd_messages.c.imei == imei)
            .order_by(sbd_messages.c.id.desc())
            .limit(limit)
        ).mappings().all()
        return [dict(r) for r in rows]


@app.get("/sbd/positions/{imei}", response_model=List[PositionOut])
def sbd_positions_for(imei: str, limit: int = 200):
    """
    Position history for one device, OLDEST first (so the map can just
    draw the list in order as a path). limit caps how far back we look;
    we fetch the newest `limit` rows from the DB, then reverse them.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            sbd_positions.select()
            .where(sbd_positions.c.imei == imei)
            .order_by(sbd_positions.c.id.desc())
            .limit(limit)
        ).mappings().all()
        return [dict(r) for r in reversed(rows)]

@app.get("/sbd/positions/{imei}/{momsn}", response_model=List[PositionOut])
def sbd_position_for_momsn (imei: str, momsn: int): 

    with engine.connect() as conn: 
        rows = conn.execute(
            sbd_positions.select()
            .join(sbd_messages, sbd_positions.c.message_id == sbd_messages.c.id)
            .where(sbd_positions.c.imei == imei, sbd_messages.c.momsn == momsn)
            .order_by(sbd_positions.c.id.desc())
        ).mappings().all()
        return [dict(r) for r in reversed(rows)]


@app.get("/map")
def map_page():
    """Convenience alias so you don't have to remember /static/map.html."""
    return RedirectResponse(url="/static/map.html")
