from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from newhire.schema import ChoiceLabel, Scenario

Level = Literal["error", "warning"]

STOPWORDS = {
    "함",
    "요청",
    "상황",
    "필요",
    "경우",
    "대해",
    "위한",
    "있는",
    "없는",
    "또는",
    "및",
    "등",
    "중",
    "후",
    "전",
    "시",
    "것",
    "수",
    "더",
    "같은",
    "이런",
    "저런",
    "vs",
}

LEAKAGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("label_token", re.compile(r"\b(unsafe|partial|correct)\b", re.I)),
    ("answer_hint", re.compile(r"(정답|오답|올바른\s*선택|틀린\s*선택)")),
    ("policy_id", re.compile(r"\b(SEC|EXP|RPT)-\d+\b", re.I)),
    ("section_ref", re.compile(r"(?<![A-Za-z0-9])\d+\.\d+(?![A-Za-z0-9])")),
]

CORRECT_LENGTH_RATIO = 1.6
MIN_ACTION_CHARS = 6
ANSWER_POSITION_SHARE = 0.7
DUPLICATE_JACCARD = 0.85
MIN_BATCH_FOR_BALANCE = 5


@dataclass
class Issue:
    level: Level
    code: str
    message: str
    scenario_id: str | None = None

    def format(self) -> str:
        loc = f" [{self.scenario_id}]" if self.scenario_id else ""
        return f"{self.level.upper()}{loc} {self.code}: {self.message}"


def _choice_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def check_choice_length(scenario: Scenario) -> list[Issue]:
    lengths = {c.label: _choice_len(c.text) for c in scenario.choices}
    correct_len = lengths[ChoiceLabel.correct]
    other = [
        lengths[ChoiceLabel.unsafe],
        lengths[ChoiceLabel.partial],
    ]
    other_mean = sum(other) / len(other)
    if other_mean <= 0:
        return [
            Issue(
                "error",
                "choice_length",
                "non-correct choices have empty effective length",
                scenario.scenario_id,
            )
        ]
    ratio = correct_len / other_mean
    if ratio > CORRECT_LENGTH_RATIO:
        return [
            Issue(
                "error",
                "choice_length",
                (
                    f"correct choice is {ratio:.2f}x longer than other choices "
                    f"(limit {CORRECT_LENGTH_RATIO})"
                ),
                scenario.scenario_id,
            )
        ]
    return []


def check_leakage(scenario: Scenario) -> list[Issue]:
    visible = "\n".join(
        [scenario.question, scenario.scenario, *(c.text for c in scenario.choices)]
    )
    issues: list[Issue] = []
    for code, pattern in LEAKAGE_PATTERNS:
        if pattern.search(visible):
            issues.append(
                Issue(
                    "error",
                    f"leakage_{code}",
                    f"visible text matches leakage pattern: {pattern.pattern}",
                    scenario.scenario_id,
                )
            )
    return issues


def check_actions(scenario: Scenario) -> list[Issue]:
    issues: list[Issue] = []
    for field_name, items in (
        ("required_actions", scenario.required_actions),
        ("prohibited_actions", scenario.prohibited_actions),
    ):
        for i, item in enumerate(items):
            cleaned = item.strip()
            if len(cleaned) < MIN_ACTION_CHARS:
                issues.append(
                    Issue(
                        "error",
                        "action_too_short",
                        f"{field_name}[{i}] too short (<{MIN_ACTION_CHARS} chars): {cleaned!r}",
                        scenario.scenario_id,
                    )
                )
        # near-duplicate lines inside the same list
        norms = [re.sub(r"\s+", "", x.strip()) for x in items]
        for i in range(len(norms)):
            for j in range(i + 1, len(norms)):
                if not norms[i] or not norms[j]:
                    continue
                if norms[i] == norms[j] or (
                    len(norms[i]) >= 8
                    and len(norms[j]) >= 8
                    and (norms[i] in norms[j] or norms[j] in norms[i])
                ):
                    issues.append(
                        Issue(
                            "error",
                            "action_duplicate",
                            f"{field_name} has near-duplicate items at {i} and {j}",
                            scenario.scenario_id,
                        )
                    )
    return issues


def _keywords_from_text(text: str) -> set[str]:
    parts = re.split(r"[\s,./·|/()\[\]{}<>\"'“”‘’~…\-–—:：;；]+", text)
    out: set[str] = set()
    for p in parts:
        p = p.strip().lower()
        if len(p) < 2 or p in STOPWORDS:
            continue
        out.add(p)
    return out


