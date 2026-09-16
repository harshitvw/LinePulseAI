"""Durable, append-only human decision memory for LinePulse AI.

The SQLite database contains only operator-entered review decisions and verified
maintenance outcomes.  It never contains, and cannot issue, equipment commands.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DECISIONS = {"APPROVE", "MODIFY", "REJECT"}
OUTCOMES = {"RESOLVED", "PARTIAL", "UNRESOLVED"}


class DecisionRepository:
    """Store the human-in-the-loop audit trail in SQLite.

    ``:memory:`` is supported for tests.  A single connection is retained in
    that mode because independent SQLite in-memory connections do not share
    state.
    """

    def __init__(self, db_path: str | Path = "runtime/linepulse.db") -> None:
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._memory_connection: sqlite3.Connection | None = None

        if self.db_path == ":memory:":
            self._memory_connection = self._new_connection(":memory:")
        else:
            Path(self.db_path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._initialize()

    @staticmethod
    def _new_connection(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, timeout=15, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 15000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._memory_connection or self._new_connection(self.db_path)
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                if self._memory_connection is None:
                    connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL DEFAULT
                        (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    asset_id TEXT NOT NULL,
                    asset_type TEXT NOT NULL,
                    decision TEXT NOT NULL
                        CHECK (decision IN ('APPROVE', 'MODIFY', 'REJECT')),
                    rationale TEXT NOT NULL,
                    owner TEXT NOT NULL,
                    failure_mode TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    modified_action TEXT,
                    selected_action TEXT NOT NULL,
                    model_status TEXT NOT NULL,
                    model_risk_score REAL NOT NULL,
                    model_horizon_days INTEGER NOT NULL,
                    model_snapshot_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    equipment_action_taken INTEGER NOT NULL DEFAULT 0
                        CHECK (equipment_action_taken = 0)
                );

                CREATE INDEX IF NOT EXISTS idx_decisions_asset
                    ON decisions(asset_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_decisions_mode
                    ON decisions(failure_mode, id DESC);

                CREATE TABLE IF NOT EXISTS outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id INTEGER NOT NULL,
                    asset_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT
                        (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    outcome TEXT NOT NULL
                        CHECK (outcome IN ('RESOLVED', 'PARTIAL', 'UNRESOLVED')),
                    notes TEXT NOT NULL DEFAULT '',
                    verified_by TEXT NOT NULL DEFAULT 'Equipment Owner',
                    equipment_action_taken INTEGER NOT NULL DEFAULT 0
                        CHECK (equipment_action_taken = 0),
                    FOREIGN KEY(decision_id) REFERENCES decisions(id)
                );

                CREATE INDEX IF NOT EXISTS idx_outcomes_decision
                    ON outcomes(decision_id, id DESC);
                CREATE INDEX IF NOT EXISTS idx_outcomes_asset
                    ON outcomes(asset_id, id DESC);
                """
            )

    @staticmethod
    def _normalise_decision(decision: str) -> str:
        value = str(decision).strip().upper()
        if value not in DECISIONS:
            raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
        return value

    @staticmethod
    def _normalise_outcome(outcome: str) -> str:
        aliases = {
            "PARTIALLY_RESOLVED": "PARTIAL",
            "NOT_RESOLVED": "UNRESOLVED",
            "NOT RESOLVED": "UNRESOLVED",
        }
        value = aliases.get(str(outcome).strip().upper(), str(outcome).strip().upper())
        if value not in OUTCOMES:
            raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}")
        return value

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for name in ("model_snapshot_json", "evidence_json"):
            if name in result:
                raw = result.pop(name)
                key = name.removesuffix("_json")
                try:
                    result[key] = json.loads(raw or "{}")
                except (TypeError, json.JSONDecodeError):
                    result[key] = {}
        if "equipment_action_taken" in result:
            result["equipment_action_taken"] = bool(result["equipment_action_taken"])
        return result

    def add_decision(
        self,
        *,
        asset_id: str,
        decision: str,
        rationale: str,
        owner: str,
        failure_mode: str,
        recommended_action: str,
        modified_action: str | None,
        model_status: str,
        model_risk_score: float,
        model_horizon_days: int,
        model_snapshot: dict[str, Any],
        evidence: list[dict[str, Any]] | dict[str, Any],
    ) -> int:
        normalized = self._normalise_decision(decision)
        asset_id = str(asset_id).strip()
        rationale = str(rationale).strip()
        owner = str(owner).strip()
        modified = str(modified_action or "").strip() or None

        if not asset_id:
            raise ValueError("asset_id is required")
        if not rationale:
            raise ValueError("rationale is required so the review remains auditable")
        if not owner:
            raise ValueError("owner is required")
        if normalized == "MODIFY" and not modified:
            raise ValueError("modified_action is required when decision is MODIFY")

        selected_action = modified if normalized == "MODIFY" else recommended_action
        if normalized == "REJECT":
            selected_action = "No maintenance action approved"

        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO decisions (
                    asset_id, asset_type, decision, rationale, owner, failure_mode,
                    recommended_action, modified_action, selected_action,
                    model_status, model_risk_score, model_horizon_days,
                    model_snapshot_json, evidence_json, equipment_action_taken
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    asset_id,
                    str(model_snapshot.get("type") or model_snapshot.get("asset_type") or "Unknown"),
                    normalized,
                    rationale,
                    owner,
                    str(failure_mode),
                    str(recommended_action),
                    modified,
                    str(selected_action),
                    str(model_status).upper(),
                    float(model_risk_score),
                    int(model_horizon_days),
                    json.dumps(model_snapshot, default=str, separators=(",", ":")),
                    json.dumps(evidence, default=str, separators=(",", ":")),
                ),
            )
            return int(cursor.lastrowid)

    def get_case(self, case_id: int) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT d.*,
                       o.id AS outcome_id,
                       o.outcome,
                       o.notes AS outcome_notes,
                       o.verified_by,
                       o.created_at AS outcome_created_at
                FROM decisions d
                LEFT JOIN outcomes o ON o.id = (
                    SELECT o2.id FROM outcomes o2
                    WHERE o2.decision_id = d.id
                    ORDER BY o2.id DESC LIMIT 1
                )
                WHERE d.id = ?
                """,
                (int(case_id),),
            ).fetchone()
        decoded = self._decode(row)
        if decoded is None:
            raise KeyError(case_id)
        return decoded

    def list_cases(
        self,
        *,
        limit: int = 100,
        asset_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        parameters: list[Any] = []
        where = ""
        if asset_id:
            where = "WHERE d.asset_id = ?"
            parameters.append(str(asset_id))
        parameters.append(limit)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT d.*,
                       o.id AS outcome_id,
                       o.outcome,
                       o.notes AS outcome_notes,
                       o.verified_by,
                       o.created_at AS outcome_created_at
                FROM decisions d
                LEFT JOIN outcomes o ON o.id = (
                    SELECT o2.id FROM outcomes o2
                    WHERE o2.decision_id = d.id
                    ORDER BY o2.id DESC LIMIT 1
                )
                {where}
                ORDER BY d.id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._decode(row) or {} for row in rows]

    def add_outcome(
        self,
        case_id: int,
        outcome: str,
        notes: str = "",
        verified_by: str = "Equipment Owner",
    ) -> dict[str, Any]:
        normalized = self._normalise_outcome(outcome)
        current = self.get_case(case_id)
        if current["decision"] == "REJECT":
            raise ValueError("A rejected recommendation has no maintenance outcome to verify")
        verifier = str(verified_by).strip()
        if not verifier:
            raise ValueError("verified_by is required")

        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO outcomes (
                    decision_id, asset_id, outcome, notes,
                    verified_by, equipment_action_taken
                ) VALUES (?, ?, ?, ?, ?, 0)
                """,
                (
                    int(case_id),
                    current["asset_id"],
                    normalized,
                    str(notes).strip(),
                    verifier,
                ),
            )
        return self.get_case(case_id)

    def latest_asset_outcomes(self) -> dict[str, dict[str, Any]]:
        """Return the latest verified outcome for each asset."""

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT o.*, d.failure_mode, d.selected_action, d.model_status,
                       d.model_risk_score, d.model_horizon_days
                FROM outcomes o
                JOIN decisions d ON d.id = o.decision_id
                WHERE o.id = (
                    SELECT o2.id FROM outcomes o2
                    WHERE o2.asset_id = o.asset_id
                    ORDER BY o2.id DESC LIMIT 1
                )
                """
            ).fetchall()
        return {
            str(row["asset_id"]): (self._decode(row) or {})
            for row in rows
        }

    def successful_similar_cases(
        self,
        failure_mode: str,
        *,
        asset_type: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return human-verified resolved actions for recommendation memory."""

        type_clause = ""
        parameters: list[Any] = [str(failure_mode)]
        if asset_type:
            type_clause = "AND lower(d.asset_type) = lower(?)"
            parameters.append(str(asset_type))
        parameters.append(max(1, min(int(limit), 50)))
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT d.id AS decision_id, d.asset_id, d.failure_mode,
                       d.selected_action, d.owner, d.rationale,
                       o.outcome, o.notes AS outcome_notes,
                       o.verified_by, o.created_at AS verified_at
                FROM decisions d
                JOIN outcomes o ON o.decision_id = d.id
                WHERE lower(d.failure_mode) = lower(?)
                  {type_clause}
                  AND o.id = (
                      SELECT o2.id FROM outcomes o2
                      WHERE o2.decision_id = d.id
                      ORDER BY o2.id DESC LIMIT 1
                  )
                  AND o.outcome = 'RESOLVED'
                  AND d.decision IN ('APPROVE', 'MODIFY')
                ORDER BY o.id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._decode(row) or {} for row in rows]

    def outcome_history(self, case_id: int) -> list[dict[str, Any]]:
        self.get_case(case_id)  # raises a consistent KeyError for unknown cases
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM outcomes WHERE decision_id = ? ORDER BY id",
                (int(case_id),),
            ).fetchall()
        return [self._decode(row) or {} for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connection() as connection:
            decisions = int(
                connection.execute("SELECT count(*) FROM decisions").fetchone()[0]
            )
            outcomes = int(
                connection.execute("SELECT count(*) FROM outcomes").fetchone()[0]
            )
        return {"decisions": decisions, "verified_outcomes": outcomes}

    def clear(self) -> None:
        """Clear user-entered demo memory; source data and model are untouched."""

        with self._connection() as connection:
            connection.execute("DELETE FROM outcomes")
            connection.execute("DELETE FROM decisions")


# Backwards-friendly alias used by a few local notebooks.
FeedbackRepository = DecisionRepository
