from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from newhire.prompt import SYSTEM_PROMPT, build_user_prompt
from newhire.schema import Scenario, assert_topic_policy_match

TOPIC_ABBREV = {
    "data_sharing": "DS",
    "expense_approval": "EA",
    "reporting": "RP",
}

DEFAULT_MODEL = "gpt-5-mini"
MAX_ATTEMPTS = 2
DEFAULT_MIX = {
    "data_sharing": 8,
    "expense_approval": 6,
    "reporting": 6,
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_policy(org_dir: Path, topic: str) -> dict[str, Any]:
    manifest = load_json(org_dir / "policies" / "manifest.json")
    matches = [m for m in manifest if m.get("topic") == topic and m.get("is_active", True)]
    if not matches:
        available = sorted({m.get("topic") for m in manifest if m.get("topic")})
        raise SystemExit(
            f"No active policy for topic={topic!r}. Available: {', '.join(available)}"
        )
    return matches[0]


def load_subtopics(org_dir: Path) -> dict[str, Any]:
    path = org_dir / "subtopics.json"
    if not path.is_file():
        raise SystemExit(f"subtopics.json not found: {path}")
    return load_json(path)


def subtopics_for_topic(catalog: dict[str, Any], topic: str) -> list[dict[str, Any]]:
    items = [s for s in catalog.get("subtopics", []) if s.get("topic") == topic]
    if not items:
        raise SystemExit(f"No subtopics for topic={topic!r}")
    return items


def default_out_path(org_dir: Path, topic: str) -> Path:
    abbrev = TOPIC_ABBREV.get(topic, topic[:2].upper())
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return org_dir / "generated" / f"OO-AX-{abbrev}-{ts}.json"


def default_batch_out_path(org_dir: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return org_dir / "generated" / f"batch_{ts}.jsonl"


def make_scenario_id(topic: str, index: int) -> str:
    abbrev = TOPIC_ABBREV.get(topic, topic[:2].upper())
    return f"OO-AX-{abbrev}-{index:03d}"


def _topic_index_from_id(scenario_id: str) -> int:
    try:
        return int(scenario_id.rsplit("-", 1)[-1])
    except ValueError:
        return 0


def build_missing_plan(catalog: dict[str, Any], existing_path: Path) -> list[dict[str, Any]]:
    from newhire.validate import load_scenarios

    existing = load_scenarios(existing_path)
    used = {s.subtopic for s in existing}
    next_n: dict[str, int] = {}
    for scenario in existing:
        next_n[scenario.topic] = max(next_n.get(scenario.topic, 0), _topic_index_from_id(scenario.scenario_id))

    plan: list[dict[str, Any]] = []
    for sub in catalog.get("subtopics", []):
        if sub["id"] in used:
            continue
        topic = sub["topic"]
        next_n[topic] = next_n.get(topic, 0) + 1
        plan.append({"topic": topic, "subtopic": sub, "n": next_n[topic]})
    if not plan:
        raise SystemExit(f"No missing subtopics vs {existing_path}")
    return plan


def build_batch_plan(
    catalog: dict[str, Any],
    *,
    count: int | None,
    topic: str | None,
    subtopic_id: str | None,
) -> list[dict[str, Any]]:
    """Return ordered list of {topic, subtopic, index_in_topic}."""
    all_subs: list[dict[str, Any]] = catalog["subtopics"]

    if subtopic_id:
        match = next((s for s in all_subs if s["id"] == subtopic_id), None)
        if not match:
            raise SystemExit(f"Unknown subtopic id: {subtopic_id}")
        if topic and match["topic"] != topic:
            raise SystemExit(
                f"subtopic {subtopic_id} belongs to {match['topic']}, not {topic}"
            )
        return [{"topic": match["topic"], "subtopic": match, "n": 1}]

    if topic and not count:
        # one item: first subtopic of topic (or round-robin start)
        subs = subtopics_for_topic(catalog, topic)
        return [{"topic": topic, "subtopic": subs[0], "n": 1}]

    mix = catalog.get("default_batch_mix", DEFAULT_MIX)
    if topic:
        n = count or 1
        mix = {topic: n}
    elif count and count != sum(mix.values()):
        # scale default mix proportionally to count
        total = sum(DEFAULT_MIX.values())
        mix = {
            t: max(1, round(count * (DEFAULT_MIX[t] / total)))
            for t in DEFAULT_MIX
        }
        # adjust to exact count
        while sum(mix.values()) > count:
            key = max(mix, key=mix.get)
            if mix[key] > 1:
                mix[key] -= 1
            else:
                break
        while sum(mix.values()) < count:
            key = min(mix, key=mix.get)
            mix[key] += 1

    plan: list[dict[str, Any]] = []
    counters: dict[str, int] = {}
    for t, n in mix.items():
        subs = subtopics_for_topic(catalog, t)
        for i in range(n):
            counters[t] = counters.get(t, 0) + 1
            plan.append(
                {
                    "topic": t,
                    "subtopic": subs[i % len(subs)],
                    "n": counters[t],
                }
            )
    return plan


def call_openai(*, client: OpenAI, model: str, user_prompt: str) -> str:
    # Some models (e.g. gpt-5-*) only allow the default temperature.
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Empty response from OpenAI")
    return content


def parse_and_validate(
    raw: str,
    *,
    expected_topic: str,
    expected_policy_id: str,
    expected_subtopic: str,
) -> Scenario:
    data = json.loads(raw)
    scenario = Scenario.model_validate(data)
    assert_topic_policy_match(
        scenario,
        expected_topic=expected_topic,
        expected_policy_id=expected_policy_id,
        expected_subtopic=expected_subtopic,
    )
    return scenario


def generate_once(
    *,
    client: OpenAI,
    model: str,
    organization: dict[str, Any],
    policy_meta: dict[str, Any],
    policy_text: str,
    topic: str,
    difficulty: str,
    subtopic: dict[str, Any],
    scenario_id: str,
) -> Scenario:
    user_prompt = build_user_prompt(
        organization=organization,
        policy_id=policy_meta["document_id"],
        policy_title=policy_meta["title"],
        policy_text=policy_text,
        topic=topic,
        difficulty=difficulty,
        key_sections=policy_meta.get("key_sections", []),
        subtopic=subtopic,
        scenario_id=scenario_id,
    )
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = call_openai(client=client, model=model, user_prompt=user_prompt)
            scenario = parse_and_validate(
                raw,
                expected_topic=topic,
                expected_policy_id=policy_meta["document_id"],
                expected_subtopic=subtopic["id"],
            )
            # Normalize id in case model drifts
            scenario.scenario_id = scenario_id
            scenario.subtopic = subtopic["id"]
            return scenario
        except (json.JSONDecodeError, ValidationError, ValueError, RuntimeError) as exc:
            last_error = exc
            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}",
                file=sys.stderr,
            )
    raise RuntimeError(f"Generation failed after {MAX_ATTEMPTS} attempts: {last_error}")


