"""Flask API for iRizq Halal Investing ebook landing page."""

from __future__ import annotations

import logging
import os
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg2
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from logging_setup import configure_logging

configure_logging()
LOGGER = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
CORS(app)

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
DEFAULT_PAGE = "ebook-landing"
PDF_RELATIVE_PATH = Path("static/downloads/iRizq-Halal-Investing-Roadmap.pdf")
PDF_ATTACHMENT_NAME = "iRizq-Halal-Investing-Roadmap.pdf"
EMAIL_SUBJECT = "Your Free Halal Investing Roadmap is here 🌿"

PLAIN_TEXT_BODY = """Bismillah,

JazakAllah Khayran for downloading the iRizq Beginner Halal Investing Roadmap.

Your free guide is attached to this email. Inside you will find 8 simple steps to building wealth the halal way — from getting your financial foundation right all the way to thinking long-term and avoiding emotional mistakes.

Also check out our free Halal Stock Checker at stocks.irizq.com to screen any US-listed stock for Shariah compliance.

If you have any questions, just reply to this email.

Barak Allahu feekum,
Sarfaraz
iRizq.com | stocks.irizq.com
"""

HTML_BODY = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background-color:#0A0A0A;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:600px;margin:0 auto;padding:32px 24px;color:#F2F8F1;line-height:1.6;">
    <p style="margin:0 0 16px;">Bismillah,</p>
    <p style="margin:0 0 16px;">
      JazakAllah Khayran for downloading the
      <span style="color:#87C77B;font-weight:600;">iRizq Beginner Halal Investing Roadmap</span>.
    </p>
    <p style="margin:0 0 16px;">
      Your free guide is attached to this email. Inside you will find
      8 simple steps to building wealth the halal way — from getting
      your financial foundation right all the way to thinking long-term
      and avoiding emotional mistakes.
    </p>
    <p style="margin:0 0 16px;">
      Also check out our free Halal Stock Checker at
      <a href="https://stocks.irizq.com" style="color:#87C77B;text-decoration:none;">stocks.irizq.com</a>
      to screen any US-listed stock for Shariah compliance.
    </p>
    <p style="margin:0 0 16px;">If you have any questions, just reply to this email.</p>
    <p style="margin:0 0 8px;">Barak Allahu feekum,<br>Sarfaraz</p>
    <p style="margin:0;color:#87C77B;">
      <a href="https://www.irizq.com" style="color:#87C77B;text-decoration:none;">iRizq.com</a>
      |
      <a href="https://stocks.irizq.com" style="color:#87C77B;text-decoration:none;">stocks.irizq.com</a>
    </p>
  </div>
</body>
</html>
"""


def _normalize_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    return url


def _get_db_connection() -> Any:
    dsn = _normalize_database_url(os.environ.get("DATABASE_URL", ""))
    parsed = urlparse(dsn)
    connect_kwargs: dict[str, Any] = {"connect_timeout": 10}
    host = (parsed.hostname or "").lower()
    if host and host not in {"localhost", "127.0.0.1"}:
        connect_kwargs["sslmode"] = os.environ.get("ANALYTICS_SSLMODE", "require")
    return psycopg2.connect(dsn, **connect_kwargs)


def ensure_ebook_stats_table() -> None:
    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS stock_investing_ebook_stats (
                    id SERIAL PRIMARY KEY,
                    event_type VARCHAR(20) NOT NULL,
                    page VARCHAR(100) DEFAULT 'ebook-landing',
                    ip_address VARCHAR(45),
                    created_at TIMESTAMP DEFAULT NOW()
                );
                """
            )
        conn.commit()


def log_ebook_event(*, event_type: str, page: str, ip_address: str | None) -> None:
    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO stock_investing_ebook_stats (event_type, page, ip_address)
                VALUES (%s, %s, %s)
                """,
                (event_type, page, ip_address),
            )
        conn.commit()


def count_ebook_visits(page: str = DEFAULT_PAGE) -> int:
    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM stock_investing_ebook_stats
                WHERE event_type = %s AND page = %s
                """,
                ("visit", page),
            )
            row = cur.fetchone()
    return int((row or [0])[0] or 0)


def send_roadmap_email(recipient_email: str) -> None:
    sender_email = (os.environ.get("SENDER_EMAIL") or "").strip()
    sender_name = (os.environ.get("SENDER_NAME") or "iRizq").strip()
    app_password = (os.environ.get("GMAIL_APP_PASSWORD") or "").strip()

    if not sender_email or not app_password:
        raise RuntimeError("SENDER_EMAIL and GMAIL_APP_PASSWORD must be configured.")

    pdf_path = Path(__file__).resolve().parent / PDF_RELATIVE_PATH
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found at {pdf_path}")

    message = MIMEMultipart("mixed")
    message["Subject"] = EMAIL_SUBJECT
    message["From"] = f"{sender_name} <{sender_email}>"
    message["To"] = recipient_email

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(PLAIN_TEXT_BODY, "plain", "utf-8"))
    alternative.attach(MIMEText(HTML_BODY, "html", "utf-8"))
    message.attach(alternative)

    with open(pdf_path, "rb") as pdf_file:
        attachment = MIMEBase("application", "pdf")
        attachment.set_payload(pdf_file.read())
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition",
        f'attachment; filename="{PDF_ATTACHMENT_NAME}"',
    )
    message.attach(attachment)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(sender_email, app_password)
        smtp.sendmail(sender_email, [recipient_email], message.as_string())


@app.before_request
def _ensure_stats_table() -> None:
    if not app.config.get("EBOOK_STATS_TABLE_READY"):
        try:
            ensure_ebook_stats_table()
            app.config["EBOOK_STATS_TABLE_READY"] = True
        except Exception:
            LOGGER.exception("Failed to initialize stock_investing_ebook_stats table.")


@app.get("/health")
def health() -> tuple[dict[str, str], int]:
    return {"status": "ok"}, 200


@app.post("/subscribe")
def subscribe() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email") or "").strip().lower()
    if not email or not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "Invalid email address."}), 400

    ip_address = request.remote_addr
    try:
        log_ebook_event(event_type="download", page=DEFAULT_PAGE, ip_address=ip_address)
    except Exception:
        LOGGER.exception("Failed to log download event for %s", email)

    try:
        send_roadmap_email(email)
    except Exception:
        LOGGER.exception("Failed to send roadmap email to %s", email)

    return jsonify({"ok": True}), 200


@app.post("/track-visit")
def track_visit() -> tuple[Any, int]:
    payload = request.get_json(silent=True) or {}
    page = str(payload.get("page") or DEFAULT_PAGE).strip() or DEFAULT_PAGE
    ip_address = request.remote_addr

    try:
        log_ebook_event(event_type="visit", page=page, ip_address=ip_address)
    except Exception:
        LOGGER.exception("Failed to log visit event for page %s", page)
        return jsonify({"ok": False, "error": "Failed to track visit."}), 500

    return jsonify({"ok": True}), 200


@app.get("/stats/ebook")
def ebook_stats() -> tuple[Any, int]:
    try:
        visits = count_ebook_visits(DEFAULT_PAGE)
    except Exception:
        LOGGER.exception("Failed to load ebook visit stats.")
        return jsonify({"ok": False, "error": "Failed to load stats."}), 500

    return jsonify({"visits": visits}), 200


def _serve_landing_page() -> Any:
    return send_from_directory(Path(__file__).resolve().parent, "irizq-landing.html")


@app.get("/ebook")
def ebook_landing_page() -> Any:
    return _serve_landing_page()


@app.get("/")
def landing_page() -> Any:
    return _serve_landing_page()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
