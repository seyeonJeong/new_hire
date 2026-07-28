# Newhire

정책 기반 신입 온보딩·상황판단(SJT) 플랫폼.

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
