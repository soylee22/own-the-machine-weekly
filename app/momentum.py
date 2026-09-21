"""Momentum calculations adapted from the public Momentum Power Scanner."""

from __future__ import annotations

import math
from typing import Any


def _closes(bars: list[dict[str, Any]]) -> list[float]:
    return [float(row["close"]) for row in sorted(bars, key=lambda row: row["date"]) if float(row["close"]) > 0]


def _session_return(closes: list[float], sessions: int) -> float | None:
    if len(closes) <= sessions:
        return None
    return closes[-1] / closes[-1 - sessions] - 1.0


def k_ratio_from_closes(closes: list[float], window: int = 252) -> float | None:
    """Return the t-statistic of a log-price trend over up to 252 sessions."""

    values = closes[-window:]
    if len(values) < 60 or any(value <= 0 for value in values):
        return None
    y = [math.log(value) for value in values]
    n = len(y)
    x_mean = (n - 1) / 2.0
    y_mean = sum(y) / n
    ss_xx = sum((index - x_mean) ** 2 for index in range(n))
    if ss_xx <= 0:
        return None
    slope = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(y)) / ss_xx
    intercept = y_mean - slope * x_mean
    residuals = [value - (intercept + slope * index) for index, value in enumerate(y)]
    dof = n - 2
    mse = sum(value * value for value in residuals) / dof if dof > 0 else 0.0
    if mse <= 0 or not math.isfinite(mse):
        return None
    standard_error = math.sqrt(mse / ss_xx)
    return slope / standard_error if standard_error > 0 else None


