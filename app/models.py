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


class PositionOut(BaseModel):
    """One GPS fix, decoded out of an SBD frame's history TLV. This is
    what the map draws -- one dot (or one point in a path) per row."""
    lat: float
    lon: float
    ts: Optional[datetime] = None


class SbdMessageOut(BaseModel):
    """One decoded SBD uplink (one .sbd email attachment)."""
    id: int
    imei: Optional[str] = None
    momsn: Optional[int] = None
    filename: Optional[str] = None
    msg_type: Optional[int] = None
    msg_type_name: Optional[str] = None
    battery_v: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    received_at: datetime
