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


REPAIR_SYSTEM_PROMPT = """\
당신은 대기업 SI 신입사원 온보딩용 SJT 문항 수정자입니다.
기존 시나리오 JSON과 품질 이슈 목록을 보고, 이슈를 해소한 새 JSON 1건만 작성합니다.

규칙:
1. 한국어로 작성한다.
2. 출력은 JSON 객체 하나만. 마크다운/해설 금지.
3. 반드시 아래 필드를 모두 포함한 완전한 JSON을 출력한다:
   scenario_id, organization, target_role, topic, subtopic, difficulty,
   primary_competency, scenario, question, choices, correct_choice_id,
   rationale(correct/unsafe/partial), required_actions, prohibited_actions,
   policy_ref(policy_id + sections), meta(version/status)
4. topic, subtopic, policy_ref.policy_id, scenario_id는 입력값을 유지한다.
5. choices는 A/B/C 3개, label은 unsafe/partial/correct 각 1개.
6. correct_choice_id는 label=correct인 choice의 id와 일치해야 한다.
7. 질문·보기·시나리오 본문에 unsafe/partial/correct, 정답/오답, SEC|EXP|RPT-번호, 조항번호(예: 4.2)를 넣지 않는다.
8. 세 보기 텍스트 길이를 비슷하게 맞춘다. correct만 절차를 길게 나열하지 않는다.
9. 이슈에 target_correct_choice_id가 있으면 그 id가 correct가 되게 작성한다.
10. meta.status는 "draft", meta.version은 "v0.1".
11. 기존 문항의 좋은 설정(인물·압력)은 유지하되, 이슈 해결을 위해 보기/표현은 바꿔도 된다.
12. rationale, required_actions, prohibited_actions, policy_ref.sections를 절대 생략하지 않는다.
"""


def build_repair_user_prompt(
    *,
    organization: dict[str, Any],
    policy_id: str,
    policy_text: str,
    subtopic: dict[str, Any],
    old_scenario: dict[str, Any],
    issue_lines: list[str],
    scenario_id: str,
    target_correct_choice_id: str | None = None,
) -> str:
    org_block = {
        "id": organization["organization_id"],
        "name": organization["name"],
        "industry": organization["industry"],
        "department": organization["department"],
        "target_role": organization["target_role"],
    }
    issues_bullet = "\n".join(f"- {line}" for line in issue_lines)
    if target_correct_choice_id:
        issues_bullet += (
            f"\n- [repair] target_correct_choice_id: {target_correct_choice_id}"
        )
    required_fields = [
        "scenario_id",
        "organization",
        "target_role",
        "topic",
        "subtopic",
        "difficulty",
        "primary_competency",
        "scenario",
        "question",
        "choices",
        "correct_choice_id",
        "rationale",
        "required_actions",
        "prohibited_actions",
        "policy_ref",
        "meta",
    ]
    return f"""\
## 조직
{json.dumps(org_block, ensure_ascii=False, indent=2)}

## 세부 토픽 (유지)
- subtopic id: {subtopic["id"]}
- title: {subtopic.get("title", "")}
- trigger: {subtopic.get("trigger", "")}
- conflict: {subtopic.get("conflict", "")}

## 내규 전문 ({policy_id})
{policy_text}

## 기존 시나리오 (참고)
{json.dumps(old_scenario, ensure_ascii=False, indent=2)}

## 품질 이슈 (반드시 해결)
{issues_bullet}

## 필수 출력 필드
{json.dumps(required_fields, ensure_ascii=False)}
- rationale: {{"correct": "...", "unsafe": "...", "partial": "..."}}
- required_actions: ["...", "..."]
- prohibited_actions: ["...", "..."]
- policy_ref: {{"policy_id": "{policy_id}", "sections": ["4.2", "..."]}}

## 수정 지시
- 위 이슈를 모두 반영한 **완전한** 시나리오 JSON 1건을 작성하세요.
- 필드를 생략하지 마세요. 기존 시나리오에 있던 rationale/actions/policy_ref는 필요 시 수정·유지하세요.
- scenario_id는 "{scenario_id}" 로 유지하세요.
- subtopic은 "{subtopic["id"]}" 로 유지하세요.
"""


