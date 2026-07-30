from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from newhire.prompt import REPAIR_SYSTEM_PROMPT, build_repair_user_prompt
from newhire.schema import Scenario, assert_topic_policy_match
from newhire.validate import (
    ANSWER_POSITION_SHARE,
    Issue,
    load_scenarios,
    load_subtopic_catalog,
    summarize,
    validate_batch,
)

ChoiceId = Literal["A", "B", "C"]
DEFAULT_MODEL = "gpt-5-mini"
MAX_ATTEMPTS = 2


@dataclass
class RepairTask:
    scenario_id: str
    issue_lines: list[str] = field(default_factory=list)
    target_correct_choice_id: ChoiceId | None = None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_policy(org_dir: Path, topic: str) -> dict[str, Any]:
    manifest = load_json(org_dir / "policies" / "manifest.json")
    matches = [m for m in manifest if m.get("topic") == topic and m.get("is_active", True)]
    if not matches:
        raise SystemExit(f"No active policy for topic={topic!r}")
    return matches[0]


def target_counts(n: int) -> dict[ChoiceId, int]:
    base = n // 3
    rem = n % 3
    counts: dict[ChoiceId, int] = {"A": base, "B": base, "C": base}
    for i, key in enumerate(("A", "B", "C")):
        if i < rem:
            counts[key] += 1
    return counts


def build_repair_plan(
    scenarios: list[Scenario],
    issues: list[Issue],
) -> dict[str, RepairTask]:
    by_id: dict[str, RepairTask] = {}

    def task_for(sid: str) -> RepairTask:
        if sid not in by_id:
            by_id[sid] = RepairTask(scenario_id=sid)
        return by_id[sid]

    # Per-scenario errors/warnings (except batch-level)
    for issue in issues:
        if issue.scenario_id and issue.code != "near_duplicate":
            t = task_for(issue.scenario_id)
            t.issue_lines.append(f"[{issue.level}] {issue.code}: {issue.message}")

    # Near duplicates: repair the second id mentioned
    for issue in issues:
        if issue.code != "near_duplicate":
            continue
        # message like: "NOVA-AX-DS-001 ~ NOVA-AX-DS-002 jaccard=0.90 ..."
        parts = issue.message.split("~")
        if len(parts) < 2:
            continue
        second = parts[1].strip().split()[0]
        t = task_for(second)
        t.issue_lines.append(f"[warning] near_duplicate: {issue.message}")
        t.issue_lines.append(
            "[repair] rewrite scenario/question to reduce overlap with the paired item"
        )

    # Answer position rebalance
    if len(scenarios) >= 5:
        counts = Counter(s.correct_choice_id for s in scenarios)
        n = len(scenarios)
        skewed = any(cnt / n >= ANSWER_POSITION_SHARE for cnt in counts.values())
        if skewed:
            goals = target_counts(n)
            assigned: Counter[str] = Counter()
            desired_map: dict[str, ChoiceId] = {}

            # Pass 1: keep current id while quota remains
            for scenario in scenarios:
                current = scenario.correct_choice_id
                if assigned[current] < goals[current]:
                    desired_map[scenario.scenario_id] = current
                    assigned[current] += 1

            # Pass 2: fill remaining slots from under-quota labels
            for scenario in scenarios:
                if scenario.scenario_id in desired_map:
                    continue
                for cid in ("A", "B", "C"):
                    if assigned[cid] < goals[cid]:
                        desired_map[scenario.scenario_id] = cid  # type: ignore[assignment]
                        assigned[cid] += 1
                        break

            for scenario in scenarios:
                desired = desired_map.get(scenario.scenario_id, scenario.correct_choice_id)
                if desired != scenario.correct_choice_id:
                    t = task_for(scenario.scenario_id)
                    t.target_correct_choice_id = desired
                    t.issue_lines.append(
                        "[repair] reason: batch answer_position_skew "
                        f"(rebalance toward A/B/C ≈ equal; was {dict(counts)})"
                    )
                elif scenario.scenario_id in by_id:
                    t = by_id[scenario.scenario_id]
                    if t.target_correct_choice_id is None:
                        t.target_correct_choice_id = desired

    return by_id


