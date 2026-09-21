"""Evidence-first event discovery and deterministic magazine selection."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from urllib.parse import quote, urlsplit

from .config import Holding
from .privacy import sanitise_text, sanitise_url


Opener = Callable[..., Any]
CONCRETE_PATTERNS = (
    r"\bcontracts?\b",
    r"\bawards?\b",
    r"\bdeliver(?:s|y|ies|ed|ing)?\b",
    r"\blaunch(?:es|ed|ing)?\b",
    r"\btests?\b",
    r"\btested\b",
    r"\bcertif(?:y|ies|ied|ication|ications)\b",
    r"\bfactor(?:y|ies)\b",
    r"\bcapacity\b",
    r"\bacqui(?:re|res|red|sition|sitions)\b",
    r"\bfinanc(?:e|es|ed|ing)\b",
    r"\bsanction(?:s|ed|ing)?\b",
    r"\bdiscover(?:y|ies|ed|ies)?\b",
    r"\bproduction\b",
    r"\bmanufactur(?:e|es|ed|ing)\b",
    r"\bdemonstrat(?:e|es|ed|ion|ions)\b",
    r"\bfirst flight\b",
    r"\bcommercial launch\b",
    r"\benters service\b",
    r"\border(?:s|ed|ing)?\b",
    r"\bprogramme\b",
)
CLICKBAIT_TERMS = {"price target", "buy", "sell", "should you", "stock could", "analyst"}
HIGH_QUALITY_SECONDARY_HOSTS = {"reuters.com", "ft.com", "bloomberg.com", "bbc.co.uk", "businessgreen.com", "defensenews.com", "janes.com", "navalnews.com", "flightglobal.com"}
LOW_QUALITY_SECONDARY_HOSTS = {"ad-hoc-news.de"}
OFFICIAL_HOST_HINTS = {
    "baesystems.com",
    "geaerospace.com",
    "lockheedmartin.com",
    "rheinmetall.com",
    "rolls-royce.com",
    "jpmorganchase.com",
    "goldmansachs.com",
    "hsbc.com",
    "mufg.jp",
    "morganstanley.com",
    "bp.com",
    "chevron.com",
    "exxonmobil.com",
    "shell.com",
    "ishares.com",
    "sec.gov",
}


def _feed_url(query: str) -> str:
    return "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-GB&gl=GB&ceid=GB:en"


def _open(url: str, opener: Opener, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "OwnTheMachineWeekly/0.1 (public research pipeline)", "Accept": "application/rss+xml,application/xml"})
    try:
        response = opener(request, timeout=timeout)
    except TypeError:
        response = opener(request)
    with response:
        return response.read()


def _parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, IndexError):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None


def _source_kind(source_url: str, source_name: str, holding: Holding) -> str:
    host = (urlsplit(source_url).hostname or "").lower()
    official_host = (urlsplit(holding.official_url).hostname or "").lower()
    if host.endswith("sec.gov") or any(host == hint or host.endswith("." + hint) for hint in OFFICIAL_HOST_HINTS) or (official_host and (host == official_host or host.endswith("." + official_host))):
        return "primary"
    if host.endswith("news.google.com"):
        return "discovery"
    return "secondary"


def has_concrete_terms(text: str) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in CONCRETE_PATTERNS)


def concrete_term_count(text: str) -> int:
    return sum(bool(re.search(pattern, text, flags=re.IGNORECASE)) for pattern in CONCRETE_PATTERNS)


def _publisher_tier(url: str, source_kind: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if source_kind == "primary":
        return "primary"
    if any(host == value or host.endswith("." + value) for value in HIGH_QUALITY_SECONDARY_HOSTS):
        return "high-quality-secondary"
    if any(host == value or host.endswith("." + value) for value in LOW_QUALITY_SECONDARY_HOSTS):
        return "low-quality-secondary"
    return "secondary"


def _event_score(event: dict[str, Any], issue_date: dt.date) -> int:
    published = dt.date.fromisoformat(event["published_date"])
    age = max(0, (issue_date - published).days)
    score = max(0, 28 - min(age, 28))
    score += {"primary": 26, "secondary": 12, "discovery": 5}.get(event["source_kind"], 0)
    score += {"high-quality-secondary": 8, "low-quality-secondary": -20}.get(event.get("publisher_tier"), 0)
    text = f"{event['title']} {event.get('summary', '')}".lower()
    concrete = concrete_term_count(text)
    score += min(28, concrete * 5)
    if re.search(r"\$?\d[\d,.]*\s*(million|billion|bn|m)\b", text):
        score += 7
    if any(term in text for term in CLICKBAIT_TERMS):
        score -= 18
    if event.get("source_kind") == "discovery" and not concrete:
        score -= 20
    return max(0, score)


def _normalise_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _token_similarity(left: str, right: str) -> float:
    a = set(_normalise_title(left).split())
    b = set(_normalise_title(right).split())
    return len(a & b) / len(a | b) if a and b else 0.0


def deduplicate_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for event in sorted(events, key=lambda row: (-int(row.get("score", 0)), row["published_date"], row["title"])):
        fingerprint = hashlib.sha256(_normalise_title(event["title"]).encode("utf-8")).hexdigest()[:16]
        if fingerprint in seen_ids:
            continue
        if any(
            event["holding_id"] == prior["holding_id"]
            and _token_similarity(event["title"], prior["title"]) >= 0.75
            for prior in kept
        ):
            continue
        seen_ids.add(fingerprint)
        event = dict(event)
        event["fingerprint"] = fingerprint
        kept.append(event)
    return kept


def parse_rss(xml_bytes: bytes, holding: Holding, issue_date: dt.date, window_days: int = 21) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_bytes)
    events: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        title = sanitise_text(item.findtext("title") or "")
        link = item.findtext("link") or ""
        source_node = item.find("source")
        source_name = sanitise_text(source_node.text or "") if source_node is not None else "Google News"
        source_url = source_node.attrib.get("url", "") if source_node is not None else link
        published_date = _parse_date(item.findtext("pubDate"))
        if not title or not link or published_date is None:
            continue
        age_days = (issue_date - published_date).days
        if published_date > issue_date or age_days > window_days:
            continue
        summary = sanitise_text(html.unescape(item.findtext("description") or ""))
        try:
            public_link = sanitise_url(link)
            publisher_link = sanitise_url(source_url)
        except ValueError:
            continue
        event = {
            "holding_id": holding.id,
            "holding_name": holding.name,
            "title": title,
            "summary": summary[:500],
            "published_date": published_date.isoformat(),
            "source_name": source_name or "Unknown source",
            "source_url": public_link,
            "publisher_url": publisher_link,
            "source_kind": _source_kind(publisher_link, source_name, holding),
            "publisher_tier": None,
            "event_type": "operational" if has_concrete_terms(f"{title} {summary}") else "report",
            "recency_class": "issue" if age_days <= 7 else "context",
            "age_days": age_days,
        }
        event["publisher_tier"] = _publisher_tier(event["publisher_url"], event["source_kind"])
        event["score"] = _event_score(event, issue_date)
        events.append(event)
    return events


def fetch_google_events(
    holding: Holding,
    issue_date: dt.date,
    opener: Opener = urllib.request.urlopen,
    timeout: float = 20.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = _feed_url(holding.source_query)
    fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    try:
        raw = _open(url, opener, timeout)
        events = parse_rss(raw, holding, issue_date)
        receipt = {
            "holding_id": holding.id,
            "kind": "discovery-feed",
            "provider": "google-news-rss",
            "url": url,
            "status": "ready",
            "fetched_at": fetched_at,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "event_count": len(events),
        }
        return events, receipt
    except Exception as exc:
        return [], {
            "holding_id": holding.id,
            "kind": "discovery-feed",
            "provider": "google-news-rss",
            "url": url,
            "status": "failed",
            "fetched_at": fetched_at,
            "error": str(exc)[:240],
            "event_count": 0,
        }


def fetch_sec_events(
    holding: Holding,
    issue_date: dt.date,
    opener: Opener = urllib.request.urlopen,
    timeout: float = 20.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch recent SEC filing metadata where a public CIK is configured."""

    if holding.cik is None:
        return [], {"holding_id": holding.id, "kind": "primary-feed", "provider": "sec", "status": "not-configured", "event_count": 0}
    cik = f"{holding.cik:010d}"
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    fetched_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    try:
        raw = _open(url, opener, timeout)
        payload = __import__("json").loads(raw.decode("utf-8"))
        recent = (payload.get("filings") or {}).get("recent") or {}
        events = []
        records = []
        forms = recent.get("form", [])
        for index, filed in enumerate(recent.get("filingDate", [])):
            filed_date = _parse_date(filed)
            if filed_date is None or filed_date > issue_date or (issue_date - filed_date).days > 21:
                continue
            form = forms[index] if index < len(forms) else "filing"
            if form not in {"8-K", "6-K", "10-Q", "10-K"}:
                continue
            accession = recent.get("accessionNumber", [""])[index]
            document = recent.get("primaryDocument", [""])[index]
            accession_path = accession.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(holding.cik)}/{accession_path}/{document}"
            records.append({"form": form, "filed_date": filed_date.isoformat(), "url": sanitise_url(filing_url)})
        for record in records:
            event = {
                "holding_id": holding.id, "holding_name": holding.name,
                "title": f"{holding.name} filed {record['form']} with the SEC",
                "summary": f"Primary filing dated {record['filed_date']}. Open the filing for the underlying disclosure.",
                "published_date": record["filed_date"], "source_name": "U.S. SEC",
                "source_url": record["url"], "publisher_url": "https://www.sec.gov",
                "source_kind": "primary", "publisher_tier": "primary", "event_type": "filing",
                "recency_class": "issue" if (issue_date - dt.date.fromisoformat(record["filed_date"])).days <= 7 else "context",
                "age_days": (issue_date - dt.date.fromisoformat(record["filed_date"])).days,
            }
            event["score"] = _event_score(event, issue_date)
            events.append(event)
        return events, {
            "holding_id": holding.id,
            "kind": "primary-feed",
            "provider": "sec",
            "url": url,
            "status": "ready",
            "fetched_at": fetched_at,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "event_count": 0,
            "filing_count": len(records),
            "filings": records,
        }
    except Exception as exc:
        return [], {
            "holding_id": holding.id,
            "kind": "primary-feed",
            "provider": "sec",
            "url": url,
            "status": "failed",
            "fetched_at": fetched_at,
            "error": str(exc)[:240],
            "event_count": 0,
        }


