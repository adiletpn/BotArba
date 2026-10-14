"""Структуры данных уровня БД."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import aiosqlite

from app.clock import parse_utc_text

OperationType = Literal["start", "income", "expense", "correction", "refund"]
OperationSource = Literal["apipay", "manual"]

#: Человекочитаемые подписи типов операций. Живут здесь, а не в хендлере,
#: потому что их показывают и «История» в боте, и выгрузка в Google Таблицы —
#: расхождение подписей выглядело бы как расхождение данных.
OPERATION_LABELS: dict[str, str] = {
    "start": "Старт",
    "income": "Поступление",
    "expense": "Расход",
    "correction": "Корректировка",
    "refund": "Возврат",
}


@dataclass(frozen=True, slots=True)
class Operation:
    id: int
    type: OperationType
    amount: int           # тиыны, со знаком
    category: str | None
    comment: str | None
    source: OperationSource
    external_id: str | None
    created_by: int | None
    occurred_at: datetime
    created_at: datetime
    local_date: str
    is_cancelled: bool

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Operation":
        return cls(
            id=row["id"],
            type=row["type"],
            amount=row["amount"],
            category=row["category"],
            comment=row["comment"],
            source=row["source"],
            external_id=row["external_id"],
            created_by=row["created_by"],
            occurred_at=parse_utc_text(row["occurred_at"]),
            created_at=parse_utc_text(row["created_at"]),
            local_date=row["local_date"],
            is_cancelled=bool(row["is_cancelled"]),
        )
