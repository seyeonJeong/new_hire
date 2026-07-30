from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from newhire.api_schemas import (
    Feedback,
    PublicChoice,
    PublicOrganization,
    ScenarioNextResponse,
    SubmitRequest,
    SubmitResponse,
)
from newhire.schema import ChoiceLabel, Scenario
from newhire.store import ScenarioStore

load_dotenv()

DEFAULT_SCENARIO_FILE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "nova_soft"
    / "generated"
    / "batch_20260728T014723Z.repaired.jsonl"
)


def _scenario_file() -> Path:
    override = os.getenv("NEWHIRE_SCENARIO_FILE")
    return Path(override).resolve() if override else DEFAULT_SCENARIO_FILE


def create_app(store: ScenarioStore | None = None) -> FastAPI:
    scenario_store = store or ScenarioStore(_scenario_file())

    app = FastAPI(title="Newhire API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = scenario_store

    @app.get("/health")
    def health() -> dict[str, str | int]:
        return {"status": "ok", "scenarios": scenario_store.count}

    @app.get("/scenarios/next", response_model=ScenarioNextResponse)
    def next_scenario() -> ScenarioNextResponse:
        scenario = scenario_store.next()
        return to_public(scenario)

    @app.post("/scenarios/{scenario_id}/submit", response_model=SubmitResponse)
    def submit(scenario_id: str, body: SubmitRequest) -> SubmitResponse:
        scenario = scenario_store.get(scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Scenario not found")

        selected = next((c for c in scenario.choices if c.id == body.choice_id), None)
        if selected is None:
            raise HTTPException(status_code=400, detail="Invalid choice_id")

        is_correct = body.choice_id == scenario.correct_choice_id
        selected_label = selected.label.value
        selected_feedback = {
            ChoiceLabel.correct.value: scenario.rationale.correct,
            ChoiceLabel.unsafe.value: scenario.rationale.unsafe,
            ChoiceLabel.partial.value: scenario.rationale.partial,
        }[selected_label]

        return SubmitResponse(
            scenario_id=scenario.scenario_id,
            choice_id=body.choice_id,
            is_correct=is_correct,
            correct_choice_id=scenario.correct_choice_id,
            selected_label=selected_label,  # type: ignore[arg-type]
            feedback=Feedback(
                selected=selected_feedback,
                correct=scenario.rationale.correct,
                required_actions=scenario.required_actions,
                prohibited_actions=scenario.prohibited_actions,
            ),
        )

    return app


def to_public(scenario: Scenario) -> ScenarioNextResponse:
    return ScenarioNextResponse(
        scenario_id=scenario.scenario_id,
        organization=PublicOrganization(
            name=scenario.organization.name,
            department=scenario.organization.department,
        ),
        topic=scenario.topic,
        subtopic=scenario.subtopic,
        difficulty=scenario.difficulty,
        scenario=scenario.scenario,
        question=scenario.question,
        choices=[PublicChoice(id=c.id, text=c.text) for c in scenario.choices],
    )


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run(
        "newhire.api:app",
        host=os.getenv("NEWHIRE_API_HOST", "127.0.0.1"),
        port=int(os.getenv("NEWHIRE_API_PORT", "8000")),
        reload=os.getenv("NEWHIRE_API_RELOAD", "1") == "1",
    )


if __name__ == "__main__":
    run()