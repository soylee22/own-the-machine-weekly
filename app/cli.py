"""Command line entry point for the weekly issue builder."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from .dates import last_completed_sunday, parse_date, schedule_window_open
from .pipeline import build_edition, write_edition


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build one dated Own the Machine Weekly edition.")
    parser.add_argument("--asof", metavar="YYYY-MM-DD", help="Issue Sunday. Defaults to the last completed Sunday.")
    parser.add_argument("--scheduled", action="store_true", help="Enforce the Sunday 19:37 Europe/London schedule window.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Public provider timeout in seconds. Default: 20.")
    parser.add_argument("--no-news", action="store_true", help="Skip public news discovery and create a data-only edition.")
    parser.add_argument("--no-sec", action="store_true", help="Skip SEC filing receipt discovery.")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable run summary.")
    return parser


def _summary(edition: dict, write_result: dict) -> dict:
    return {
        "status": edition["status"],
        "issue_date": edition["issue_date"],
        "quality": edition["quality"],
        "archive_path": write_result["archive_path"],
        "published_to_site_data": write_result["published_to_site_data"],
        "comparison_universe_fingerprint": edition["comparison_universe_fingerprint"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc)
    if args.scheduled and not schedule_window_open(now):
        payload = {"status": "skipped", "reason": "The delayed Sunday schedule window is closed.", "now_london": now.astimezone(ZoneInfo("Europe/London")).isoformat()}
        print(json.dumps(payload, sort_keys=True) if args.json else payload["reason"])
        return 0
    try:
        issue_date = parse_date(args.asof) if args.asof else last_completed_sunday(now)
        if issue_date.weekday() != 6:
            parser.error("--asof must identify a Sunday")
        edition, receipts = build_edition(
            Path(__file__).resolve().parents[1],
            issue_date,
            include_news=not args.no_news,
            include_sec=not args.no_sec,
            timeout=args.timeout,
        )
        result = write_edition(Path(__file__).resolve().parents[1], edition, receipts)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    summary = _summary(edition, result)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Own the Machine Weekly {summary['issue_date']}: {summary['status']}")
        print(f"Market-ready holdings: {summary['quality']['ready_market_count']}")
        print(f"Stories: {summary['quality']['story_count']}")
        print(f"Archive: {summary['archive_path']}")
        print(f"Live site data replaced: {summary['published_to_site_data']}")
    return 0 if edition["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
