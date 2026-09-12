from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .reputation import BayesianReputation

ZERO_HASH = "0" * 64


class CounterpartyStore:
    """Durable, concurrency-safe evidence and audit store.

    SQLite is intentionally used for the hackathon host: transactions are easy to
    inspect, WAL handles concurrent readers, and BEGIN IMMEDIATE serializes the
    hash-chain head update so two requests cannot mint the same sequence number.
    """

    def __init__(self, path: str | os.PathLike[str] = "counterparty.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def _init_db(self) -> None:
        with self._init_lock, self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY,
                    delivery_id TEXT NOT NULL UNIQUE,
                    service_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('PASS','FAIL')),
                    latency_ms INTEGER,
                    evidence_hash TEXT NOT NULL,
                    created_ns INTEGER NOT NULL,
                    UNIQUE(service_id, evidence_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_observations_service
                    ON observations(service_id, task_type, created_ns);

                CREATE TABLE IF NOT EXISTS protocol_observations (
                    id TEXT PRIMARY KEY,
                    probe_id TEXT NOT NULL UNIQUE,
                    service_id TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('PASS','FAIL')),
                    latency_ms INTEGER NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    created_ns INTEGER NOT NULL,
                    UNIQUE(service_id, evidence_hash)
                );
                CREATE INDEX IF NOT EXISTS idx_protocol_observations_service
                    ON protocol_observations(service_id, created_ns);

                CREATE TABLE IF NOT EXISTS audit_events (
                    seq INTEGER PRIMARY KEY,
                    id TEXT NOT NULL UNIQUE,
                    ts_ns INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    hash TEXT NOT NULL UNIQUE
                );
                """
            )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()

    def append_audit(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.transaction() as con:
            return self._append_audit_tx(con, event_type, payload)

    def _append_audit_tx(self, con: sqlite3.Connection, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = con.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        seq = (int(row["seq"]) + 1) if row else 1
        previous_hash = str(row["hash"]) if row else ZERO_HASH
        record = {
            "id": str(uuid.uuid4()),
            "seq": seq,
            "ts_ns": time.time_ns(),
            "event_type": event_type,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        material = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode()
        record_hash = hashlib.sha256(material).hexdigest()
        con.execute(
            "INSERT INTO audit_events(seq,id,ts_ns,event_type,payload_json,previous_hash,hash) VALUES(?,?,?,?,?,?,?)",
            (seq, record["id"], record["ts_ns"], event_type, json.dumps(payload, sort_keys=True, default=str), previous_hash, record_hash),
        )
        record["hash"] = record_hash
        return record

    def record_verification(
        self,
        delivery_id: str,
        service_id: str,
        task_type: str,
        outcome: str,
        evidence_hash: str,
        latency_ms: int | None,
        audit_payload: dict[str, Any],
        reputation_eligible: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically update reputation (when decisive) and append its audit receipt.

        The transaction is serialized with BEGIN IMMEDIATE. A crash cannot leave a
        trust observation without its audit record, or vice versa. Replays are
        retained in the audit trail but never counted twice in reputation.
        """
        if outcome not in {"PASS", "FAIL", "INCONCLUSIVE"}:
            raise ValueError("invalid verification outcome")
        with self.transaction() as con:
            updated = False
            if reputation_eligible and outcome in {"PASS", "FAIL"}:
                try:
                    con.execute(
                        "INSERT INTO observations(id,delivery_id,service_id,task_type,outcome,latency_ms,evidence_hash,created_ns) VALUES(?,?,?,?,?,?,?,?)",
                        (str(uuid.uuid4()), delivery_id, service_id, task_type, outcome, latency_ms, evidence_hash, time.time_ns()),
                    )
                    updated = True
                except sqlite3.IntegrityError:
                    updated = False
            payload = dict(audit_payload)
            payload["reputation_updated"] = updated
            payload["replay_suppressed"] = outcome in {"PASS", "FAIL"} and not updated
            event = self._append_audit_tx(con, "verify_delivery", payload)
            return event, updated

    def record_protocol_observation(
        self,
        probe_id: str,
        service_id: str,
        outcome: str,
        evidence_hash: str,
        latency_ms: int,
        audit_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        """Atomically persist one trusted canary and its audit receipt.

        Protocol canaries are deliberately stored separately from task-delivery
        evidence. They can break marketplace cold start and support a provisional
        routing decision, but they never masquerade as proof that a provider has
        already succeeded on the buyer's domain-specific task.
        """
        if outcome not in {"PASS", "FAIL"}:
            raise ValueError("protocol observations must be decisive PASS/FAIL outcomes")
        with self.transaction() as con:
            updated = False
            try:
                con.execute(
                    "INSERT INTO protocol_observations(id,probe_id,service_id,outcome,latency_ms,evidence_hash,created_ns) VALUES(?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), probe_id, service_id, outcome, latency_ms, evidence_hash, time.time_ns()),
                )
                updated = True
            except sqlite3.IntegrityError:
                updated = False
            payload = dict(audit_payload)
            payload["protocol_reputation_updated"] = updated
            payload["replay_suppressed"] = not updated
            event = self._append_audit_tx(con, "protocol_probe", payload)
            return event, updated

    def verify_audit(self) -> bool:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
        previous = ZERO_HASH
        expected_seq = 1
        for row in rows:
            if int(row["seq"]) != expected_seq or row["previous_hash"] != previous:
                return False
            payload = json.loads(row["payload_json"])
            record = {
                "id": row["id"],
                "seq": int(row["seq"]),
                "ts_ns": int(row["ts_ns"]),
                "event_type": row["event_type"],
                "payload": payload,
                "previous_hash": row["previous_hash"],
            }
            material = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode()
            if hashlib.sha256(material).hexdigest() != row["hash"]:
                return False
            previous = row["hash"]
            expected_seq += 1
        return True

    def audit_head(self) -> dict[str, Any]:
        with self._connect() as con:
            row = con.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        if row is None:
            return {"count": 0, "head": ZERO_HASH}
        return {"count": int(row["seq"]), "head": str(row["hash"])}

    def get_audit_event(self, receipt: str) -> dict[str, Any] | None:
        with self._connect() as con:
            r = con.execute("SELECT * FROM audit_events WHERE hash=?", (receipt,)).fetchone()
        if r is None:
            return None
        return {
            "id": r["id"], "seq": r["seq"], "ts_ns": r["ts_ns"],
            "event_type": r["event_type"], "payload": json.loads(r["payload_json"]),
            "previous_hash": r["previous_hash"], "hash": r["hash"],
        }

    def audit_events(self, limit: int = 100) -> list[dict[str, Any]]:
        limit = min(max(int(limit), 1), 1000)
        with self._connect() as con:
            rows = con.execute("SELECT * FROM audit_events ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return [
            {
                "id": r["id"], "seq": r["seq"], "ts_ns": r["ts_ns"],
                "event_type": r["event_type"], "payload": json.loads(r["payload_json"]),
                "previous_hash": r["previous_hash"], "hash": r["hash"],
            }
            for r in reversed(rows)
        ]

    def record_observation(
        self,
        delivery_id: str,
        service_id: str,
        task_type: str,
        outcome: str,
        evidence_hash: str,
        latency_ms: int | None = None,
    ) -> bool:
        if outcome not in {"PASS", "FAIL"}:
            raise ValueError("only decisive PASS/FAIL outcomes become reputation observations")
        try:
            with self.transaction() as con:
                con.execute(
                    "INSERT INTO observations(id,delivery_id,service_id,task_type,outcome,latency_ms,evidence_hash,created_ns) VALUES(?,?,?,?,?,?,?,?)",
                    (str(uuid.uuid4()), delivery_id, service_id, task_type, outcome, latency_ms, evidence_hash, time.time_ns()),
                )
            return True
        except sqlite3.IntegrityError:
            # Same trusted delivery id or same evidence for the same provider: replay.
            return False

    def reputation(self, service_id: str, task_type: str = "general") -> tuple[BayesianReputation, int | None]:
        # Task-specific evidence plus general evidence; avoid double counting when task_type=general.
        params: tuple[Any, ...]
        if task_type == "general":
            sql = "SELECT outcome, latency_ms FROM observations WHERE service_id=? AND task_type='general'"
            params = (service_id,)
        else:
            sql = "SELECT outcome, latency_ms FROM observations WHERE service_id=? AND task_type IN (?, 'general')"
            params = (service_id, task_type)
        with self._connect() as con:
            rows = con.execute(sql, params).fetchall()
        successes = sum(1 for r in rows if r["outcome"] == "PASS")
        failures = sum(1 for r in rows if r["outcome"] == "FAIL")
        latencies = sorted(int(r["latency_ms"]) for r in rows if r["latency_ms"] is not None)
        median = None
        if latencies:
            mid = len(latencies) // 2
            median = latencies[mid] if len(latencies) % 2 else (latencies[mid - 1] + latencies[mid]) // 2
        return BayesianReputation(successes, failures), median

    def protocol_reputation(self, service_id: str) -> tuple[BayesianReputation, int | None]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT outcome, latency_ms FROM protocol_observations WHERE service_id=?",
                (service_id,),
            ).fetchall()
        successes = sum(1 for r in rows if r["outcome"] == "PASS")
        failures = sum(1 for r in rows if r["outcome"] == "FAIL")
        latencies = sorted(int(r["latency_ms"]) for r in rows)
        median = None
        if latencies:
            mid = len(latencies) // 2
            median = latencies[mid] if len(latencies) % 2 else (latencies[mid - 1] + latencies[mid]) // 2
        return BayesianReputation(successes, failures), median
