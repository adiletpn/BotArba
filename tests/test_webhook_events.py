import pytest

from app.apipay.webhook import (
    IgnoredEvent,
    check_sandbox_flag,
    extract_paid_invoice,
    extract_refund,
)

# Пример из официальной спеки ApiPay (x-webhooks: invoice.status_changed)
PAID_EVENT = {
    "event": "invoice.status_changed",
    "is_sandbox": False,
    "invoice": {
        "id": 42,
        "external_order_id": "order_123",
        "amount": "190000.00",
        "status": "paid",
        "kaspi_invoice_id": "13234689513",
        "client_phone": "87071234567",
        "is_sandbox": False,
        "kaspi_source_type": "GOLD",
        "kaspi_sale_type": "Remote",
        "paid_at": "2026-10-13T14:35:00+00:00",
    },
    "source": "My API Key",
    "timestamp": "2026-10-13T14:35:01+00:00",
}


def test_paid_invoice_is_extracted_with_exact_amount():
    invoice = extract_paid_invoice(PAID_EVENT)
    assert invoice.invoice_id == 42
    assert invoice.amount == 19_000_000       # 190 000 ₸ в тиынах
    assert invoice.external_id == "invoice:42"
    assert invoice.net_amount == 19_000_000


@pytest.mark.parametrize("status", ["pending", "cancelled", "expired", "error"])
def test_non_paid_statuses_are_ignored(status):
    payload = {**PAID_EVENT, "invoice": {**PAID_EVENT["invoice"], "status": status}}
    with pytest.raises(IgnoredEvent):
        extract_paid_invoice(payload)


def test_partially_refunded_invoice_still_counts_as_received():
    payload = {
        **PAID_EVENT,
        "invoice": {**PAID_EVENT["invoice"], "status": "partially_refunded",
                    "total_refunded": "20000.00"},
    }
    invoice = extract_paid_invoice(payload)
    assert invoice.amount == 19_000_000
    assert invoice.refunded == 2_000_000
    assert invoice.net_amount == 17_000_000


REFUND_EVENT = {
    "event": "invoice.refunded",
    "is_sandbox": False,
    "refund": {
        "id": 5,
        "amount": "2000.00",
        "status": "completed",
        "kaspi_refund_id": "1126827352",
        "reason": "Возврат товара",
        "created_at": "2026-10-13T10:00:00+00:00",
    },
    "invoice": {"id": 42, "amount": "5000.00", "total_refunded": "2000.00",
                "is_fully_refunded": False, "status": "partially_refunded"},
}


def test_completed_refund_is_extracted():
    refund = extract_refund(REFUND_EVENT)
    assert refund.refund_id == 5
    assert refund.invoice_id == 42
    assert refund.amount == 200_000
    assert refund.external_id == "refund:5"


@pytest.mark.parametrize("status", ["pending", "processing", "failed"])
def test_unfinished_refunds_do_not_touch_the_balance(status):
    payload = {**REFUND_EVENT, "refund": {**REFUND_EVENT["refund"], "status": status}}
    with pytest.raises(IgnoredEvent):
        extract_refund(payload)


def test_sandbox_events_are_dropped_in_production_mode():
    with pytest.raises(IgnoredEvent):
        check_sandbox_flag({"is_sandbox": True}, sandbox_mode=False)
    # и наоборот: в режиме песочницы не принимаем боевые события
    with pytest.raises(IgnoredEvent):
        check_sandbox_flag({"is_sandbox": False}, sandbox_mode=True)


def test_matching_mode_passes():
    check_sandbox_flag({"is_sandbox": False}, sandbox_mode=False)
    check_sandbox_flag({"is_sandbox": True}, sandbox_mode=True)
