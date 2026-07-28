# Newhire Demo Data

공개 데모용 **가상 기업** 데이터

## Layout

```text
data/
└── nova_soft/
    ├── README.md
    ├── organization.json
    ├── approval_structure.json
    ├── subtopics.json
    ├── policies/
    │   ├── manifest.json
    │   ├── SEC-001-data-sharing.md
    │   ├── EXP-001-expense-approval.md
    │   └── RPT-001-reporting.md
    └── generated/          # LLM 산출 (draft)
```

## Generate

```bash
python -m newhire.generate --topic data_sharing
python -m newhire.generate --count 20
```

`--count 20`은 `subtopics.json`의 기본 비율(자료 8 / 비용 6 / 보고 6)로 세부 토픽을 돌아가며 생성합니다.

## Usage (now → later)

1. **Now:** 정책 Markdown 전문을 프롬프트에 넣어 시나리오 생성
2. **Later:** 같은 파일을 청크·임베딩해 RAG로 관련 조항만 검색
