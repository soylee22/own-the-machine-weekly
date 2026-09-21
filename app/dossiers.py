"""Permanent, non-weekly explainers for each machine category."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Holding


DOSSIER_COPY: dict[str, dict[str, Any]] = {
    "defence-prime": {
        "machine_question": "What machine do I actually own?",
        "what_it_is": "A defence prime coordinates long programmes across engineering, manufacturing, software, support and government procurement.",
        "systems": ["air systems", "maritime systems", "land systems", "electronic warfare", "mission software"],
        "watch": "Orders, programme milestones, production capacity, certification, deliveries and funded backlog.",
        "diagram_label": "programme system",
        "source_note": "The weekly layer needs a named programme or operational milestone before it creates a story.",
    },
    "aerospace-engine": {
        "machine_question": "What machine do I actually own?",
        "what_it_is": "An aerospace engine business turns long certification cycles, installed fleets, service networks and manufacturing capacity into recurring industrial work.",
        "systems": ["commercial engines", "military propulsion", "test cells", "maintenance networks", "materials and components"],
        "watch": "First flights, engine tests, certifications, deliveries, shop visits, fleet hours and production constraints.",
        "diagram_label": "propulsion loop",
        "source_note": "A test, certification or delivery is stronger evidence than a generic demand statement.",
    },
    "bank": {
        "machine_question": "What machine do I actually own?",
        "what_it_is": "A large bank is a regulated balance-sheet and payments system. Its machine is the combination of funding, credit, markets, custody and client distribution.",
        "systems": ["deposit funding", "commercial credit", "payments", "markets", "wealth and custody"],
        "watch": "Capital decisions, major financing, platform launches, regulatory actions, credit quality and technology infrastructure.",
        "diagram_label": "capital circuit",
        "source_note": "A rate headline alone is not a company event. The edition looks for a dated decision or operational change.",
    },
    "energy": {
        "machine_question": "What machine do I actually own?",
        "what_it_is": "An integrated energy company links upstream resources, processing, transport, refining, chemicals, trading and increasingly low-carbon projects.",
        "systems": ["production", "processing", "transport", "refining", "power and low-carbon projects"],
        "watch": "New capacity, project sanction, first production, discoveries, infrastructure start-up, outages and regulatory decisions.",
        "diagram_label": "energy chain",
        "source_note": "The weekly layer separates a physical project milestone from a commodity-price explanation.",
    },
    "gold": {
        "machine_question": "What machine do I actually own?",
        "what_it_is": "SGLN is treated provisionally as listed physical-gold exposure. The instrument listing and product terms still require Lee's confirmation.",
        "systems": ["allocated metal", "custody", "creation and redemption", "exchange listing", "tracking and fees"],
        "watch": "Product notices, custody or structural changes, gold-market sessions and any confirmed listing detail.",
        "diagram_label": "custody chain",
        "source_note": "Gold is an asset exposure, not an operating company. No operational company story is invented for it.",
    },
}


def load_dossier_copy(root: Path | None = None) -> dict[str, dict[str, Any]]:
    if root is None:
        return {}
    path = root / "config" / "dossier-copy.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cnx1"] = payload.get("cnx1-nasdaq", payload.get("cnx1", {}))
    payload["vall"] = payload.get("vall-global", payload.get("vall", {}))
    return {str(key): dict(value) for key, value in payload.items() if isinstance(value, dict)}


def build_dossier(holding: Holding, overrides: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    copy = dict((overrides or {}).get(holding.id) or DOSSIER_COPY[holding.dossier_type])
    copy["slug"] = holding.id
    copy["name"] = holding.name
    copy["symbol"] = holding.symbol
    copy["official_source"] = copy.get("official_source") or holding.official_url
    copy.setdefault("against", "Review the stated mechanism, evidence and execution risk before drawing a conclusion.")
    if holding.id == "ge-aerospace":
        copy["comparability_note"] = (
            "The five-year price series spans GE Aerospace's 2024 separation from General Electric's former industrial businesses. "
            "Treat long-window comparability as limited."
        )
    else:
        copy["comparability_note"] = "No special perimeter warning is encoded. Review corporate actions before interpreting long windows."
    if holding.id == "vall":
        copy["comparability_note"] = "This newly launched fund has limited live history. The site shows missing long-window returns rather than inventing them from an index proxy."
    return copy


def build_dossiers(holdings: list[Holding], root: Path | None = None) -> list[dict[str, Any]]:
    overrides = load_dossier_copy(root)
    return [build_dossier(holding, overrides) for holding in holdings]
