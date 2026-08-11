from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, field_validator

from newhire.generate import (
    DEFAULT_MODEL,
    load_json,
    load_subtopics,
    repo_root,
    resolve_policy,
)
from newhire.prompt import (
    COMPETENCY_HINTS,
    SUBTOPIC_SYSTEM_PROMPT,
    TOPIC_ID_PREFIX,
    build_subtopic_user_prompt,
)
from newhire.schema import Competency

ID_RE = re.compile(r"^[a-z]+(?:_[a-z0-9]+)+$")


class SubtopicDraft(BaseModel):
    id: str
    topic: str
    title: str = Field(min_length=1)
    trigger: str = Field(min_length=1)
    conflict: str = Field(min_length=1)
    primary_competency_hint: str

    @field_validator("primary_competency_hint")
    @classmethod
    def check_competency(cls, value: str) -> str:
        allowed = {c.value for c in Competency}
        if value not in allowed:
            raise ValueError(
                f"primary_competency_hint must be one of {sorted(allowed)}, got {value!r}"
            )
        return value


def call_openai(*, client: OpenAI, model: str, user_prompt: str) -> dict[str, Any]:
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SUBTOPIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("LLM returned non-object JSON")
    return data


def validate_id(subtopic_id: str, *, prefix: str) -> None:
    if not subtopic_id.startswith(f"{prefix}_"):
        raise ValueError(f"id must start with {prefix}_, got {subtopic_id!r}")
    if not ID_RE.fullmatch(subtopic_id):
        raise ValueError(f"id must be lowercase snake_case, got {subtopic_id!r}")


def normalize_items(
    raw: dict[str, Any],
    *,
    topic: str,
    prefix: str,
    existing_ids: set[str],
) -> list[SubtopicDraft]:
    items = raw.get("subtopics")
    if not isinstance(items, list) or not items:
        raise ValueError("response must contain non-empty subtopics list")

    out: list[SubtopicDraft] = []
    seen: set[str] = set()
    for item in items:
        draft = SubtopicDraft.model_validate(item)
        if draft.topic != topic:
            draft.topic = topic
        validate_id(draft.id, prefix=prefix)
        if draft.id in existing_ids or draft.id in seen:
            raise ValueError(f"duplicate subtopic id: {draft.id}")
        seen.add(draft.id)
        out.append(draft)
    return out


def merge_subtopics(
    catalog: dict[str, Any],
    new_items: list[SubtopicDraft],
) -> dict[str, Any]:
    merged = dict(catalog)
    subs = list(catalog.get("subtopics", []))
    subs.extend(item.model_dump() for item in new_items)
    merged["subtopics"] = subs
    return merged


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate new SJT subtopics from a policy markdown and merge into subtopics.json"
    )
    parser.add_argument(
        "--topic",
        required=True,
        choices=sorted(TOPIC_ID_PREFIX.keys()),
        help="Policy topic to expand",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="How many new subtopics to request (default: 3)",
    )
    parser.add_argument(
        "--org-dir",
        type=Path,
        default=None,
        help="Organization data dir (default: data/oo_soft)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"OpenAI model (default: env LLM_MODEL or {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print new subtopics only; do not write subtopics.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path to write only the newly generated subtopics JSON",
    )
    args = parser.parse_args(argv)

    if args.count < 1:
        raise SystemExit("--count must be >= 1")

    load_dotenv(repo_root() / ".env")
    org_dir = (args.org_dir or (repo_root() / "data" / "oo_soft")).resolve()
    catalog_path = org_dir / "subtopics.json"
    catalog = load_subtopics(org_dir)
    organization = load_json(org_dir / "organization.json")

    policy_meta = resolve_policy(org_dir, args.topic)
    policy_path = org_dir / "policies" / policy_meta["path"]
    policy_text = policy_path.read_text(encoding="utf-8")
    prefix = TOPIC_ID_PREFIX[args.topic]
    existing = catalog.get("subtopics", [])
    existing_ids = {s["id"] for s in existing if s.get("id")}

    model = args.model or os.getenv("LLM_MODEL", DEFAULT_MODEL)
    client = OpenAI()
    user_prompt = build_subtopic_user_prompt(
        organization=organization,
        topic=args.topic,
        policy_id=policy_meta["document_id"],
        policy_title=policy_meta["title"],
        policy_text=policy_text,
        existing_subtopics=existing,
        count=args.count,
        id_prefix=prefix,
    )

    print(
        f"Generating {args.count} subtopics for topic={args.topic} "
        f"policy={policy_meta['document_id']} model={model}",
        flush=True,
    )
    raw = call_openai(client=client, model=model, user_prompt=user_prompt)
    try:
        drafts = normalize_items(
            raw, topic=args.topic, prefix=prefix, existing_ids=existing_ids
        )
    except Exception as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        print(json.dumps(raw, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc

    if len(drafts) > args.count:
        drafts = drafts[: args.count]
    elif len(drafts) < args.count:
        print(
            f"warning: requested {args.count}, got {len(drafts)}",
            file=sys.stderr,
        )

    payload = {"subtopics": [d.model_dump() for d in drafts]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        save_json(args.out, payload)
        print(f"wrote new subtopics -> {args.out}", flush=True)

    if args.dry_run:
        print("dry-run: subtopics.json not modified", flush=True)
        return

    merged = merge_subtopics(catalog, drafts)
    save_json(catalog_path, merged)
    print(
        f"merged {len(drafts)} into {catalog_path} "
        f"(total={len(merged['subtopics'])})",
        flush=True,
    )


if __name__ == "__main__":
    main()
