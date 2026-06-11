"""Lightweight PostgreSQL analytics helpers for API routes."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor

from config import settings

_STATS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _normalize_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql://" + url[len("postgresql+psycopg2://") :]
    return url


@contextmanager
def _connection() -> Iterator[Any]:
    url = _normalize_database_url(settings.database_url)
    parsed = urlparse(url)
    connect_kwargs: dict[str, Any] = {"connect_timeout": 10}
    hostname = (parsed.hostname or "").lower()
    if hostname and hostname not in {"localhost", "127.0.0.1"}:
        connect_kwargs["sslmode"] = settings.analytics_sslmode
    conn = psycopg2.connect(url, **connect_kwargs)
    try:
        yield conn
    finally:
        conn.close()


def ensure_events_table() -> None:
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    ticker TEXT NULL,
                    source TEXT NULL,
                    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
                );
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_event_type_timestamp
                ON events (event_type, timestamp DESC);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_events_user_id
                ON events (user_id);
                """
            )
        conn.commit()


def infer_source(utm_source: str | None, referer: str | None) -> str:
    if utm_source and utm_source.strip():
        return utm_source.strip().lower()
    if referer and referer.strip():
        parsed = urlparse(referer.strip())
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            return host
    return "direct"


def _invalidate_stats_cache() -> None:
    _STATS_CACHE.clear()


def track_event(
    *,
    event_type: str,
    user_id: str,
    ticker: str | None = None,
    source: str | None = None,
) -> None:
    with _connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events (event_type, user_id, ticker, source)
                VALUES (%s, %s, %s, %s)
                """,
                (event_type, user_id, ticker, source),
            )
        conn.commit()
    _invalidate_stats_cache()


def _count_by_event_type(cur: Any, event_type: str) -> int:
    cur.execute("SELECT COUNT(*) FROM events WHERE event_type = %s", (event_type,))
    row = cur.fetchone()
    return int((row or [0])[0] or 0)


def _count_unique_users(cur: Any) -> int:
    cur.execute("SELECT COUNT(DISTINCT user_id) FROM events")
    row = cur.fetchone()
    return int((row or [0])[0] or 0)


def _count_return_users(cur: Any) -> int:
    cur.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT user_id
            FROM events
            GROUP BY user_id
            HAVING COUNT(*) > 1
        ) AS returning_users
        """
    )
    row = cur.fetchone()
    return int((row or [0])[0] or 0)


def _top_tickers(cur: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT ticker, COUNT(*) AS search_count
        FROM events
        WHERE event_type = %s AND ticker IS NOT NULL AND ticker <> ''
        GROUP BY ticker
        ORDER BY search_count DESC, ticker ASC
        LIMIT %s
        """,
        ("search", limit),
    )
    rows = cur.fetchall() or []
    return [{"ticker": str(row[0]), "search_count": int(row[1])} for row in rows]


def _traffic_sources(cur: Any) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT COALESCE(NULLIF(source, ''), 'direct') AS source_label, COUNT(*) AS event_count
        FROM events
        GROUP BY COALESCE(NULLIF(source, ''), 'direct')
        ORDER BY event_count DESC, source_label ASC
        """
    )
    rows = cur.fetchall() or []
    return [{"source": str(row[0]), "count": int(row[1])} for row in rows]


def _recent_events(*, limit: int = 50) -> list[dict[str, Any]]:
    with _connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT event_type, user_id, ticker, COALESCE(NULLIF(source, ''), 'direct') AS source, timestamp
                FROM events
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall() or []
    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "event_type": str(row.get("event_type") or ""),
                "user_id": str(row.get("user_id") or ""),
                "ticker": row.get("ticker"),
                "source": str(row.get("source") or "direct"),
                "timestamp": row.get("timestamp"),
            }
        )
    return output


def get_dashboard_metrics() -> dict[str, Any]:
    now = time.time()
    cached = _STATS_CACHE.get("dashboard")
    if cached and cached[0] > now:
        return cached[1]

    with _connection() as conn:
        with conn.cursor() as cur:
            total_visits = _count_by_event_type(cur, "visit")
            total_searches = _count_by_event_type(cur, "search")
            unique_users = _count_unique_users(cur)
            return_users = _count_return_users(cur)
            top_tickers = _top_tickers(cur, limit=10)
            traffic_sources = _traffic_sources(cur)

    conversion_rate = (total_searches / total_visits) if total_visits > 0 else 0.0
    payload = {
        "total_visits": total_visits,
        "total_searches": total_searches,
        "unique_users": unique_users,
        "return_users": return_users,
        "top_tickers": top_tickers,
        "traffic_sources": traffic_sources,
        "conversion_rate": conversion_rate,
        "last_events": _recent_events(limit=50),
    }
    ttl = max(settings.analytics_cache_ttl_seconds, 1)
    _STATS_CACHE["dashboard"] = (now + ttl, payload)
    return payload
