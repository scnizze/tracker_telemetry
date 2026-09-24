"""
Database access layer, built on SQLAlchemy Core.

The important idea in this file: the SAME code talks to either SQLite
(zero setup, for quick local runs) or Postgres (a real database server),
purely based on the DATABASE_URL environment variable. Nothing in
main.py needs to know or care which one is in use.

This is a small, concrete example of a bigger DevOps principle (the
"config" factor of the well-known 12-factor app checklist): behavior
that differs between environments (dev vs. containerized vs. production)
should be controlled by configuration/environment variables, never by
hardcoding or duplicating code paths.

- No DATABASE_URL set  -> falls back to a local SQLite file (telemetry.db)
- DATABASE_URL set      -> connects to that database instead (e.g. Postgres)

Two "families" of tables live here:
  - telemetry: the original JSON-in/JSON-out demo endpoint.
  - sbd_messages / sbd_positions: real data decoded from Iridium SBD
    emails (see app/sbd_frame.py and email_poller.py). One row in
    sbd_messages per email/frame; one row in sbd_positions per GPS fix
    inside that frame's history TLV (a single frame can carry many
    fixes, since the device buffers them between uplinks).
"""
import os
import time

from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    Integer,
    String,
    Float,
    DateTime,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql import func

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///telemetry.db")

# pool_pre_ping checks a connection is still alive before using it from the
# pool -- cheap insurance against "connection went away" errors.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
metadata = MetaData()

telemetry = Table(
    "telemetry",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("device_id", String, nullable=False),
    Column("ts", String, nullable=False),
    Column("lat", Float),
    Column("lon", Float),
    Column("battery_pct", Float),
    Column("satellites", Integer),
    Column("event", String, nullable=True),
    Column("received_at", DateTime(timezone=True), server_default=func.now()),
)

sbd_messages = Table(
    "sbd_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("imei", String, nullable=True, index=True),
    Column("momsn", Integer, nullable=True),
    Column("filename", String, nullable=True),
    Column("msg_type", Integer, nullable=True),
    Column("msg_type_name", String, nullable=True),
    Column("flags", Integer, nullable=True),
    Column("lat", Float, nullable=True),          # header fix (no absolute time)
    Column("lon", Float, nullable=True),
    Column("battery_v", Float, nullable=True),
    Column("iri_timer", Integer, nullable=True),
    Column("raw_hex", String, nullable=True),
    Column("email_subject", String, nullable=True),
    Column("email_date", DateTime(timezone=True), nullable=True),
    Column("received_at", DateTime(timezone=True), server_default=func.now()),
)

sbd_positions = Table(
    "sbd_positions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("message_id", Integer, nullable=False),
    Column("imei", String, nullable=True, index=True),
    Column("lat", Float, nullable=False),
    Column("lon", Float, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=True),
)


def init_db():
    """
    Create any tables that don't exist yet.

    Retries for a bit on connection failure: when docker-compose starts
    the API and database containers together, the API can come up before
    Postgres is actually ready to accept connections. Rather than crash
    on the first attempt, we retry for a few seconds -- a small,
    hand-rolled version of what a "wait for it" / readiness check does.

    metadata.create_all() only CREATES missing tables; it never alters
    an existing one. That's why we can add sbd_messages/sbd_positions
    here without touching the telemetry table or writing a migration --
    but the day we need to change a column on an existing table, this
    stops being enough and it's time to look at a real migration tool
    (Alembic is the usual choice for SQLAlchemy projects).
    """
    last_err = None
    for attempt in range(15):
        try:
            metadata.create_all(engine)
            return
        except OperationalError as e:
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"Could not connect to the database after retries: {last_err}")
