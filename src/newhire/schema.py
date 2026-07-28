from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ChoiceLabel(str, Enum):
    unsafe = "unsafe"
    partial = "partial"
    correct = "correct"


class Competency(str, Enum):
    risk_awareness = "risk_awareness"
    policy_application = "policy_application"
    escalation = "escalation"
    communication = "communication"


class Organization(BaseModel):
    id: str
    name: str
    industry: str
    department: str


class Choice(BaseModel):
    id: Literal["A", "B", "C"]
    text: str = Field(min_length=1)
    label: ChoiceLabel


class Rationale(BaseModel):
    correct: str = Field(min_length=1)
    unsafe: str = Field(min_length=1)
    partial: str = Field(min_length=1)


class PolicyRef(BaseModel):
    policy_id: str
    sections: list[str] = Field(min_length=1)


class Meta(BaseModel):
    version: str = "v0.1"
    status: Literal["draft", "reviewed", "gold"] = "draft"


class Scenario(BaseModel):
    scenario_id: str
    organization: Organization
    target_role: str
    topic: str
    subtopic: str = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]
    primary_competency: Competency
    scenario: str = Field(min_length=1)
    question: str = Field(min_length=1)
    choices: list[Choice] = Field(min_length=3, max_length=3)
    correct_choice_id: Literal["A", "B", "C"]
    rationale: Rationale
    required_actions: list[str] = Field(min_length=1)
    prohibited_actions: list[str] = Field(min_length=1)
    policy_ref: PolicyRef
    meta: Meta = Field(default_factory=Meta)

    @field_validator("choices")
    @classmethod
    def unique_choice_ids(cls, choices: list[Choice]) -> list[Choice]:
        ids = [c.id for c in choices]
        if sorted(ids) != ["A", "B", "C"]:
            raise ValueError("choices must have ids A, B, C exactly once each")
        return choices

    @model_validator(mode="after")
    def check_labels_and_correct(self) -> Scenario:
        labels = {c.label for c in self.choices}
        expected = {ChoiceLabel.unsafe, ChoiceLabel.partial, ChoiceLabel.correct}
        if labels != expected:
            raise ValueError(
                "choices must include exactly one of each label: unsafe, partial, correct"
            )
        correct = next(c for c in self.choices if c.label == ChoiceLabel.correct)
        if correct.id != self.correct_choice_id:
            raise ValueError(
                f"correct_choice_id={self.correct_choice_id} must match the choice "
                f"with label=correct (id={correct.id})"
            )
        return self


def assert_topic_policy_match(
    scenario: Scenario,
    *,
    expected_topic: str,
    expected_policy_id: str,
    expected_subtopic: str | None = None,
) -> None:
    if scenario.topic != expected_topic:
        raise ValueError(
            f"topic mismatch: got {scenario.topic!r}, expected {expected_topic!r}"
        )
    if scenario.policy_ref.policy_id != expected_policy_id:
        raise ValueError(
            f"policy_id mismatch: got {scenario.policy_ref.policy_id!r}, "
            f"expected {expected_policy_id!r}"
        )
    if expected_subtopic is not None and scenario.subtopic != expected_subtopic:
        raise ValueError(
            f"subtopic mismatch: got {scenario.subtopic!r}, "
            f"expected {expected_subtopic!r}"
        )
