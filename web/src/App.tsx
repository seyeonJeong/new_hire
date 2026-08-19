import { useEffect, useRef, useState } from 'react'
import {
  fetchEvaluation,
  retryEvaluation,
  startQuizPack,
  submitChoice,
  type AttemptRecord,
  type EvaluationStatus,
  type ScenarioNext,
  type SubmitResult,
} from './api'
import './index.css'

type Phase = 'loading' | 'ready' | 'submitting' | 'feedback' | 'summary' | 'error'

const TOPIC_LABEL: Record<string, string> = {
  data_sharing: '자료 공유',
  expense_approval: '비용 승인',
  reporting: '보고',
}

function normalizePack(scenarios: ScenarioNext[]): ScenarioNext[] {
  return scenarios.map((item, index) => ({
    ...item,
    quiz_index: index + 1,
    quiz_total: scenarios.length,
  }))
}

function isEvalTerminal(status: EvaluationStatus['status'] | undefined): boolean {
  return status === 'done' || status === 'error'
}

/** AI 결과는 앞 문제부터 큐 순서(1→5)로만 공개 */
function canRevealAgent(
  attempts: AttemptRecord[],
  index: number,
  evalStatuses: Record<string, EvaluationStatus>,
): boolean {
  for (let i = 0; i < index; i += 1) {
    const id = attempts[i]?.result.evaluation_id
    if (!id) continue
    if (!isEvalTerminal(evalStatuses[id]?.status)) return false
  }
  return true
}

function agentProgress(
  attempts: AttemptRecord[],
  evalStatuses: Record<string, EvaluationStatus>,
): { done: number; total: number } {
  const ids = attempts
    .map((a) => a.result.evaluation_id)
    .filter((id): id is string => Boolean(id))
  const done = ids.filter((id) => isEvalTerminal(evalStatuses[id]?.status)).length
  return { done, total: ids.length }
}

function statusLabel(
  reveal: boolean,
  agent: EvaluationStatus | null | undefined,
): { text: string; kind: 'wait' | 'run' | 'ok' | 'fail' | 'none' } {
  if (!agent) return { text: 'AI 없음', kind: 'none' }
  if (!reveal) return { text: '대기', kind: 'wait' }
  if (agent.status === 'done') return { text: '완료', kind: 'ok' }
  if (agent.status === 'error') return { text: '실패', kind: 'fail' }
  if (agent.status === 'running') return { text: '분석 중', kind: 'run' }
  return { text: '대기', kind: 'wait' }
}