TOPIC_ID_PREFIX = {
    "data_sharing": "ds",
    "expense_approval": "ea",
    "reporting": "rp",
}

COMPETENCY_HINTS = (
    "risk_awareness",
    "policy_application",
    "escalation",
    "communication",
)


SUBTOPIC_SYSTEM_PROMPT = """\
당신은 대기업 SI 신입사원 온보딩용 상황판단검사(SJT) 세부 토픽 설계자입니다.
주어진 가상 회사 내규를 읽고, 아직 카탈로그에 없는 세부 토픽을 JSON으로 제안합니다.

규칙:
1. 한국어로 작성한다.
2. 내규에 실제로 적힌 의무·금지·예외·보고 경로만 근거로 한다. 없는 조항을 지어내지 않는다.
3. 각 토픽은 신입이 현장에서 망설일 Trigger와 업무상 갈등(conflict)을 가진다.
4. 이미 제공된 기존 토픽의 title/trigger와 의미상 겹치지 않는다. (표현만 바꾼 중복 금지)
5. primary_competency_hint는 risk_awareness | policy_application | escalation | communication 중 하나.
6. id는 지정된 접두사 + 소문자 스네이크케이스 (예: ds_masking_before_send).
7. JSON만 출력한다. 마크다운 코드블록이나 해설을 붙이지 않는다.

출력 형식:
{
  "subtopics": [
    {
      "id": "ds_example_id",
      "topic": "data_sharing",
      "title": "짧은 제목",
      "trigger": "상황을 촉발하는 사건",
      "conflict": "가치 A vs 가치 B",
      "primary_competency_hint": "policy_application"
    }
  ]
}
"""


def build_subtopic_user_prompt(
    *,
    organization: dict[str, Any],
    topic: str,
    policy_id: str,
    policy_title: str,
    policy_text: str,
    existing_subtopics: list[dict[str, Any]],
    count: int,
    id_prefix: str,
) -> str:
    org_block = {
        "id": organization["organization_id"],
        "name": organization["name"],
        "industry": organization["industry"],
        "department": organization["department"],
        "target_role": organization["target_role"],
    }
    existing_brief = [
        {
            "id": s.get("id"),
            "title": s.get("title"),
            "trigger": s.get("trigger"),
            "conflict": s.get("conflict"),
        }
        for s in existing_subtopics
        if s.get("topic") == topic
    ]
    schema_hint = {
        "subtopics": [
            {
                "id": f"{id_prefix}_snake_case_id",
                "topic": topic,
                "title": "...",
                "trigger": "...",
                "conflict": "...",
                "primary_competency_hint": " | ".join(COMPETENCY_HINTS),
            }
        ]
    }
    return f"""\
## 조직
{json.dumps(org_block, ensure_ascii=False, indent=2)}

## 생성 조건
- topic: {topic}
- policy_id: {policy_id}
- policy_title: {policy_title}
- 요청 개수: {count}
- id 접두사: {id_prefix}_ (반드시 이 접두사로 시작, 소문자 스네이크케이스)
- primary_competency_hint 허용값: {", ".join(COMPETENCY_HINTS)}

## 기존 세부 토픽 (겹치지 말 것)
{json.dumps(existing_brief, ensure_ascii=False, indent=2)}

## 내규 전문 ({policy_id})
{policy_text}

## 출력 JSON 스키마 힌트
{json.dumps(schema_hint, ensure_ascii=False, indent=2)}

위 내규에서 아직 기존 토픽이 다루지 않은 세부 상황을 {count}개 뽑아 JSON으로 작성하세요.
title·trigger가 기존 항목과 비슷하면 탈락입니다. 다른 조항·다른 압력을 쓰세요.
모든 항목의 topic 값은 "{topic}" 으로 고정하세요.
"""
