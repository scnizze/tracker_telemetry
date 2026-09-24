"""
Structured decoder for NOMAD SBD uplink frames.

This is the "data" sibling of sbd_decode.py (the command-line tool you
already have for eyeballing a single frame). sbd_decode.py prints a
human-readable report; this module returns a plain Python dict instead,
because the email poller and the API need DATA they can put in the
database and draw on a map, not text.

Wire format (see sbd_decode.py's header comment for the full story,
mirrors App/sbd_frame.c):

    byte0 = (version << 5) | (msg_type & 0x1F)
    byte1 = flags
    lat   int32   degrees x 1e7
    lon   int32   degrees x 1e7
    batt  uint8   volts / 0.02
    timer uint16  seconds since the sending device booted
    ...then 0..n TLVs: type (1 B), length (1 B), value (length B)

We only care about one TLV type here: 0x02, the GNSS movement history.
That's deliberate -- it's the one field in the frame that carries an
absolute timestamp (the header's lat/lon is only "here's where I am
right now", with no wall-clock time attached), so it's what a map needs.

NOTE: this duplicates a small slice of sbd_decode.py's parsing instead
of importing it. In a bigger project you'd factor the shared bytes-in
logic into one module both tools import, and keep the text-formatting
and the dict-building as two thin layers on top of it. We're skipping
that refactor for now to keep this change small and easy to review --
it's on the list if the frame format grows more TLV types.
"""
import re
import struct
from datetime import datetime, timezone

FRAME_VERSION = 1
FIXED_BYTES = 13

LATLON_NODATA = -0x80000000      # INT32_MIN
BATTERY_NODATA = 0xFF
IRITIMER_NODATA = 0xFFFF

TLV_GNSS_HISTORY = 0x02
SAMPLE_BYTES = 12

MSG_TYPES = {
    0x00: "standard transmission",
    0x01: "diagnostic / debug",
    0x02: "alert - missing beacons nearby",
    0x03: "alert - zone-out event",
    0x04: "config response / ACK",
}


class BadFrame(Exception):
    """The bytes are not a frame we can make sense of."""


def _latlon(raw):
    return None if raw == LATLON_NODATA else raw / 1e7


def decode_frame(frame: bytes) -> dict:
    """
    Parse raw SBD bytes (exactly what an .sbd attachment contains) into
    a dict. Raises BadFrame if the bytes don't look like a v1 frame.
    """
    n = len(frame)
    if n < FIXED_BYTES:
        raise BadFrame(f"only {n} bytes - the fixed part alone is {FIXED_BYTES}")

    b0, b1, lat_raw, lon_raw, batt, timer = struct.unpack_from(">BBiiBH", frame, 0)
    version, msg_type = (b0 >> 5) & 0x07, b0 & 0x1F

    history = []
    warnings = []
    pos = FIXED_BYTES
    while pos < n:
        if n - pos < 2:
            warnings.append(f"{n - pos} trailing byte(s) - too short for a TLV header")
            break
        t, length = frame[pos], frame[pos + 1]
        pos += 2
        if pos + length > n:
            warnings.append(f"TLV 0x{t:02X} claims {length} bytes but only {n - pos} remain")
            break
        value = frame[pos:pos + length]
        pos += length

        if t == TLV_GNSS_HISTORY:
            if len(value) % SAMPLE_BYTES:
                warnings.append(
                    f"GNSS history length {len(value)} is not a multiple of {SAMPLE_BYTES}"
                )
            for i in range(len(value) // SAMPLE_BYTES):
                slat, slon, sts = struct.unpack_from(">iiI", value, i * SAMPLE_BYTES)
                history.append({
                    "lat": _latlon(slat),
                    "lon": _latlon(slon),
                    "ts": datetime.fromtimestamp(sts, timezone.utc) if sts else None,
                })
        # Any other TLV (e.g. the beacon bit array) is skipped on purpose --
        # we only need position data for the map right now.

    return {
        "version": version,
        "msg_type": msg_type,
        "msg_type_name": MSG_TYPES.get(msg_type, "unknown"),
        "flags": b1,
        "lat": _latlon(lat_raw),
        "lon": _latlon(lon_raw),
        "battery_v": None if batt == BATTERY_NODATA else round(batt * 0.02, 2),
        "iri_timer": None if timer == IRITIMER_NODATA else timer,
        "history": history,      # newest-first list of {lat, lon, ts}
        "warnings": warnings,
        "raw_hex": frame.hex().upper(),
    }


def describe_filename(filename: str):
    """
    Iridium names delivered messages <IMEI>_<MOMSN>.sbd.
    Returns (imei, momsn) or (None, None) if the name doesn't match.
    """
    m = re.fullmatch(r'(\d{15})_(\d+)\.sbd', filename, re.IGNORECASE)
    if not m:
        return None, None
    return m.group(1), int(m.group(2))
