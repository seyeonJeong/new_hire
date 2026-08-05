from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from newhire.schema import PolicyRef

SECTION_HEADER = re.compile(r"^(#{2,3})\s+(\d+(?:\.\d+)*)\b.*$", re.MULTILINE)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_policies_dir() -> Path:
    return repo_root() / "data" / "oo_soft" / "policies"


@lru_cache(maxsize=8)
def _load_manifest(policies_dir: str) -> list[dict]:
    path = Path(policies_dir) / "manifest.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_policy_path(policy_id: str, policies_dir: Path | None = None) -> Path:
    root = policies_dir or default_policies_dir()
    for item in _load_manifest(str(root.resolve())):
        if item.get("document_id") == policy_id and item.get("is_active", True):
            return root / item["path"]
    raise FileNotFoundError(f"No active policy document for id={policy_id!r}")


def _normalize_section_id(value: str) -> str:
    match = re.match(r"^(\d+(?:\.\d+)*)", value.strip())
    return match.group(1) if match else value.strip()


def extract_sections(markdown: str, section_ids: list[str]) -> str:
    wanted = {_normalize_section_id(s) for s in section_ids}
    headers = list(SECTION_HEADER.finditer(markdown))
    if not headers:
        return markdown.strip()

    chunks: list[str] = []
    for i, match in enumerate(headers):
        section_id = match.group(2)
        if section_id not in wanted:
            continue
        start = match.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(markdown)
        chunks.append(markdown[start:end].strip())

    if chunks:
        return "\n\n".join(chunks)
    return markdown.strip()


def load_policy_excerpts(
    policy_ref: PolicyRef,
    *,
    policies_dir: Path | None = None,
) -> str:
    path = resolve_policy_path(policy_ref.policy_id, policies_dir)
    text = path.read_text(encoding="utf-8")
    excerpts = extract_sections(text, policy_ref.sections)
    header = f"# {policy_ref.policy_id} (sections: {', '.join(policy_ref.sections)})"
    return f"{header}\n\n{excerpts}"
