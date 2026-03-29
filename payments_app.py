#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Система сопровождения электронных платежей
Терминальное приложение с SQLite3
"""

import sqlite3
import os
import sys
from datetime import datetime
from typing import Optional

DB_NAME = "payments_system.db"

# ─────────────────────────────────────────
# ЦВЕТА ДЛЯ ТЕРМИНАЛА
# ─────────────────────────────────────────
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE   = "\033[97m"
    GRAY    = "\033[90m"

def clr(text, color):
    return f"{color}{text}{C.RESET}"

# ─────────────────────────────────────────
# ИНИЦИАЛИЗАЦИЯ БД
# ─────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    cur.executescript("""
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS clients (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name   TEXT    NOT NULL,
        email       TEXT    UNIQUE NOT NULL,
        phone       TEXT,
        status      TEXT    DEFAULT 'active' CHECK(status IN ('active','blocked','pending')),
        created_at  TEXT    DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS accounts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id   INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
        account_no  TEXT    UNIQUE NOT NULL,
        currency    TEXT    DEFAULT 'RUB' CHECK(currency IN ('RUB','USD','EUR')),
        balance     REAL    DEFAULT 0.00,
        is_active   INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        from_account_id INTEGER REFERENCES accounts(id),
        to_account_id   INTEGER REFERENCES accounts(id),
        amount          REAL    NOT NULL CHECK(amount > 0),
        type            TEXT    NOT NULL CHECK(type IN ('transfer','deposit','withdrawal','fee')),
        status          TEXT    DEFAULT 'pending' CHECK(status IN ('pending','completed','failed','reversed')),
        description     TEXT,
        created_at      TEXT    DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS system_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type  TEXT    NOT NULL,
        message     TEXT,
        created_at  TEXT    DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS tariffs (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT    NOT NULL,
        transfer_fee_pct REAL   DEFAULT 0.0,
        min_fee         REAL    DEFAULT 0.0,
        max_daily_limit REAL    DEFAULT 100000.0,
        is_active       INTEGER DEFAULT 1
    );
    """)

    # Запросы:
    # №1
    cur.executescript("""
SELECT 
    c.id,
    c.full_name,
    c.email,
    SUM(t.amount) AS total_sent
FROM transactions t
JOIN accounts a ON a.id = t.from_account_id
JOIN clients c  ON c.id = a.client_id
WHERE t.type = 'transfer'
  AND t.status = 'completed'
  AND strftime('%Y', t.created_at) = strftime('%Y', 'now')
GROUP BY c.id
ORDER BY total_sent DESC
LIMIT 1;""")
    
    # №2
    cur.executescript("""
SELECT 
    t.id,
    t.type,
    t.amount,
    t.status,
    t.description,
    t.created_at,
    fa.account_no AS from_account,
    ta.account_no AS to_account
FROM transactions t
LEFT JOIN accounts fa ON fa.id = t.from_account_id
LEFT JOIN accounts ta ON ta.id = t.to_account_id
WHERE date(t.created_at) = date('now')
ORDER BY t.created_at DESC;""")
    
    # №3
    cur.executescript("""
SELECT 
    tr.id,
    tr.name,
    tr.transfer_fee_pct,
    tr.min_fee,
    COUNT(t.id) AS usage_count
FROM transactions t
JOIN accounts a  ON a.id = t.from_account_id
JOIN clients c   ON c.id = a.client_id
JOIN tariffs tr  ON tr.is_active = 1
WHERE strftime('%Y-%m', t.created_at) = strftime('%Y-%m', 'now')
GROUP BY tr.id
ORDER BY usage_count DESC
LIMIT 1;""")
    
    # for row in row:
    #     total = row['total_sent'] if row['total_sent'] else 0
    #     print(f"{row['full_name']} ({row['full_name']})")
    #     print(f"  Больше всего денег перевёл: {total:,.0f} ₽")
    #     print(f"  Все транзакции: {row['deals_count']}")
    #     print(f"  Средний чек:   {row['avg_deal']:,.0f} ₽")
    #     print()

    # Демо-данные (если БД пустая)
    cur.execute("SELECT COUNT(*) FROM clients")
    if cur.fetchone()[0] == 0:
        seed_demo_data(cur)

    conn.commit()
    conn.close()

def seed_demo_data(cur):
    clients = [
        ("Иванов Иван Иванович",   "ivanov@mail.ru",   "+7-900-100-0001"),
        ("Петрова Мария Сергеевна","petrova@mail.ru",  "+7-900-100-0002"),
        ("Смирнов Алексей Борисович","smirnov@mail.ru","+7-900-100-0003"),
    ]
    cur.executemany("INSERT INTO clients(full_name,email,phone) VALUES(?,?,?)", clients)

    accounts = [
        (1, "ACC-0001-RUB", "RUB", 15000.00),
        (1, "ACC-0002-USD", "USD", 250.00),0
        (2, "ACC-0003-RUB", "RUB", 7500.50),
        (3, "ACC-0004-RUB", "RUB", 32000.00),
    ]
    cur.executemany("INSERT INTO accounts(client_id,account_no,currency,balance) VALUES(?,?,?,?)", accounts)

    tariffs = [
        ("Стандарт",  0.5,  10.0, 50000.0),
        ("Бизнес",    0.2,   5.0, 500000.0),
        ("Премиум",   0.0,   0.0, 9999999.0),
    ]
    cur.executemany("INSERT INTO tariffs(name,transfer_fee_pct,min_fee,max_daily_limit) VALUES(?,?,?,?)", tariffs)

    transactions = [
        (1, 3, 2000.00, "transfer",    "completed", "Перевод Ивановой"),
        (3, 1,  500.00, "transfer",    "completed", "Возврат"),
        (4, 2, 1000.00, "transfer",    "failed",    "Превышен лимит"),
        (None,1,5000.00,"deposit",     "completed", "Пополнение счёта"),
        (1,None,300.00, "withdrawal",  "completed", "Снятие наличных"),
    ]
    cur.executemany(
        "INSERT INTO transactions(from_account_id,to_account_id,amount,type,status,description) VALUES(?,?,?,?,?,?)",
        transactions
    )

    cur.execute("INSERT INTO system_log(event_type,message) VALUES('INIT','База данных инициализирована с демо-данными')")

# ─────────────────────────────────────────
# УТИЛИТЫ
# ─────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def log_event(event_type: str, message: str):
    with get_conn() as conn:
        conn.execute("INSERT INTO system_log(event_type,message) VALUES(?,?)", (event_type, message))

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

def header(title: str):
    print()
    print(clr("═" * 56, C.CYAN))
    print(clr(f"  💳  {title}", C.BOLD + C.CYAN))
    print(clr("═" * 56, C.CYAN))

def separator():
    print(clr("─" * 56, C.GRAY))

def pause():
    input(clr("\n  [Enter] — продолжить...", C.GRAY))

def fmt_status(s):
    colors = {"active":"green","completed":"green","pending":"yellow",
              "blocked":"red","failed":"red","reversed":"magenta"}
    icons  = {"active":"✅","completed":"✅","pending":"⏳",
              "blocked":"🚫","failed":"❌","reversed":"↩️"}
    col_map = {"green":C.GREEN,"yellow":C.YELLOW,"red":C.RED,"magenta":C.MAGENTA}
    c = col_map.get(colors.get(s,"white"), C.WHITE)
    return f"{icons.get(s,'•')} {clr(s, c)}"

def input_int(prompt, min_val=1, max_val=9999) -> Optional[int]:
    try:
        val = int(input(clr(f"  {prompt}: ", C.YELLOW)))
        if not (min_val <= val <= max_val):
            print(clr(f"  Введите число от {min_val} до {max_val}", C.RED))
            return None
        return val
    except ValueError:
        print(clr("  Ошибка: введите целое число", C.RED))
        return None

def input_float(prompt) -> Optional[float]:
    try:
        val = float(input(clr(f"  {prompt}: ", C.YELLOW)))
        if val <= 0:
            print(clr("  Сумма должна быть больше 0", C.RED))
            return None
        return val
    except ValueError:
        print(clr("  Ошибка: введите число", C.RED))
        return None

# ─────────────────────────────────────────
# БЛОК: КЛИЕНТЫ
# ─────────────────────────────────────────
def menu_clients():
    while True:
        header("Управление клиентами")
        print(clr("  1", C.GREEN) + "  Список клиентов")
        print(clr("  2", C.GREEN) + "  Добавить клиента")
        print(clr("  3", C.GREEN) + "  Сменить статус клиента")
        print(clr("  4", C.GREEN) + "  Счета клиента")
        print(clr("  0", C.RED)   + "  ← Назад")
        separator()
        ch = input(clr("  Выбор: ", C.CYAN)).strip()
        if ch == "1": list_clients()
        elif ch == "2": add_client()
        elif ch == "3": change_client_status()
        elif ch == "4": client_accounts()
        elif ch == "0": break

def list_clients():
    header("Список клиентов")
    with get_conn() as conn:
        rows = conn.execute("SELECT id,full_name,email,phone,status,created_at FROM clients ORDER BY id").fetchall()
    if not rows:
        print(clr("  Клиентов нет", C.GRAY))
    for r in rows:
        print(f"  {clr(f'[{r[0]}]',C.CYAN)} {clr(r[1],C.BOLD)}")
        print(f"       📧 {r[2]}   📱 {r[3] or '—'}")
        print(f"       Статус: {fmt_status(r[4])}   📅 {r[5]}")
        separator()
    pause()

def add_client():
    header("Новый клиент")
    name  = input(clr("  ФИО: ", C.YELLOW)).strip()
    email = input(clr("  Email: ", C.YELLOW)).strip()
    phone = input(clr("  Телефон (необязательно): ", C.YELLOW)).strip() or None
    if not name or not email:
        print(clr("  ФИО и email обязательны", C.RED)); pause(); return
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO clients(full_name,email,phone) VALUES(?,?,?)", (name,email,phone))
        log_event("CLIENT_ADD", f"Добавлен клиент: {name}")
        print(clr("  ✅ Клиент добавлен!", C.GREEN))
    except sqlite3.IntegrityError:
        print(clr("  ❌ Email уже существует", C.RED))
    pause()

def change_client_status():
    header("Смена статуса клиента")
    list_clients()
    cid = input_int("ID клиента")
    if not cid: pause(); return
    print(clr("  Статусы: ", C.CYAN) + "active / blocked / pending")
    new_status = input(clr("  Новый статус: ", C.YELLOW)).strip()
    if new_status not in ("active","blocked","pending"):
        print(clr("  Неверный статус", C.RED)); pause(); return
    with get_conn() as conn:
        n = conn.execute("UPDATE clients SET status=? WHERE id=?", (new_status, cid)).rowcount
    if n:
        log_event("CLIENT_STATUS", f"Клиент #{cid} → {new_status}")
        print(clr(f"  ✅ Статус обновлён", C.GREEN))
    else:
        print(clr("  Клиент не найден", C.RED))
    pause()

def client_accounts():
    header("Счета клиента")
    cid = input_int("ID клиента")
    if not cid: pause(); return
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.id,a.account_no,a.currency,a.balance,a.is_active "
            "FROM accounts a WHERE a.client_id=? ORDER BY a.id", (cid,)
        ).fetchall()
    if not rows:
        print(clr("  Счетов нет", C.GRAY))
    for r in rows:
        status_txt = clr("активен",C.GREEN) if r[4] else clr("закрыт",C.RED)
        print(f"  {clr(f'[{r[0]}]',C.CYAN)} {r[1]}")
        print(f"       💰 {clr(f'{r[3]:,.2f} {r[2]}', C.BOLD)}   {status_txt}")
        separator()
    pause()

# ─────────────────────────────────────────
# БЛОК: СЧЕТА
# ─────────────────────────────────────────
def menu_accounts():
    while True:
        header("Управление счетами")
        print(clr("  1", C.GREEN) + "  Все счета")
        print(clr("  2", C.GREEN) + "  Открыть счёт")
        print(clr("  3", C.GREEN) + "  Пополнить счёт")
        print(clr("  4", C.GREEN) + "  Закрыть счёт")
        print(clr("  0", C.RED)   + "  ← Назад")
        separator()
        ch = input(clr("  Выбор: ", C.CYAN)).strip()
        if ch == "1": list_accounts()
        elif ch == "2": open_account()
        elif ch == "3": deposit_account()
        elif ch == "4": close_account()
        elif ch == "0": break

def list_accounts():
    header("Все счета")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.id,c.full_name,a.account_no,a.currency,a.balance,a.is_active "
            "FROM accounts a JOIN clients c ON c.id=a.client_id ORDER BY a.id"
        ).fetchall()
    for r in rows:
        st = clr("✅ активен",C.GREEN) if r[5] else clr("🔒 закрыт",C.RED)
        print(f"  {clr(f'[{r[0]}]',C.CYAN)} {r[2]}  {clr(r[1],C.BOLD)}")
        print(f"       💰 {clr(f'{r[4]:,.2f} {r[3]}', C.YELLOW)}  {st}")
        separator()
    pause()

def open_account():
    header("Открыть счёт")
    cid = input_int("ID клиента")
    if not cid: pause(); return
    print(clr("  Валюта: ", C.CYAN) + "RUB / USD / EUR")
    currency = input(clr("  Валюта: ", C.YELLOW)).strip().upper()
    if currency not in ("RUB","USD","EUR"):
        print(clr("  Неверная валюта", C.RED)); pause(); return
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    acc_no = f"ACC-{cid:04d}-{ts[-6:]}-{currency}"
    try:
        with get_conn() as conn:
            conn.execute("INSERT INTO accounts(client_id,account_no,currency) VALUES(?,?,?)", (cid,acc_no,currency))
        log_event("ACCOUNT_OPEN", f"Открыт счёт {acc_no}")
        print(clr(f"  ✅ Счёт открыт: {acc_no}", C.GREEN))
    except sqlite3.IntegrityError:
        print(clr("  ❌ Ошибка создания счёта", C.RED))
    pause()

def deposit_account():
    header("Пополнение счёта")
    acc_id = input_int("ID счёта")
    if not acc_id: pause(); return
    amount = input_float("Сумма пополнения")
    if not amount: pause(); return
    with get_conn() as conn:
        acc = conn.execute("SELECT id,balance,currency FROM accounts WHERE id=? AND is_active=1", (acc_id,)).fetchone()
        if not acc:
            print(clr("  Счёт не найден или закрыт", C.RED)); pause(); return
        conn.execute("UPDATE accounts SET balance=balance+? WHERE id=?", (amount, acc_id))
        conn.execute("INSERT INTO transactions(to_account_id,amount,type,status,description) VALUES(?,?,'deposit','completed','Пополнение счёта')", (acc_id, amount))
    log_event("DEPOSIT", f"Счёт #{acc_id} пополнен на {amount}")
    print(clr(f"  ✅ Счёт пополнен на {amount:,.2f} {acc['currency']}", C.GREEN))
    pause()

def close_account():
    header("Закрытие счёта")
    acc_id = input_int("ID счёта")
    if not acc_id: pause(); return
    with get_conn() as conn:
        acc = conn.execute("SELECT balance FROM accounts WHERE id=? AND is_active=1", (acc_id,)).fetchone()
        if not acc:
            print(clr("  Счёт не найден или уже закрыт", C.RED)); pause(); return
        if acc[0] > 0:
            print(clr(f"  ⚠️  На счёте остаток: {acc[0]:,.2f}. Сначала выведите средства.", C.YELLOW))
            pause(); return
        conn.execute("UPDATE accounts SET is_active=0 WHERE id=?", (acc_id,))
    log_event("ACCOUNT_CLOSE", f"Счёт #{acc_id} закрыт")
    print(clr("  ✅ Счёт закрыт", C.GREEN))
    pause()

# ─────────────────────────────────────────
# БЛОК: ТРАНЗАКЦИИ
# ─────────────────────────────────────────
def menu_transactions():
    while True:
        header("Транзакции")
        print(clr("  1", C.GREEN) + "  История транзакций")
        print(clr("  2", C.GREEN) + "  Выполнить перевод")
        print(clr("  3", C.GREEN) + "  Снятие средств")
        print(clr("  0", C.RED)   + "  ← Назад")
        separator()
        ch = input(clr("  Выбор: ", C.CYAN)).strip()
        if ch == "1": list_transactions()
        elif ch == "2": make_transfer()
        elif ch == "3": withdrawal()
        elif ch == "0": break

def list_transactions():
    header("История транзакций")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT t.id,t.type,t.amount,t.status,t.description,t.created_at,"
            " fa.account_no, ta.account_no "
            "FROM transactions t "
            "LEFT JOIN accounts fa ON fa.id=t.from_account_id "
            "LEFT JOIN accounts ta ON ta.id=t.to_account_id "
            "ORDER BY t.id DESC LIMIT 20"
        ).fetchall()
    type_icon = {"transfer":"🔄","deposit":"⬇️","withdrawal":"⬆️","fee":"💸"}
    for r in rows:
        icon = type_icon.get(r[1],"•")
        from_acc = r[6] or "—"
        to_acc   = r[7] or "—"
        print(f"  {clr(f'[{r[0]}]',C.CYAN)} {icon} {clr(r[1].upper(),C.BOLD)}  {clr(f'{r[2]:,.2f}',C.YELLOW)}")
        print(f"       {clr(from_acc,C.GRAY)} → {clr(to_acc,C.GRAY)}  {fmt_status(r[3])}")
        print(f"       📝 {r[4] or '—'}  📅 {r[5]}")
        separator()
    pause()

def make_transfer():
    header("Перевод между счетами")
    from_id = input_int("ID счёта отправителя")
    if not from_id: pause(); return
    to_id   = input_int("ID счёта получателя")
    if not to_id: pause(); return
    if from_id == to_id:
        print(clr("  Нельзя переводить на тот же счёт", C.RED)); pause(); return
    amount = input_float("Сумма перевода")
    if not amount: pause(); return
    desc = input(clr("  Назначение (необязательно): ", C.YELLOW)).strip() or "Перевод"

    with get_conn() as conn:
        src = conn.execute("SELECT id,balance,currency FROM accounts WHERE id=? AND is_active=1", (from_id,)).fetchone()
        dst = conn.execute("SELECT id,currency FROM accounts WHERE id=? AND is_active=1", (to_id,)).fetchone()
        if not src:
            print(clr("  Счёт отправителя не найден", C.RED)); pause(); return
        if not dst:
            print(clr("  Счёт получателя не найден", C.RED)); pause(); return
        if src[0] == 0 and src[1] != dst[1]:
            pass  # разные валюты — упрощённо разрешаем
        if src[1] < amount:
            print(clr(f"  ❌ Недостаточно средств (баланс: {src[1]:,.2f} {src[2]})", C.RED))
            conn.execute("INSERT INTO transactions(from_account_id,to_account_id,amount,type,status,description) VALUES(?,?,?,'transfer','failed',?)",
                         (from_id, to_id, amount, desc))
            pause(); return
        conn.execute("UPDATE accounts SET balance=balance-? WHERE id=?", (amount, from_id))
        conn.execute("UPDATE accounts SET balance=balance+? WHERE id=?", (amount, to_id))
        conn.execute("INSERT INTO transactions(from_account_id,to_account_id,amount,type,status,description) VALUES(?,?,?,'transfer','completed',?)",
                     (from_id, to_id, amount, desc))
    log_event("TRANSFER", f"Перевод {amount} со счёта #{from_id} на #{to_id}")
    print(clr(f"  ✅ Перевод {amount:,.2f} выполнен успешно!", C.GREEN))
    pause()

def withdrawal():
    header("Снятие средств")
    acc_id = input_int("ID счёта")
    if not acc_id: pause(); return
    amount = input_float("Сумма снятия")
    if not amount: pause(); return
    with get_conn() as conn:
        acc = conn.execute("SELECT balance,currency FROM accounts WHERE id=? AND is_active=1", (acc_id,)).fetchone()
        if not acc:
            print(clr("  Счёт не найден", C.RED)); pause(); return
        if acc[0] < amount:
            print(clr(f"  ❌ Недостаточно средств ({acc[0]:,.2f} {acc[1]})", C.RED)); pause(); return
        conn.execute("UPDATE accounts SET balance=balance-? WHERE id=?", (amount, acc_id))
        conn.execute("INSERT INTO transactions(from_account_id,amount,type,status,description) VALUES(?,?,'withdrawal','completed','Снятие наличных')", (acc_id, amount))
    log_event("WITHDRAWAL", f"Снятие {amount} со счёта #{acc_id}")
    print(clr(f"  ✅ Снято {amount:,.2f} {acc[1]}", C.GREEN))
    pause()

# ─────────────────────────────────────────
# БЛОК: ОТЧЁТЫ
# ─────────────────────────────────────────
def menu_reports():
    while True:
        header("Отчёты и статистика")
        print(clr("  1", C.GREEN) + "  Общая сводка системы")
        print(clr("  2", C.GREEN) + "  Топ-5 счетов по балансу")
        print(clr("  3", C.GREEN) + "  Статистика транзакций")
        print(clr("  4", C.GREEN) + "  Журнал системных событий")
        print(clr("  5", C.GREEN) + "  Тарифы")
        print(clr("  0", C.RED)   + "  ← Назад")
        separator()
        ch = input(clr("  Выбор: ", C.CYAN)).strip()
        if ch == "1": report_summary()
        elif ch == "2": report_top_accounts()
        elif ch == "3": report_transactions()
        elif ch == "4": report_log()
        elif ch == "5": report_tariffs()
        elif ch == "0": break

def report_summary():
    header("Общая сводка системы")
    with get_conn() as conn:
        n_clients   = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        n_active    = conn.execute("SELECT COUNT(*) FROM clients WHERE status='active'").fetchone()[0]
        n_accounts  = conn.execute("SELECT COUNT(*) FROM accounts WHERE is_active=1").fetchone()[0]
        total_rub   = conn.execute("SELECT COALESCE(SUM(balance),0) FROM accounts WHERE currency='RUB' AND is_active=1").fetchone()[0]
        n_tx        = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        n_ok        = conn.execute("SELECT COUNT(*) FROM transactions WHERE status='completed'").fetchone()[0]
        n_fail      = conn.execute("SELECT COUNT(*) FROM transactions WHERE status='failed'").fetchone()[0]

    print(f"  👥 Клиентов всего:        {clr(n_clients, C.BOLD)}")
    print(f"  ✅ Активных клиентов:     {clr(n_active, C.GREEN)}")
    print(f"  🏦 Активных счетов:       {clr(n_accounts, C.BOLD)}")
    print(f"  💰 Сумма балансов (RUB):  {clr(f'{total_rub:,.2f} ₽', C.YELLOW)}")
    separator()
    print(f"  📊 Всего транзакций:      {clr(n_tx, C.BOLD)}")
    print(f"  ✅ Выполненных:           {clr(n_ok, C.GREEN)}")
    print(f"  ❌ Неуспешных:            {clr(n_fail, C.RED)}")
    if n_tx > 0:
        pct = round(n_ok / n_tx * 100, 1)
        bar_len = int(pct / 5)
        bar = clr("█" * bar_len, C.GREEN) + clr("░" * (20 - bar_len), C.GRAY)
        print(f"\n  Успешность: [{bar}] {clr(f'{pct}%', C.BOLD)}")
    pause()



def report_top_accounts():
    header("Топ-5 счетов по балансу")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.account_no,c.full_name,a.currency,a.balance "
            "FROM accounts a JOIN clients c ON c.id=a.client_id "
            "WHERE a.is_active=1 ORDER BY a.balance DESC LIMIT 5"
        ).fetchall()
    for i, r in enumerate(rows, 1):
        medal = ["🥇","🥈","🥉","4️⃣ ","5️⃣ "][i-1]
        print(f"  {medal} {clr(r[1],C.BOLD)}")
        print(f"       {r[0]}  💰 {clr(f'{r[3]:,.2f} {r[2]}', C.YELLOW)}")
        separator()
    pause()

def report_transactions():
    header("Статистика транзакций")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT type, COUNT(*), COALESCE(SUM(amount),0) FROM transactions GROUP BY type"
        ).fetchall()
    type_icon = {"transfer":"🔄","deposit":"⬇️","withdrawal":"⬆️","fee":"💸"}
    print(f"  {'Тип':<15} {'Кол-во':>8} {'Оборот':>16}")
    separator()
    for r in rows:
        icon = type_icon.get(r[0],"•")
        print(f"  {icon} {clr(r[0]+':', C.CYAN):<20} {r[1]:>5}    {clr(f'{r[2]:>12,.2f}', C.YELLOW)}")
    pause()

def report_log():
    header("Журнал системных событий (последние 15)")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT event_type,message,created_at FROM system_log ORDER BY id DESC LIMIT 15"
        ).fetchall()
    for r in rows:
        print(f"  {clr(r[2],C.GRAY)}  {clr(r[0],C.CYAN)}")
        print(f"    {r[1]}")
    pause()

def report_tariffs():
    header("Тарифные планы")
    with get_conn() as conn:
        rows = conn.execute("SELECT name,transfer_fee_pct,min_fee,max_daily_limit,is_active FROM tariffs").fetchall()
    for r in rows:
        st = clr("✅ активен",C.GREEN) if r[4] else clr("🔒 неактивен",C.RED)
        print(f"  {clr(r[0],C.BOLD)}  {st}")
        print(f"       Комиссия: {r[1]}%  |  Мин. {r[2]} ₽  |  Лимит/день: {r[3]:,.0f} ₽")
        separator()
    pause()

# ─────────────────────────────────────────
# ГЛАВНОЕ МЕНЮ
# ─────────────────────────────────────────
def main():
    init_db()
    while True:
        clear()
        print()
        print(clr("  ╔══════════════════════════════════════════════════╗", C.CYAN))
        print(clr("  ║   💳  СИСТЕМА ЭЛЕКТРОННЫХ ПЛАТЕЖЕЙ  💳           ║", C.BOLD + C.CYAN))
        print(clr("  ║        Управление и сопровождение ИС             ║", C.CYAN))
        print(clr("  ╚══════════════════════════════════════════════════╝", C.CYAN))
        print()
        print(clr("  1", C.GREEN) + "  👥  Клиенты")
        print(clr("  2", C.GREEN) + "  🏦  Счета")
        print(clr("  3", C.GREEN) + "  🔄  Транзакции")
        print(clr("  4", C.GREEN) + "  📊  Отчёты и статистика")
        print()
        print(clr("  0", C.RED)   + "  🚪  Выход")
        separator()
        ch = input(clr("  Выбор: ", C.CYAN)).strip()
        if ch == "1": menu_clients()
        elif ch == "2": menu_accounts()
        elif ch == "3": menu_transactions()
        elif ch == "4": menu_reports()
        elif ch == "0":
            print(clr("\n  До свидания! 👋\n", C.CYAN))
            log_event("SYSTEM","Сеанс завершён")
            sys.exit(0)

if __name__ == "__main__":
    main()
