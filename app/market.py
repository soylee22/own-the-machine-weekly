"""Public market data providers and dated performance calculations."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .config import Holding
from .dates import PERIODS, period_anchor


USER_AGENT = "OwnTheMachineWeekly/0.1 (public research pipeline)"
Bar = dict[str, Any]
Opener = Callable[..., Any]


@dataclass
class MarketSeries:
    symbol: str
    currency: str
    provider: str
    source_url: str
    adjusted: bool
    bars: list[Bar]
    corporate_actions: list[dict[str, Any]]
    fetched_at: str
    status: str
    error: str | None = None
    provider_attempts: list[dict[str, Any]] | None = None
    adjustment_status: str = "unavailable"
    quality_warnings: list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _request_bytes(url: str, opener: Opener, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/csv,*/*"})
    try:
        response = opener(request, timeout=timeout)
    except TypeError:
        response = opener(request)
    with response:
        return response.read()


def _timestamp_date(value: int | float) -> dt.date:
    return dt.datetime.fromtimestamp(float(value), dt.timezone.utc).date()


def _normalise_bars(rows: list[Bar], asof: dt.date) -> list[Bar]:
    clean: dict[str, Bar] = {}
    for row in rows:
        date_value = row["date"]
        if isinstance(date_value, str):
            date_value = dt.date.fromisoformat(date_value)
        if date_value > asof:
            continue
        close = float(row["close"])
        if not math.isfinite(close) or close <= 0:
            continue
        volume = row.get("volume")
        clean[date_value.isoformat()] = {
            "date": date_value.isoformat(),
            "close": round(close, 8),
            "volume": int(volume) if volume is not None and math.isfinite(float(volume)) else None,
        }
    return [clean[key] for key in sorted(clean)]


def _unadjusted_discontinuities(rows: list[Bar]) -> list[str]:
    """Find jumps that can be an unadjusted split or a broken provider row."""

    ordered = sorted(rows, key=lambda row: row["date"])
    warnings: list[str] = []
    for previous, current in zip(ordered, ordered[1:]):
        ratio = float(current["close"]) / float(previous["close"])
        if ratio > 3.0 or ratio < (1.0 / 3.0):
            warnings.append(f"{previous['date']} to {current['date']} close ratio {ratio:.3f}")
    return warnings


def validate_corporate_actions(actions: list[dict[str, Any]], asof: dt.date | None = None) -> None:
    seen: set[tuple[str, str]] = set()
    for action in actions:
        action_type = str(action.get("type", ""))
        action_date = dt.date.fromisoformat(str(action["date"]))
        if asof and action_date > asof:
            raise ValueError(f"Corporate action is after cut-off: {action_date}")
        key = (action_type, action_date.isoformat())
        if key in seen:
            raise ValueError(f"Duplicate corporate action: {key}")
        seen.add(key)
        if action_type == "dividend" and float(action.get("amount", 0)) < 0:
            raise ValueError("Dividend amount cannot be negative")
        if action_type == "split":
            if float(action.get("numerator", 0)) <= 0 or float(action.get("denominator", 0)) <= 0:
                raise ValueError("Split ratio must be positive")


def _yahoo_url(symbol: str, start: dt.date, end: dt.date) -> str:
    period1 = int(dt.datetime.combine(start, dt.time(), tzinfo=dt.timezone.utc).timestamp())
    period2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time(), tzinfo=dt.timezone.utc).timestamp())
    query = urllib.parse.urlencode(
        {"period1": period1, "period2": period2, "interval": "1d", "events": "div,splits", "includeAdjustedClose": "true"}
    )
    return f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='.-')}?{query}"


def fetch_yahoo(
    symbol: str,
    start: dt.date,
    asof: dt.date,
    opener: Opener = urllib.request.urlopen,
) -> MarketSeries:
    url = _yahoo_url(symbol, start, asof)
    payload = json.loads(_request_bytes(url, opener).decode("utf-8"))
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        error = ((payload.get("chart") or {}).get("error") or {}).get("description") or "Yahoo returned no result"
        raise ValueError(error)
    result = result[0]
    timestamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    adjusted_values = (((result.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose") or []
    use_adjusted = len(adjusted_values) == len(timestamps) and all(value is not None for value in adjusted_values)
    rows = []
    for index, timestamp in enumerate(timestamps):
        close = adjusted_values[index] if use_adjusted and index < len(adjusted_values) else (closes[index] if index < len(closes) else None)
        if close is None:
            continue
        rows.append({
            "date": _timestamp_date(timestamp),
            "close": close,
            "volume": volumes[index] if index < len(volumes) else None,
        })
    actions: list[dict[str, Any]] = []
    events = result.get("events") or {}
    for timestamp, item in (events.get("dividends") or {}).items():
        actions.append({"type": "dividend", "date": _timestamp_date(int(timestamp)).isoformat(), "amount": item.get("amount")})
    for timestamp, item in (events.get("splits") or {}).items():
        actions.append({
            "type": "split",
            "date": _timestamp_date(int(timestamp)).isoformat(),
            "numerator": item.get("numerator"),
            "denominator": item.get("denominator"),
        })
    actions = [action for action in actions if dt.date.fromisoformat(action["date"]) <= asof]
    validate_corporate_actions(actions, asof)
    meta = result.get("meta") or {}
    bars = _normalise_bars(rows, asof)
    quality_warnings = [] if use_adjusted else _unadjusted_discontinuities(bars)
    if quality_warnings:
        raise ValueError("unadjusted discontinuity detected: " + ", ".join(quality_warnings[:3]))
    return MarketSeries(
        symbol=symbol,
        currency=str(meta.get("currency") or "unknown"),
        provider="yahoo-chart",
        source_url=url,
        adjusted=use_adjusted,
        bars=bars,
        corporate_actions=actions,
        fetched_at=_utc_now(),
        status="ready",
        provider_attempts=[{"provider": "yahoo-chart", "status": "ready"}],
        adjustment_status="adjusted" if use_adjusted else "unavailable",
        quality_warnings=quality_warnings,
    )


def _stooq_symbol(symbol: str) -> str:
    if "." not in symbol:
        return f"{symbol.lower()}.us"
    root, suffix = symbol.rsplit(".", 1)
    suffixes = {"L": "uk", "DE": "de", "T": "jp"}
    return f"{root.lower()}.{suffixes.get(suffix.upper(), suffix.lower())}"


def _stooq_url(symbol: str, start: dt.date, asof: dt.date) -> str:
    query = urllib.parse.urlencode({"s": _stooq_symbol(symbol), "d1": start.strftime("%Y%m%d"), "d2": asof.strftime("%Y%m%d"), "i": "d"})
    return f"https://stooq.com/q/d/l/?{query}"


def fetch_stooq(
    symbol: str,
    start: dt.date,
    asof: dt.date,
    opener: Opener = urllib.request.urlopen,
) -> MarketSeries:
    url = _stooq_url(symbol, start, asof)
    text = _request_bytes(url, opener).decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        if not row.get("Date") or not row.get("Close") or row["Close"] == "-":
            continue
        rows.append({"date": dt.date.fromisoformat(row["Date"]), "close": row["Close"], "volume": row.get("Volume")})
    if not rows:
        raise ValueError("Stooq returned no usable rows")
    bars = _normalise_bars(rows, asof)
    quality_warnings = _unadjusted_discontinuities(bars)
    if quality_warnings:
        raise ValueError("unadjusted discontinuity detected: " + ", ".join(quality_warnings[:3]))
    return MarketSeries(
        symbol=symbol,
        currency="unknown",
        provider="stooq-csv",
        source_url=url,
        adjusted=False,
        bars=bars,
        corporate_actions=[],
        fetched_at=_utc_now(),
        status="ready",
        provider_attempts=[{"provider": "stooq-csv", "status": "ready"}],
        adjustment_status="unavailable",
        quality_warnings=quality_warnings,
    )


def _cache_path(cache_dir: Path | None, symbol: str, asof: dt.date) -> Path | None:
    if cache_dir is None:
        return None
    digest = hashlib.sha256(symbol.encode("utf-8")).hexdigest()[:12]
    return cache_dir / f"{digest}-{asof.isoformat()}.json"


def _read_cache(path: Path, symbol: str, asof: dt.date) -> MarketSeries | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("symbol") != symbol or payload.get("status") != "ready":
            return None
        payload["bars"] = _normalise_bars(payload.get("bars", []), asof)
        if not payload["bars"]:
            return None
        return MarketSeries(**payload)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_cache(path: Path, series: MarketSeries) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(series.as_dict(), indent=2, sort_keys=True), encoding="utf-8")


def fetch_series(
    holding: Holding,
    asof: dt.date,
    opener: Opener = urllib.request.urlopen,
    cache_dir: Path | None = None,
    pause_seconds: float = 0.0,
) -> MarketSeries:
    start = asof - dt.timedelta(days=365 * 6 + 30)
    cache_file = _cache_path(cache_dir, holding.symbol, asof)
    if cache_file:
        cached = _read_cache(cache_file, holding.symbol, asof)
        if cached:
            cached.provider = f"cache:{cached.provider}"
            cached.provider_attempts = [{"provider": "cache", "status": "ready"}]
            return cached
    attempts: list[dict[str, Any]] = []
    for provider in (fetch_yahoo, fetch_stooq):
        try:
            series = provider(holding.symbol, start, asof, opener=opener)
            if len(series.bars) < 2:
                raise ValueError("provider returned fewer than two dated bars")
            series.provider_attempts = attempts + [{"provider": series.provider, "status": "ready"}]
            if cache_file:
                _write_cache(cache_file, series)
            if pause_seconds:
                time.sleep(pause_seconds)
            return series
        except Exception as exc:  # providers are independent and failure is reported
            attempts.append({"provider": provider.__name__, "status": "failed", "error": str(exc)[:240]})
    return MarketSeries(
        symbol=holding.symbol,
        currency=holding.currency,
        provider="none",
        source_url="",
        adjusted=False,
        bars=[],
        corporate_actions=[],
        fetched_at=_utc_now(),
        status="failed",
        error="; ".join(f"{item['provider']}: {item['error']}" for item in attempts),
        provider_attempts=attempts,
    )


def _bar_date(row: Bar) -> dt.date:
    return dt.date.fromisoformat(str(row["date"]))


def latest_bar(bars: list[Bar], asof: dt.date) -> Bar | None:
    candidates = [row for row in bars if _bar_date(row) <= asof]
    return candidates[-1] if candidates else None


def _bar_on_or_before(bars: list[Bar], target: dt.date) -> Bar | None:
    candidates = [row for row in bars if _bar_date(row) <= target]
    return candidates[-1] if candidates else None


def performance_metrics(bars: list[Bar], asof: dt.date) -> dict[str, Any]:
    """Return fixed-period returns using the last dated session at or before asof."""

    ordered = sorted(bars, key=lambda row: row["date"])
    latest = latest_bar(ordered, asof)
    output: dict[str, Any] = {
        "latest_date": None,
        "latest_close": None,
        "freshness_days": None,
        "freshness_status": "missing",
        "periods": {},
    }
    if latest is None:
        for period in PERIODS:
            output["periods"][period] = {"status": "missing", "return": None, "base_date": None, "latest_date": None}
        return output
    latest_date = _bar_date(latest)
    latest_close = float(latest["close"])
    output["latest_date"] = latest_date.isoformat()
    output["latest_close"] = latest_close
    freshness_days = (asof - latest_date).days
    output["freshness_days"] = freshness_days
    output["freshness_status"] = "ready" if freshness_days <= 7 else "stale"
    latest_index = ordered.index(latest)
    for period in PERIODS:
        if period == "1D":
            previous = ordered[max(0, latest_index - 1)] if latest_index > 0 else None
            base = previous
            target = latest_date - dt.timedelta(days=1)
        else:
            target = period_anchor(latest_date, period)
            base = _bar_on_or_before(ordered, target)
        if base is None:
            status = "stale" if output["freshness_status"] == "stale" else "missing"
            output["periods"][period] = {"status": status, "return": None, "base_date": None, "latest_date": latest_date.isoformat(), "anchor_gap_days": None}
            continue
        anchor_gap_days = (target - _bar_date(base)).days
        tolerance = {"1D": 4, "1W": 10, "1M": 20, "YTD": 35, "1Y": 20, "5Y": 60}[period]
        period_status = "ready"
        if output["freshness_status"] == "stale":
            period_status = "stale"
        elif anchor_gap_days > tolerance:
            period_status = "anchor_gap"
        base_close = float(base["close"])
        output["periods"][period] = {
            "status": period_status,
            "return": latest_close / base_close - 1.0 if period_status == "ready" else None,
            "base_date": _bar_date(base).isoformat(),
            "latest_date": latest_date.isoformat(),
            "anchor_gap_days": anchor_gap_days,
        }
    return output