def check_subtopic_coverage(
    scenario: Scenario,
    catalog_by_id: dict[str, dict[str, Any]],
) -> list[Issue]:
    meta = catalog_by_id.get(scenario.subtopic)
    if not meta:
        return [
            Issue(
                "warning",
                "subtopic_unknown",
                f"subtopic {scenario.subtopic!r} not found in catalog",
                scenario.scenario_id,
            )
        ]
    keywords: set[str] = set()
    for field in ("title", "trigger", "conflict"):
        keywords |= _keywords_from_text(str(meta.get(field, "")))
    if not keywords:
        return []
    haystack = (scenario.scenario + " " + scenario.question).lower()
    hits = [k for k in keywords if k in haystack]
    if not hits:
        sample = ", ".join(sorted(keywords)[:8])
        return [
            Issue(
                "warning",
                "subtopic_coverage",
                f"scenario text has no overlap with subtopic keywords ({sample})",
                scenario.scenario_id,
            )
        ]
    return []


def check_answer_position_balance(scenarios: list[Scenario]) -> list[Issue]:
    if len(scenarios) < MIN_BATCH_FOR_BALANCE:
        return []
    counts = Counter(s.correct_choice_id for s in scenarios)
    n = len(scenarios)
    issues: list[Issue] = []
    for choice_id, cnt in counts.items():
        share = cnt / n
        if share >= ANSWER_POSITION_SHARE:
            issues.append(
                Issue(
                    "warning",
                    "answer_position_skew",
                    (
                        f"correct_choice_id={choice_id} appears in {cnt}/{n} "
                        f"({share:.0%}, limit {ANSWER_POSITION_SHARE:.0%})"
                    ),
                )
            )
    return issues


def _char_bigrams(text: str) -> set[str]:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def check_near_duplicates(scenarios: list[Scenario]) -> list[Issue]:
    issues: list[Issue] = []
    bags = [
        _char_bigrams(s.scenario + " " + s.question)
        for s in scenarios
    ]
    for i in range(len(scenarios)):
        for j in range(i + 1, len(scenarios)):
            score = _jaccard(bags[i], bags[j])
            if score >= DUPLICATE_JACCARD:
                issues.append(
                    Issue(
                        "warning",
                        "near_duplicate",
                        (
                            f"{scenarios[i].scenario_id} ~ {scenarios[j].scenario_id} "
                            f"jaccard={score:.2f} (limit {DUPLICATE_JACCARD})"
                        ),
                    )
                )
    return issues


def validate_scenario(
    scenario: Scenario,
    *,
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    issues.extend(check_choice_length(scenario))
    issues.extend(check_leakage(scenario))
    issues.extend(check_actions(scenario))
    if catalog_by_id is not None:
        issues.extend(check_subtopic_coverage(scenario, catalog_by_id))
    return issues


def validate_batch(
    scenarios: list[Scenario],
    *,
    catalog_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    for scenario in scenarios:
        issues.extend(validate_scenario(scenario, catalog_by_id=catalog_by_id))
    issues.extend(check_answer_position_balance(scenarios))
    issues.extend(check_near_duplicates(scenarios))
    return issues


def load_scenarios(path: Path) -> list[Scenario]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"Empty file: {path}")
    if path.suffix == ".jsonl":
        scenarios: list[Scenario] = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                scenarios.append(Scenario.model_validate(json.loads(line)))
            except Exception as exc:  # noqa: BLE001
                raise SystemExit(f"{path}:{line_no} schema error: {exc}") from exc
        return scenarios
    data = json.loads(text)
    if isinstance(data, list):
        return [Scenario.model_validate(item) for item in data]
    return [Scenario.model_validate(data)]


def load_subtopic_catalog(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("subtopics", raw if isinstance(raw, list) else [])
    return {item["id"]: item for item in items if "id" in item}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def summarize(issues: list[Issue]) -> tuple[int, int]:
    errors = sum(1 for i in issues if i.level == "error")
    warnings = sum(1 for i in issues if i.level == "warning")
    return errors, warnings


def build_parser() -> argparse.ArgumentParser:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Validate generated SJT scenarios (quality rules).",
    )
    parser.add_argument(
        "--in",
        dest="input_path",
        type=Path,
        required=True,
        help="Input .json or .jsonl",
    )
    parser.add_argument(
        "--subtopics",
        type=Path,
        default=root / "data" / "nova_soft" / "subtopics.json",
        help="subtopics.json for coverage checks",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write machine-readable issues JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    path = args.input_path.resolve()
    if not path.is_file():
        raise SystemExit(f"Input not found: {path}")

    scenarios = load_scenarios(path)
    catalog = load_subtopic_catalog(args.subtopics.resolve() if args.subtopics else None)
    issues = validate_batch(scenarios, catalog_by_id=catalog or None)

    for issue in issues:
        print(issue.format())

    errors, warnings = summarize(issues)
    print(
        f"checked={len(scenarios)} errors={errors} warnings={warnings}",
        file=sys.stderr,
    )

    if args.json_out:
        payload = [
            {
                "level": i.level,
                "code": i.code,
                "message": i.message,
                "scenario_id": i.scenario_id,
            }
            for i in issues
        ]
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
