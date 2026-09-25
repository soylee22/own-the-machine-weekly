import datetime as dt
import json
import math
import statistics
import time
import urllib.parse
import urllib.request
import warnings

START_FETCH = dt.date(2021, 9, 1)
END = dt.date(2026, 9, 24)

PORTFOLIO = {
    "SGLN.L": 0.30,
    "VT": 0.10,          # proxy/backfill for VALL.L (same FTSE Global All Cap family)
    "CNX1.L": 0.10,
    "MCD": 0.05,
    "JPM": 0.04,
    "RR.L": 0.04,
    "LMT": 0.04,
    "GS": 0.04,
    "GE": 0.04,
    "MS": 0.04,
    "HSBA.L": 0.04,
    "BA.L": 0.04,
    "RHM.DE": 0.04,
    "MUFG": 0.04,
    "BP.L": 0.025,
    "SHEL.L": 0.025,
}
BENCHMARK = {"VUAG.L": 1/3, "VUKG.L": 1/3, "SGLN.L": 1/3}

GBP_TICKERS = {
    "SGLN.L", "CNX1.L", "RR.L", "HSBA.L", "BA.L", "BP.L", "SHEL.L",
    "VUAG.L", "VUKG.L", "RDSB.L", "RDSA.L",
}
USD_TICKERS = {"VT", "MCD", "JPM", "LMT", "GS", "GE", "MS", "MUFG"}
EUR_TICKERS = {"RHM.DE"}


