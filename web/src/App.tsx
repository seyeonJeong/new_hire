import { useEffect, useState } from 'react'
import {
  fetchNextScenario,
  submitChoice,
  type ScenarioNext,
  type SubmitResult,
} from './api'
import './index.css'

type Phase = 'loading' | 'ready' | 'submitting' | 'feedback' | 'error'

const TOPIC_LABEL: Record<string, string> = {
  data_sharing: '자료 공유',
  expense_approval: '비용 승인',
  reporting: '보고',
}

export default function App() {
  const [phase, setPhase] = useState<Phase>('loading')
  const [scenario, setScenario] = useState<ScenarioNext | null>(null)
  const [selected, setSelected] = useState<'A' | 'B' | 'C' | null>(null)
  const [result, setResult] = useState<SubmitResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [animKey, setAnimKey] = useState(0)

  async function loadNext() {
    setPhase('loading')
    setSelected(null)
    setResult(null)
    setError(null)
    try {
      const next = await fetchNextScenario()
      setScenario(next)
      setAnimKey((k) => k + 1)
      setPhase('ready')
    } catch (err) {
      setError(err instanceof Error ? err.message : '문제를 불러오지 못했습니다.')
      setPhase('error')
    }
  }

  useEffect(() => {
    void loadNext()
  }, [])

  async function onSubmit() {
    if (!scenario || !selected) return
    setPhase('submitting')
    setError(null)
    try {
      const res = await submitChoice(scenario.scenario_id, selected)
      setResult(res)
      setPhase('feedback')
    } catch (err) {
      setError(err instanceof Error ? err.message : '제출에 실패했습니다.')
      setPhase('ready')
    }
  }

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
            <button type="button" className="btn primary" onClick={() => void loadNext()}>
              다시 시도
            </button>
          </div>
        )}

        {scenario && (phase === 'ready' || phase === 'submitting' || phase === 'feedback') && (
          <>
            <div className="meta-row">
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
                <button type="button" className="btn primary" onClick={() => void loadNext()}>
                  다음 문제
                </button>
              </section>
            )}

            {error && phase === 'ready' && <p className="status error-text">{error}</p>}
          </>
        )}
      </main>
    </div>
  )
}
