import datetime as dt

from app.momentum import apply_momentum, compute_trend_features, k_ratio_from_closes


def bars(multiplier=1.0, count=320):
    return [
        {"date": (dt.date(2025, 1, 1) + dt.timedelta(days=index)).isoformat(), "close": multiplier * (100 + index * 0.2 + (index % 7) * 0.03), "volume": 1}
        for index in range(count)
    ]


def test_k_ratio_requires_sufficient_history():
    assert k_ratio_from_closes([100.0] * 20) is None
    assert k_ratio_from_closes([100.0 + index for index in range(100)]) is not None


def test_portfolio_score_covers_non_stage2_holding():
    first = compute_trend_features(bars(1.0))
    second = compute_trend_features(bars(0.8))
    assert first and second
    result = apply_momentum({"one": first, "two": second})
    assert result["one"]["portfolio_momentum_score"] is not None
    assert result["two"]["portfolio_momentum_score"] is not None
    assert result["two"]["stage2"] is False or result["two"]["stage2"] is True


def test_score_is_unavailable_instead_of_averaging_three_components():
    first = compute_trend_features(bars(1.0))
    assert first
    first["k_ratio"] = None
    result = apply_momentum({"one": first})
    assert result["one"]["portfolio_momentum_score"] is None
    assert result["one"]["score_status"] == "unavailable"


def test_stage2_does_not_fake_broad_market_rs_from_portfolio_rank():
    first = compute_trend_features(bars(1.0))
    assert first
    result = apply_momentum({"one": first})["one"]
    assert result["portfolio_rs_rating"] is not None
    assert result["market_rs_rating"] is None
    assert result["gates"]["g8_rs_rating_ge_70"] is None
    assert result["stage2"] is None
    assert result["stage2_status"] == "market-rs-unavailable"