def build_parser() -> argparse.ArgumentParser:
    root = repo_root()
    parser = argparse.ArgumentParser(
        description="Generate SJT scenario JSON from fictional company policies.",
    )
    parser.add_argument(
        "--org",
        type=Path,
        default=root / "data" / "oo_soft",
        help="Organization data directory (default: data/oo_soft)",
    )
    parser.add_argument(
        "--topic",
        default=None,
        help="Single topic (default for count=1: data_sharing; with --count uses mix unless set)",
    )
    parser.add_argument(
        "--subtopic",
        default=None,
        help="Specific subtopic id from subtopics.json",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Batch size (default mix 8/6/6=20 when --count 20)",
    )
    parser.add_argument(
        "--difficulty",
        default="medium",
        choices=["easy", "medium", "hard"],
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"OpenAI model (default: $OPENAI_MODEL / $LLM_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (.json for 1, .jsonl for batch)",
    )
    parser.add_argument(
        "--missing-from",
        type=Path,
        default=None,
        help="Generate only catalog subtopics not already in this JSONL",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    load_dotenv(repo_root() / ".env")
    args = build_parser().parse_args(argv)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set (check .env)")

    model = (
        args.model
        or os.getenv("OPENAI_MODEL")
        or os.getenv("LLM_MODEL")
        or DEFAULT_MODEL
    )
    org_dir = args.org.resolve()
    if not org_dir.is_dir():
        raise SystemExit(f"Organization directory not found: {org_dir}")

    organization = load_json(org_dir / "organization.json")
    catalog = load_subtopics(org_dir)

    # Default: one data_sharing if nothing specified
    topic = args.topic
    count = args.count
    if (
        topic is None
        and count is None
        and args.subtopic is None
        and args.missing_from is None
    ):
        topic = "data_sharing"

    if args.missing_from:
        plan = build_missing_plan(catalog, args.missing_from.resolve())
    else:
        plan = build_batch_plan(
            catalog,
            count=count,
            topic=topic,
            subtopic_id=args.subtopic,
        )

    policy_cache: dict[str, tuple[dict[str, Any], str]] = {}
    client = OpenAI(api_key=api_key)

    results: list[Scenario] = []
    failures: list[str] = []

    for i, item in enumerate(plan, start=1):
        t = item["topic"]
        sub = item["subtopic"]
        sid = make_scenario_id(t, item["n"])
        print(f"[{i}/{len(plan)}] {sid} topic={t} subtopic={sub['id']}", flush=True)

        if t not in policy_cache:
            meta = resolve_policy(org_dir, t)
            path = org_dir / "policies" / meta["path"]
            if not path.is_file():
                raise SystemExit(f"Policy file not found: {path}")
            policy_cache[t] = (meta, path.read_text(encoding="utf-8"))
        policy_meta, policy_text = policy_cache[t]

        try:
            scenario = generate_once(
                client=client,
                model=model,
                organization=organization,
                policy_meta=policy_meta,
                policy_text=policy_text,
                topic=t,
                difficulty=args.difficulty,
                subtopic=sub,
                scenario_id=sid,
            )
            results.append(scenario)
        except Exception as exc:  # noqa: BLE001 — continue batch
            msg = f"{sid} failed: {exc}"
            print(msg, file=sys.stderr)
            failures.append(msg)

    if not results:
        raise SystemExit("No scenarios generated")

    out_path = args.out.resolve() if args.out else (
        default_batch_out_path(org_dir)
        if len(plan) > 1
        else default_out_path(org_dir, results[0].topic)
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if len(plan) > 1 or out_path.suffix == ".jsonl":
        with out_path.open("w", encoding="utf-8") as f:
            for scenario in results:
                f.write(scenario.model_dump_json() + "\n")
    else:
        out_path.write_text(
            results[0].model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    print(out_path)
    print(f"generated={len(results)} failed={len(failures)}", file=sys.stderr)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
