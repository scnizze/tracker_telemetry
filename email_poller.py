#!/usr/bin/env python3
"""
Email poller: the piece that makes this whole thing "automatic".

The story, end to end:

  1. Your NOMAD tracker radios a frame up to Iridium over SBD.
  2. Iridium emails it to you as a .sbd attachment (that's just how you
     configured Direct-IP/email delivery on the Iridium side -- nothing
     to build there).
  3. THIS SCRIPT checks that mailbox every POLL_INTERVAL_SECONDS, finds
     any email it hasn't looked at yet, pulls out the .sbd attachment,
     decodes it with app/sbd_frame.py, and writes the result into the
     same database the API (app/main.py) reads from.
  4. The map (/map) picks it up on its next 30-second refresh. No step
     in between needs you to do anything by hand.

Run it (separately from the API -- two processes, one job each):

    python -m venv .venv
    .venv\\Scripts\\activate          # Windows
    pip install -r requirements.txt
    copy .env.example .env            # then fill in your real values
    python email_poller.py

Gmail setup (see .env.example for exactly which values it needs):
  1. Turn on 2-Step Verification on the Gmail account: myaccount.google.com/security
  2. Create an "App Password" for it: myaccount.google.com/apppasswords
     (pick any name, e.g. "tracker-telemetry") -- Google gives you a
     16-character password. That goes in GMAIL_APP_PASSWORD, NOT your
     normal Gmail password (which won't work here even if you tried).
  3. Put your Gmail address and that app password in .env.

Why polling instead of a "push" from Iridium straight to this PC?
Iridium can also deliver over HTTP POST (their "Direct-IP" push mode),
but that needs your PC to have a public IP and an open port -- awkward
for a home machine. Checking an inbox every minute needs nothing open;
your PC only ever makes outbound connections, to Gmail.
"""
import email
import imaplib
import logging
import os
import sys
import time
from email.utils import parsedate_to_datetime

from dotenv import load_dotenv

load_dotenv()  # reads a .env file in this folder into os.environ, if present

from app.database import engine, sbd_messages, sbd_positions, init_db  # noqa: E402
from app.sbd_frame import decode_frame, describe_filename, BadFrame  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("email_poller")

IMAP_HOST = os.environ.get("IMAP_HOST", "imap.gmail.com")
IMAP_FOLDER = os.environ.get("IMAP_FOLDER", "INBOX")
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))


def connect():
    """Log in to the mailbox. IMAP4_SSL means the connection is encrypted
    from the first byte, same idea as https:// vs http://."""
    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    conn.login(GMAIL_USER, GMAIL_APP_PASSWORD)
    conn.select(IMAP_FOLDER)
    return conn


def find_sbd_attachments(msg: email.message.Message):
    """Yield (filename, bytes) for every attachment that looks like an
    .sbd file. An email can carry other junk (signatures, inline
    images) -- walk() visits every part, and we only keep the ones with
    a filename ending in .sbd."""
    for part in msg.walk():
        filename = part.get_filename()
        if filename and filename.lower().endswith(".sbd"):
            payload = part.get_payload(decode=True)
            if payload:
                yield filename, payload


def save_decoded(filename, frame_bytes, email_subject, email_date):
    """Decode one frame and write it to the database. Returns True if
    it decoded cleanly, False if it was skipped (so the caller can
    still count it as 'handled', just not usable data)."""
    try:
        decoded = decode_frame(frame_bytes)
    except BadFrame as e:
        log.warning("  %s: could not decode (%s) - skipping", filename, e)
        return False

    imei, momsn = describe_filename(filename)

    with engine.begin() as conn:
        result = conn.execute(sbd_messages.insert().values(
            imei=imei,
            momsn=momsn,
            filename=filename,
            msg_type=decoded["msg_type"],
            msg_type_name=decoded["msg_type_name"],
            flags=decoded["flags"],
            lat=decoded["lat"],
            lon=decoded["lon"],
            battery_v=decoded["battery_v"],
            iri_timer=decoded["iri_timer"],
            raw_hex=decoded["raw_hex"],
            email_subject=email_subject,
            email_date=email_date,
        ))
        message_id = result.inserted_primary_key[0]

        # The history TLV is 0..21 GPS fixes with real timestamps --
        # each becomes its own row so the map can draw a path, not just
        # the single latest dot.
        good_fixes = [h for h in decoded["history"] if h["lat"] is not None]
        for fix in good_fixes:
            conn.execute(sbd_positions.insert().values(
                message_id=message_id,
                imei=imei,
                lat=fix["lat"],
                lon=fix["lon"],
                ts=fix["ts"],
            ))

    log.info(
        "  %s: decoded OK (imei=%s momsn=%s, %d position(s) saved)",
        filename, imei, momsn, len(good_fixes),
    )
    if decoded["warnings"]:
        for w in decoded["warnings"]:
            log.warning("    !! %s", w)
    return True


def poll_once(conn):
    """Check for unread mail, process every .sbd attachment found, and
    mark those emails as read so we don't process them again next time."""
    status, data = conn.search(None, "UNSEEN")
    if status != "OK":
        log.error("IMAP search failed: %s", status)
        return
    uids = data[0].split()
    if not uids:
        log.info("checked mailbox: nothing new")
        return

    log.info("checked mailbox: %d new message(s)", len(uids))
    for uid in uids:
        status, msg_data = conn.fetch(uid, "(RFC822)")
        if status != "OK":
            log.error("could not fetch message %s", uid)
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        subject = msg.get("Subject", "")
        try:
            date = parsedate_to_datetime(msg.get("Date"))
        except (TypeError, ValueError):
            date = None

        attachments = list(find_sbd_attachments(msg))
        if not attachments:
            log.info("  (subject: %r) - no .sbd attachment, ignoring", subject)
        for filename, payload in attachments:
            save_decoded(filename, payload, subject, date)

        # Explicitly mark as read. FETCH usually does this as a side
        # effect already, but being explicit means we don't depend on
        # that side effect continuing to happen.
        conn.store(uid, "+FLAGS", "\\Seen")


def main():
    if not GMAIL_USER or not GMAIL_APP_PASSWORD:
        sys.exit(
            "GMAIL_USER and GMAIL_APP_PASSWORD must be set (put them in a .env "
            "file next to this script -- see .env.example)."
        )

    log.info("starting up: making sure the database tables exist...")
    init_db()

    log.info("polling %s as %s every %ss (Ctrl+C to stop)",
              IMAP_HOST, GMAIL_USER, POLL_INTERVAL_SECONDS)

    while True:
        try:
            conn = connect()
        except imaplib.IMAP4.error as e:
            log.error("could not log in (%s) - will retry in %ss", e, POLL_INTERVAL_SECONDS)
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        try:
            while True:
                poll_once(conn)
                time.sleep(POLL_INTERVAL_SECONDS)
        except (imaplib.IMAP4.abort, OSError) as e:
            # The connection dropped (Wi-Fi hiccup, Gmail closed an idle
            # connection, etc.) -- log it and reconnect instead of
            # crashing the whole script over a blip.
            log.warning("connection dropped (%s) - reconnecting", e)
        finally:
            try:
                conn.logout()
            except Exception:
                pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("stopped by Ctrl+C")
