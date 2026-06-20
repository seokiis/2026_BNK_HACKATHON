# 구현 명세 02: DART 감사보고서 + Bing Grounding 연동

> 이 파일을 읽고 구현하세요. 기존 코드는 수정하지 않고 **새 파일만 추가**합니다.

---

## 목표

재무 분석 결과 반려/경계선 판정이 나온 기업에 대해:
1. **DART OpenAPI**로 감사보고서·재무제표·공시를 조회
2. **Bing Grounding**으로 산업현황·뉴스를 실시간 검색
3. 결과를 종합해 "보완 근거"를 생성하여 심사의견서에 반영

---

## 아키텍처 흐름

```
[기업 입력 (사업자번호 + 업종코드)]
        │
        ├── (1) DART API 호출
        │       → 감사의견 (적정/한정/부적정/의견거절)
        │       → 계속기업 불확실성 여부
        │       → 최근 공시 (유상증자, 소송, 합병 등)
        │
        ├── (2) Bing Grounding 호출
        │       → 업종 산업현황 (호황/보통/침체)
        │       → 관련 뉴스 3~5건 (제목, 요약, URL)
        │       → 시장 전망
        │
        └── (3) GPT로 보완 근거 생성
                → "부채비율 초과이나, 반도체 산업 호황으로..."
                → 7명 토론의 산업분석가 agent에게 주입
```

---

## Part 1: DART OpenAPI 연동

### 새 파일: `backend/services/dart_client.py`

```python
"""
DART OpenAPI 클라이언트.
감사보고서, 재무제표, 공시 목록을 조회한다.
"""
import os
import httpx

DART_BASE = "https://opendart.fss.or.kr/api"
DART_API_KEY = os.environ.get("DART_API_KEY", "")


async def get_audit_opinion(corp_code: str, bsns_year: str = "2024") -> dict:
    """
    감사보고서에서 감사의견을 추출.
    
    Returns:
        {
            "audit_opinion": "적정" | "한정" | "부적정" | "의견거절",
            "going_concern": bool,  # 계속기업 불확실성 존재 여부
            "auditor": "삼일회계법인",
            "report_date": "2025-03-15"
        }
    """
    # DART API: 감사보고서 전문 → /document.json
    # 또는 간편: /fnlttSinglAcnt.json 에서 감사의견 필드 확인
    pass


async def get_financial_statements(corp_code: str, bsns_year: str = "2024") -> dict:
    """
    DART 재무제표 조회 (교차검증용).
    
    Returns:
        {
            "total_assets": int,
            "total_liabilities": int,
            "revenue": int,
            "operating_income": int,
            "net_income": int,
            "debt_ratio": float,
            "icr": float
        }
    """
    # API: /fnlttSinglAcntAll.json
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": "11011",  # 사업보고서
        "fs_div": "OFS",  # 개별재무제표
    }
    pass


async def get_recent_disclosures(corp_code: str, months: int = 6) -> list[dict]:
    """
    최근 N개월 주요 공시 목록.
    
    Returns:
        [
            {
                "title": "유상증자 결정",
                "date": "2025-01-15",
                "type": "주요사항보고",
                "url": "https://dart.fss.or.kr/..."
            }
        ]
    """
    # API: /list.json
    pass


async def search_corp_code(company_name: str) -> str | None:
    """
    기업명으로 DART corp_code 검색.
    DART는 전체 기업 목록 XML을 제공 → 사전 다운로드 후 매핑 권장.
    또는 /company.json API 사용.
    """
    pass
```

### DART API 핵심 엔드포인트 정리

| 용도 | 엔드포인트 | 주요 파라미터 |
|------|-----------|-------------|
| 공시 목록 | `/list.json` | corp_code, bgn_de, end_de, pblntf_ty |
| 재무제표(전체) | `/fnlttSinglAcntAll.json` | corp_code, bsns_year, reprt_code, fs_div |
| 감사보고서 원문 | `/document.json` | rcept_no (공시 접수번호) |
| 기업 개황 | `/company.json` | corp_code |

### .env에 추가할 변수

```env
DART_API_KEY=<.env에만 저장, 코드에 하드코딩 금지>
```

### config.py에 추가할 필드 (Settings 클래스)

