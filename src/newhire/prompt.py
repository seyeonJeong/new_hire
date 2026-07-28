from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """\
당신은 대기업 SI 신입사원 온보딩용 상황판단검사(SJT) 문항 작성자입니다.
주어진 가상 회사 내규와 세부 토픽(Trigger·갈등)만을 근거로, 객관식 시나리오 1건을 JSON으로 작성합니다.

규칙:
1. 한국어로 작성한다.
2. FAQ·교과서 예시가 아니라, 신입이 현장에서 실제로 망설일 상황을 만든다.
3. choices는 정확히 3개(A/B/C)이며 label은 unsafe, partial, correct를 각각 1개씩 갖는다.
4. correct_choice_id는 label이 correct인 choice의 id와 일치해야 한다.
5. 질문·보기 본문에 "정답", "올바른", "금지", "부분적으로", unsafe/partial/correct 같은 라벨·정답 힌트를 넣지 않는다.
6. policy_ref.sections는 제공된 내규에 실제로 존재하는 절 번호만 사용한다.
7. rationale은 내규 조항을 근거로 짧게 설명한다. (응시자에게는 보이지 않는 채점용)
8. meta.status는 "draft", meta.version은 "v0.1"로 둔다.
9. subtopic 필드는 입력으로 주어진 subtopic id를 그대로 넣는다.
10. JSON 객체 하나만 출력한다. 마크다운 코드블록이나 해설을 붙이지 않는다.

난이도·혼동 설계 (중요):
- 정답이 한눈에 보이게 만들지 말 것. correct 보기는 내규의 핵심 절차를 따르되, 조항 번호를 나열하거나 체크리스트처럼 쓰지 말 것.
- partial은 correct와 겉보기 유사해야 한다. 같은 채널·비슷한 매너·일부 올바른 조치를 포함하되, 핵심 절차 1가지만 빠지거나 순서가 틀린다.
- unsafe는 명백한 악행처럼 과장하지 말 것. "급해서", "고객이 시켜서", "나중에 보고" 같은 현실 가능한 합리화로 보이게 할 것.
- 세 보기 길이와 말투를 비슷하게 맞출 것. correct만 유난히 길고 완벽한 문장이면 안 된다.
- 정답이 항상 C가 아니게 id를 섞을 것.
- 반드시 주어진 Trigger와 업무상 갈등을 시나리오에 반영할 것.
"""


DIFFICULTY_HINTS = {
    "easy": "압력은 약하게, 오답은 비교적 분명하게. 그래도 correct만 교과서 문장으로 쓰지 말 것.",
    "medium": (
        "partial이 correct와 매우 비슷해야 한다. "
        "응시자가 둘 다 '맞는 것 같음'으로 느끼게 만들 것."
    ),
    "hard": (
        "세 보기 모두 그럴듯하게. unsafe도 일부 올바른 행동을 포함하되 치명적 위반이 숨겨져 있음. "
        "correct는 완전 나열형이 아니라 우선순위·판단이 드러나는 짧은 행동 선택."
    ),
}


def build_user_prompt(
    *,
    organization: dict[str, Any],
    policy_id: str,
    policy_title: str,
    policy_text: str,
    topic: str,
    difficulty: str,
    key_sections: list[str],
    subtopic: dict[str, Any],
    scenario_id: str,
) -> str:
    org_block = {
        "id": organization["organization_id"],
        "name": organization["name"],
        "industry": organization["industry"],
        "department": organization["department"],
        "target_role": organization["target_role"],
    }
    schema_hint = {
        "scenario_id": scenario_id,
        "organization": {
            "id": org_block["id"],
            "name": org_block["name"],
            "industry": org_block["industry"],
            "department": org_block["department"],
        },
        "target_role": org_block["target_role"],
        "topic": topic,
        "subtopic": subtopic["id"],
        "difficulty": difficulty,
        "primary_competency": (
            subtopic.get("primary_competency_hint")
            or "risk_awareness | policy_application | escalation | communication 중 1"
        ),
        "scenario": "상황 서술 (Trigger·갈등 반영, 2~4문장)",
        "question": "가장 적절한 다음 행동은?",
        "choices": [
            {"id": "A", "text": "비슷한 길이의 행동 선택지", "label": "unsafe|partial|correct"},
            {"id": "B", "text": "비슷한 길이의 행동 선택지", "label": "unsafe|partial|correct"},
            {"id": "C", "text": "비슷한 길이의 행동 선택지", "label": "unsafe|partial|correct"},
        ],
        "correct_choice_id": "A|B|C",
        "rationale": {"correct": "...", "unsafe": "...", "partial": "..."},
        "required_actions": ["..."],
        "prohibited_actions": ["..."],
        "policy_ref": {"policy_id": policy_id, "sections": ["..."]},
        "meta": {"version": "v0.1", "status": "draft"},
    }
    difficulty_hint = DIFFICULTY_HINTS.get(difficulty, DIFFICULTY_HINTS["medium"])
    return f"""\
## 조직
{json.dumps(org_block, ensure_ascii=False, indent=2)}

## 세부 토픽 (반드시 반영)
- subtopic id: {subtopic["id"]}
- title: {subtopic["title"]}
- trigger: {subtopic["trigger"]}
- conflict: {subtopic["conflict"]}
- competency hint: {subtopic.get("primary_competency_hint", "")}

## 생성 조건
- topic: {topic}
- difficulty: {difficulty}
- policy_id: {policy_id}
- policy_title: {policy_title}
- scenario_id: {scenario_id} (그대로 사용)
- 참고 핵심 조항: {", ".join(key_sections)}
- 난이도 가이드: {difficulty_hint}

## 내규 전문 ({policy_id})
{policy_text}

## 출력 JSON 스키마 힌트
{json.dumps(schema_hint, ensure_ascii=False, indent=2)}

위 내규와 세부 토픽만 근거로, 보기가 서로 헷갈리는 시나리오 1건을 JSON으로 작성하세요.
correct 보기에 조항 번호·절차를 길게 나열하지 마세요.
subtopic 값은 "{subtopic["id"]}" 로 고정하세요.
"""
