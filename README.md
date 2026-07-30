# Newhire

신입사원 역량 평가 에이전트.

## Demo data

가상 기업 **NOVA Soft** 내규·조직 데이터: [`data/nova_soft/`](data/nova_soft/)

## Scenario generation (v1)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m newhire.generate --topic data_sharing
python -m newhire.generate --count 20
```

`.env`에 `OPENAI_API_KEY` 필요. 1건은 `generated/*.json`, 배치는 `generated/batch_*.jsonl`.
세부 토픽: [`data/nova_soft/subtopics.json`](data/nova_soft/subtopics.json)

## Scenario validation

```bash
python -m newhire.validate --in data/nova_soft/generated/batch_20260728T014723Z.jsonl
```

- **error:** 보기 길이 불균형, 정답 누설, 필수/금지 행동 부실  
- **warning:** 정답 위치 편중, subtopic 미반영, 유사 중복

## Scenario repair

이슈를 프롬프트에 넣어 LLM으로 재생성합니다.

```bash
# 수리 계획만 확인
python -m newhire.repair --in data/nova_soft/generated/batch_20260728T014723Z.jsonl --plan-only

# 실제 수리 (최대 2라운드)
python -m newhire.repair --in data/nova_soft/generated/batch_20260728T014723Z.jsonl --max-rounds 2
```

## API (MVP)

```bash
source .venv/bin/activate
pip install -e .
uvicorn newhire.api:app --reload --port 8000
```

- `GET /health`
- `GET /scenarios/next` — 다음 문제 (정답 필드 제외)
- `POST /scenarios/{scenario_id}/submit` — `{ "choice_id": "B" }` 제출·채점
- 문서: http://127.0.0.1:8000/docs

## Web UI (MVP)

```bash
cd web
npm install
npm run dev
```

브라우저: http://127.0.0.1:5173  
API(`:8000`)가 켜져 있어야 합니다.