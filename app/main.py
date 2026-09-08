"""
Telemetry ingestion API.

Modeled on the hybrid satellite/LTE GNSS tracker: a device periodically
reports its position, battery, and satellite count, and occasionally an
event (e.g. leaving a geofence). This service accepts those reports and
lets you query them back.

Run it directly (before/without Docker):

    python -m venv .venv
    .venv\\Scripts\\activate        # Windows
    pip install -r requirements.txt
    uvicorn app.main:app --reload

Or via docker-compose (API + Postgres together):

    docker compose up --build

Then open http://127.0.0.1:8000/docs for the interactive API docs.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from typing import List

from app.database import init_db, engine, telemetry
from app.models import TelemetryIn, TelemetryOut


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
