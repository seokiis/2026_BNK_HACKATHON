# AI 여신심사 어시스턴트

대출 상담 시 고객 서류를 AI가 분석해 여신 심사의견서 초안을 생성하는 서비스.
7명의 AI agent가 토론하여 9개 심사 항목별 의견을 자동 작성하고, 항목마다
상·중·하 진단과 데이터 부족·누락을 제시한다. 목적은 영업점 직원이 심사역에게
반려당하는 횟수를 줄이는 것.

> BNK 해커톤(1박 2일) 프로젝트. Microsoft Foundry + Azure AI Search 기반.

---

## 폴더 구조

```
loan-assistant/
├── CLAUDE.md                      # Claude Code 자동 인식 지침 (행동 원칙·라우팅)
├── README.md                      # 이 파일 (사람용 안내)
├── .gitignore                     # .env 등 커밋 제외
│
├── .github/
│   └── copilot-instructions.md    # Copilot 자동 인식 지침 (CLAUDE.md와 동일)
│
├── .claude/
│   └── agents/                    # 개발용 sub-agent 6종 (빌드타임 도구)
│       ├── pm-architect.md        # 기획·요구사항
│       ├── ui-designer.md         # 화면 설계
│       ├── credit-expert.md       # 여신 실무 검증
│       ├── ai-developer.md        # AI Search·RAG·7명 토론 구현
│       ├── backend-developer.md   # FastAPI·배포
│       └── frontend-developer.md  # React UI
│
└── docs/                          # 서비스 정의·명세 (agent가 참조)
    ├── SERVICE.md                 # 서비스 정의·사용자·전체 흐름
    ├── FEATURES.md                # 기능 1~13 명세·담당 매핑
    ├── REVIEW_AGENTS.md           # 7명 토론 agent·토론 흐름·루프 규칙
    └── REVIEW_ITEMS.md            # 9개 항목·등급/데이터 판정 기준
```

## 두 종류의 "agent" 구분 (중요)

| | `.claude/agents/` 6종 | `docs/REVIEW_AGENTS.md` 7명 |
|---|---|---|
| 정체 | 개발을 돕는 빌드타임 도구 | 서비스 안에서 도는 런타임 AI |
| 시점 | 코드 짤 때 | 사용자가 심사할 때 |
| 예 | ai-developer, frontend-developer | 의장, 수석 CPA, 검증관 |

## 사용 방법

1. 이 폴더를 VSCode로 연다.
2. Claude Code 또는 Copilot으로 작업한다. 두 도구 모두 위 지침을 자동으로 읽는다.
3. 작업 요청 시 적절한 개발용 agent가 선택되고, 필요한 `docs/`를 참조한다.

예시 명령:
- "FEATURES.md 기준으로 백엔드 API 골격 만들어줘" → backend-developer
- "7명 토론 오케스트레이션 구현해줘" → ai-developer (REVIEW_AGENTS.md 참조)
- "9개 항목 결과 화면 만들어줘" → frontend-developer + ui-designer

## 인프라 (Day 1)

Azure 리소스 구축 후 `.env`를 채워야 실제 동작한다. 인프라 가이드와 `.env`,
`fill_env.sh`는 서비스 정의 확정 후 별도로 준비한다. (현재 미포함)

## 기술 스택

- LLM 두뇌: Microsoft Foundry 배포 GPT 계열
- 지식·검색: Azure AI Search (하이브리드 + 시맨틱 RAG)
- 토론 오케스트레이션: FastAPI 백엔드 코드 (프레임워크 미사용)
- 프론트: React + TypeScript
- 배포: Azure Container Apps