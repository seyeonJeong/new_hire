from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from newhire.api_schemas import (
    EvaluationStatusResponse,
    Feedback,
    PublicChoice,
    PublicOrganization,
    QuizDoneResponse,
    QuizStartResponse,
    ScenarioNextResponse,
    SubmitRequest,
    SubmitResponse,
)
from newhire.eval_jobs import EvaluationJobStore, retry_agent_evaluation, start_agent_evaluation
from newhire.schema import ChoiceLabel, Scenario
from newhire.store import ScenarioStore

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_SCENARIO_FILE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "oo_soft"
    / "generated"
    / "batch_current.repaired.jsonl"
)


def _scenario_file() -> Path:
    override = os.getenv("NEWHIRE_SCENARIO_FILE")
    return Path(override).resolve() if override else DEFAULT_SCENARIO_FILE


def _quiz_limit() -> int:
    return max(1, int(os.getenv("NEWHIRE_QUIZ_LIMIT", "5")))


def _agent_eval_enabled() -> bool:
    flag = os.getenv("NEWHIRE_AGENT_EVAL", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def create_app(store: ScenarioStore | None = None) -> FastAPI:
    quiz_total = _quiz_limit()
    scenario_store = store or ScenarioStore(_scenario_file(), limit=quiz_total)
    jobs = EvaluationJobStore()

    app = FastAPI(title="Newhire API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.store = scenario_store
    app.state.jobs = jobs
    app.state.quiz_total = quiz_total

    @app.get("/health")
    def health() -> dict[str, str | int | bool]:
        return {
            "status": "ok",
            "scenarios": scenario_store.count,
            "quiz_total": quiz_total,
            "agent_eval": _agent_eval_enabled(),
        }

    @app.post("/quiz/reset")
    def reset_quiz() -> dict[str, int | str]:
        scenario_store.reset()
        return {"status": "ok", "quiz_total": quiz_total}

    @app.post("/quiz/start", response_model=QuizStartResponse)
    def start_quiz() -> QuizStartResponse:
        scenario_store.reset()
        pack = scenario_store.quiz_scenarios()
        scenarios = [
            to_public(s, quiz_index=i + 1, quiz_total=len(pack))
            for i, s in enumerate(pack)
        ]
        scenario_store.exhaust()
        return QuizStartResponse(quiz_total=len(pack), scenarios=scenarios)

    @app.get("/scenarios/next", response_model=None)
    def next_scenario() -> ScenarioNextResponse | QuizDoneResponse:
        scenario = scenario_store.next()
        if scenario is None:
            return QuizDoneResponse(quiz_total=quiz_total)
        return to_public(scenario, quiz_index=scenario_store.cursor, quiz_total=quiz_total)

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
        static_feedback = {
            ChoiceLabel.correct.value: scenario.rationale.correct,
            ChoiceLabel.unsafe.value: scenario.rationale.unsafe,
            ChoiceLabel.partial.value: scenario.rationale.partial,
        }[selected_label]

        feedback = Feedback(
            selected=static_feedback,
            correct=scenario.rationale.correct,
            required_actions=scenario.required_actions,
            prohibited_actions=scenario.prohibited_actions,
            source="static",
        )

        evaluation_id: str | None = None
        if _agent_eval_enabled():
            job = jobs.create(scenario.scenario_id, body.choice_id)
            evaluation_id = job.evaluation_id
            start_agent_evaluation(jobs, job, scenario, body.choice_id)

        return SubmitResponse(
            scenario_id=scenario.scenario_id,
            choice_id=body.choice_id,
            is_correct=is_correct,
            correct_choice_id=scenario.correct_choice_id,
            selected_label=selected_label,  # type: ignore[arg-type]
            feedback=feedback,
            evaluation_id=evaluation_id,
            quiz_total=quiz_total,
        )

    @app.get("/evaluations/{evaluation_id}", response_model=EvaluationStatusResponse)
    def evaluation_status(evaluation_id: str) -> EvaluationStatusResponse:
        job = jobs.get(evaluation_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        return EvaluationStatusResponse(
            evaluation_id=job.evaluation_id,
            scenario_id=job.scenario_id,
            choice_id=job.choice_id,  # type: ignore[arg-type]
            status=job.status,
            agent_label=job.agent_label,
            feedback=job.feedback,
            error=job.error,
        )

    @app.post("/evaluations/{evaluation_id}/retry", response_model=EvaluationStatusResponse)
    def retry_evaluation(evaluation_id: str) -> EvaluationStatusResponse:
        job = jobs.get(evaluation_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        if job.status == "running":
            raise HTTPException(status_code=409, detail="Evaluation already running")
        scenario = scenario_store.get(job.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Scenario not found")
        retry_agent_evaluation(jobs, job, scenario)
        refreshed = jobs.get(evaluation_id)
        assert refreshed is not None
        return EvaluationStatusResponse(
            evaluation_id=refreshed.evaluation_id,
            scenario_id=refreshed.scenario_id,
            choice_id=refreshed.choice_id,  # type: ignore[arg-type]
            status=refreshed.status,
            agent_label=refreshed.agent_label,
            feedback=refreshed.feedback,
            error=refreshed.error,
        )

    return app


def to_public(
    scenario: Scenario,
    *,
    quiz_index: int,
    quiz_total: int,
) -> ScenarioNextResponse:
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
        quiz_index=quiz_index,
        quiz_total=quiz_total,
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
