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

export type CriterionVerdict = {
  criterion: string
  kind: 'required' | 'prohibited'
  met: boolean
  evidence?: string
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
  verdicts?: CriterionVerdict[]
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
  choice_id: string
  kind?: 'mcq' | 'open'
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

function connectionHint(err: unknown): string {
  if (err instanceof TypeError) {
    return '서버에 연결하지 못했습니다. API(8000)와 웹(5173)이 켜져 있는지 확인하세요.'
  }
  return err instanceof Error ? err.message : '요청에 실패했습니다.'
}

export async function startQuizPack(): Promise<QuizStart> {
  try {
    const res = await fetch('/quiz/start', { method: 'POST' })
    if (!res.ok) throw new Error(await readError(res))
    return res.json()
  } catch (err) {
    throw new Error(connectionHint(err))
  }
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

export async function retryEvaluation(evaluationId: string): Promise<EvaluationStatus> {
  const res = await fetch(`/evaluations/${encodeURIComponent(evaluationId)}/retry`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export type OpenChatMessage = {
  speaker: 'trainee' | 'counterpart'
  text: string
}

export type OpenSession = {
  session_id: string
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
  opening: string
  messages: OpenChatMessage[]
  trainee_turns: number
  max_trainee_turns: number
  evaluation_id?: string | null
}

export type OpenEvaluateResult = {
  session_id: string
  evaluation_id: string
  status: 'pending' | 'running' | 'done' | 'error'
}

export async function startOpenResponse(excludeIds: string[]): Promise<OpenSession> {
  try {
    const res = await fetch('/open-response/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ exclude_ids: excludeIds }),
    })
    if (!res.ok) throw new Error(await readError(res))
    return res.json()
  } catch (err) {
    throw new Error(connectionHint(err))
  }
}

export async function sendOpenMessage(
  sessionId: string,
  text: string,
): Promise<OpenSession> {
  const res = await fetch(`/open-response/${encodeURIComponent(sessionId)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function evaluateOpenSession(sessionId: string): Promise<OpenEvaluateResult> {
  const res = await fetch(`/open-response/${encodeURIComponent(sessionId)}/evaluate`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}
