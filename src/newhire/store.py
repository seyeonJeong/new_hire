from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

from newhire.schema import Scenario
from newhire.validate import load_scenarios


def select_balanced(scenarios: list[Scenario], limit: int) -> list[Scenario]:
    """Pick up to `limit` items with mixed correct_choice_id, shuffled each call."""
    if limit >= len(scenarios):
        return list(scenarios)

    by_answer: dict[str, list[Scenario]] = defaultdict(list)
    for scenario in scenarios:
        by_answer[scenario.correct_choice_id].append(scenario)

    order = ["A", "B", "C"]
    for key in order:
        random.shuffle(by_answer[key])

    selected: list[Scenario] = []
    used: set[str] = set()
    idx = {key: 0 for key in order}

    while len(selected) < limit:
        progressed = False
        for key in order:
            if len(selected) >= limit:
                break
            bucket = by_answer[key]
            while idx[key] < len(bucket):
                candidate = bucket[idx[key]]
                idx[key] += 1
                if candidate.scenario_id in used:
                    continue
                selected.append(candidate)
                used.add(candidate.scenario_id)
                progressed = True
                break
        if not progressed:
            break

    if len(selected) < limit:
        for scenario in scenarios:
            if scenario.scenario_id in used:
                continue
            selected.append(scenario)
            used.add(scenario.scenario_id)
            if len(selected) >= limit:
                break

    random.shuffle(selected)
    return selected


class ScenarioStore:
    """In-memory store loaded from a repaired/generated JSONL file."""

    def __init__(self, path: Path, *, limit: int | None = None) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"Scenario file not found: {path}")
        self.path = path
        self.limit = limit
        loaded = load_scenarios(path)
        if not loaded:
            raise ValueError(f"No scenarios in {path}")
        self._all = loaded
        self._scenarios = self._pick()
        if not self._scenarios:
            raise ValueError(f"No scenarios after applying limit={limit}")
        self._by_id = {s.scenario_id: s for s in self._all}
        self._cursor = 0

    def _pick(self) -> list[Scenario]:
        if self.limit is None:
            return list(self._all)
        return select_balanced(self._all, self.limit)

    def next(self) -> Scenario | None:
        if self._cursor >= len(self._scenarios):
            return None
        scenario = self._scenarios[self._cursor]
        self._cursor += 1
        return scenario

    def reset(self) -> None:
        self._scenarios = self._pick()
        self._cursor = 0

    def quiz_scenarios(self) -> list[Scenario]:
        return list(self._scenarios)

    def exhaust(self) -> None:
        self._cursor = len(self._scenarios)

    def get(self, scenario_id: str) -> Scenario | None:
        return self._by_id.get(scenario_id)

    def pick_open(self, exclude_ids: set[str] | None = None) -> Scenario:
        skip = exclude_ids or set()
        pool = [s for s in self._all if s.scenario_id not in skip]
        if not pool:
            pool = list(self._all)
        return random.choice(pool)

    @property
    def count(self) -> int:
        return len(self._scenarios)

    @property
    def cursor(self) -> int:
        return self._cursor
