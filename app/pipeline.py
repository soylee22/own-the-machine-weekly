"""Build dated editions and publish only validated static-site data."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import urllib.request
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Holding, load_holdings
from .dossiers import build_dossiers
from .editorial import discover_events, build_editorial
from .market import MarketSeries, fetch_series, performance_metrics
from .market_rs import fetch_market_rs
from .momentum import apply_momentum, compute_trend_features
from .privacy import assert_public_payload


LONDON = ZoneInfo("Europe/London")
SCHEMA_VERSION = 1


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _issue_generated_at(issue_date: dt.date) -> str:
    return dt.datetime.combine(issue_date, dt.time(19, 37), tzinfo=LONDON).isoformat()


def _generation_timestamp(root: Path, issue_date: dt.date) -> str:
    """Keep an issue's first real build time stable across same-date reruns."""

    path = root / "data" / "editions" / issue_date.isoformat() / "edition.json"
    scheduled_placeholder = _issue_generated_at(issue_date)
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            value = existing.get("generated_at")
            if isinstance(value, str) and value and value != scheduled_placeholder:
                return value
        except (OSError, json.JSONDecodeError):
            pass
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _load_previous(root: Path, issue_date: dt.date) -> dict[str, Any] | None:
    candidates: list[tuple[dt.date, Path]] = []
    for path in (root / "data" / "editions").glob("*/edition.json"):
        try:
            date_value = dt.date.fromisoformat(path.parent.name)
        except ValueError:
            continue
        if date_value < issue_date:
            candidates.append((date_value, path))
    if not candidates:
        return None
    _, path = max(candidates)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _load_media(root: Path) -> dict[str, Any]:
    path = root / "config" / "media.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _instrument_from_series(holding: Holding, series: MarketSeries, issue_date: dt.date) -> tuple[dict[str, Any], dict[str, Any] | None]:
    metrics = performance_metrics(series.bars, issue_date)
    instrument: dict[str, Any] = {
        "id": holding.id,
        "name": holding.name,
        "symbol": holding.symbol,
        "exchange": holding.exchange,
        "currency": holding.currency,
        "asset_type": holding.asset_type,
        "country": holding.country,
        "coverage": "verified-2026-09-21",
        "listing_date": holding.listing_date,
        "listing_note": (
            f"Configured exchange listing begins {holding.listing_date}; earlier provider observations are excluded."
            if holding.listing_date
            else "Instrument coverage was verified read-only on 2026-09-21. No account data is retained."
        ),
        "market": {
            "status": series.status,
            "provider": series.provider,
            "source_url": series.source_url,
            "adjusted": series.adjusted,
            "adjustment_status": series.adjustment_status,
            "quality_warnings": series.quality_warnings or [],
            "corporate_actions": series.corporate_actions,
            "bar_count": len(series.bars),
            "close_tail": series.bars[-12:],
            "error": series.error,
        },
        "metrics": metrics,
        "return_basis": "total_return_adjusted" if series.adjusted else "price_close_fallback",
    }
    if series.status != "ready":
        instrument["metrics"] = performance_metrics([], issue_date)
        return instrument, None
    if metrics["freshness_status"] != "ready":
        return instrument, None
    if not series.adjusted:
        instrument["market"]["quality_warnings"] = list(instrument["market"]["quality_warnings"]) + [
            "Price-only fallback is excluded from portfolio momentum to avoid mixing return bases."
        ]
        return instrument, None
    features = compute_trend_features(series.bars)
    return instrument, features


def _universe_identity(holdings: list[Holding]) -> tuple[list[dict[str, Any]], str]:
    universe = [
        {"id": holding.id, "name": holding.name, "symbol": holding.symbol, "coverage": "verified-2026-09-21"}
        for holding in holdings
    ]
    fingerprint = hashlib.sha256(_json_bytes(universe)).hexdigest()
    return universe, fingerprint


