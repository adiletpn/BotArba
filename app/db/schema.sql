-- Схема BotArba. Денежные суммы — целые ТИЫНЫ (1 ₸ = 100 тиын), без float.
-- Баланс нигде не хранится числом: он всегда Σ operations.amount
-- по неотменённым строкам (требование ТЗ — ошибку можно найти и исправить).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Белый список: кто вообще может говорить с ботом.
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL DEFAULT '',
    role        TEXT    NOT NULL DEFAULT 'owner'
                CHECK (role IN ('owner', 'viewer')),
    created_at  TEXT    NOT NULL,

    -- Доступ отзывается флагом, а не удалением строки: на users ссылается
    -- operations.created_by, и удаление владельца снесло бы историю по FK.
    is_active   INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- Все движения денег. Одна строка = одно событие, строки не перезаписываются:
-- отмена — это is_cancelled, корректировка — отдельная операция типа correction.
CREATE TABLE IF NOT EXISTS operations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT    NOT NULL
                 CHECK (type IN ('start', 'income', 'expense', 'correction', 'refund')),

    -- Сумма в тиынах СО ЗНАКОМ: расходы и возвраты отрицательные,
    -- correction может быть любого знака. Так баланс = SUM(amount).
    amount       INTEGER NOT NULL,

    category     TEXT,
    comment      TEXT,

    source       TEXT    NOT NULL DEFAULT 'manual'
                 CHECK (source IN ('apipay', 'manual')),

    -- ID платежа/возврата в ApiPay. UNIQUE гарантирует, что повторный вебхук
    -- не удвоит сумму. NULL для ручных операций (в SQLite NULL не конфликтуют).
    external_id  TEXT    UNIQUE,

    created_by   INTEGER REFERENCES users(telegram_id),

    -- occurred_at — когда деньги реально двинулись (paid_at у ApiPay).
    -- created_at  — когда мы записали строку. Различаются: продажи мимо ApiPay
    -- подтягиваются из истории Kaspi задним числом, иногда через часы.
    occurred_at  TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,

    -- Календарный день операции в зоне мерчанта (Asia/Almaty), YYYY-MM-DD.
    -- Денормализация от occurred_at: дневные срезы в SQLite иначе требуют
    -- арифметики с часовым поясом прямо в запросе.
    local_date   TEXT    NOT NULL,

    is_cancelled INTEGER NOT NULL DEFAULT 0 CHECK (is_cancelled IN (0, 1)),
    cancelled_at TEXT,

    CHECK (type NOT IN ('expense', 'refund') OR amount < 0),
    CHECK (type NOT IN ('start', 'income') OR amount > 0),
    CHECK (amount <> 0)
);

-- Дневные срезы: сводка и «остаток на начало дня».
CREATE INDEX IF NOT EXISTS idx_operations_local_date
    ON operations (local_date) WHERE is_cancelled = 0;

-- «История»: последние 10 операций.
CREATE INDEX IF NOT EXISTS idx_operations_occurred_at
    ON operations (occurred_at DESC);

-- Статьи расходов. Пополняемый список: пользователь может ввести свою статью
-- текстом, и она сохранится здесь для будущих кнопок.
CREATE TABLE IF NOT EXISTS categories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    sort      INTEGER NOT NULL DEFAULT 100
);

-- Настройки и служебные метки (время сводки, зона, last_apipay_sync).
-- Key-value, чтобы добавление настройки не требовало миграции схемы.
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Журнал вебхуков: ТЗ требует логировать все входящие, чтобы можно было
-- разобрать спорный случай. Пишем и отвергнутые (плохая подпись) тоже.
CREATE TABLE IF NOT EXISTS webhook_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at  TEXT    NOT NULL,
    event        TEXT,
    invoice_id   TEXT,
    signature_ok INTEGER,
    is_sandbox   INTEGER,
    status_code  INTEGER NOT NULL,
    outcome      TEXT    NOT NULL,
    body         TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_logs_received_at
    ON webhook_logs (received_at DESC);
