from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from contextlib import contextmanager
from uuid import uuid4

from .schemas import Ref, RunResult


def canonical(value) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def within(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if (
        Path(relative).is_absolute()
        or not path.is_relative_to(root.resolve())
        or path == root.resolve()
    ):
        raise ValueError("path escapes its root")
    return path


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class Storage:
    """Small immutable objects and durable job state; arrays remain in files.

    SQLite is deliberately local to this single-worker module, independent of the
    chat database. BEGIN IMMEDIATE provides atomic submit/cancel/claim operations.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "preprocessing.db"
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS objects(
                  owner TEXT, id TEXT, kind TEXT, body TEXT,
                  PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY, owner TEXT, plan_id TEXT, status TEXT,
                  cancel INTEGER DEFAULT 0, created REAL,
                  UNIQUE(owner,plan_id));
                CREATE TABLE IF NOT EXISTS records(
                  job_id TEXT, key TEXT, method_id TEXT, record_id TEXT,
                  status TEXT, attempt INTEGER DEFAULT 0, result TEXT, error TEXT,
                  PRIMARY KEY(job_id,key));
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def put(self, owner: str, kind: str, value) -> Ref:
        body = canonical(value)
        identity = hashlib.sha256(body.encode()).hexdigest()
        with self.db() as db:
            db.execute(
                "INSERT OR IGNORE INTO objects VALUES(?,?,?,?)",
                (owner, identity, kind, body),
            )
        return Ref(id=identity, sha256=identity)

    def get(self, owner: str, ref: Ref, kind: str):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM objects WHERE owner=? AND id=? AND kind=?",
                (owner, ref.id, kind),
            ).fetchone()
        if row is None:
            raise KeyError("resource not found")
        value = json.loads(row["body"])
        if digest(value) != ref.sha256 or ref.id != ref.sha256:
            raise ValueError("immutable object checksum mismatch")
        return value

    def list_objects(self, owner: str, kind: str):
        with self.db() as db:
            rows = db.execute(
                "SELECT id,body FROM objects WHERE owner=? AND kind=? ORDER BY id",
                (owner, kind),
            ).fetchall()
        return [
            {"ref": {"id": r["id"], "sha256": r["id"]}, "value": json.loads(r["body"])}
            for r in rows
        ]

    def submit(self, owner: str, ref: Ref, plan) -> RunResult:
        with self.db() as db:
            prior = db.execute(
                "SELECT id FROM jobs WHERE owner=? AND plan_id=?", (owner, ref.id)
            ).fetchone()
            if prior:
                identity = prior["id"]
            else:
                identity = uuid4().hex
                db.execute(
                    "INSERT INTO jobs(id,owner,plan_id,status,created) VALUES(?,?,?,?,?)",
                    (identity, owner, ref.id, "queued", time.time()),
                )
                for record in plan.records:
                    key = digest([record.method_ref.id, record.record_id])
                    db.execute(
                        "INSERT INTO records(job_id,key,method_id,record_id,status) VALUES(?,?,?,?,?)",
                        (
                            identity,
                            key,
                            record.method_ref.id,
                            record.record_id,
                            "queued",
                        ),
                    )
        return self.status(owner, identity)

    def status(self, owner: str, job_id: str) -> RunResult:
        with self.db() as db:
            job = db.execute(
                "SELECT * FROM jobs WHERE id=? AND owner=?", (job_id, owner)
            ).fetchone()
            if job is None:
                raise KeyError("job not found")
            records = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM records WHERE job_id=? ORDER BY key", (job_id,)
                ).fetchall()
            ]
        for record in records:
            record["result"] = (
                json.loads(record["result"]) if record["result"] else None
            )
        return RunResult(
            job_id=job_id,
            plan_ref=Ref(id=job["plan_id"], sha256=job["plan_id"]),
            status=job["status"],
            records=records,
            completed=sum(r["status"] == "completed" for r in records),
            total=len(records),
            cancel_requested=bool(job["cancel"]),
        )

    def control(self, owner: str, job_id: str, action: str):
        self.status(owner, job_id)
        with self.db() as db:
            job = db.execute(
                "SELECT * FROM jobs WHERE id=? AND owner=?", (job_id, owner)
            ).fetchone()
            if action == "cancel":
                if job["status"] in ("queued", "running", "interrupted"):
                    db.execute("UPDATE jobs SET cancel=1 WHERE id=?", (job_id,))
                    if job["status"] != "running":
                        db.execute(
                            "UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,)
                        )
                        db.execute(
                            "UPDATE records SET status='cancelled' WHERE job_id=? AND status!='completed'",
                            (job_id,),
                        )
            elif action == "retry":
                if job["status"] not in (
                    "partial",
                    "failed",
                    "interrupted",
                    "cancelled",
                ):
                    raise ValueError("only a terminal incomplete job may be retried")
                db.execute(
                    "UPDATE jobs SET status='queued',cancel=0 WHERE id=?", (job_id,)
                )
                db.execute(
                    "UPDATE records SET status='queued',error=NULL WHERE job_id=? AND status!='completed'",
                    (job_id,),
                )
            else:
                raise ValueError("unknown job action")
        return self.status(owner, job_id)

    def job_for_plan(self, owner: str, plan_id: str):
        self.get(owner, Ref(id=plan_id, sha256=plan_id), "plan")
        with self.db() as db:
            row = db.execute(
                "SELECT id FROM jobs WHERE owner=? AND plan_id=?", (owner, plan_id)
            ).fetchone()
        return self.status(owner, row["id"]) if row else None

    def recover(self):
        # Caller MUST hold the OS worker lock. Its acquisition proves a prior
        # worker is no longer alive; elapsed heartbeats alone cannot prove that.
        with self.db() as db:
            db.execute(
                "UPDATE records SET status='interrupted',error='Worker interrupted; record will restart' WHERE status='running'"
            )
            db.execute("UPDATE jobs SET status='interrupted' WHERE status='running'")

    def claim(self):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE status IN ('queued','interrupted') AND cancel=0 ORDER BY created LIMIT 1"
            ).fetchone()
            if row:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
                return dict(row)
        return None

    def record_start(self, job_id: str, key: str) -> int:
        with self.db() as db:
            db.execute(
                "UPDATE records SET status='running',attempt=attempt+1,result=NULL,error=NULL WHERE job_id=? AND key=?",
                (job_id, key),
            )
            return db.execute(
                "SELECT attempt FROM records WHERE job_id=? AND key=?", (job_id, key)
            ).fetchone()[0]

    def record_finish(
        self, job_id: str, key: str, status: str, result=None, error=None
    ):
        with self.db() as db:
            db.execute(
                "UPDATE records SET status=?,result=?,error=? WHERE job_id=? AND key=?",
                (status, canonical(result) if result else None, error, job_id, key),
            )

    def finish_job(self, owner: str, job_id: str):
        result = self.status(owner, job_id)
        state = (
            "cancelled"
            if result.cancel_requested
            else "completed"
            if result.completed == result.total
            else "partial"
            if result.completed
            else "failed"
        )
        with self.db() as db:
            db.execute("UPDATE jobs SET status=? WHERE id=?", (state, job_id))
        return self.status(owner, job_id)

    def artifact(self, owner: str, job_id: str, key: str, name: str) -> Path:
        result = self.status(owner, job_id)
        record = next(
            (
                r
                for r in result.records
                if r["key"] == key and r["status"] == "completed"
            ),
            None,
        )
        if not record:
            raise KeyError("completed record not found")
        artifact = next(
            (a for a in record["result"]["artifacts"] if a["name"] == name), None
        )
        if not artifact:
            raise KeyError("artifact not found")
        path = within(self.root, artifact["path"])
        if file_hash(path) != artifact["sha256"]:
            raise ValueError("artifact checksum mismatch")
        return path