def yahoo_chart(symbol, start=START_FETCH, end=END):
    p1 = int(dt.datetime.combine(start, dt.time(), tzinfo=dt.timezone.utc).timestamp())
    p2 = int(dt.datetime.combine(end + dt.timedelta(days=1), dt.time(), tzinfo=dt.timezone.utc).timestamp())
    q = urllib.parse.urlencode({
        "period1": p1,
        "period2": p2,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    })
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='.-=')}?{q}"
    last_error = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            result = ((payload.get("chart") or {}).get("result") or [None])[0]
            if not result:
                raise RuntimeError(str((payload.get("chart") or {}).get("error")))
            ts = result.get("timestamp") or []
            adj = ((((result.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose") or [])
            close = ((((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or [])
            out = {}
            for i, stamp in enumerate(ts):
                val = adj[i] if i < len(adj) and adj[i] is not None else (close[i] if i < len(close) else None)
                if val is None or not math.isfinite(float(val)) or float(val) <= 0:
                    continue
                d = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date()
                out[d] = float(val)
            if not out:
                raise RuntimeError("no usable prices")
            return out
        except Exception as exc:
            last_error = exc
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"{symbol}: {last_error}")


def try_yahoo(symbol):
    try:
        return yahoo_chart(symbol)
    except Exception:
        return {}


def ffill_on_calendar(series, calendar, allow_flat_prestart=False):
    if not series:
        raise RuntimeError("empty series")
    keys = sorted(series)
    first_d = keys[0]
    first_v = series[first_d]
    out = {}
    last = None
    for d in calendar:
        if d in series:
            last = series[d]
        if last is None and allow_flat_prestart and d < first_d:
            out[d] = first_v
        elif last is not None:
            out[d] = last
    return out


def quantile(vals, p):
    xs = sorted(vals)
    if not xs:
        return float("nan")
    k = (len(xs)-1) * p
    lo = int(math.floor(k)); hi = int(math.ceil(k))
    if lo == hi:
        return xs[lo]
    return xs[lo] * (hi-k) + xs[hi] * (k-lo)


def max_drawdown(values):
    peak = -float("inf")
    worst = 0.0
    for v in values:
        peak = max(peak, v)
        dd = v / peak - 1.0
        worst = min(worst, dd)
    return worst


def simulate(price_by_symbol, weights, dates, rebalance="annual"):
    start_val = 10000.0
    units = {s: start_val*w/price_by_symbol[s][dates[0]] for s,w in weights.items()}
    vals = []
    current_year = dates[0].year
    for d in dates:
        if rebalance == "annual" and d.year != current_year:
            total = sum(units[s] * price_by_symbol[s][d] for s in weights)
            units = {s: total*w/price_by_symbol[s][d] for s,w in weights.items()}
            current_year = d.year
        vals.append(sum(units[s] * price_by_symbol[s][d] for s in weights))
    return vals


def metrics(dates, vals):
    rets = [vals[i]/vals[i-1]-1.0 for i in range(1, len(vals))]
    years = (dates[-1]-dates[0]).days / 365.2425
    total = vals[-1]/vals[0]-1.0
    cagr = (vals[-1]/vals[0])**(1/years)-1 if years >= 1 else total
    mean_d = statistics.fmean(rets)
    vol_d = statistics.stdev(rets)
    vol = vol_d * math.sqrt(252)
    sharpe = (mean_d*252)/vol if vol else float("nan")
    downside_d = math.sqrt(statistics.fmean([min(0.0, r)**2 for r in rets]))
    downside = downside_d * math.sqrt(252)
    sortino = (mean_d*252)/downside if downside else float("nan")
    mdd = max_drawdown(vals)
    calmar = cagr/abs(mdd) if mdd else float("nan")
    q05 = quantile(rets, .05)
    cvar = statistics.fmean([r for r in rets if r <= q05])
    # month-end return sequence
    month_ends = {}
    for d,v in zip(dates, vals):
        month_ends[(d.year,d.month)] = v
    mk = sorted(month_ends)
    mrets = [month_ends[mk[i]]/month_ends[mk[i-1]]-1 for i in range(1,len(mk))]
    # calendar returns for full years between first and last partial years
    year_ends = {}
    for d,v in zip(dates, vals):
        year_ends[d.year] = v
    cal = {}
    for y in range(dates[0].year+1, dates[-1].year):
        if y in year_ends and y-1 in year_ends:
            cal[str(y)] = year_ends[y]/year_ends[y-1]-1
    # rolling 252-session returns
    roll = [vals[i]/vals[i-252]-1 for i in range(252, len(vals))]
    return {
        "total_return": total,
        "cagr": cagr,
        "volatility": vol,
        "sharpe_0rf": sharpe,
        "sortino_0target": sortino,
        "downside_deviation": downside,
        "max_drawdown": mdd,
        "calmar": calmar,
        "daily_var95": -q05,
        "daily_cvar95": -cvar,
        "positive_months": sum(r>0 for r in mrets)/len(mrets),
        "best_month": max(mrets),
        "worst_month": min(mrets),
        "rolling_1y_min": min(roll),
        "rolling_1y_median": statistics.median(roll),
        "rolling_1y_max": max(roll),
        "calendar_returns": cal,
        "ending_10k": vals[-1],
    }


def relative_metrics(a_vals, b_vals):
    ar = [a_vals[i]/a_vals[i-1]-1 for i in range(1,len(a_vals))]
    br = [b_vals[i]/b_vals[i-1]-1 for i in range(1,len(b_vals))]
    ma = statistics.fmean(ar); mb = statistics.fmean(br)
    cov = sum((x-ma)*(y-mb) for x,y in zip(ar,br))/(len(ar)-1)
    vb = statistics.variance(br)
    corr = cov/(statistics.stdev(ar)*statistics.stdev(br))
    beta = cov/vb
    active = [x-y for x,y in zip(ar,br)]
    te = statistics.stdev(active)*math.sqrt(252)
    ir = statistics.fmean(active)*252/te if te else float("nan")
    return {"correlation": corr, "beta_vs_benchmark": beta, "tracking_error": te, "information_ratio": ir}


def run_window(price_by_symbol, start_date, end_date):
    all_symbols = set(PORTFOLIO) | set(BENCHMARK)
    dates = sorted(set.intersection(*[
        set(d for d in price_by_symbol[s] if start_date <= d <= end_date)
        for s in all_symbols
    ]))
    if len(dates) < 500:
        raise RuntimeError(f"too few common dates: {len(dates)}")
    # We constructed each price series over the same master calendar, so use every day.
    a = simulate(price_by_symbol, PORTFOLIO, dates, "annual")
    b = simulate(price_by_symbol, BENCHMARK, dates, "annual")
    a_nr = simulate(price_by_symbol, PORTFOLIO, dates, "none")
    b_nr = simulate(price_by_symbol, BENCHMARK, dates, "none")
    return {
        "start": dates[0].isoformat(),
        "end": dates[-1].isoformat(),
        "sessions": len(dates),
        "portfolio": metrics(dates, a),
        "benchmark": metrics(dates, b),
        "relative": relative_metrics(a,b),
        "buy_hold_sensitivity": {
            "portfolio_cagr": metrics(dates,a_nr)["cagr"],
            "benchmark_cagr": metrics(dates,b_nr)["cagr"],
            "portfolio_mdd": metrics(dates,a_nr)["max_drawdown"],
            "benchmark_mdd": metrics(dates,b_nr)["max_drawdown"],
        },
    }


def test_chatgpt_portfolio_backtest():
    requested = set(PORTFOLIO) | set(BENCHMARK)
    raw = {}
    errors = {}
    for sym in sorted(requested | {"GBPUSD=X", "EURGBP=X"}):
        try:
            raw[sym] = yahoo_chart(sym)
        except Exception as exc:
            errors[sym] = str(exc)
    # Shell predecessor backfill if Yahoo still serves the delisted London line.
    shell_predecessor = None
    for old in ("RDSB.L", "RDSA.L"):
        x = try_yahoo(old)
        if x:
            raw[old] = x
            shell_predecessor = old
            break

    critical_missing = [s for s in requested | {"GBPUSD=X","EURGBP=X"} if s not in raw]
    if critical_missing:
        raise AssertionError("Missing Yahoo data: " + json.dumps({s: errors.get(s) for s in critical_missing}))

    # Master calendar: union of all live requested instruments and FX trading days.
    master = sorted(set().union(*(set(v) for k,v in raw.items() if k in requested | {"GBPUSD=X","EURGBP=X"})))
    master = [d for d in master if START_FETCH <= d <= END]

    # Backfill Shell's current line from predecessor if available. Otherwise flat-fill the short pre-2022 gap.
    shell = dict(raw["SHEL.L"])
    shell_fallback_mode = "flat-before-SHEL-listing"
    if shell_predecessor:
        for d,v in raw[shell_predecessor].items():
            if d < min(shell):
                shell[d] = v
        shell_fallback_mode = shell_predecessor
    raw["SHEL.L"] = shell

    ffilled = {}
    for sym in requested | {"GBPUSD=X","EURGBP=X"}:
        allow_flat = sym == "SHEL.L" and shell_predecessor is None
        ffilled[sym] = ffill_on_calendar(raw[sym], master, allow_flat_prestart=allow_flat)

    # Trim calendar to dates on/after 2021-09-24 for which every required series and FX rate exists.
    master = [d for d in master if d >= dt.date(2021,9,24) and all(d in ffilled[s] for s in requested | {"GBPUSD=X","EURGBP=X"})]

    gbpusd = ffilled["GBPUSD=X"]
    eurgbp = ffilled["EURGBP=X"]
    prices_gbp = {}
    for sym in requested:
        p = ffilled[sym]
        if sym in GBP_TICKERS:
            prices_gbp[sym] = {d:p[d] for d in master}
        elif sym in USD_TICKERS:
            prices_gbp[sym] = {d:p[d]/gbpusd[d] for d in master}
        elif sym in EUR_TICKERS:
            prices_gbp[sym] = {d:p[d]*eurgbp[d] for d in master}
        else:
            raise AssertionError(f"currency mapping missing: {sym}")

    result = {
        "assumptions": {
            "reporting_currency": "GBP",
            "adjusted_close": True,
            "rebalancing": "annual",
            "risk_free_rate": 0.0,
            "vall_proxy": "VT",
            "shell_backfill": shell_fallback_mode,
            "benchmark": "1/3 VUAG.L + 1/3 VUKG.L + 1/3 SGLN.L",
            "portfolio_weights": PORTFOLIO,
        },
        "five_year": run_window(prices_gbp, dt.date(2021,9,24), END),
        "three_year": run_window(prices_gbp, dt.date(2023,9,25), END),
    }
    warnings.warn("CHATGPT_BACKTEST=" + json.dumps(result, sort_keys=True), UserWarning)
    assert abs(sum(PORTFOLIO.values())-1.0) < 1e-9
    assert abs(sum(BENCHMARK.values())-1.0) < 1e-9
