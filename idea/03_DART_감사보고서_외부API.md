# 아이디어 03: DART 감사보고서 연동 + 외부 API 키 정리

> 대화 일시: 2026-06-20 01:28  
> 핵심: DART에서 감사보고서 수집 → 심사 근거 강화

---

## 1. DART OpenAPI 활용

### 사용 가능한 API

| API | 용도 | 심사 활용 |
|-----|------|----------|
| 감사보고서 원문 | 외부감사 의견, 계속기업 불확실성 | 특이사항 항목 |
| 재무제표 (단일/다중) | 자산·부채·손익 수치 | 상환재원·재무분석 |
| 사업보고서 | 사업 현황, 매출 구성 | 업체현황·산업분석 |
| 주요 공시 | 유상증자, 합병, 소송 등 | 특이사항·리스크 |

### 핵심 엔드포인트

```python
import requests

DART_API_KEY = os.environ["DART_API_KEY"]  # .env에서 로드
BASE_URL = "https://opendart.fss.or.kr/api"

# 1) 기업 고유번호 조회 (corp_code 필요)
# → 사전에 기업명 → corp_code 매핑 테이블 구축 필요

# 2) 감사보고서 원문 조회
audit_report = requests.get(f"{BASE_URL}/document.json", params={
    "crtfc_key": DART_API_KEY,
    "rcept_no": "접수번호"  # 공시 검색으로 먼저 얻음
}).json()

# 3) 재무제표 조회 (단일회사, 주요계정)
financial = requests.get(f"{BASE_URL}/fnlttSinglAcntAll.json", params={
    "crtfc_key": DART_API_KEY,
    "corp_code": "00126380",  # 기업 고유코드
    "bsns_year": "2024",
    "reprt_code": "11011",  # 사업보고서
    "fs_div": "OFS"  # 개별재무제표
}).json()

# 4) 공시 검색 (최근 공시 목록)
disclosures = requests.get(f"{BASE_URL}/list.json", params={
    "crtfc_key": DART_API_KEY,
    "corp_code": "00126380",
    "bgn_de": "20240101",
    "end_de": "20251231",
    "pblntf_ty": "A"  # 정기공시
}).json()
```

### 심사에서의 활용 시나리오

```
[DART 감사보고서 조회]
    │
    ├── 감사의견: "적정" → 긍정 요소
    ├── 감사의견: "한정/부적정" → 강한 부정 요소 (반려 근거)
    ├── "계속기업 불확실성" 문구 존재 → 최대 리스크
    │
    └── 7명 토론의 "리스크관리자" agent에게 주입
```

---

## 2. 외부 API 키가 필요한가?

### 답: 대부분 필요함. 정리:

| 데이터 소스 | API 키 필요? | 무료? | 비고 |
|------------|-------------|------|------|
| DART OpenAPI | ✅ 필요 | ✅ 무료 | 일 1만건 제한 |
| Bing Grounding | ❌ 별도 불필요 | Azure 과금 | Foundry Connection으로 처리 |
| Bing Search API (직접) | ✅ 필요 | 유료 | 월 1000건 무료 티어 있음 |
| 한국은행 ECOS | ✅ 필요 | ✅ 무료 | 인증키 발급 |
| 통계청 KOSIS | ✅ 필요 | ✅ 무료 | |
| 네이버 뉴스 검색 | ✅ 필요 | ✅ 무료 | 일 2.5만건 |

### 해커톤에서 실제로 쓸 것 (최소 구성)

1. **DART API** — 감사보고서 + 재무제표 (키 확보 완료 ✅)
2. **Bing Grounding** — 산업현황 + 뉴스 (Azure 연결만 하면 됨)

이 2개면 충분. 나머지는 시간 남으면 추가.

---

## 3. .env에 추가할 변수

```env
# DART OpenAPI
DART_API_KEY=<여기에_키_입력>

# Bing Grounding (Azure AI Foundry Connection ID)
BING_CONNECTION_ID=<Azure_포털에서_복사>
```

> ⚠️ .env는 .gitignore에 포함되어 있으므로 커밋 안 됨. 안전.

---

## 4. DART + Bing 통합 흐름

```
[기업 입력 (사업자번호)]
        │
        ├── (1) DART API → 감사보고서 조회
        │       → 감사의견, 계속기업 문구, 최근 재무제표
        │
        ├── (2) DART API → 최근 공시 목록 조회  
        │       → 유상증자, 합병, 소송, 횡령 등 특이사항
        │
        ├── (3) Bing Grounding → 산업현황 검색
        │       → BSI, 수출증감, 전망
        │
        ├── (4) Bing Grounding → 기업명 뉴스 검색
        │       → 최근 호재/악재 뉴스
        │
        └── (5) 위 결과를 7명 토론에 주입
                → 산업분석가: (3)(4) 활용
                → 리스크관리자: (1)(2) 활용
                → 재무분석가: DART 재무제표로 교차검증
```

---

## 5. 발표 포인트

> "실제 DART 공시와 실시간 뉴스를 AI가 자동 수집하여  
> 심사 근거를 보강합니다. 모의 데이터가 아닌 **실제 데이터**입니다."

이건 다른 팀과 확실히 차별화되는 지점.