def compute_trend_features(bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compute the scanner's price and return features for one series."""

    closes = _closes(bars)
    if len(closes) < 220:
        return None
    price = closes[-1]
    sma50 = sum(closes[-50:]) / 50
    sma150 = sum(closes[-150:]) / 150
    sma200 = sum(closes[-200:]) / 200
    sma200_21d_ago = sum(closes[-221:-21]) / 200 if len(closes) >= 221 else None
    high_52w = max(closes[-252:]) if len(closes) >= 252 else max(closes)
    low_52w = min(closes[-252:]) if len(closes) >= 252 else min(closes)
    return {
        "price": price,
        "sma50": sma50,
        "sma150": sma150,
        "sma200": sma200,
        "sma200_21d_ago": sma200_21d_ago,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "return_3m": _session_return(closes, 63),
        "return_6m": _session_return(closes, 126),
        "return_9m": _session_return(closes, 189),
        "return_12m": _session_return(closes, 252),
        "k_ratio": k_ratio_from_closes(closes),
        "weeks_strengthening": weeks_strengthening(bars),
    }


def evaluate_gates(features: dict[str, Any], rs_rating: float | None) -> dict[str, bool]:
    """Apply the eight Stage 2 gates from the public scanner."""

    rs = rs_rating if rs_rating is not None else 0.0
    return {
        "g1_price_above_150_200": features["price"] > features["sma150"] and features["price"] > features["sma200"],
        "g2_sma150_above_sma200": features["sma150"] > features["sma200"],
        "g3_sma200_trending_up": features["sma200"] > features["sma200_21d_ago"],
        "g4_sma50_above_150_200": features["sma50"] > features["sma150"] and features["sma50"] > features["sma200"],
        "g5_price_above_sma50": features["price"] > features["sma50"],
        "g6_30pct_above_52w_low": features["price"] >= 1.30 * features["low_52w"],
        "g7_within_25pct_of_52w_high": features["price"] >= 0.75 * features["high_52w"],
        "g8_rs_rating_ge_70": rs >= 70.0,
    }


def weighted_performance(features: dict[str, Any]) -> float | None:
    parts = [features.get("return_3m"), features.get("return_6m"), features.get("return_9m"), features.get("return_12m")]
    if any(part is None or not math.isfinite(float(part)) for part in parts):
        return None
    return 0.4 * parts[0] + 0.2 * parts[1] + 0.2 * parts[2] + 0.2 * parts[3]


def _average_rank(values: list[float], value: float) -> float:
    positions = [index + 1 for index, item in enumerate(sorted(values)) if item == value]
    return sum(positions) / len(positions)


def rs_ratings(features_by_id: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    weighted = {key: weighted_performance(value) for key, value in features_by_id.items()}
    valid = [float(value) for value in weighted.values() if value is not None]
    if not valid:
        return {key: None for key in weighted}
    count = len(valid)
    output: dict[str, float | None] = {}
    for key, value in weighted.items():
        if value is None:
            output[key] = None
        else:
            output[key] = round(1.0 + 98.0 * (_average_rank(valid, float(value)) / count), 1)
    return output


def weeks_strengthening(bars: list[dict[str, Any]], weeks: int = 8) -> int | None:
    """Count positive five-session observations across the most recent weeks."""

    closes = _closes(bars)
    if len(closes) < (weeks + 1) * 5:
        return None
    positives = 0
    for week in range(weeks):
        end_index = len(closes) - 1 - week * 5
        start_index = end_index - 5
        if closes[end_index] > closes[start_index]:
            positives += 1
    return positives


def _percentile(values: list[float], value: float) -> float:
    return _average_rank(values, value) / len(values)


def apply_momentum(features_by_id: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Add a portfolio-relative score to every valid holding and a separate Stage 2 badge.

    The old scanner ranked only Stage 2 survivors. The magazine keeps that
    badge, but its Portfolio Momentum Score ranks the full valid coverage
    universe. A score is unavailable unless all four documented components
    exist for that holding.
    """

    ratings = rs_ratings(features_by_id)
    output: dict[str, dict[str, Any]] = {}
    for key, feature in features_by_id.items():
        item = dict(feature)
        rating = ratings[key]
        gates = evaluate_gates(item, rating) if item.get("sma200_21d_ago") is not None else {}
        item["weighted_perf"] = weighted_performance(item)
        item["rs_rating"] = rating
        item["gates"] = gates
        item["gates_passed"] = sum(gates.values())
        item["stage2"] = bool(gates) and all(gates.values())
        item["dist_from_high"] = (item["high_52w"] - item["price"]) / item["high_52w"] if item.get("high_52w") else None
        output[key] = item
    score_universe = [item for item in output.values() if all(item.get(field) is not None for field in ("rs_rating", "dist_from_high", "return_12m", "k_ratio"))]
    rs_values = [float(item["rs_rating"]) for item in score_universe]
    prox_values = [float(-item["dist_from_high"]) for item in score_universe]
    one_year_values = [float(item["return_12m"]) for item in score_universe]
    k_values = [float(item["k_ratio"]) for item in score_universe]
    ranked: list[tuple[float, str]] = []
    for key, item in output.items():
        required = ("rs_rating", "dist_from_high", "return_12m", "k_ratio")
        if not all(item.get(field) is not None for field in required):
            item["composite"] = None
            item["portfolio_momentum_score"] = None
            item["score_status"] = "unavailable"
            item["score_unavailable_reason"] = "Requires RS, 52-week-high distance, 1Y return and K-ratio."
            item["score_components"] = {}
            item["rank_overall"] = None
            continue
        ranks = [
            _percentile(rs_values, float(item["rs_rating"])),
            _percentile(prox_values, -float(item["dist_from_high"])),
            _percentile(one_year_values, float(item["return_12m"])),
            _percentile(k_values, float(item["k_ratio"])),
        ]
        item["composite"] = sum(ranks) / 4.0
        item["portfolio_momentum_score"] = item["composite"]
        item["score_status"] = "ready"
        item["score_unavailable_reason"] = None
        item["score_components"] = {
            "rs_percentile": ranks[0],
            "high_proximity_percentile": ranks[1],
            "one_year_percentile": ranks[2],
            "k_ratio_percentile": ranks[3],
        }
        ranked.append((item["composite"] or 0.0, key))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    for index, (_, key) in enumerate(ranked, start=1):
        output[key]["rank_overall"] = index
    return output
