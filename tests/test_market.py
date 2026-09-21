import datetime as dt
import json

import pytest

from app.market import fetch_stooq, fetch_yahoo, performance_metrics, validate_corporate_actions


class Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def yahoo_opener(payload):
    def opener(request, timeout=20):
        return Response(json.dumps(payload).encode())

    return opener


def test_partial_adjusted_series_never_mixes_price_bases():
    payload = {
        "chart": {"result": [{
            "timestamp": [1778976000, 1779062400, 1779148800],
            "meta": {"currency": "USD"},
            "indicators": {
                "quote": [{"close": [100, 101, 102], "volume": [1, 1, 1]}],
                "adjclose": [{"adjclose": [90, 91]}],
            },
        }]}
    }
    result = fetch_yahoo("TEST", dt.date(2026, 5, 18), dt.date(2026, 5, 20), yahoo_opener(payload))
    assert result.adjusted is False
    assert result.adjustment_status == "unavailable"
    assert [row["close"] for row in result.bars] == [100.0, 101.0, 102.0]


def test_unadjusted_stooq_split_jump_is_rejected():
    csv_payload = b"Date,Open,High,Low,Close,Volume\n2026-05-18,100,100,100,100,1\n2026-05-19,25,25,25,25,1\n2026-05-20,26,26,26,26,1\n"
    with pytest.raises(ValueError, match="unadjusted discontinuity"):
        fetch_stooq("TEST", dt.date(2026, 5, 18), dt.date(2026, 5, 20), lambda request, timeout=20: Response(csv_payload))


def test_corporate_action_validation_rejects_future_and_invalid_split():
    with pytest.raises(ValueError, match="after cut-off"):
        validate_corporate_actions([{"type": "dividend", "date": "2026-09-21", "amount": 1}], dt.date(2026, 9, 20))
    with pytest.raises(ValueError, match="positive"):
        validate_corporate_actions([{"type": "split", "date": "2026-09-20", "numerator": 0, "denominator": 1}], dt.date(2026, 9, 20))


def test_stale_last_bar_does_not_become_current_weekly_performance():
    bars = [{"date": (dt.date(2026, 9, 1) + dt.timedelta(days=index)).isoformat(), "close": 100 + index, "volume": 1} for index in range(5)]
    metrics = performance_metrics(bars, dt.date(2026, 9, 20))
    assert metrics["freshness_status"] == "stale"
    assert metrics["periods"]["1W"]["status"] == "stale"
    assert metrics["periods"]["1W"]["return"] is None


def test_anchor_gap_is_visible_when_no_nearby_base_session_exists():
    bars = [
        {"date": "2026-07-01", "close": 100, "volume": 1},
        {"date": "2026-09-18", "close": 110, "volume": 1},
    ]
    metrics = performance_metrics(bars, dt.date(2026, 9, 20))
    assert metrics["freshness_status"] == "ready"
    assert metrics["periods"]["1M"]["status"] == "anchor_gap"
    assert metrics["periods"]["1M"]["anchor_gap_days"] > 20
