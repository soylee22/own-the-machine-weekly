import pytest

from app.privacy import assert_public_payload, find_privacy_violations, sanitise_text, sanitise_url


def test_iso_date_is_not_a_phone_number():
    assert find_privacy_violations({"asof": "2026-09-20"}) == []
    assert sanitise_text("Issue date 2026-09-20") == "Issue date 2026-09-20"


def test_specific_phone_and_email_formats_are_removed():
    assert sanitise_text("Call 020 7946 0958") == "Call [phone removed]"
    assert sanitise_text("Email someone@example.com") == "Email [email removed]"


def test_public_url_rejects_userinfo_and_private_hosts():
    with pytest.raises(ValueError, match="user information"):
        sanitise_url("https://user:secret@example.com/report")
    with pytest.raises(ValueError, match="Non-public"):
        sanitise_url("http://127.0.0.1/report")
    assert sanitise_url("https://example.com/report?api_key=hidden&edition=1") == "https://example.com/report?edition=1"


def test_public_payload_rejects_private_fields():
    with pytest.raises(ValueError, match="private field"):
        assert_public_payload({"holding": {"units": 2}})
