from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


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


class SubmitRequest(BaseModel):
    choice_id: Literal["A", "B", "C"]


class Feedback(BaseModel):
    selected: str
    correct: str
    required_actions: list[str]
    prohibited_actions: list[str]


class SubmitResponse(BaseModel):
    scenario_id: str
    choice_id: Literal["A", "B", "C"]
    is_correct: bool
    correct_choice_id: Literal["A", "B", "C"]
    selected_label: Literal["unsafe", "partial", "correct"]
    feedback: Feedback
