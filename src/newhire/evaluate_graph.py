from __future__ import annotations

import json
import os
from typing import Any, Literal, TypedDict

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from newhire import agent_prompts as prompts
from newhire.policy_excerpts import load_policy_excerpts
from newhire.schema import Scenario

load_dotenv()


class ResponseAnalysis(BaseModel):
    intent: str
    actions_taken: list[str] = Field(default_factory=list)
    risks_or_gaps: list[str] = Field(default_factory=list)
    summary: str


class PolicyEvaluation(BaseModel):
    label: Literal["unsafe", "partial", "correct"]
    policy_grounds: list[str] = Field(default_factory=list)
    followed: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)
    rationale: str


class TrainingCoach(BaseModel):
    coach_message: str
    required_actions: list[str] = Field(default_factory=list)
    prohibited_actions: list[str] = Field(default_factory=list)
    next_tip: str


class AgentEvaluationResult(BaseModel):
    analysis: ResponseAnalysis
    evaluation: PolicyEvaluation
    coach: TrainingCoach


class EvalState(TypedDict, total=False):
    scenario_text: str
    question: str
    choices_text: str
    choice_id: str
    choice_text: str
    policy_ref_text: str
    policy_excerpts: str
    analysis: dict[str, Any]
    evaluation: dict[str, Any]
    coach: dict[str, Any]


def default_model() -> str:
    return os.getenv("LLM_MODEL", "gpt-5-mini")


def _chat_json(
    client: OpenAI,
    *,
    system: str,
    user: str,
    model: str,
) -> dict[str, Any]:
    response = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = response.choices[0].message.content or "{}"
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("LLM returned non-object JSON")
    return data


def _format_choices(scenario: Scenario) -> str:
    return "\n".join(f"- {c.id}: {c.text}" for c in scenario.choices)


def build_graph(client: OpenAI, model: str):
    from langgraph.graph import END, START, StateGraph

    def analyze(state: EvalState) -> dict[str, Any]:
        raw = _chat_json(
            client,
            system=prompts.RESPONSE_ANALYSIS_SYSTEM,
            user=prompts.RESPONSE_ANALYSIS_USER.format(
                scenario=state["scenario_text"],
                question=state["question"],
                choices=state["choices_text"],
                choice_id=state["choice_id"],
                choice_text=state["choice_text"],
            ),
            model=model,
        )
        parsed = ResponseAnalysis.model_validate(raw)
        return {"analysis": parsed.model_dump()}

    def evaluate(state: EvalState) -> dict[str, Any]:
        raw = _chat_json(
            client,
            system=prompts.POLICY_EVALUATION_SYSTEM,
            user=prompts.POLICY_EVALUATION_USER.format(
                analysis_json=json.dumps(state["analysis"], ensure_ascii=False, indent=2),
                policy_ref=state["policy_ref_text"],
                policy_excerpts=state["policy_excerpts"],
            ),
            model=model,
        )
        parsed = PolicyEvaluation.model_validate(raw)
        return {"evaluation": parsed.model_dump()}

    def coach(state: EvalState) -> dict[str, Any]:
        raw = _chat_json(
            client,
            system=prompts.TRAINING_COACH_SYSTEM,
            user=prompts.TRAINING_COACH_USER.format(
                evaluation_json=json.dumps(
                    state["evaluation"], ensure_ascii=False, indent=2
                ),
                choice_text=state["choice_text"],
            ),
            model=model,
        )
        parsed = TrainingCoach.model_validate(raw)
        return {"coach": parsed.model_dump()}

    graph = StateGraph(EvalState)
    graph.add_node("response_analysis", analyze)
    graph.add_node("policy_evaluation", evaluate)
    graph.add_node("training_coach", coach)
    graph.add_edge(START, "response_analysis")
    graph.add_edge("response_analysis", "policy_evaluation")
    graph.add_edge("policy_evaluation", "training_coach")
    graph.add_edge("training_coach", END)
    return graph.compile()


def _agent_mode() -> str:
    # graph = 3 sequential LangGraph nodes (default).
    # fast = 1 LLM call covering analysis → evaluation → coach.
    return os.getenv("NEWHIRE_AGENT_MODE", "graph").strip().lower()


def _prepare_inputs(
    scenario: Scenario,
    choice_id: Literal["A", "B", "C"],
) -> EvalState:
    selected = next((c for c in scenario.choices if c.id == choice_id), None)
    if selected is None:
        raise ValueError(f"Invalid choice_id={choice_id!r}")
    return {
        "scenario_text": scenario.scenario,
        "question": scenario.question,
        "choices_text": _format_choices(scenario),
        "choice_id": choice_id,
        "choice_text": selected.text,
        "policy_ref_text": json.dumps(
            scenario.policy_ref.model_dump(), ensure_ascii=False
        ),
        "policy_excerpts": load_policy_excerpts(scenario.policy_ref),
    }


def evaluate_choice_fast(
    scenario: Scenario,
    choice_id: Literal["A", "B", "C"],
    *,
    client: OpenAI | None = None,
    model: str | None = None,
) -> AgentEvaluationResult:
    state = _prepare_inputs(scenario, choice_id)
    openai_client = client or OpenAI()
    used_model = model or default_model()
    raw = _chat_json(
        openai_client,
        system=prompts.FAST_EVAL_SYSTEM,
        user=prompts.FAST_EVAL_USER.format(
            scenario=state["scenario_text"],
            question=state["question"],
            choices=state["choices_text"],
            choice_id=state["choice_id"],
            choice_text=state["choice_text"],
            policy_ref=state["policy_ref_text"],
            policy_excerpts=state["policy_excerpts"],
        ),
        model=used_model,
    )
    try:
        return AgentEvaluationResult.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError("Fast agent evaluation returned invalid output") from exc


def evaluate_choice_graph(
    scenario: Scenario,
    choice_id: Literal["A", "B", "C"],
    *,
    client: OpenAI | None = None,
    model: str | None = None,
) -> AgentEvaluationResult:
    state = _prepare_inputs(scenario, choice_id)
    openai_client = client or OpenAI()
    used_model = model or default_model()
    final = build_graph(openai_client, used_model).invoke(state)

    try:
        return AgentEvaluationResult(
            analysis=ResponseAnalysis.model_validate(final["analysis"]),
            evaluation=PolicyEvaluation.model_validate(final["evaluation"]),
            coach=TrainingCoach.model_validate(final["coach"]),
        )
    except (KeyError, ValidationError) as exc:
        raise RuntimeError("Agent evaluation graph returned incomplete output") from exc


def evaluate_choice(
    scenario: Scenario,
    choice_id: Literal["A", "B", "C"],
    *,
    client: OpenAI | None = None,
    model: str | None = None,
) -> AgentEvaluationResult:
    if _agent_mode() in {"fast", "one", "1"}:
        return evaluate_choice_fast(scenario, choice_id, client=client, model=model)
    return evaluate_choice_graph(scenario, choice_id, client=client, model=model)