```python
dart_api_key: Optional[str] = ""
```

---

## Part 2: Bing Grounding 연동

### 새 파일: `backend/services/bing_grounding.py`

```python
"""
Bing Grounding을 통한 실시간 산업현황·뉴스 검색.
Azure OpenAI의 data_sources 기능을 활용한다.
"""
import json
from openai import AsyncAzureOpenAI
from config import get_settings


async def search_industry_status(industry_code: str, industry_name: str, company_name: str) -> dict:
    """
    Bing Grounding으로 산업현황 조회.
    
    Args:
        industry_code: "C26", "F41" 등
        industry_name: "반도체·전자부품", "건설업" 등
        company_name: 기업명 (맥락 제공용)
    
    Returns:
        {
            "industry_status": "호황" | "보통" | "침체",
            "key_indicators": {
                "bsi_index": 118,
                "export_growth_yoy": "+23.5%",
                "production_index_trend": "상승"
            },
            "outlook": "AI 수요 확대로 2026년까지 성장 지속 전망",
            "news": [
                {
                    "title": "삼성전자 반도체 투자 3조 확대",
                    "summary": "...",
                    "source_url": "https://...",
                    "date": "2025-12-10"
                }
            ],
            "impact_on_repayment": "긍정 — 산업 호황으로 매출 확대 가능성 높음",
            "sources": ["한국은행 BSI 2025.12", "..."]
        }
    """
    s = get_settings()
    client = AsyncAzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
    )

    prompt = f"""당신은 BNK금융그룹의 산업 분석 전문가입니다.
다음 기업의 업종에 대해 최신 산업현황을 조사하세요.

기업명: {company_name}
업종: {industry_name} (코드: {industry_code})

다음 항목을 조사해 JSON으로 응답하세요:
1. industry_status: 산업 경기 상태 ("호황" / "보통" / "침체")
2. key_indicators: BSI지수, 수출증감률(YoY), 생산지수 추세
3. outlook: 향후 1년 전망 요약 (2~3문장)
4. news: 최근 3개월 주요 뉴스 3건 (title, summary, source_url, date)
5. impact_on_repayment: 해당 산업 현황이 대출 상환 능력에 미치는 영향 (긍정/부정 + 근거)
6. sources: 참고한 출처 목록

JSON만 반환하세요. 마크다운 코드블록 없이."""

    response = await client.chat.completions.create(
        model=s.azure_openai_chat_deployment,
        messages=[
            {"role": "system", "content": "산업 분석 전문가. 검색 결과 기반으로만 답변. 없는 수치는 생성 금지."},
            {"role": "user", "content": prompt},
        ],
        extra_body={
            "data_sources": [{
                "type": "bing_grounding",
                "parameters": {
                    "connection_id": s.bing_connection_id,  # config에 추가 필요
                    "market": "ko-KR",
                    "count": 10
                }
            }]
        },
        temperature=0.3,
        max_tokens=1000,
    )

    # 응답 파싱
    content = response.choices[0].message.content
    return json.loads(content)
```

### config.py에 추가할 필드

```python
bing_connection_id: Optional[str] = ""  # Azure AI Foundry Bing Connection ID
```

### .env에 추가

```env
BING_CONNECTION_ID=/subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/connections/<connection-name>
```

---

## Part 3: 통합 서비스 (DART + Bing → 보완 근거 생성)

### 새 파일: `backend/services/external_research.py`

```python
"""
외부 데이터 리서치 통합 서비스.
DART + Bing Grounding 결과를 종합해 보완 근거를 생성한다.
"""
from services.dart_client import get_audit_opinion, get_recent_disclosures
from services.bing_grounding import search_industry_status


async def research_company(
    corp_code: str,
    industry_code: str,
    industry_name: str,
    company_name: str,
    financial_issues: list[str],  # ["부채비율 초과", "ICR 기준 미달"] 등
) -> dict:
    """
    기업에 대한 외부 리서치 수행.
    재무 문제가 있을 때 보완 가능한 근거를 찾는다.
    
    Returns:
        {
            "dart": { audit_opinion, disclosures },
            "industry": { status, indicators, news, outlook },
            "補完_summary": "부채비율 초과(250%)이나, 반도체 산업 호황(BSI 118)...",
            "recommendation": "조건부 승인 검토" | "반려 유지",
            "confidence": 0.7
        }
    """
    # 1) DART 조회
    audit = await get_audit_opinion(corp_code)
    disclosures = await get_recent_disclosures(corp_code)
    
    # 2) Bing Grounding 산업현황
    industry = await search_industry_status(industry_code, industry_name, company_name)
    
    # 3) 종합 판단 (GPT로 요약)
    # → 재무 문제 + DART 결과 + 산업현황을 종합해서
    #   "보완 가능" vs "보완 불가" 판단
    
    return {
        "dart": {"audit_opinion": audit, "disclosures": disclosures},
        "industry": industry,
        "supplementary_summary": "...",  # GPT가 생성
        "recommendation": "...",
        "confidence": 0.0,
    }
```

