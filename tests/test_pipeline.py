import json
from pathlib import Path

from app.config import load_holdings
from app.pipeline import assess_quality, write_edition
from app.privacy import find_privacy_violations


ROOT = Path(__file__).resolve().parents[1]


def test_verified_universe_has_seventeen_public_instruments():
    metadata, holdings = load_holdings(ROOT / "config" / "holdings.yaml")
    assert metadata["coverage"] == "verified-2026-09-21"
    assert len(holdings) == 17
    assert {holding.symbol for holding in holdings} >= {"CNX1.L", "VALL.L", "MUFG"}
    assert all(not hasattr(holding, "units") for holding in holdings)


def test_failed_edition_does_not_replace_good_live_site_data(tmp_path):
    site_data = tmp_path / "site/src/data"
    site_data.mkdir(parents=True)
    good = {"issue_date": "2026-09-13", "status": "ready"}
    (site_data / "edition.json").write_text(json.dumps(good), encoding="utf-8")
    failed = {
        "issue_date": "2026-09-20",
        "status": "failed",
        "quality": {"publishable": False},
    }
    result = write_edition(tmp_path, failed, [])
    assert result["published_to_site_data"] is False
    assert json.loads((site_data / "edition.json").read_text(encoding="utf-8")) == good


def test_older_publishable_edition_cannot_replace_newer_live_site_data(tmp_path):
    site_data = tmp_path / "site/src/data"
    site_data.mkdir(parents=True)
    newer = {"issue_date": "2026-09-20", "status": "ready", "quality": {"publishable": True}}
    (site_data / "edition.json").write_text(json.dumps(newer), encoding="utf-8")
    older = {"issue_date": "2026-09-13", "status": "ready", "quality": {"publishable": True}}
    result = write_edition(tmp_path, older, [])
    assert result["published_to_site_data"] is False
    assert result["guard"] == "older_issue_did_not_replace_newer_live_data"
    assert json.loads((site_data / "edition.json").read_text(encoding="utf-8")) == newer


def test_consecutive_successful_sundays_publish_in_order(tmp_path):
    first = {"issue_date": "2026-09-13", "status": "ready", "quality": {"publishable": True}}
    second = {"issue_date": "2026-09-20", "status": "ready", "quality": {"publishable": True}}
    assert write_edition(tmp_path, first, [])["published_to_site_data"] is True
    assert write_edition(tmp_path, second, [])["published_to_site_data"] is True
    live = json.loads((tmp_path / "site/src/data/edition.json").read_text(encoding="utf-8"))
    assert live["issue_date"] == "2026-09-20"
    assert (tmp_path / "data/editions/2026-09-13/edition.json").exists()
    assert (tmp_path / "data/editions/2026-09-20/edition.json").exists()


def test_failed_same_date_refresh_preserves_good_archive(tmp_path):
    good = {"issue_date": "2026-09-20", "status": "ready", "quality": {"publishable": True}}
    failed = {"issue_date": "2026-09-20", "status": "failed", "quality": {"publishable": False}}
    write_edition(tmp_path, good, [])
    result = write_edition(tmp_path, failed, [{"status": "failed"}])
    assert result["guard"] == "good_same_date_archive_preserved"
    assert json.loads((tmp_path / "data/editions/2026-09-20/edition.json").read_text(encoding="utf-8"))["status"] == "ready"
    assert (tmp_path / "data/editions/2026-09-20/failed-attempt.json").exists()


def test_severe_partial_and_all_news_failure_fail_the_publication_gate():
    severe_markets = [{"status": "ready", "freshness_status": "ready"}] + [{"status": "failed", "freshness_status": "missing"}] * 16
    failed_news = [{"provider": "google-news-rss", "status": "failed"}] * 17
    severe = assess_quality(severe_markets, failed_news, 17, include_news=True)
    assert severe["publishable"] is False
    assert "below" in severe["note"]
    mostly_ready = [{"status": "ready", "freshness_status": "ready"}] * 16 + [{"status": "failed", "freshness_status": "missing"}]
    all_news_failed = assess_quality(mostly_ready, failed_news, 17, include_news=True)
    assert all_news_failed["publishable"] is False
    assert "news discovery feeds failed" in all_news_failed["note"]


def test_partial_publish_has_a_frontend_visible_quality_note():
    markets = [{"status": "ready", "freshness_status": "ready"}] * 16 + [{"status": "failed", "freshness_status": "missing"}]
    news = [{"provider": "google-news-rss", "status": "ready"}]
    quality = assess_quality(markets, news, 17, include_news=True)
    assert quality["publishable"] is True
    assert quality["partial"] is True
    assert "Partial refresh" in quality["note"]


def test_real_generated_edition_contract_and_public_boundary():
    path = ROOT / "site/src/data/edition.json"
    assert path.exists()
    edition = json.loads(path.read_text(encoding="utf-8"))
    _, configured = load_holdings(ROOT / "config/holdings.yaml")
    configured_ids = [holding.id for holding in configured]
    assert edition["schema_version"] == 1
    assert edition["status"] in {"ready", "partial", "failed"}
    assert edition["issue_date"] == edition["cutoff"]["issue_date"]
    assert [row["id"] for row in edition["comparison_universe"]] == configured_ids
    assert {row["id"] for row in edition["instruments"]} == set(configured_ids)
    assert {row["slug"] for row in edition["dossiers"]} == set(configured_ids)
    assert edition["quality"]["ready_market_count"] <= len(configured_ids)
    assert edition["editorial"]["next_week"]["status"] in {"ready", "not-supported"}
    assert find_privacy_violations(edition) == []


def test_immutable_launch_fixture_matches_the_first_real_edition():
    fixture = json.loads((ROOT / "tests/fixtures/launch-expectations.json").read_text(encoding="utf-8"))
    launch = json.loads((ROOT / "data/editions/2026-09-20/edition.json").read_text(encoding="utf-8"))
    assert launch["issue_date"] == fixture["issue_date"]
    assert launch["status"] == fixture["status"]
    assert [row["id"] for row in launch["comparison_universe"]] == fixture["holding_ids"]
    assert launch["editorial"]["next_week"]["status"] == fixture["next_week_status"]
    assert sum(bool(dossier.get("against")) for dossier in launch["dossiers"]) == fixture["dossier_against_count"]
