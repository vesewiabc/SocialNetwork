#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Аналитические запросы — Система электронных платежей
Запуск: python3 queries.py
"""

import sqlite3

DB_NAME = "payments_system.db"

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
RED    = "\033[91m"
GRAY   = "\033[90m"

def sep():
    print(GRAY + "─" * 60 + RESET)

def header(title):
    print()
    print(CYAN + "═" * 60 + RESET)
    print(BOLD + CYAN + f"  {title}" + RESET)
    print(CYAN + "═" * 60 + RESET)

conn = sqlite3.connect(DB_NAME)
conn.row_factory = sqlite3.Row

# Миграция: добавляем tariff_id если отсутствует
cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
if "tariff_id" not in cols:
    conn.execute("ALTER TABLE transactions ADD COLUMN tariff_id INTEGER REFERENCES tariffs(id)")
    conn.execute("UPDATE transactions SET tariff_id = 1 WHERE type IN ('transfer', 'withdrawal')")
    conn.commit()

# ─────────────────────────────────────────────────────────────
# ЗАПРОС 1: Клиент, переведший больше всего денег в этом году
# ─────────────────────────────────────────────────────────────
header("1. Клиент с наибольшим объёмом переводов в этом году")

row = conn.execute("""
    SELECT
        c.id,
        c.full_name,
        c.email,
        SUM(t.amount) AS total_sent
    FROM transactions t
    JOIN accounts a ON a.id = t.from_account_id
    JOIN clients c  ON c.id = a.client_id
    WHERE t.type    = 'transfer'
      AND t.status  = 'completed'
      AND strftime('%Y', t.created_at) = strftime('%Y', 'now')
    GROUP BY c.id
    ORDER BY total_sent DESC
    LIMIT 1
""").fetchone()

if row:
    print(f"  👤 ID:        {row['id']}")
    print(f"  📛 ФИО:       {BOLD}{row['full_name']}{RESET}")
    print(f"  📧 Email:     {row['email']}")
    print(f"  💸 Отправил:  {YELLOW}{row['total_sent']:,.2f} ₽{RESET}")
else:
    print(f"  {GRAY}Нет данных за текущий год{RESET}")

# ─────────────────────────────────────────────────────────────
# ЗАПРОС 2: Все транзакции за сегодня
# ─────────────────────────────────────────────────────────────
header("2. Все транзакции за сегодня")

#t.type - поле(колонка) в таблице транзакций, которая указывает на тип транзакций.
rows = conn.execute("""
    SELECT
        t.id,
        t.type,
        t.amount,
        t.status,
        t.description,
        t.created_at,
        fa.account_no AS from_acc,
        ta.account_no AS to_acc
    FROM transactions t
    LEFT JOIN accounts fa ON fa.id = t.from_account_id
    LEFT JOIN accounts ta ON ta.id = t.to_account_id
    WHERE date(t.created_at) = date('now')
    ORDER BY t.created_at DESC
""").fetchall()

type_icon    = {"transfer": "🔄", "deposit": "⬇️ ", "withdrawal": "⬆️ ", "fee": "💸"}
status_color = {"completed": GREEN, "failed": RED, "pending": YELLOW, "reversed": "\033[95m"}

if rows:
    for r in rows:
        icon  = type_icon.get(r['type'], "•")
        sc    = status_color.get(r['status'], RESET)
        from_ = r['from_acc'] or "—"
        to_   = r['to_acc']   or "—"
        print(f"  {CYAN}[#{r['id']}]{RESET} {icon} {BOLD}{r['type'].upper()}{RESET}  "
              f"{YELLOW}{r['amount']:,.2f} ₽{RESET}  {sc}{r['status']}{RESET}")
        print(f"       {GRAY}{from_} → {to_}{RESET}  📝 {r['description'] or '—'}")
        sep()
else:
    print(f"  {GRAY}Транзакций за сегодня нет{RESET}")

# ─────────────────────────────────────────────────────────────
# ЗАПРОС 3: Самый популярный тариф в этом месяце
# ─────────────────────────────────────────────────────────────
header("3. Самый популярный тариф в этом месяце")

row = conn.execute("""
    SELECT
        tr.id,
        tr.name,
        tr.transfer_fee_pct,
        tr.min_fee,
        tr.max_daily_limit,
        COUNT(t.id) AS usage_count
    FROM transactions t
    JOIN tariffs tr ON tr.id = t.tariff_id
    WHERE strftime('%Y-%m', t.created_at) = strftime('%Y-%m', 'now')
    GROUP BY tr.id
    ORDER BY usage_count DESC
    LIMIT 1
""").fetchone()

if row:
    print(f"  🏆 Тариф:         {BOLD}{row['name']}{RESET}")
    print(f"  📊 Использований:  {YELLOW}{row['usage_count']}{RESET}")
    print(f"  💰 Комиссия:      {row['transfer_fee_pct']}%  |  Мин. {row['min_fee']} ₽")
    print(f"  🔒 Лимит/день:    {row['max_daily_limit']:,.0f} ₽")
else:
    print(f"  {GRAY}Нет данных за текущий месяц{RESET}")

print()
conn.close()
