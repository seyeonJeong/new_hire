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
}

export type SubmitResult = {
  scenario_id: string
  choice_id: 'A' | 'B' | 'C'
  is_correct: boolean
  correct_choice_id: 'A' | 'B' | 'C'
  selected_label: 'unsafe' | 'partial' | 'correct'
  feedback: {
    selected: string
    correct: string
    required_actions: string[]
    prohibited_actions: string[]
  }
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

export async function fetchNextScenario(): Promise<ScenarioNext> {
  const res = await fetch('/scenarios/next')
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
