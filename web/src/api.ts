export type PublicChoice = {
  id: 'A' | 'B' | 'C'
  text: string
}

export type ScenarioNext = {
  scenario_id: string
  organization: {
    name: string
    department: string
  }
  topic: string
  subtopic: string
  difficulty: string
  scenario: string
  question: string
  choices: PublicChoice[]
  quiz_index: number
  quiz_total: number
}

export type QuizStart = {
  quiz_total: number
  scenarios: ScenarioNext[]
}

export type FeedbackPayload = {
  selected: string
  correct: string
  required_actions: string[]
  prohibited_actions: string[]
  next_tip?: string | null
  policy_grounds?: string[]
  followed?: string[]
  missed?: string[]
  analysis_summary?: string | null
  source?: 'agent' | 'static'
}

export type SubmitResult = {
  scenario_id: string
  choice_id: 'A' | 'B' | 'C'
  is_correct: boolean
  correct_choice_id: 'A' | 'B' | 'C'
  selected_label: 'unsafe' | 'partial' | 'correct'
  evaluation_id?: string | null
  agent_label?: 'unsafe' | 'partial' | 'correct' | null
  feedback: FeedbackPayload
  quiz_index?: number | null
  quiz_total?: number | null
}

export type EvaluationStatus = {
  evaluation_id: string
  scenario_id: string
  choice_id: 'A' | 'B' | 'C'
  status: 'pending' | 'running' | 'done' | 'error'
  agent_label?: 'unsafe' | 'partial' | 'correct' | null
  feedback?: FeedbackPayload | null
  error?: string | null
}

export type AttemptRecord = {
  scenario: ScenarioNext
  result: SubmitResult
}

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data?.detail === 'string') return data.detail
    return JSON.stringify(data)
  } catch {
    return res.statusText || '요청에 실패했습니다.'
  }
}

export async function startQuizPack(): Promise<QuizStart> {
  const res = await fetch('/quiz/start', { method: 'POST' })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function submitChoice(
  scenarioId: string,
  choiceId: 'A' | 'B' | 'C',
): Promise<SubmitResult> {
  const res = await fetch(`/scenarios/${encodeURIComponent(scenarioId)}/submit`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ choice_id: choiceId }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function fetchEvaluation(evaluationId: string): Promise<EvaluationStatus> {
  const res = await fetch(`/evaluations/${encodeURIComponent(evaluationId)}`)
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}
