from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from newhire.api_schemas import (
    EvaluationStatusResponse,
    Feedback,
    OpenChatMessage,
    OpenEvaluateResponse,
    OpenMessageRequest,
    OpenSessionResponse,
    OpenStartRequest,
    PublicChoice,
    PublicOrganization,
    QuizDoneResponse,
    QuizStartResponse,
    ScenarioNextResponse,
    SubmitRequest,
    SubmitResponse,
)
from newhire.eval_jobs import (
    EvaluationJob,
    EvaluationJobStore,
    retry_agent_evaluation,
    start_agent_evaluation,
    start_open_evaluation,
)
from newhire.open_sessions import (
    MAX_TRAINEE_TURNS,
    MIN_TRAINEE_TURNS,
    OpenSession,
    OpenSessionStore,
    trainee_turn_count,
)
from newhire.counterpart import generate_counterpart_reply
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


def _org_dir(scenario_file: Path) -> Path:
    if scenario_file.parent.name == "generated":
        return scenario_file.parent.parent
    return scenario_file.parent


def load_subtopic_cues(org_dir: Path) -> dict[str, dict[str, str]]:
    path = org_dir / "subtopics.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    cues: dict[str, dict[str, str]] = {}
    for item in data.get("subtopics", []):
        sid = str(item.get("id") or "").strip()
        if not sid:
            continue
        cues[sid] = {
            "trigger": str(item.get("trigger") or "").strip(),
            "conflict": str(item.get("conflict") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "expected_stance": str(item.get("expected_stance") or "refuse").strip(),
        }
    return cues


def trigger_as_speech(trigger: str) -> str:
    """Turn a catalog trigger (often a 3rd-person note) into a counterpart line."""
    text = trigger.strip().rstrip(". ")
    if not text:
        return "지금 당장 처리해 주세요. 나중에 맞춰도 되니까 오늘은 이대로 진행해 주시죠."
    if text.endswith(("요", "요?", "다", "까?", "세요", "죠", "죠?")):
        return text
    if text.endswith("함"):
        reason = text[:-1] + "한 건이라서요"
    elif text.endswith("임"):
        reason = text[:-1] + "인 상황이라서요"
    else:
        reason = text + "라서요"
    return (
        f"제가 급해서 연락드린 거예요. {reason}. "
        f"절차는 나중에 맞추더라도, 오늘은 그냥 진행해 주세요."
    )


def opening_for(scenario: Scenario, cues: dict[str, dict[str, str]]) -> str:
    trigger = (cues.get(scenario.subtopic) or {}).get("trigger", "")
    return trigger_as_speech(trigger)


def to_eval_status(job: EvaluationJob) -> EvaluationStatusResponse:
    return EvaluationStatusResponse(
        evaluation_id=job.evaluation_id,
        scenario_id=job.scenario_id,
        choice_id=job.choice_id,
        kind=job.kind,
        status=job.status,
        agent_label=job.agent_label,
        feedback=job.feedback,
        error=job.error,
    )


def to_open_session(
    session: OpenSession,
    scenario: Scenario,
    opening: str,
) -> OpenSessionResponse:
    return OpenSessionResponse(
        session_id=session.session_id,
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
        opening=opening,
        messages=[OpenChatMessage.model_validate(item) for item in session.messages],
        trainee_turns=trainee_turn_count(session.messages),
        max_trainee_turns=MAX_TRAINEE_TURNS,
        evaluation_id=session.evaluation_id,
    )


def create_app(store: ScenarioStore | None = None) -> FastAPI:
    quiz_total = _quiz_limit()
    scenario_file = _scenario_file()
    scenario_store = store or ScenarioStore(scenario_file, limit=quiz_total)
    jobs = EvaluationJobStore()
    open_sessions = OpenSessionStore()
    cues = load_subtopic_cues(_org_dir(scenario_file))

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
    app.state.open_sessions = open_sessions
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
        return to_eval_status(job)

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
        return to_eval_status(refreshed)

    @app.post("/open-response/start", response_model=OpenSessionResponse)
    def start_open_response(body: OpenStartRequest | None = None) -> OpenSessionResponse:
        payload = body or OpenStartRequest()
        scenario = scenario_store.pick_open(set(payload.exclude_ids))
        opening = opening_for(scenario, cues)
        session = open_sessions.create(scenario.scenario_id, opening)
        return to_open_session(session, scenario, opening)

    @app.post("/open-response/{session_id}/messages", response_model=OpenSessionResponse)
    def append_open_message(session_id: str, body: OpenMessageRequest) -> OpenSessionResponse:
        session = open_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Open session not found")
        if session.evaluation_id:
            raise HTTPException(status_code=409, detail="이미 평가가 시작되었습니다")
        if trainee_turn_count(session.messages) >= MAX_TRAINEE_TURNS:
            raise HTTPException(status_code=400, detail="더 이상 응답할 수 없습니다")
        text = body.text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="메시지를 입력하세요")
        updated = open_sessions.append_trainee(session_id, text)
        assert updated is not None
        scenario = scenario_store.get(updated.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Scenario not found")
        cue = cues.get(scenario.subtopic) or {}
        reply = generate_counterpart_reply(
            scenario,
            updated.messages,
            conflict=cue.get("conflict", ""),
            trigger=cue.get("trigger", ""),
            stance=cue.get("expected_stance", "refuse"),
        )
        updated = open_sessions.append_counterpart(session_id, reply) or updated
        return to_open_session(updated, scenario, opening_for(scenario, cues))

    @app.post("/open-response/{session_id}/evaluate", response_model=OpenEvaluateResponse)
    def evaluate_open_session(session_id: str) -> OpenEvaluateResponse:
        session = open_sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Open session not found")
        if trainee_turn_count(session.messages) < MIN_TRAINEE_TURNS:
            raise HTTPException(status_code=400, detail="먼저 응답을 작성하세요")
        if session.evaluation_id:
            job = jobs.get(session.evaluation_id)
            if job is None:
                raise HTTPException(status_code=404, detail="Evaluation not found")
            return OpenEvaluateResponse(
                session_id=session.session_id,
                evaluation_id=job.evaluation_id,
                status=job.status,
            )
        scenario = scenario_store.get(session.scenario_id)
        if scenario is None:
            raise HTTPException(status_code=404, detail="Scenario not found")
        job = jobs.create(
            scenario.scenario_id,
            "",
            kind="open",
            messages=session.messages,
        )
        open_sessions.set_evaluation(session_id, job.evaluation_id)
        cue = cues.get(scenario.subtopic) or {}
        start_open_evaluation(
            jobs, job, scenario, stance=cue.get("expected_stance", "refuse")
        )
        return OpenEvaluateResponse(
            session_id=session.session_id,
            evaluation_id=job.evaluation_id,
            status=job.status,
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
