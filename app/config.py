"""Load the small, public holdings configuration without a YAML dependency."""

from __future__ import annotations

import ast
import datetime as dt
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


_PRIVATE_FIELD_NAMES = {
    "units",
    "shares",
    "quantity",
    "balance",
    "cost",
    "purchase_price",
    "selling_price",
    "portfolio_value",
    "account_id",
    "credential",
    "token",
    "secret",
    "password",
}


@dataclass(frozen=True)
class Holding:
    id: str
    name: str
    symbol: str
    exchange: str
    currency: str
    asset_type: str
    country: str
    official_url: str
    source_query: str
    dossier_type: str
    cik: int | None = None
    listing_date: str | None = None
    listing_date: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strip_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
            continue
        if char in {"'", '"'}:
            quote = None if quote == char else (char if quote is None else quote)
        elif char == "#" and quote is None:
            return value[:index].rstrip()
    return value.strip()


def _scalar(value: str) -> Any:
    value = _strip_comment(value)
    if not value:
        return ""
    if value in {"null", "~"}:
        return None
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    if value[:1] in {"[", "{"}:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _parse_flat_yaml(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    top: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_holdings = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped == "holdings:":
            in_holdings = True
            continue
        if in_holdings and stripped.startswith("- "):
            current = {}
            rows.append(current)
            pair = stripped[2:].strip()
            if pair:
                key, separator, value = pair.partition(":")
                if not separator:
                    raise ValueError(f"Invalid holding line: {raw_line}")
                current[key.strip()] = _scalar(value.strip())
            continue
        if in_holdings and current is not None and ":" in stripped:
            key, _, value = stripped.partition(":")
            current[key.strip()] = _scalar(value.strip())
            continue
        if ":" in stripped:
            key, _, value = stripped.partition(":")
            top[key.strip()] = _scalar(value.strip())
    return top, rows


def load_holdings(path: Path) -> tuple[dict[str, Any], list[Holding]]:
    top, rows = _parse_flat_yaml(path)
    for row in rows:
        forbidden = sorted(set(row) & _PRIVATE_FIELD_NAMES)
        if forbidden:
            raise ValueError(f"Private holding fields are forbidden: {', '.join(forbidden)}")
        required = {
            "id",
            "name",
            "symbol",
            "exchange",
            "currency",
            "asset_type",
            "country",
            "official_url",
            "source_query",
            "dossier_type",
        }
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"Holding {row.get('id', '<unknown>')} misses: {', '.join(missing)}")
        if row.get("listing_date") is not None:
            try:
                dt.date.fromisoformat(str(row["listing_date"]))
            except ValueError as exc:
                raise ValueError(f"Holding {row.get('id', '<unknown>')} has invalid listing_date") from exc
        if row.get("listing_date") is not None:
            try:
                dt.date.fromisoformat(str(row["listing_date"]))
            except ValueError as exc:
                raise ValueError(f"Holding {row.get('id', '<unknown>')} has invalid listing_date") from exc
    holdings = [
        Holding(
            id=str(row["id"]),
            name=str(row["name"]),
            symbol=str(row["symbol"]),
            exchange=str(row["exchange"]),
            currency=str(row["currency"]),
            asset_type=str(row["asset_type"]),
            country=str(row["country"]),
            official_url=str(row["official_url"]),
            source_query=str(row["source_query"]),
            dossier_type=str(row["dossier_type"]),
            cik=int(row["cik"]) if row.get("cik") is not None else None,
            listing_date=str(row["listing_date"]) if row.get("listing_date") is not None else None,
            listing_date=str(row["listing_date"]) if row.get("listing_date") is not None else None,
        )
        for row in rows
    ]
    ids = [holding.id for holding in holdings]
    if len(ids) != len(set(ids)):
        raise ValueError("Holding identifiers must be unique")
    symbols = [holding.symbol for holding in holdings]
    if len(symbols) != len(set(symbols)):
        raise ValueError("Holding symbols must be unique")
    return top, holdings
