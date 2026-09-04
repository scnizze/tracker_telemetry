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


def init_db():
    """
    Create the table if it doesn't exist yet.

    Retries for a bit on connection failure: when docker-compose starts
    the API and database containers together, the API can come up before
    Postgres is actually ready to accept connections. Rather than crash
    on the first attempt, we retry for a few seconds -- a small,
    hand-rolled version of what a "wait for it" / readiness check does.
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
