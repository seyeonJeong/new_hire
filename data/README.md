# Newhire Demo Data

공개 데모용 **가상 기업** 데이터입니다. 실제 회사 기밀문서를 넣지 마세요.

## Layout

```text
data/
└── nova_soft/
    ├── README.md
    ├── organization.json
    ├── approval_structure.json
    └── policies/
        ├── manifest.json
        ├── SEC-001-data-sharing.md
        ├── EXP-001-expense-approval.md
        └── RPT-001-reporting.md
```

시나리오 JSON은 이 폴더에 두지 않습니다. LLM 생성 파이프라인에서 별도 산출합니다.

## Usage (now → later)

1. **Now:** 정책 Markdown 전문을 프롬프트에 넣어 시나리오 생성
2. **Later:** 같은 파일을 청크·임베딩해 RAG로 관련 조항만 검색
