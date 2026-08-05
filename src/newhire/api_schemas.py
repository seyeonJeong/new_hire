from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PublicOrganization(BaseModel):
    name: str
    department: str


class PublicChoice(BaseModel):
    id: Literal["A", "B", "C"]
    text: str


class ScenarioNextResponse(BaseModel):
    scenario_id: str
    organization: PublicOrganization
    topic: str
    subtopic: str
    difficulty: str
    scenario: str
    question: str
    choices: list[PublicChoice]
    quiz_index: int
    quiz_total: int


class QuizDoneResponse(BaseModel):
    done: Literal[True] = True
    quiz_total: int
    message: str = "퀴즈가 끝났습니다."


class QuizStartResponse(BaseModel):
    quiz_total: int
    scenarios: list[ScenarioNextResponse]


class SubmitRequest(BaseModel):
    choice_id: Literal["A", "B", "C"]


class Feedback(BaseModel):
    selected: str
    correct: str
    required_actions: list[str]
    prohibited_actions: list[str]
    next_tip: str | None = None
    policy_grounds: list[str] = Field(default_factory=list)
    followed: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)
    analysis_summary: str | None = None
    source: Literal["agent", "static"] = "static"


class SubmitResponse(BaseModel):
    scenario_id: str
    choice_id: Literal["A", "B", "C"]
    is_correct: bool
    correct_choice_id: Literal["A", "B", "C"]
    selected_label: Literal["unsafe", "partial", "correct"]
    feedback: Feedback
    evaluation_id: str | None = None
    agent_label: Literal["unsafe", "partial", "correct"] | None = None
    quiz_index: int | None = None
    quiz_total: int | None = None


class EvaluationStatusResponse(BaseModel):
    evaluation_id: str
    scenario_id: str
    choice_id: Literal["A", "B", "C"]
    status: Literal["pending", "running", "done", "error"]
    agent_label: Literal["unsafe", "partial", "correct"] | None = None
    feedback: Feedback | None = None
    error: str | None = None
