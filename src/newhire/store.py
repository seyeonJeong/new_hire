from __future__ import annotations

from pathlib import Path

from newhire.schema import Scenario
from newhire.validate import load_scenarios


class ScenarioStore:
    """In-memory store loaded from a repaired/generated JSONL file."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"Scenario file not found: {path}")
        self.path = path
        self._scenarios = load_scenarios(path)
        if not self._scenarios:
            raise ValueError(f"No scenarios in {path}")
        self._by_id = {s.scenario_id: s for s in self._scenarios}
        self._cursor = 0

    def next(self) -> Scenario:
        scenario = self._scenarios[self._cursor % len(self._scenarios)]
        self._cursor += 1
        return scenario

    def get(self, scenario_id: str) -> Scenario | None:
        return self._by_id.get(scenario_id)

    @property
    def count(self) -> int:
        return len(self._scenarios)
