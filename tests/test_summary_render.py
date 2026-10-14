"""Рендер сводки сверяется с образцом из ТЗ посимвольно.

В образце ТЗ разряды разделены обычным пробелом, а бот ставит неразрывный
(U+00A0), чтобы Telegram не рвал сумму по строкам. Для сравнения приводим
к обычному пробелу — проверяем раскладку, а не выбор кода пробела.
"""

from zoneinfo import ZoneInfo

from app.services.summary import DaySummary, render_summary

ALMATY = ZoneInfo("Asia/Almaty")

SPEC_SAMPLE = """📊 Сводка за 13.10.2026

На начало дня:   1 000 000 ₸
Поступления:     +190 000 ₸  (12 оплат)
Расходы:         −100 000 ₸
  • Закуп — 80 000 ₸
  • Реклама — 20 000 ₸

Баланс сейчас:   1 090 000 ₸"""


def _normalize(text: str) -> str:
    return text.replace(" ", " ")


def test_render_matches_the_spec_sample_character_for_character():
    summary = DaySummary(
        local_date="2026-10-13",
        opening=100_000_000,
        income=19_000_000,
        income_count=12,
        refund_count=0,
        expenses=-10_000_000,
        corrections=0,
        balance=109_000_000,
        expense_rows=(("Закуп", -8_000_000), ("Реклама", -2_000_000)),
    )
    assert _normalize(render_summary(summary, ALMATY)) == SPEC_SAMPLE


def test_stale_apipay_adds_the_required_note():
    from datetime import datetime, timezone

    summary = DaySummary(
        local_date="2026-10-13",
        opening=100_000_000, income=0, income_count=0, refund_count=0,
        expenses=0, corrections=0, balance=100_000_000,
        apipay_fresh=False,
        # 13:40 UTC = 18:40 по Алматы — ровно как в примере ТЗ
        last_sync=datetime(2026, 10, 13, 13, 40, tzinfo=timezone.utc),
    )
    rendered = render_summary(summary, ALMATY)
    assert "Данные ApiPay обновлены в 18:40" in rendered
    # Сводка всё равно отправляется целиком, а не заменяется ошибкой
    assert "Баланс сейчас:" in rendered


def test_payment_counter_uses_russian_plural_forms():
    def render_with(count: int) -> str:
        return render_summary(
            DaySummary(local_date="2026-10-13", opening=0, income=1_000,
                       income_count=count, refund_count=0, expenses=0,
                       corrections=0, balance=1_000),
            ALMATY,
        )

    assert "(1 оплата)" in render_with(1)
    assert "(2 оплаты)" in render_with(2)
    assert "(5 оплат)" in render_with(5)
    assert "(11 оплат)" in render_with(11)
    assert "(21 оплата)" in render_with(21)


def test_corrections_line_appears_only_when_non_zero():
    base = dict(local_date="2026-10-13", opening=0, income=0, income_count=0,
                refund_count=0, expenses=0, balance=0)
    assert "Корректировки" not in render_summary(DaySummary(**base, corrections=0), ALMATY)
    assert "Корректировки" in render_summary(DaySummary(**base, corrections=5_000), ALMATY)
