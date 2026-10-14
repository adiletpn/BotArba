import json

from app.apipay.webhook import compute_signature, verify_signature

SECRET = "whsec_test"


def test_valid_signature_passes():
    body = b'{"event":"invoice.status_changed"}'
    assert verify_signature(body, compute_signature(body, SECRET), SECRET) is True


def test_tampered_body_fails():
    body = b'{"amount":"190000.00"}'
    signature = compute_signature(body, SECRET)
    assert verify_signature(b'{"amount":"999999.00"}', signature, SECRET) is False


def test_wrong_secret_fails():
    body = b"{}"
    assert verify_signature(body, compute_signature(body, "other"), SECRET) is False


def test_missing_header_fails_when_secret_is_set():
    assert verify_signature(b"{}", None, SECRET) is False
    assert verify_signature(b"{}", "", SECRET) is False


def test_without_secret_verification_is_disabled():
    # Секрет не настроен: подпись не приходит, статус подтверждаем через API.
    assert verify_signature(b"{}", None, "") is True


def test_signature_is_computed_over_raw_bytes_not_reserialized_json():
    payload = {"event": "invoice.status_changed", "invoice": {"id": 42}}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    reserialized = json.dumps(payload, indent=2).encode()
    assert compute_signature(raw, SECRET) != compute_signature(reserialized, SECRET)
