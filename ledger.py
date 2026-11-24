import re
import sqlite3
from datetime import date
from pathlib import Path

STATUSES = {"active": "Active", "completed": "Completed", "paused": "Paused", "waiting":"Waiting"}
KINDS = {"income": "Payment", "expense": "Expense"}
MAX_AMOUNT = 999_999_999_999
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def parse_amount(text, minimum):
    text = text.translate(DIGITS).strip()
    for separator in (",", "٬", " ", "\u00a0", "\u202f"):
        text = text.replace(separator, ",")
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", text):
        raise ValueError("مبلغ را به تومان و به‌صورت عدد صحیح وارد کنید.")
    digits = text.replace(",", "")
    if len(digits) > 12:
        raise ValueError("مبلغ خارج از محدودهٔ مجاز است.")
    value = int(digits)
    if not minimum <= value <= MAX_AMOUNT:
        raise ValueError("مبلغ خارج از محدودهٔ مجاز است.")
    return value


class Ledger:
    def __init__(self, path):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL CHECK(length(trim(title)) > 0),
                client TEXT NOT NULL CHECK(length(trim(client)) > 0),
                contract INTEGER NOT NULL CHECK(contract BETWEEN 0 AND 999999999999),
                status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'paused'))
            );
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
                kind TEXT NOT NULL CHECK(kind IN ('income', 'expense')),
                amount INTEGER NOT NULL CHECK(amount BETWEEN 1 AND 999999999999),
                day TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS entries_project ON entries(project_id);
        """)

        with self.db:
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(projects)")}
            if "currency" not in columns:
                self.db.execute("ALTER TABLE projects ADD COLUMN currency TEXT DEFAULT 'IRT'")
                self.db.execute("ALTER TABLE projects ADD COLUMN hourly INTEGER DEFAULT 0")
                self.db.execute("ALTER TABLE projects ADD COLUMN minutes INTEGER DEFAULT 0")

            if "waiting" not in columns:
                self.db.execute("ALTER TABLE projects ADD COLUMN waiting INTEGER NOT NULL DEFAULT 0")
                self.db.execute("ALTER TABLE projects ADD COLUMN reminded TEXT")
            self.db.execute("""CREATE TABLE IF NOT EXISTS crm(
                id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                created TEXT NOT NULL, note TEXT NOT NULL CHECK(length(trim(note))>0))""")

    def close(self):
        self.db.close()

    def projects(self):
        return self.db.execute("""
            SELECT CASE WHEN p.waiting THEN 'waiting' ELSE p.status END AS status, p.*,
                   COALESCE(t.received, 0) AS received,
                   COALESCE(t.spent, 0) AS spent
            FROM projects p
            LEFT JOIN (
                SELECT project_id,
                       SUM(CASE kind WHEN 'income' THEN amount ELSE 0 END) AS received,
                       SUM(CASE kind WHEN 'expense' THEN amount ELSE 0 END) AS spent
                FROM entries GROUP BY project_id
            ) t ON t.project_id = p.id
            ORDER BY p.id DESC
        """).fetchall()

    def entries(self):
        return self.db.execute("""
            SELECT e.*, p.title AS project
            FROM entries e JOIN projects p ON p.id = e.project_id
            ORDER BY e.day DESC, e.id DESC
        """).fetchall()

    def save_project(self, record_id, title, client, contract, status, currency="IRT", hourly=0, minutes=0):
        fields = (title.strip(), client.strip(), contract, "active" if status=="waiting" else status, currency, hourly, minutes, int(status=="waiting"))
        with self.db:
            if record_id is None:
                return self.db.execute(
                    "INSERT INTO projects(title, client, contract, status, currency, hourly, minutes, waiting) VALUES(?, ?, ?, ?, ?, ?, ?, ?)", fields
                ).lastrowid
            self.db.execute(
                "UPDATE projects SET title=?, client=?, contract=?, status=?, currency=?, hourly=?, minutes=?, reminded=CASE WHEN waiting=0 THEN NULL ELSE reminded END, waiting=? WHERE id=?",
                (*fields, record_id)
            )
        return record_id

    def save_entry(self, record_id, project_id, kind, amount, day, note):
        fields = (project_id, kind, amount, date.fromisoformat(day).isoformat(), note.strip())
        with self.db:
            if record_id is None:
                return self.db.execute(
                    "INSERT INTO entries(project_id, kind, amount, day, note) VALUES(?, ?, ?, ?, ?)", fields
                ).lastrowid
            self.db.execute(
                "UPDATE entries SET project_id=?, kind=?, amount=?, day=?, note=? WHERE id=?",
                (*fields, record_id)
            )
        return record_id

    def delete_project(self, record_id):
        with self.db:
            self.db.execute("DELETE FROM projects WHERE id=?", (record_id,))

    def delete_entry(self, record_id):
        with self.db:
            self.db.execute("DELETE FROM entries WHERE id=?", (record_id,))


def balance(project):
    return max(project["contract"] - project["received"], 0)


def seed_demo(ledger):
    samples = [
        ("Commerce platform", "Aban Studio", 48_000_000, "active", 30_000_000, 8_500_000),
        ("Operations dashboard", "Madar Group", 32_000_000, "completed", 32_000_000, 6_200_000),
        ("Brand identity", "Royesh", 18_000_000, "active", 7_500_000, 2_300_000),
    ]
    for title, client, contract, status, received, spent in reversed(samples):
        project = ledger.save_project(None, title, client, contract, status, "IRR")
        ledger.save_entry(None, project, "income", received, date.today().isoformat(), "Client payment")
        ledger.save_entry(None, project, "expense", spent, date.today().isoformat(), "Delivery cost")



