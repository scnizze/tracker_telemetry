"""
Pydantic models: define the *shape* of data going in and out of the API.
FastAPI uses these to validate requests automatically and to generate
the interactive API docs at /docs.
"""
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class TelemetryIn(BaseModel):
    device_id: str = Field(..., examples=["tracker-01"])
    ts: str = Field(..., description="ISO-8601 timestamp from the device")
    lat: float
    lon: float
    battery_pct: float = Field(..., ge=0, le=100)
    satellites: int = Field(..., ge=0)
    event: Optional[str] = Field(
        default=None, description="e.g. 'geofence_exit', 'low_battery'"
    )


class TelemetryOut(TelemetryIn):
    id: int
    received_at: datetime
