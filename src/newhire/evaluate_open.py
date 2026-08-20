from __future__ import annotations

import json
from typing import Any, Literal

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from newhire import agent_prompts as prompts
from newhire.evaluate_graph import (
    AgentEvaluationResult,
    PolicyEvaluation,
    ResponseAnalysis,
    TrainingCoach,
    _chat_json,
    default_model,
)
from newhire.policy_excerpts import load_policy_excerpts
from newhire.rubric import (
    CriterionVerdict,
    align_verdicts,
    followed_and_missed,
    format_criteria,
    label_from_verdicts,
)
from newhire.schema import Scenario

load_dotenv()

Speaker = Literal["trainee", "counterpart"]


class ChatTurn(BaseModel):
    speaker: Speaker
    text: str


def format_transcript(messages: list[ChatTurn] | list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in messages:
        speaker = item.speaker if isinstance(item, ChatTurn) else str(item.get("speaker", ""))
        text = item.text if isinstance(item, ChatTurn) else str(item.get("text", ""))
        label = "신입" if speaker == "trainee" else "상대"
        lines.append(f"{label}: {text}")
    return "\n".join(lines) if lines else "(대화 없음)"


def _finalize_open_evaluation(
    scenario: Scenario, raw: dict[str, Any], *, stance: str = "refuse"
) -> tuple[PolicyEvaluation, list[CriterionVerdict]]:
    draft = raw.get("evaluation") if isinstance(raw.get("evaluation"), dict) else raw
    if not isinstance(draft, dict):
        draft = {}
    verdicts = align_verdicts(
        scenario.required_actions,
        scenario.prohibited_actions,
        list(draft.get("verdicts") or []),
    )
    followed, missed = followed_and_missed(verdicts)
    evaluation = PolicyEvaluation(
        label=label_from_verdicts(verdicts, stance=stance),
        policy_grounds=[str(x) for x in (draft.get("policy_grounds") or [])],
        followed=followed,
        missed=missed,
        rationale=str(draft.get("rationale") or ""),
    )
    return evaluation, verdicts


def evaluate_open_response(
    scenario: Scenario,
    messages: list[ChatTurn] | list[dict[str, Any]],
    *,
    stance: str = "refuse",
    client: OpenAI | None = None,
    model: str | None = None,
) -> AgentEvaluationResult:
    openai_client = client or OpenAI()
    used_model = model or default_model()
    raw = _chat_json(
        openai_client,
        system=prompts.OPEN_EVAL_SYSTEM,
        user=prompts.OPEN_EVAL_USER.format(
            scenario=scenario.scenario,
            question=scenario.question,
            transcript=format_transcript(messages),
            policy_ref=json.dumps(scenario.policy_ref.model_dump(), ensure_ascii=False),
            policy_excerpts=load_policy_excerpts(scenario.policy_ref),
            criteria=format_criteria(scenario),
        ),
        model=used_model,
    )
    try:
        analysis_raw = raw.get("analysis") if isinstance(raw.get("analysis"), dict) else {}
        coach_raw = raw.get("coach") if isinstance(raw.get("coach"), dict) else {}
        analysis = ResponseAnalysis.model_validate(
            {
                "intent": analysis_raw.get("intent") or "",
                "actions_taken": analysis_raw.get("actions_taken") or [],
                "risks_or_gaps": analysis_raw.get("risks_or_gaps") or [],
                "summary": analysis_raw.get("summary") or "",
            }
        )
        evaluation, verdicts = _finalize_open_evaluation(scenario, raw, stance=stance)
        coach = TrainingCoach.model_validate(
            {
                "coach_message": coach_raw.get("coach_message") or "",
                "required_actions": coach_raw.get("required_actions") or [],
                "prohibited_actions": coach_raw.get("prohibited_actions") or [],
                "next_tip": coach_raw.get("next_tip") or "",
            }
        )
        return AgentEvaluationResult(
            analysis=analysis,
            evaluation=evaluation,
            coach=coach,
            verdicts=verdicts,
        )
    except ValidationError as exc:
        raise RuntimeError("Open-response evaluation returned invalid output") from exc