def call_openai(*, client: OpenAI, model: str, user_prompt: str) -> str:
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Empty response from OpenAI")
    return content


def merge_repair_payload(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Fill omitted fields from the old scenario so partial LLM edits still validate."""
    merged = dict(old)
    merged.update(new)
    # Nested objects that models often truncate
    if "rationale" not in new or not isinstance(new.get("rationale"), dict):
        merged["rationale"] = old.get("rationale")
    else:
        rationale = dict(old.get("rationale") or {})
        rationale.update(new["rationale"])
        merged["rationale"] = rationale
    if "policy_ref" not in new or not isinstance(new.get("policy_ref"), dict):
        merged["policy_ref"] = old.get("policy_ref")
    else:
        policy_ref = dict(old.get("policy_ref") or {})
        policy_ref.update(new["policy_ref"])
        if not policy_ref.get("sections"):
            policy_ref["sections"] = (old.get("policy_ref") or {}).get("sections")
        merged["policy_ref"] = policy_ref
    for key in ("required_actions", "prohibited_actions"):
        if key not in new or not new.get(key):
            merged[key] = old.get(key)
    if "meta" not in new or not isinstance(new.get("meta"), dict):
        merged["meta"] = old.get("meta") or {"version": "v0.1", "status": "draft"}
    return merged


def repair_one(
    *,
    client: OpenAI,
    model: str,
    organization: dict[str, Any],
    policy_meta: dict[str, Any],
    policy_text: str,
    subtopic: dict[str, Any],
    old: Scenario,
    task: RepairTask,
) -> Scenario:
    old_dict = json.loads(old.model_dump_json())
    user_prompt = build_repair_user_prompt(
        organization=organization,
        policy_id=policy_meta["document_id"],
        policy_text=policy_text,
        subtopic=subtopic,
        old_scenario=old_dict,
        issue_lines=task.issue_lines,
        scenario_id=old.scenario_id,
        target_correct_choice_id=task.target_correct_choice_id,
    )
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = call_openai(client=client, model=model, user_prompt=user_prompt)
            data = merge_repair_payload(old_dict, json.loads(raw))
            scenario = Scenario.model_validate(data)
            assert_topic_policy_match(
                scenario,
                expected_topic=old.topic,
                expected_policy_id=policy_meta["document_id"],
                expected_subtopic=old.subtopic,
            )
            scenario.scenario_id = old.scenario_id
            scenario.subtopic = old.subtopic
            scenario.topic = old.topic
            if (
                task.target_correct_choice_id
                and scenario.correct_choice_id != task.target_correct_choice_id
            ):
                raise ValueError(
                    f"target_correct_choice_id={task.target_correct_choice_id} "
                    f"but got {scenario.correct_choice_id}"
                )
            return scenario
        except (json.JSONDecodeError, ValidationError, ValueError, RuntimeError) as exc:
            last_error = exc
            print(
                f"  attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}",
                file=sys.stderr,
            )
    raise RuntimeError(f"Repair failed for {old.scenario_id}: {last_error}")


def write_scenarios(path: Path, scenarios: list[Scenario]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jsonl" or len(scenarios) > 1:
        with path.open("w", encoding="utf-8") as f:
            for scenario in scenarios:
                f.write(scenario.model_dump_json() + "\n")
    else:
        path.write_text(scenarios[0].model_dump_json(indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Repair SJT scenarios using validation issues in the LLM prompt.",
    )
    parser.add_argument("--in", dest="input_path", type=Path, required=True)
    parser.add_argument(
        "--org",
        type=Path,
        default=root / "data" / "nova_soft",
    )
    parser.add_argument(
        "--subtopics",
        type=Path,
        default=None,
        help="Defaults to <org>/subtopics.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: <in> with .repaired.jsonl)",
    )
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Print repair plan JSON and exit without calling the LLM",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv(repo_root() / ".env")
    args = build_parser().parse_args(argv)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key and not args.plan_only:
        raise SystemExit("OPENAI_API_KEY is not set (check .env)")

    model = (
        args.model
        or os.getenv("OPENAI_MODEL")
        or os.getenv("LLM_MODEL")
        or DEFAULT_MODEL
    )
    org_dir = args.org.resolve()
    in_path = args.input_path.resolve()
    if not in_path.is_file():
        raise SystemExit(f"Input not found: {in_path}")

    subtopics_path = (
        args.subtopics.resolve()
        if args.subtopics
        else org_dir / "subtopics.json"
    )
    organization = load_json(org_dir / "organization.json")
    catalog = load_subtopic_catalog(subtopics_path)
    if not catalog:
        raise SystemExit(f"No subtopics loaded from {subtopics_path}")

    scenarios = load_scenarios(in_path)
    by_id = {s.scenario_id: s for s in scenarios}

    out_path = args.out.resolve() if args.out else in_path.with_name(
        in_path.stem + ".repaired" + (in_path.suffix or ".jsonl")
    )

    policy_cache: dict[str, tuple[dict[str, Any], str]] = {}
    client = OpenAI(api_key=api_key) if api_key else None

    for round_idx in range(1, args.max_rounds + 1):
        issues = validate_batch(scenarios, catalog_by_id=catalog)
        errors, warnings = summarize(issues)
        print(
            f"round {round_idx}: errors={errors} warnings={warnings}",
            file=sys.stderr,
        )
        plan = build_repair_plan(scenarios, issues)
        if not plan:
            print("nothing to repair", file=sys.stderr)
            break

        plan_payload = {
            sid: {
                "target_correct_choice_id": t.target_correct_choice_id,
                "issues": t.issue_lines,
            }
            for sid, t in plan.items()
        }
        if args.plan_only:
            print(json.dumps(plan_payload, ensure_ascii=False, indent=2))
            return

        assert client is not None
        print(f"repairing {len(plan)} scenario(s)", file=sys.stderr)
        for sid, task in plan.items():
            old = by_id[sid]
            print(
                f"  [{sid}] target={task.target_correct_choice_id} "
                f"issues={len(task.issue_lines)}",
                flush=True,
            )
            if old.topic not in policy_cache:
                meta = resolve_policy(org_dir, old.topic)
                path = org_dir / "policies" / meta["path"]
                policy_cache[old.topic] = (meta, path.read_text(encoding="utf-8"))
            policy_meta, policy_text = policy_cache[old.topic]
            sub = catalog.get(old.subtopic)
            if not sub:
                print(f"  skip {sid}: unknown subtopic {old.subtopic}", file=sys.stderr)
                continue
            try:
                fixed = repair_one(
                    client=client,
                    model=model,
                    organization=organization,
                    policy_meta=policy_meta,
                    policy_text=policy_text,
                    subtopic=sub,
                    old=old,
                    task=task,
                )
                by_id[sid] = fixed
            except Exception as exc:  # noqa: BLE001
                print(f"  failed {sid}: {exc}", file=sys.stderr)

        # keep original order
        scenarios = [by_id[s.scenario_id] for s in scenarios]
        for s in scenarios:
            by_id[s.scenario_id] = s

        # re-validate; stop early if clean of errors and no skew/dup warnings we care about
        post = validate_batch(scenarios, catalog_by_id=catalog)
        e2, w2 = summarize(post)
        print(f"round {round_idx} done: errors={e2} warnings={w2}", file=sys.stderr)
        if e2 == 0 and not build_repair_plan(scenarios, post):
            break

    write_scenarios(out_path, scenarios)
    print(out_path)

    final_issues = validate_batch(scenarios, catalog_by_id=catalog)
    for issue in final_issues:
        print(issue.format())
    fe, fw = summarize(final_issues)
    print(f"final: checked={len(scenarios)} errors={fe} warnings={fw}", file=sys.stderr)
    if fe:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