def _universe_changes(previous: dict[str, Any] | None, current: list[dict[str, Any]], fingerprint: str) -> dict[str, Any]:
    previous_universe = (previous or {}).get("comparison_universe", [])
    old_by_id = {row.get("id"): row for row in previous_universe}
    new_by_id = {row.get("id"): row for row in current}
    return {
        "previous_fingerprint": (previous or {}).get("comparison_universe_fingerprint"),
        "current_fingerprint": fingerprint,
        "changed": bool(previous_universe) and fingerprint != (previous or {}).get("comparison_universe_fingerprint"),
        "added": [new_by_id[key] for key in sorted(set(new_by_id) - set(old_by_id))],
        "removed": [old_by_id[key] for key in sorted(set(old_by_id) - set(new_by_id))],
    }


def _score_changes(previous: dict[str, Any] | None, instruments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not previous:
        return []
    old_by_id = {item.get("id"): item for item in previous.get("instruments", [])}
    changes = []
    for item in instruments:
        old_score = ((old_by_id.get(item["id"]) or {}).get("momentum") or {}).get("portfolio_momentum_score")
        new_score = (item.get("momentum") or {}).get("portfolio_momentum_score")
        if old_score is None or new_score is None:
            continue
        changes.append({
            "holding_id": item["id"],
            "name": item["name"],
            "previous_score": old_score,
            "current_score": new_score,
            "change": new_score - old_score,
        })
    return sorted(changes, key=lambda row: (-abs(row["change"]), row["holding_id"]))


def _score_universe(instruments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    universe = [
        {"id": item["id"], "name": item["name"], "symbol": item["symbol"]}
        for item in instruments
        if (item.get("momentum") or {}).get("score_status") == "ready"
    ]
    return universe, hashlib.sha256(_json_bytes(universe)).hexdigest()


def _market_receipt(holding: Holding, series: MarketSeries) -> dict[str, Any]:
    return {
        "holding_id": holding.id,
        "kind": "market-data",
        "provider": series.provider,
        "url": series.source_url,
        "status": series.status,
        "fetched_at": series.fetched_at,
        "adjusted": series.adjusted,
        "adjustment_status": series.adjustment_status,
        "corporate_action_count": len(series.corporate_actions),
        "quality_warnings": series.quality_warnings or [],
        "error": series.error,
    }


def assess_quality(
    market_health: list[dict[str, Any]],
    source_health: list[dict[str, Any]],
    configured_holdings: int,
    include_news: bool,
) -> dict[str, Any]:
    """Decide whether a refresh can replace the live magazine edition."""

    market_ready = sum(1 for item in market_health if item.get("status") == "ready" and item.get("freshness_status") == "ready")
    market_failed = configured_holdings - market_ready
    coverage_threshold = max(1, math.ceil(configured_holdings * 0.8))
    news_ready = sum(1 for item in source_health if item.get("provider") == "google-news-rss" and item.get("status") == "ready")
    news_failed = sum(1 for item in source_health if item.get("provider") == "google-news-rss" and item.get("status") == "failed")
    coverage_ok = market_ready >= coverage_threshold
    news_ok = (not include_news) or news_ready > 0
    publishable = coverage_ok and news_ok
    partial = publishable and (market_ready < configured_holdings or not include_news)
    if not coverage_ok:
        note = f"Refresh withheld. Price coverage is {market_ready}/{configured_holdings}, below the {coverage_threshold}-holding threshold."
    elif include_news and not news_ok:
        note = f"Refresh withheld. All {news_failed} configured news discovery feeds failed."
    elif not include_news:
        note = "Explicit --no-news mode. Price data passed the coverage gate, but this is not a normal magazine refresh."
    elif partial:
        note = f"Partial refresh. Price coverage is {market_ready}/{configured_holdings}. Missing holdings remain visible."
    else:
        note = "Full price coverage and at least one successful public news discovery feed passed the publication gate."
    return {
        "ready_market_count": market_ready,
        "failed_market_count": market_failed,
        "market_coverage_ratio": market_ready / configured_holdings if configured_holdings else 0.0,
        "market_coverage_threshold": coverage_threshold,
        "source_provider_ready_count": sum(1 for item in source_health if item.get("status") == "ready"),
        "source_provider_failed_count": sum(1 for item in source_health if item.get("status") == "failed"),
        "news_discovery_ready_count": news_ready,
        "news_discovery_failed_count": news_failed,
        "news_requirement": "not-required-explicit-no-news" if not include_news else "at-least-one-successful-feed",
        "publishable": publishable,
        "partial": partial,
        "note": note,
    }


def _archive_index(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted((root / "data" / "editions").glob("*/edition.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append({
            "issue_date": payload.get("issue_date", path.parent.name),
            "status": payload.get("status", "unknown"),
            "path": f"archive/{path.parent.name}.json",
            "story_count": len(((payload.get("editorial") or {}).get("stories") or [])),
            "ready_market_count": (payload.get("quality") or {}).get("ready_market_count", 0),
        })
    return entries


def build_edition(
    root: Path,
    issue_date: dt.date,
    opener: Callable[..., Any] | None = None,
    include_news: bool = True,
    include_sec: bool = True,
    timeout: float = 20.0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build one edition without changing the current live edition."""

    config, holdings = load_holdings(root / "config" / "holdings.yaml")
    previous = _load_previous(root, issue_date)
    universe, fingerprint = _universe_identity(holdings)
    market_cache = root / "data" / "cache" / "market"
    instruments: list[dict[str, Any]] = []
    features_by_id: dict[str, dict[str, Any]] = {}
    receipts: list[dict[str, Any]] = []
    market_health: list[dict[str, Any]] = []
    opener_value = opener
    for holding in holdings:
        series = fetch_series(holding, issue_date, opener=opener_value or urllib.request.urlopen, cache_dir=market_cache, pause_seconds=0.05)
        instrument, features = _instrument_from_series(holding, series, issue_date)
        instruments.append(instrument)
        if features is not None:
            features_by_id[holding.id] = features
        receipts.append(_market_receipt(holding, series))
        market_health.append({
            "holding_id": holding.id,
            "provider": series.provider,
            "status": series.status,
            "latest_date": instrument["metrics"].get("latest_date"),
            "freshness_status": instrument["metrics"].get("freshness_status"),
            "adjustment_status": series.adjustment_status,
        })
    market_rs_lookup, market_rs_receipt = fetch_market_rs(issue_date, opener_value or urllib.request.urlopen, timeout)
    market_rs_by_id = {}
    for holding in holdings:
        row = market_rs_lookup.get(holding.symbol)
        if row is not None:
            market_rs_by_id[holding.id] = row
    receipts.append(market_rs_receipt)
    momentum = apply_momentum(features_by_id, market_rs_by_id)
    for instrument in instruments:
        instrument["momentum"] = momentum.get(instrument["id"], {
            "portfolio_momentum_score": None,
            "composite": None,
            "score_status": "unavailable",
            "score_unavailable_reason": "Insufficient fresh price history for all four components.",
            "stage2": None,
            "stage2_status": "unavailable",
            "market_rs_rating": None,
            "market_rs_status": "unavailable",
            "gates": {},
            "gates_passed": None,
        })
    score_universe, score_universe_fingerprint = _score_universe(instruments)
    if include_news:
        events, source_receipts, source_health = discover_events(holdings, issue_date, opener_value or urllib.request.urlopen, timeout, include_sec=include_sec)
    else:
        events, source_receipts, source_health = [], [], [{"provider": "news", "status": "not-run", "event_count": 0}]
    receipts.extend(source_receipts)
    editorial = build_editorial(holdings, instruments, events, issue_date, previous)
    media = _load_media(root)
    receipts.append({
        "kind": "image",
        "provider": "NASA Glenn Research Center",
        "status": "recorded",
        "url": media["hero"]["source"],
        "image_url": media["hero"]["image_url"],
        "local_asset": media["hero"]["path"],
        "credit": media["hero"]["credit"],
        "reuse_note": media["hero"]["reuse_note"],
    })
    quality = assess_quality(market_health, source_health, len(holdings), include_news)
    quality["event_count"] = len(events)
    quality["story_count"] = len(editorial["stories"])
    status = "ready" if quality["publishable"] and quality["ready_market_count"] == len(holdings) and not quality["partial"] else ("partial" if quality["publishable"] else "failed")
    edition: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "issue_date": issue_date.isoformat(),
        "status": status,
        "generated_at": _generation_timestamp(root, issue_date),
        "cutoff": {
            "issue_date": issue_date.isoformat(),
            "timezone": "Europe/London",
            "market_rule": "Use completed sessions dated on or before the issue Sunday.",
            "latest_session_varies_by_listing": True,
        },
        "coverage": {
            "status": str(config.get("coverage", "provisional")),
            "broad_index_etf": str(config.get("broad_index_etf", "pending")),
            "growth_index_etf": str(config.get("growth_index_etf", "not-configured")),
            "note": str(config.get("notes", "Verified public instrument coverage.")),
        },
        "image": media["hero"],
        "comparison_universe": universe,
        "comparison_universe_fingerprint": fingerprint,
        "comparison_universe_changes": _universe_changes(previous, universe, fingerprint),
        "score_universe": score_universe,
        "score_universe_fingerprint": score_universe_fingerprint,
        "score_changes": _score_changes(previous, instruments),
        "instruments": instruments,
        "dossiers": build_dossiers(holdings, root),
        "editorial": editorial,
        "source_health": {"market": market_health, "news": source_health},
        "quality": quality,
        "limitations": [
            "Coverage was verified read-only on 2026-09-21. This application retains no Trading 212 account data.",
            "No units, costs, balances or portfolio values are ingested or emitted.",
            "X enrichment is optional and not configured.",
            "Price context does not establish causal links to events.",
            "Long-window comparability can change after corporate restructuring. GE Aerospace is flagged in its dossier.",
            "Market RS comes from the Momentum Power broad-universe scanner and is unavailable rather than substituted when that feed is stale or missing.",
        ],
    }
    assert_public_payload(edition)
    return edition, receipts


def write_edition(root: Path, edition: dict[str, Any], receipts: list[dict[str, Any]]) -> dict[str, Any]:
    """Write the dated archive. Replace live site data only for publishable editions."""

    issue_date_text = str(edition["issue_date"])
    issue_date = dt.date.fromisoformat(issue_date_text)
    edition_dir = root / "data" / "editions" / issue_date_text
    existing_path = edition_dir / "edition.json"
    existing: dict[str, Any] | None = None
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
    new_publishable = bool((edition.get("quality") or {}).get("publishable"))
    old_publishable = bool((existing or {}).get("quality", {}).get("publishable"))
    if existing is not None and old_publishable and (not new_publishable or edition.get("status") != "ready"):
        # Preserve a good same-date issue and retain the failed attempt visibly.
        _write_json(edition_dir / "failed-attempt.json", edition)
        _write_json(edition_dir / "failed-receipts.json", receipts)
        return {
            "published_to_site_data": False,
            "archive_path": str(existing_path),
            "guard": "good_same_date_archive_preserved",
        }
    _write_json(existing_path, edition)
    _write_json(edition_dir / "receipts.json", receipts)
    if not new_publishable:
        return {"published_to_site_data": False, "archive_path": str(edition_dir / "edition.json")}
    index = _archive_index(root)
    site_data = root / "site" / "src" / "data"
    live_path = site_data / "edition.json"
    if live_path.exists():
        try:
            live_issue = dt.date.fromisoformat(json.loads(live_path.read_text(encoding="utf-8")).get("issue_date", ""))
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            live_issue = None
        if live_issue is not None and issue_date < live_issue:
            return {
                "published_to_site_data": False,
                "archive_path": str(edition_dir / "edition.json"),
                "guard": "older_issue_did_not_replace_newer_live_data",
            }
    _write_json(site_data / "edition.json", edition)
    _write_json(site_data / "receipts.json", receipts)
    _write_json(site_data / "archive.json", index)
    for path in (root / "data" / "editions").glob("*/edition.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("quality", {}).get("publishable"):
            _write_json(site_data / "archive" / f"{path.parent.name}.json", payload)
    return {"published_to_site_data": True, "archive_path": str(edition_dir / "edition.json")}
