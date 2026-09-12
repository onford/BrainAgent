"""Durable read-only tool reservations; recovery never replenishes a budget.

A crash after sending a request but before saving its result has an unknown
outcome. Such a request is reported as uncertain, never silently sent again.
Completed tool results are committed before the aggregate sources document.
"""
import json
from pathlib import Path
from time import time

import portalocker

from app.preprocessing.storage import digest, write_json
from .cognition_contracts import ResearchAction, ResearchSources, ToolObservation


def action_key(action):
    return digest(action.model_dump(exclude={"rationale", "category"}))


class ResearchJournal:
    def __init__(self, path, sources):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock():
            if not self.path.exists():
                rows = []
                for observation in sources.observations:
                    source_id = (observation.output or {}).get("source_id")
                    local = ResearchSources(
                        documents=[d for d in sources.documents if d.id == source_id],
                        observations=[observation],
                    )
                    rows.append(dict(sequence=observation.sequence,
                        key=action_key(observation.action), action=observation.action.model_dump(),
                        status="completed", result=local.model_dump(mode="json")))
                write_json(self.path, dict(version="1", budgets={}, actions=rows))

    def lock(self):
        return portalocker.Lock(self.path.with_suffix(".lock"), timeout=5)

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def bind_budget(self, purpose, max_actions, identity, max_seconds):
        key = digest([identity, max_actions, max_seconds])
        with self.lock():
            saved = self.read()
            budget = saved["budgets"].get(purpose)
            if budget and budget["identity"] != key:
                raise ValueError("research inputs or limits changed; start a new workflow")
            if not budget:
                saved["budgets"][purpose] = dict(identity=key, max_actions=max_actions,
                    started_at=time(), expires_at=time() + max_seconds)
                write_json(self.path, saved)

    @staticmethod
    def _remaining(saved, purpose):
        budget = saved["budgets"][purpose]
        if time() >= budget["expires_at"]:
            return 0
        used = sum(r["action"].get("purpose") == purpose for r in saved["actions"])
        return max(0, budget["max_actions"] - used)

    def remaining(self, purpose):
        with self.lock():
            return self._remaining(self.read(), purpose)

    def reserve(self, actions):
        with self.lock():
            saved = self.read()
            for purpose in {a.purpose for a in actions} & saved["budgets"].keys():
                if sum(a.purpose == purpose for a in actions) > self._remaining(saved, purpose):
                    raise TimeoutError("persistent research action/time budget exhausted")
            sequence = max((r["sequence"] for r in saved["actions"]), default=0)
            tickets = []
            for action in actions:
                sequence += 1
                key = action_key(action)
                previous = next((r for r in saved["actions"] if r["key"] == key), None)
                row = dict(sequence=sequence, key=key, action=action.model_dump(),
                    reserved_at=time(), status="reserved", result=None)
                if previous:
                    result = previous["result"] or self.uncertain(previous).model_dump(mode="json")
                    row.update(status="completed", result=result, reused_sequence=previous["sequence"])
                saved["actions"].append(row)
                budget = saved["budgets"].get(action.purpose)
                tickets.append({**row, "seconds_left": max(0, budget["expires_at"] - time()) if budget else None})
            write_json(self.path, saved)
            return tickets

    @staticmethod
    def uncertain(row):
        return ResearchSources(documents=[], observations=[ToolObservation(
            sequence=row["sequence"], action=row["action"], success=False, output=None,
            error="Previous request was interrupted before its outcome was saved; outcome unknown, request not repeated.")])

    def complete(self, ticket, result):
        with self.lock():
            saved = self.read()
            row = next(r for r in saved["actions"] if r["sequence"] == ticket["sequence"])
            if row["key"] != ticket["key"] or row["status"] != "reserved":
                raise ValueError("research reservation already completed or changed")
            row.update(status="completed", completed_at=time(), result=result.model_dump(mode="json"))
            write_json(self.path, saved)

    def restore(self, sources, *, include_uncertain=False):
        """Idempotently rebuild results lost between the journal and aggregate save."""
        with self.lock():
            rows = self.read()["actions"]
        documents = {d.id: d for d in sources.documents}
        observations = {o.sequence: o for o in sources.observations}
        for row in rows:
            if row["result"]:
                result = ResearchSources.model_validate(row["result"])
            elif include_uncertain:
                result = self.uncertain(row)
            else:
                continue
            documents.update({d.id: d for d in result.documents})
            observation = result.observations[0].model_copy(update={
                "sequence": row["sequence"], "action": ResearchAction.model_validate(row["action"])})
            observations[row["sequence"]] = observation
        sources.documents = sorted(documents.values(), key=lambda d: d.id)
        sources.observations = sorted(observations.values(), key=lambda o: o.sequence)