---

## Part 4: API 엔드포인트

### 새 파일: `backend/routers/research.py`

```python
"""
외부 리서치 API 라우터.
프론트에서 "산업분석" 버튼 클릭 시 호출.
"""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["research"])


class ResearchRequest(BaseModel):
    company_id: str           # 사업자등록번호
    corp_code: str            # DART 기업코드
    industry_code: str        # C26, F41 등
    industry_name: str        # "반도체·전자부품"
    company_name: str
    financial_issues: list[str] = []  # 재무 문제 목록


class ResearchResponse(BaseModel):
    dart_audit_opinion: str
    dart_going_concern: bool
    dart_disclosures: list[dict]
    industry_status: str
    industry_outlook: str
    industry_news: list[dict]
    supplementary_summary: str
    recommendation: str


@router.post("/research/external")
async def external_research(req: ResearchRequest) -> ResearchResponse:
    """외부 데이터 리서치 (DART + Bing Grounding)"""
    from services.external_research import research_company
    
    result = await research_company(
        corp_code=req.corp_code,
        industry_code=req.industry_code,
        industry_name=req.industry_name,
        company_name=req.company_name,
        financial_issues=req.financial_issues,
    )
    
    return ResearchResponse(
        dart_audit_opinion=result["dart"]["audit_opinion"]["audit_opinion"],
        dart_going_concern=result["dart"]["audit_opinion"]["going_concern"],
        dart_disclosures=result["dart"]["disclosures"],
        industry_status=result["industry"]["industry_status"],
        industry_outlook=result["industry"]["outlook"],
        industry_news=result["industry"]["news"],
        supplementary_summary=result["supplementary_summary"],
        recommendation=result["recommendation"],
    )
```

### main.py에 라우터 등록 (추가할 줄)

```python
from routers.research import router as research_router
app.include_router(research_router, prefix="/api")
```

---

## Part 5: Azure 포털에서 해야 할 설정

1. **Bing Search Connection 생성** (Azure AI Foundry > Connections > + New > Bing Search)
2. Connection ID를 `.env`의 `BING_CONNECTION_ID`에 복사
3. `.env`에 `DART_API_KEY` 추가

---

## 파일 생성 목록 (요약)

| 파일 | 역할 |
|------|------|
| `backend/services/dart_client.py` | DART API 호출 |
| `backend/services/bing_grounding.py` | Bing Grounding 산업현황 검색 |
| `backend/services/external_research.py` | 통합 리서치 (DART + Bing → 보완근거) |
| `backend/routers/research.py` | `/api/research/external` 엔드포인트 |

## 기존 파일 수정 (최소)

| 파일 | 변경 |
|------|------|
| `backend/config.py` | `dart_api_key`, `bing_connection_id` 필드 추가 |
| `backend/main.py` | research_router 등록 (2줄) |
| `.env` | `DART_API_KEY`, `BING_CONNECTION_ID` 추가 |
| `.env.example` | 위 키 이름만 추가 (값은 빈칸) |

---

## 검증 기준

1. `GET /health` → `dart_connected: true` 표시
2. `POST /api/research/external` → 시나리오2(동진반도체소재) 입력 시 산업 호황 결과 반환
3. `POST /api/research/external` → 시나리오3(삼원건설개발) 입력 시 산업 침체 결과 반환
4. DART 감사의견이 "적정"이면 긍정, "한정/부적정"이면 반려 강화 근거로 작동
