"""Broad-market relative-strength sidecar from Momentum Power Scanner."""

from __future__ import annotations

import csv
import datetime as dt
import io
import urllib.request
from typing import Any, Callable

DEFAULT_URL = "https://raw.githubusercontent.com/soylee22/momentum-power-scanner/main/outputs/rs_universe.csv"
Opener = Callable[..., Any]

def _open(url: str, opener: Opener, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "OwnTheMachineWeekly/0.1 (broad-market RS sidecar)", "Accept": "text/csv,*/*"})
    try:
        response = opener(request, timeout=timeout)
    except TypeError:
        response = opener(request)
    with response:
        return response.read()

def fetch_market_rs(
    issue_date: dt.date,
    opener: Opener = urllib.request.urlopen,
    timeout: float = 20.0,
    url: str = DEFAULT_URL,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Fetch exact-date RS values. Stale feeds are recorded but never used."""
    fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    try:
        raw = _open(url, opener, timeout)
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        if not rows:
            raise ValueError("RS sidecar is empty")
        dates = {row.get("asof", "") for row in rows}
        if len(dates) != 1:
            raise ValueError("RS sidecar contains multiple as-of dates")
        asof = next(iter(dates))
        exact = asof == issue_date.isoformat()
        lookup: dict[str, dict[str, Any]] = {}
        if exact:
            for row in rows:
                ticker = str(row.get("ticker") or "").strip()
                if not ticker:
                    continue
                try:
                    rating = float(row["rs_rating"])
                except (TypeError, ValueError, KeyError):
                    continue
                lookup[ticker] = {
                    "status": "ready",
                    "asof": asof,
                    "rs_rating": rating,
                    "stage2": str(row.get("stage2", "")).lower() == "true",
                    "gates_passed": int(float(row.get("gates_passed") or 0)),
                    "source": "momentum-power-scanner",
                }
        return lookup, {
            "kind": "broad-market-rs", "provider": "momentum-power-scanner", "url": url,
            "status": "ready" if exact else "stale", "fetched_at": fetched_at,
            "asof": asof, "row_count": len(rows), "usable_count": len(lookup),
            "error": None if exact else f"Expected {issue_date.isoformat()}, received {asof}",
        }
    except Exception as exc:
        return {}, {
            "kind": "broad-market-rs", "provider": "momentum-power-scanner", "url": url,
            "status": "failed", "fetched_at": fetched_at, "asof": None,
            "row_count": 0, "usable_count": 0, "error": str(exc)[:240],
        }
