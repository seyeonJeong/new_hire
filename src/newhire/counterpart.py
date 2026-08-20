from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from newhire import agent_prompts as prompts
from newhire.evaluate_graph import _chat_json, default_model
from newhire.evaluate_open import ChatTurn
from newhire.schema import Scenario

load_dotenv()

logger = logging.getLogger(__name__)

FALLBACK_REPLY = "그래도 오늘은 꼭 처리해 주셔야 합니다. 나중에 정리하면 안 될까요?"


def counterpart_enabled() -> bool:
    flag = os.getenv("NEWHIRE_COUNTERPART", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def ecp_transcript(messages: list[ChatTurn] | list[dict[str, Any]]) -> str:
    """Rewrite history so the counterpart is '나' and the trainee is '상대'."""
    lines: list[str] = []
    for item in messages:
        speaker = item.speaker if isinstance(item, ChatTurn) else str(item.get("speaker", ""))
        text = item.text if isinstance(item, ChatTurn) else str(item.get("text", ""))
        label = "나" if speaker == "counterpart" else "상대"
        lines.append(f"{label}: {text}")
    return "\n".join(lines) if lines else "(대화 없음)"


FALLBACK_BY_STANCE = {
    "refuse": FALLBACK_REPLY,
    "redirect": "그럼 다른 방법이라도 알려주세요. 저는 이거 오늘 꼭 필요합니다.",
    "comply": "네, 확인되면 알려주세요.",
}


def generate_counterpart_reply(
    scenario: Scenario,
    messages: list[ChatTurn] | list[dict[str, Any]],
    *,
    conflict: str = "",
    trigger: str = "",
    stance: str = "refuse",
    client: OpenAI | None = None,
    model: str | None = None,
) -> str:
    if not counterpart_enabled():
        return FALLBACK_BY_STANCE.get(stance, FALLBACK_REPLY)
    system = prompts.COUNTERPART_SYSTEM_BY_STANCE.get(
        stance, prompts.COUNTERPART_SYSTEM_REFUSE
    )
    try:
        raw = _chat_json(
            client or OpenAI(),
            system=system,
            user=prompts.COUNTERPART_USER.format(
                scenario=scenario.scenario,
                conflict=conflict or trigger or "급함 vs 절차 준수",
                trigger=trigger or "",
                ecp_history=ecp_transcript(messages),
            ),
            model=model or default_model(),
        )
        text = str(raw.get("text") or "").strip()
        if text:
            return text
    except Exception:
        logger.exception("Counterpart reply failed; using fallback")
    return FALLBACK_BY_STANCE.get(stance, FALLBACK_REPLY)
