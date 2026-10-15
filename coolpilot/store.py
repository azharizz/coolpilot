"""SQLite owns lifecycle state, evidence, and atomic configuration promotion."""

import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone

from .dataset import DATA


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def database():
    with closing(sqlite3.connect(DATA / "coolpilot.sqlite3")) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        yield db


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    with database() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, status TEXT NOT NULL,
                request TEXT NOT NULL, summary TEXT, error TEXT, recommendation INTEGER
            );
            CREATE UNIQUE INDEX IF NOT EXISTS single_active_run ON runs ((1))
                WHERE status IN ('queued', 'running');
            CREATE TABLE IF NOT EXISTS experiments (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                sequence INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                config TEXT NOT NULL, rationale TEXT NOT NULL, result TEXT, gate TEXT,
                error TEXT, created TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                created TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY, created TEXT NOT NULL,
                experiment_id INTEGER NOT NULL REFERENCES experiments(id), action TEXT NOT NULL,
                previous_id INTEGER REFERENCES promotions(id)
            );
            CREATE TABLE IF NOT EXISTS active (
                workload TEXT PRIMARY KEY,
                promotion_id INTEGER NOT NULL REFERENCES promotions(id)
            );
        """)
        if "singleton" in {row[1] for row in db.execute("PRAGMA table_info(active)")}:
            db.executescript("""
                ALTER TABLE active RENAME TO legacy_active;
                CREATE TABLE active (
                    workload TEXT PRIMARY KEY,
                    promotion_id INTEGER NOT NULL REFERENCES promotions(id)
                );
                INSERT INTO active SELECT 'tracking', promotion_id FROM legacy_active;
                DROP TABLE legacy_active;
            """)
        if "previous_id" not in {
            row[1] for row in db.execute("PRAGMA table_info(promotions)")
        }:
            db.execute(
                "ALTER TABLE promotions ADD COLUMN previous_id INTEGER REFERENCES promotions(id)"
            )
        db.execute(
            "UPDATE experiments SET status='interrupted', error='Service restarted during measurement.' WHERE status='running'"
        )
        db.execute(
            "UPDATE runs SET status='interrupted', error='Service restarted. Completed evidence was preserved. Start a new run to continue.' WHERE status IN ('queued','running')"
        )


def create_run(request: dict) -> str:
    identifier = uuid.uuid4().hex
    with database() as db:
        db.execute(
            "INSERT INTO runs(id,created,status,request) VALUES (?,?,'queued',?)",
            (identifier, now(), json.dumps(request)),
        )
    return identifier


def update_run(identifier: str, **values):
    allowed = {"status", "summary", "error", "recommendation"}
    if not values.keys() <= allowed:
        raise ValueError("Unknown run fields")
    with database() as db:
        db.execute(
            f"UPDATE runs SET {','.join(k + '=?' for k in values)} WHERE id=?",
            (*values.values(), identifier),
        )


def event(run_id: str, kind: str, payload: dict):
    with database() as db:
        db.execute(
            "INSERT INTO events(run_id,created,kind,payload) VALUES (?,?,?,?)",
            (run_id, now(), kind, json.dumps(payload, allow_nan=False)),
        )


def start_experiment(run_id: str, kind: str, config: dict, rationale: str) -> int:
    with database() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM experiments WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        return db.execute(
            "INSERT INTO experiments(run_id,sequence,kind,status,config,rationale,created) VALUES (?,?,?,'running',?,?,?)",
            (run_id, count, kind, json.dumps(config), rationale, now()),
        ).lastrowid


def finish_experiment(identifier: int, result: dict, gate: dict):
    with database() as db:
        db.execute(
            "UPDATE experiments SET status='completed',result=?,gate=? WHERE id=?",
            (json.dumps(result, allow_nan=False), json.dumps(gate), identifier),
        )


def fail_experiment(identifier: int, error: str, status="failed"):
    with database() as db:
        db.execute(
            "UPDATE experiments SET status=?,error=? WHERE id=?",
            (status, error, identifier),
        )


def decode_experiment(row, trace=False) -> dict:
    item = dict(row)
    item["config"] = json.loads(item["config"])
    item["gate"] = json.loads(item["gate"]) if item["gate"] else None
    result = json.loads(item.pop("result")) if item["status"] == "completed" else None
    if result:
        if not trace:
            result.pop("trace")
            result["environment"].pop("opencv_build")
        item.update(result)
    return item


def experiment(identifier: int, trace=False) -> dict | None:
    with database() as db:
        row = db.execute(
            "SELECT * FROM experiments WHERE id=?", (identifier,)
        ).fetchone()
    return decode_experiment(row, trace) if row else None


def get_run(identifier: str, full=False) -> dict | None:
    with database() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (identifier,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["request"] = json.loads(result["request"])
        result["experiments"] = [
            decode_experiment(r, full)
            for r in db.execute(
                "SELECT * FROM experiments WHERE run_id=? ORDER BY sequence",
                (identifier,),
            )
        ]
        result["events"] = [
            {**dict(r), "payload": json.loads(r["payload"])}
            for r in db.execute(
                "SELECT * FROM events WHERE run_id=? ORDER BY id", (identifier,)
            )
        ]
    return result


def list_runs() -> list[dict]:
    with database() as db:
        return [
            {**dict(r), "request": json.loads(r["request"])}
            for r in db.execute("SELECT * FROM runs ORDER BY created DESC LIMIT 100")
        ]


def history(page: int, page_size: int, query: str, status: str) -> dict:
    where = "WHERE instr(lower(json_extract(request, '$.name')), lower(?)) > 0"
    parameters = [query]
    if status:
        where += " AND status=?"
        parameters.append(status)
    with database() as db:
        total = db.execute(f"SELECT COUNT(*) FROM runs {where}", parameters).fetchone()[0]
        page = min(page, max(1, (total + page_size - 1) // page_size))
        items = [
            {**dict(row), "request": json.loads(row["request"])}
            for row in db.execute(
                f"SELECT * FROM runs {where} ORDER BY created DESC, id DESC LIMIT ? OFFSET ?",
                (*parameters, page_size, (page - 1) * page_size),
            )
        ]
        running = db.execute(
            "SELECT id FROM runs WHERE status IN ('queued', 'running')"
        ).fetchone()
    return {
        "items": items, "total": total, "page": page, "page_size": page_size,
        "running_id": running[0] if running else None,
    }


def active_configuration(workload: str = "tracking") -> dict | None:
    with database() as db:
        row = db.execute(
            "SELECT p.* FROM active a JOIN promotions p ON p.id=a.promotion_id WHERE a.workload=?",
            (workload,),
        ).fetchone()
    return (
        {**dict(row), "experiment": experiment(row["experiment_id"])} if row else None
    )


def verify_camera_promotion(row):
    request = json.loads(row["request"])
    if request.get("workload", "tracking") != "camera_health":
        return
    from .benchmark import environment
    from .camera_dataset import checked
    from .models import RunRequest
    settings = RunRequest.model_validate(request).camera
    dataset = checked(settings)
    result = json.loads(row["result"])
    if dataset["development_only"] or result.get("split") != "validation":
        raise ValueError("Development evidence cannot be applied.")
    current = environment()
    if any(result["environment"].get(k) != current.get(k) for k in ("runner_sha256", "build_sha256", "architecture")):
        raise ValueError("Runtime changed since validation. Revalidate before applying.")


def promote(experiment_id: int) -> dict:
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT e.*,r.request,r.recommendation,r.status AS run_status FROM experiments e JOIN runs r ON e.run_id=r.id WHERE e.id=?",
            (experiment_id,),
        ).fetchone()
        if (
            row is None
            or row["run_status"] != "completed"
            or row["recommendation"] != experiment_id
            or row["status"] != "completed"
            or not row["kind"].endswith("validation")
            or not json.loads(row["gate"] or "{}").get("passed")
        ):
            raise ValueError(
                "Only the completed run's held-out validated recommendation can be applied."
            )
        verify_camera_promotion(row)
        workload = json.loads(row["request"]).get("workload", "tracking")
        current = db.execute(
            "SELECT promotion_id FROM active WHERE workload=?", (workload,)
        ).fetchone()
        promotion = db.execute(
            "INSERT INTO promotions(created,experiment_id,action,previous_id) VALUES (?,?,'apply',?)",
            (now(), experiment_id, current[0] if current else None),
        ).lastrowid
        db.execute(
            "INSERT INTO active VALUES (?,?) ON CONFLICT(workload) DO UPDATE SET promotion_id=excluded.promotion_id",
            (workload, promotion),
        )
    return active_configuration(workload)


def rollback(workload: str = "tracking") -> dict:
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT promotion_id FROM active WHERE workload=?", (workload,)
        ).fetchone()
        previous = (
            db.execute(
                "SELECT p.* FROM promotions p JOIN promotions current ON current.previous_id=p.id WHERE current.id=?",
                (current[0],),
            ).fetchone()
            if current
            else None
        )
        if previous is None:
            raise ValueError("No earlier applied configuration is available.")
        validated = db.execute(
            "SELECT e.*,r.request FROM experiments e JOIN runs r ON r.id=e.run_id WHERE e.id=?",
            (previous["experiment_id"],),
        ).fetchone()
        verify_camera_promotion(validated)
        db.execute(
            "UPDATE active SET promotion_id=? WHERE workload=?", (previous["id"], workload)
        )
    return active_configuration(workload)
