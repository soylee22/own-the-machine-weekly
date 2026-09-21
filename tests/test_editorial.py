import datetime as dt

from app.config import Holding
from app.editorial import build_editorial, deduplicate_events, has_concrete_terms, parse_rss


HOLDING = Holding("test", "Test Holding", "TEST", "NYSE", "USD", "equity", "US", "https://example.com/news", "Test Holding", "bank")


def event(title, published_date, event_type="operational", source_kind="secondary", holding_id="test", score=20):
    return {
        "holding_id": holding_id,
        "holding_name": "Test Holding",
        "title": title,
        "summary": "A dated source item.",
        "published_date": published_date,
        "source_name": "Example",
        "source_url": "https://example.com/story",
        "publisher_url": "https://example.com",
        "source_kind": source_kind,
        "event_type": event_type,
        "recency_class": "issue" if (dt.date(2026, 9, 20) - dt.date.fromisoformat(published_date)).days <= 7 else "context",
        "score": score,
    }


def test_concrete_detection_uses_word_boundaries():
    assert not has_concrete_terms("Latest Financial Group results")
    assert has_concrete_terms("Factory capacity expands")


def test_google_source_name_cannot_make_empty_domain_primary():
    xml = b'''<rss><channel><item><title>Factory opens</title><link>https://example.com/story</link><pubDate>Fri, 18 Sep 2026 12:00:00 GMT</pubDate><source url="https://news.example.org"></source></item></channel></rss>'''
    parsed = parse_rss(xml, HOLDING, dt.date(2026, 9, 20))
    assert parsed[0]["source_kind"] == "secondary"


def test_deduplication_keeps_one_near_duplicate():
    rows = [event("Factory opens in Wales", "2026-09-19", score=30), event("Factory opens in Wales today", "2026-09-19", score=20)]
    assert len(deduplicate_events(rows)) == 1


def test_seven_day_stories_and_older_context_are_separate_and_quiet_is_not_top_eight():
    current = event("Factory contract awarded", "2026-09-18", score=30)
    older = event("Factory capacity expands", "2026-09-01", score=40)
    other = Holding("other", "Other Holding", "OTHER", "NYSE", "USD", "equity", "US", "https://other.example/news", "Other", "bank")
    result = build_editorial(
        [HOLDING, other],
        [{"id": "test", "metrics": {"periods": {}}}, {"id": "other", "metrics": {"periods": {}}}],
        [current, older],
        dt.date(2026, 9, 20),
    )
    assert [row["title"] for row in result["stories"]] == ["Factory contract awarded"]
    assert [row["title"] for row in result["older_context"]] == ["Factory capacity expands"]
    assert result["quiet_holdings"] == ["other"]
    assert result["next_week"]["status"] == "not-supported"


def test_low_quality_secondary_is_penalised_below_normal_secondary():
    from app.editorial import _event_score
    base = event("Factory contract awarded", "2026-09-19", score=0)
    base["publisher_tier"] = "secondary"
    low = dict(base); low["publisher_tier"] = "low-quality-secondary"
    assert _event_score(low, dt.date(2026, 9, 20)) < _event_score(base, dt.date(2026, 9, 20))