def discover_events(
    holdings: list[Holding],
    issue_date: dt.date,
    opener: Opener = urllib.request.urlopen,
    timeout: float = 20.0,
    include_sec: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    health: list[dict[str, Any]] = []
    for holding in holdings:
        google_events, google_receipt = fetch_google_events(holding, issue_date, opener, timeout)
        events.extend(google_events)
        receipts.append(google_receipt)
        health.append({"holding_id": holding.id, "provider": google_receipt["provider"], "status": google_receipt["status"], "event_count": google_receipt["event_count"]})
        if include_sec and holding.cik is not None:
            sec_events, sec_receipt = fetch_sec_events(holding, issue_date, opener, timeout)
            events.extend(sec_events)
            receipts.append(sec_receipt)
            health.append({"holding_id": holding.id, "provider": sec_receipt["provider"], "status": sec_receipt["status"], "event_count": sec_receipt["event_count"]})
    return deduplicate_events(events), receipts, health


def _operation_label(event: dict[str, Any]) -> str:
    text = f"{event['title']} {event.get('summary', '')}".lower()
    labels = (
        (r"\bcontracts?\b", "contract or order"),
        (r"\bdeliver(?:s|y|ies|ed|ing)?\b", "delivery"),
        (r"\btests?\b|\btested\b", "test or demonstration"),
        (r"\bcertif(?:y|ies|ied|ication|ications)\b", "certification"),
        (r"\bfactor(?:y|ies)\b|\bcapacity\b", "factory or capacity"),
        (r"\bproduction\b", "production"),
        (r"\blaunch(?:es|ed|ing)?\b", "launch"),
        (r"\bacqui(?:re|res|red|sition|sitions)\b", "acquisition"),
        (r"\bfinanc(?:e|es|ed|ing)\b", "financing"),
    )
    for pattern, label in labels:
        if re.search(pattern, text):
            return label
    return "dated source item"


def build_editorial(
    holdings: list[Holding],
    instruments: list[dict[str, Any]],
    events: list[dict[str, Any]],
    issue_date: dt.date,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rotation_index = ((issue_date - dt.date(2024, 1, 7)).days // 7) % len(holdings) if holdings else 0
    rotating_holding = holdings[rotation_index] if holdings else None
    instrument_by_id = {item["id"]: item for item in instruments}
    eligible = [
        event for event in events
        if event.get("recency_class") == "issue"
        and event.get("event_type") == "operational"
        and event.get("source_kind") in {"primary", "secondary"}
    ]
    stories = []
    secondary_by_holding: set[str] = set()
    secondary_total = 0
    ordered = sorted(eligible, key=lambda row: (0 if row.get("source_kind") == "primary" else 1, -int(row.get("score", 0)), row["holding_id"], row["title"]))
    for event in ordered:
        if event.get("source_kind") == "secondary":
            if event["holding_id"] in secondary_by_holding or secondary_total >= 3:
                continue
            secondary_by_holding.add(event["holding_id"])
            secondary_total += 1
        if len(stories) >= 8:
            break
        story = dict(event)
        story["operation_label"] = _operation_label(event)
        instrument = instrument_by_id.get(event["holding_id"])
        story["market_context"] = (instrument or {}).get("metrics", {}).get("periods", {})
        story["market_context_note"] = "Price context is shown without asserting that the event caused the move."
        stories.append(story)
    feature = dict(stories[0]) if stories else {
        "status": "quiet",
        "headline": "No qualifying operational event crossed the evidence threshold",
        "summary": "Quiet means no supported story was selected for this issue. It is not a negative signal.",
        "holding_id": None,
        "source_kind": None,
    }
    if stories:
        feature["headline"] = feature["title"]
        feature["summary"] = feature.get("summary") or "Read the source for the dated evidence."
        feature["status"] = "ready"
    previous_by_id = {item.get("id"): item for item in (previous or {}).get("instruments", [])}
    changed: list[dict[str, Any]] = []
    for item in instruments:
        old = previous_by_id.get(item["id"])
        if not old:
            continue
        new_price = (item.get("metrics") or {}).get("latest_close")
        old_price = (old.get("metrics") or {}).get("latest_close")
        if new_price is None or old_price is None or old_price == 0:
            continue
        delta = new_price / old_price - 1.0
        if abs(delta) >= 0.02 or (item.get("momentum") or {}).get("stage2") != (old.get("momentum") or {}).get("stage2"):
            changed.append({
                "holding_id": item["id"],
                "name": item["name"],
                "latest_change": delta,
                "stage2_changed": (item.get("momentum") or {}).get("stage2") != (old.get("momentum") or {}).get("stage2"),
            })
    context = [event for event in events if event.get("recency_class") == "context"][:8]
    qualifying_ids = {event["holding_id"] for event in eligible}
    quiet_ids = sorted({holding.id for holding in holdings} - qualifying_ids)
    return {
        "feature": feature,
        "machine_of_week": {
            "holding_id": rotating_holding.id if rotating_holding else None,
            "name": rotating_holding.name if rotating_holding else None,
            "status": "ready" if rotating_holding else "unavailable",
            "note": "Deterministic rotation through the verified coverage universe. The dossier is not a recommendation.",
        },
        "stories": stories,
        "quiet_holdings": quiet_ids,
        "older_context": context,
        "changed_since_last_week": changed,
        "next_week": {
            "status": "not-supported",
            "items": [],
            "note": "The zero-key feeds expose publication dates, not reliable future event dates. No forward event calendar is inferred.",
        },
        "voices_worth_reading": {"status": "not-configured", "note": "Optional X enrichment is not configured and is not required."},
        "event_market_rule": "An event and a price move are adjacent evidence. This edition does not infer causality.",
    }
