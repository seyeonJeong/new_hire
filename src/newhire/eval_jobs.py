from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from newhire.api_schemas import Feedback
from newhire.schema import Scenario

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "running", "done", "error"]


@dataclass
class EvaluationJob:
    evaluation_id: str
    scenario_id: str
    choice_id: str
    status: JobStatus = "pending"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    error: str | None = None
    agent_label: Literal["unsafe", "partial", "correct"] | None = None
    feedback: Feedback | None = None


class EvaluationJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, EvaluationJob] = {}
        self._lock = threading.Lock()

    def create(self, scenario_id: str, choice_id: str) -> EvaluationJob:
        job = EvaluationJob(
            evaluation_id=str(uuid.uuid4()),
            scenario_id=scenario_id,
            choice_id=choice_id,
        )
        with self._lock:
            self._jobs[job.evaluation_id] = job
        return job

    def get(self, evaluation_id: str) -> EvaluationJob | None:
        with self._lock:
            return self._jobs.get(evaluation_id)

    def update(self, evaluation_id: str, **kwargs: Any) -> None:
        with self._lock:
            job = self._jobs.get(evaluation_id)
            if job is None:
                return
            for key, value in kwargs.items():
                setattr(job, key, value)


def start_agent_evaluation(
    jobs: EvaluationJobStore,
    job: EvaluationJob,
    scenario: Scenario,
    choice_id: Literal["A", "B", "C"],
) -> None:
    def _run() -> None:
        jobs.update(job.evaluation_id, status="running")
        try:
            from newhire.evaluate_graph import evaluate_choice

            agent = evaluate_choice(scenario, choice_id)
            feedback = Feedback(
                selected=agent.coach.coach_message,
                correct=agent.evaluation.rationale,
                required_actions=agent.coach.required_actions,
                prohibited_actions=agent.coach.prohibited_actions,
                next_tip=agent.coach.next_tip,
                policy_grounds=agent.evaluation.policy_grounds,
                followed=agent.evaluation.followed,
                missed=agent.evaluation.missed,
                analysis_summary=agent.analysis.summary,
                source="agent",
            )
            jobs.update(
                job.evaluation_id,
                status="done",
                agent_label=agent.evaluation.label,
                feedback=feedback,
            )
        except Exception as exc:
            logger.exception("Async agent evaluation failed: %s", job.evaluation_id)
            jobs.update(
                job.evaluation_id,
                status="error",
                error=str(exc) or "agent evaluation failed",
            )

    threading.Thread(target=_run, daemon=True, name=f"eval-{job.evaluation_id[:8]}").start()


def retry_agent_evaluation(
    jobs: EvaluationJobStore,
    job: EvaluationJob,
    scenario: Scenario,
) -> EvaluationJob:
    jobs.update(
        job.evaluation_id,
        status="pending",
        error=None,
        agent_label=None,
        feedback=None,
    )
    start_agent_evaluation(jobs, job, scenario, job.choice_id)  # type: ignore[arg-type]
    return job
