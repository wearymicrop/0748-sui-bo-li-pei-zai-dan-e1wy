from contextlib import contextmanager
import json
import sqlite3

from app.errors import BusinessError
from app.manifest import canonical


class Ledger:
    def __init__(self, path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS intakes (
                    batch TEXT NOT NULL,
                    id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (batch, id)
                );
                CREATE TABLE IF NOT EXISTS publications (
                    batch TEXT PRIMARY KEY,
                    seq INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def source(self, identifier):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM sources WHERE id = ?", (identifier,)
            ).fetchone()
        if row is None:
            raise BusinessError("SOURCE_NOT_FOUND", "未找到数据来源", 404)
        return json.loads(row[0])

    def put_source(self, identifier, payload):
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO sources VALUES (?, ?)",
                (identifier, canonical(payload)),
            )
            return cursor.rowcount == 0

    def run(self, identifier):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM runs WHERE id = ?", (identifier,)
            ).fetchone()
        if row is None:
            raise BusinessError("RUN_NOT_FOUND", "未找到归档记录", 404)
        return json.loads(row[0])

    def put_run(self, payload):
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO runs VALUES (?, ?)",
                (payload["id"], canonical(payload)),
            )
            return cursor.rowcount == 0

    def put_intake(self, batch, identifier, payload):
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO intakes (batch, id, seq, payload)
                SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ? FROM intakes WHERE batch = ?
                """,
                (batch, identifier, canonical(payload), batch),
            )
            row = conn.execute(
                "SELECT seq FROM intakes WHERE batch = ? AND id = ?",
                (batch, identifier),
            ).fetchone()
            return cursor.rowcount == 0, row[0]

    def intakes(self, batch):
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, seq, payload FROM intakes WHERE batch = ? ORDER BY seq",
                (batch,),
            ).fetchall()
        return [
            {"id": identifier, "seq": seq, "payload": json.loads(payload)}
            for identifier, seq, payload in rows
        ]

    def publication(self, batch):
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM publications WHERE batch = ?", (batch,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put_publication(self, batch, seq, payload):
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO publications VALUES (?, ?, ?)",
                (batch, seq, canonical(payload)),
            )
