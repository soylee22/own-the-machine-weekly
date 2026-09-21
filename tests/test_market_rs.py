import datetime as dt
from app.market_rs import fetch_market_rs

class Response:
    def __init__(self, payload: bytes): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.payload

def opener_for(text: str):
    return lambda request, timeout=20: Response(text.encode("utf-8"))

def test_exact_date_market_rs_sidecar_is_usable():
    text = "asof,ticker,rs_rating,stage2,gates_passed\n2026-09-20,MUFG,82.7,True,8\n"
    lookup, receipt = fetch_market_rs(dt.date(2026, 9, 20), opener=opener_for(text))
    assert receipt["status"] == "ready"
    assert lookup["MUFG"]["rs_rating"] == 82.7

def test_stale_market_rs_sidecar_is_not_used():
    text = "asof,ticker,rs_rating,stage2,gates_passed\n2026-09-13,MUFG,90,True,8\n"
    lookup, receipt = fetch_market_rs(dt.date(2026, 9, 20), opener=opener_for(text))
    assert lookup == {}
    assert receipt["status"] == "stale"