export default function App() {
  const [phase, setPhase] = useState<Phase>('loading')
  const [pack, setPack] = useState<ScenarioNext[]>([])
  const [packIndex, setPackIndex] = useState(0)
  const [scenario, setScenario] = useState<ScenarioNext | null>(null)
  const [selected, setSelected] = useState<'A' | 'B' | 'C' | null>(null)
  const [result, setResult] = useState<SubmitResult | null>(null)
  const [attempts, setAttempts] = useState<AttemptRecord[]>([])
  const [evalStatuses, setEvalStatuses] = useState<Record<string, EvaluationStatus>>({})
  const [error, setError] = useState<string | null>(null)
  const [retryingId, setRetryingId] = useState<string | null>(null)
  const [animKey, setAnimKey] = useState(0)
  const bootIdRef = useRef(0)

  function showAt(list: ScenarioNext[], index: number) {
    const next = list[index]
    if (!next) {
      setPhase('summary')
      return
    }
    setPack(list)
    setPackIndex(index)
    setScenario(next)
    setSelected(null)
    setResult(null)
    setError(null)
    setAnimKey((k) => k + 1)
    setPhase('ready')
  }

  async function bootQuiz() {
    const bootId = ++bootIdRef.current
    setAttempts([])
    setEvalStatuses({})
    setPack([])
    setPackIndex(0)
    setScenario(null)
    setResult(null)
    setSelected(null)
    setError(null)
    setRetryingId(null)
    setPhase('loading')
    try {
      const started = await startQuizPack()
      if (bootId !== bootIdRef.current) return
      if (!started.scenarios.length) {
        throw new Error('퀴즈 문제가 없습니다.')
      }
      const list = normalizePack(started.scenarios)
      showAt(list, 0)
    } catch (err) {
      if (bootId !== bootIdRef.current) return
      setError(err instanceof Error ? err.message : '퀴즈를 시작하지 못했습니다.')
      setPhase('error')
    }
  }

  useEffect(() => {
    void bootQuiz()
  }, [])

  useEffect(() => {
    const ids = attempts
      .map((a) => a.result.evaluation_id)
      .filter((id): id is string => Boolean(id))
    if (ids.length === 0) return

    const pending = ids.filter((id) => !isEvalTerminal(evalStatuses[id]?.status))
    if (pending.length === 0) return

    let cancelled = false

    async function poll() {
      for (const id of pending) {
        try {
          const status = await fetchEvaluation(id)
          if (cancelled) return
          setEvalStatuses((prev) => {
            if (
              prev[id]?.status === status.status &&
              prev[id]?.feedback?.selected === status.feedback?.selected
            ) {
              return prev
            }
            return { ...prev, [id]: status }
          })
        } catch {
          // keep polling
        }
      }
    }

    void poll()
    const timer = window.setInterval(() => {
      void poll()
    }, 2000)

    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [attempts, evalStatuses])

  async function onSubmit() {
    if (!scenario || !selected) return
    setPhase('submitting')
    setError(null)
    try {
      const res = await submitChoice(scenario.scenario_id, selected)
      setResult(res)
      setAttempts((prev) => [...prev, { scenario, result: res }])
      if (res.evaluation_id) {
        setEvalStatuses((prev) => ({
          ...prev,
          [res.evaluation_id!]: {
            evaluation_id: res.evaluation_id!,
            scenario_id: res.scenario_id,
            choice_id: res.choice_id,
            status: 'pending',
          },
        }))
      }
      setPhase('feedback')
    } catch (err) {
      setError(err instanceof Error ? err.message : '제출에 실패했습니다.')
      setPhase('ready')
    }
  }

  async function onRetryAgent(evaluationId: string) {
    setRetryingId(evaluationId)
    try {
      const status = await retryEvaluation(evaluationId)
      setEvalStatuses((prev) => ({ ...prev, [evaluationId]: status }))
    } catch (err) {
      setEvalStatuses((prev) => ({
        ...prev,
        [evaluationId]: {
          ...(prev[evaluationId] as EvaluationStatus),
          status: 'error',
          error: err instanceof Error ? err.message : '다시 시도에 실패했습니다.',
        },
      }))
    } finally {
      setRetryingId(null)
    }
  }

  function goNextOrSummary() {
    const nextIndex = packIndex + 1
    if (nextIndex >= pack.length) {
      setPhase('summary')
      return
    }
    showAt(pack, nextIndex)
  }

  const correctCount = attempts.filter((a) => a.result.is_correct).length
  const progress = agentProgress(attempts, evalStatuses)
  const quizTotal = pack.length || 5
  const quizNumber = packIndex + 1
  const allAgentDone = progress.total > 0 && progress.done === progress.total

  return (
    <div className="page">
      <div className="atmosphere" aria-hidden="true" />
      <header className="brand">
        <p className="brand-mark">Newhire</p>
        <p className="brand-line">신입사원 역량 평가 에이전트</p>
      </header>

      <main className="stage" key={animKey}>
        {phase === 'loading' && <p className="status">문제를 불러오는 중…</p>}

        {phase === 'error' && (
          <div className="status-block">
            <p className="status error-text">{error}</p>
            <button type="button" className="btn primary" onClick={() => void bootQuiz()}>
              다시 시도
            </button>
          </div>
        )}

        {phase === 'summary' && (
          <section className="summary fade-up">
            <p className="feedback-verdict">{quizTotal}문제 완료</p>
            <p className="feedback-body">
              즉시 채점 결과: {correctCount} / {attempts.length} 정답
            </p>
            {progress.total > 0 && (
              <div className="agent-progress">
                <p className="feedback-meta">
                  {allAgentDone
                    ? 'AI 코치 분석이 모두 완료되었습니다'
                    : `AI 코치 분석 ${progress.done} / ${progress.total} 완료`}
                </p>
                <div className="progress-track" aria-hidden="true">
                  <div
                    className="progress-fill"
                    style={{
                      width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            )}

            <div className="summary-list">
              {attempts.map((attempt, index) => {
                const evalId = attempt.result.evaluation_id
                const agent = evalId ? evalStatuses[evalId] : null
                const reveal = canRevealAgent(attempts, index, evalStatuses)
                const badge = statusLabel(reveal, agent)
                const agentDone = reveal && agent?.status === 'done' && agent.feedback
                const agentError = reveal && agent?.status === 'error'
                const agentWaiting =
                  Boolean(evalId) &&
                  (!reveal ||
                    !agent ||
                    agent.status === 'pending' ||
                    agent.status === 'running')

                return (
                  <article key={`${attempt.scenario.scenario_id}-${index}`} className="summary-card">
                    <h3>
                      {index + 1}. {TOPIC_LABEL[attempt.scenario.topic] ?? attempt.scenario.topic}
                      <span className={attempt.result.is_correct ? 'ok' : 'bad'}>
                        {attempt.result.is_correct ? ' 정답' : ' 오답'}
                      </span>
                      <span className={`status-pill is-${badge.kind}`}>{badge.text}</span>
                    </h3>
                    <p className="summary-q">{attempt.scenario.question}</p>

                    {!evalId && <p className="feedback-meta">AI 분석 없음</p>}
                    {agentWaiting && (
                      <p className="feedback-meta">
                        {reveal
                          ? 'AI가 내규를 기준으로 분석하는 중…'
                          : '앞 문제부터 순서대로 분석 결과를 표시합니다'}
                      </p>
                    )}
                    {agentError && (
                      <div className="retry-block">
                        <p className="error-text">AI 분석 실패: {agent?.error ?? 'unknown'}</p>
                        {evalId && (
                          <button
                            type="button"
                            className="btn ghost"
                            disabled={retryingId === evalId}
                            onClick={() => void onRetryAgent(evalId)}
                          >
                            {retryingId === evalId ? '다시 시도 중…' : '분석 다시 시도'}
                          </button>
                        )}
                      </div>
                    )}
                    {agentDone && agent.feedback && (
                      <div className="agent-block">
                        <p className="feedback-source">AI 코치 피드백</p>
                        <p className="feedback-body">{agent.feedback.selected}</p>
                        {agent.feedback.analysis_summary && (
                          <p className="feedback-meta">분석: {agent.feedback.analysis_summary}</p>
                        )}
                        {(agent.feedback.policy_grounds?.length ?? 0) > 0 && (
                          <p className="feedback-meta">
                            근거: {agent.feedback.policy_grounds?.join(' · ')}
                          </p>
                        )}
                        {agent.feedback.next_tip && (
                          <p className="feedback-tip">다음엔: {agent.feedback.next_tip}</p>
                        )}
                      </div>
                    )}
                  </article>
                )
              })}
            </div>

            <button type="button" className="btn primary" onClick={() => void bootQuiz()}>
              다시 풀기
            </button>
          </section>
        )}

        {scenario && (phase === 'ready' || phase === 'submitting' || phase === 'feedback') && (
          <>
            <div className="meta-row">
              <span>
                문제 {quizNumber} / {quizTotal}
              </span>
              <span>회사명 : {scenario.organization.name}</span>
              <span>부서명 : {scenario.organization.department}</span>
              <span>주제 : {TOPIC_LABEL[scenario.topic] ?? scenario.topic}</span>
            </div>

            <section className="situation fade-up">
              <p className="situation-text">{scenario.scenario}</p>
            </section>

            <section className="quiz fade-up delay-1">
              <h2 className="question">{scenario.question}</h2>
              <div className="choices" role="radiogroup" aria-label="선택지">
                {scenario.choices.map((choice) => {
                  const isSelected = selected === choice.id
                  const showResult = phase === 'feedback' && result
                  const isCorrectChoice =
                    showResult && choice.id === result.correct_choice_id
                  const isWrongSelected =
                    showResult && isSelected && !result.is_correct

                  return (
                    <button
                      key={choice.id}
                      type="button"
                      role="radio"
                      aria-checked={isSelected}
                      className={[
                        'choice',
                        isSelected ? 'selected' : '',
                        isCorrectChoice ? 'correct' : '',
                        isWrongSelected ? 'wrong' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      disabled={phase === 'submitting' || phase === 'feedback'}
                      onClick={() => setSelected(choice.id)}
                    >
                      <span className="choice-id">{choice.id}</span>
                      <span className="choice-text">{choice.text}</span>
                    </button>
                  )
                })}
              </div>

              {phase !== 'feedback' && (
                <button
                  type="button"
                  className="btn primary submit"
                  disabled={!selected || phase === 'submitting'}
                  onClick={() => void onSubmit()}
                >
                  {phase === 'submitting' ? '채점 중…' : '제출하기'}
                </button>
              )}
            </section>

            {phase === 'feedback' && result && (
              <section
                className={[
                  'feedback fade-up delay-2',
                  result.is_correct ? 'is-correct' : 'is-wrong',
                ].join(' ')}
              >
                <p className="feedback-verdict">
                  {result.is_correct ? '정답입니다' : '다시 생각해보세요'}
                </p>
                <p className="feedback-body">{result.feedback.selected}</p>
                {!result.is_correct && (
                  <p className="feedback-correct">{result.feedback.correct}</p>
                )}
                {result.evaluation_id && (
                  <p className="feedback-meta">AI 코치 분석은 퀴즈 끝난 뒤 결과에서 1번부터 순서대로 확인할 수 있어요.</p>
                )}
                <div className="feedback-lists">
                  <div>
                    <h3>해야 할 것</h3>
                    <ul>
                      {result.feedback.required_actions.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h3>하지 말아야 할 것</h3>
                    <ul>
                      {result.feedback.prohibited_actions.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                </div>
                <button type="button" className="btn primary" onClick={goNextOrSummary}>
                  {quizNumber >= quizTotal ? '결과 보기' : '다음 문제'}
                </button>
              </section>
            )}

            {error && phase === 'ready' && (
              <div className="inline-error">
                <p className="status error-text">{error}</p>
                <button type="button" className="btn ghost" onClick={() => void onSubmit()}>
                  다시 제출
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  )
}
