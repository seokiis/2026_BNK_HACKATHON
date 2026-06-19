"""
7명 AI 토론 오케스트레이션 — 현재 stub, ai-developer가 구현 예정

토론 순서 (REVIEW_AGENTS.md):
  1. 의장 개회
  2. 수석 CPA / 산업 애널리스트 / 평판 리스크 탐지관 독립 분석
  3. 본부 수석 심사역 / 기업영업 RM 교차 평가
  4. 여신심사 검증관 반박 (필요시 외부 데이터 추적관 호출)
  5. 재조사 루프 (최대 3회)
  6. 의장 합성 → 9개 항목 출력
"""

from typing import AsyncGenerator
from services.azure_clients import rag_search, chat
from models.schemas import ReviewItem, Grade, DataStatus, Evidence

REVIEW_ITEMS = [
    "업체현황", "자금용도", "금리결정 적정성", "상환재원",
    "특이사항", "기술금융&ESG", "종합의견", "미이행 승인조건", "영업점장 특별의견",
]

AGENT_PERSONAS = {
    "의장":          "당신은 여신심사 토론의 의장입니다. 중립적이고 절차적으로 토론을 진행하고 결과를 합성합니다.",
    "수석 CPA":      "당신은 수석 CPA입니다. 재무제표와 수치를 바탕으로 보수적으로 분석합니다.",
    "산업 애널리스트": "당신은 산업 애널리스트입니다. 업종 전망과 기술력을 거시 맥락에서 분석합니다.",
    "평판 리스크 탐지관": "당신은 평판 리스크 탐지관입니다. 비재무 리스크와 법적·평판 이슈를 집중 탐지합니다.",
    "본부 수석 심사역": "당신은 본부 수석 심사역입니다. 규정·여신 정책 관점에서 엄정하게 평가합니다.",
    "기업영업 RM":   "당신은 기업영업 RM입니다. 현장 관점과 서류에 드러나지 않는 정성 정보를 보완합니다.",
    "여신심사 검증관": "당신은 여신심사 검증관입니다. 근거 부족·논리 허점을 집요하게 반박합니다.",
}


async def run_discussion(
    business_id: str,
    company_data: dict,
    reviewer: str,
) -> AsyncGenerator[str, None]:
    """
    7명 토론을 실행하고 진행 상황을 SSE 문자열로 스트리밍한다.
    최종 결과는 'RESULT:' 접두사 JSON으로 전송한다.

    TODO (ai-developer):
      - 각 agent별 system 프롬프트 완성
      - 루프 3회 구현 및 의장의 조기 종료 판단
      - 검증관 반박 → 재조사 루프 연결
      - 외부 데이터 추적관 on-demand 호출 연결
    """
    yield f"data: [의장] 토론을 시작합니다. 사업자번호 {business_id} 심사를 개회합니다.\n\n"

    # RAG: 배정 심사역 과거 사례 + 규정 검색
    company_summary = _summarize_company(company_data)
    rag_cases = rag_search(company_summary, top=3, reviewer_filter=reviewer)
    rag_rules = rag_search("여신심사 규정 부채비율 이자보상배율 담보", top=2)
    context = _build_context(rag_cases, rag_rules)

    yield f"data: [의장] RAG 검색 완료 — 과거 사례 {len(rag_cases)}건, 규정 {len(rag_rules)}건 참조\n\n"

    # TODO: 실제 각 agent 순차 호출로 교체
    yield "data: [수석 CPA] 재무 분석 중...\n\n"
    yield "data: [산업 애널리스트] 업종 분석 중...\n\n"
    yield "data: [평판 리스크 탐지관] 비재무 리스크 탐지 중...\n\n"
    yield "data: [본부 수석 심사역] 규정 적합성 검토 중...\n\n"
    yield "data: [기업영업 RM] 현장 정보 보완 중...\n\n"
    yield "data: [여신심사 검증관] 근거 검증 중...\n\n"

    # 의장이 9개 항목 합성 (임시: 단일 LLM 호출)
    yield "data: [의장] 9개 항목 합성 중...\n\n"
    items = _synthesize_items(company_data, context)

    import json
    yield f"data: RESULT:{json.dumps([i.model_dump() for i in items], ensure_ascii=False)}\n\n"


def _summarize_company(company_data: dict) -> str:
    info = company_data.get("company_info", {})
    fin  = company_data.get("financial_statements", {})
    assets = fin.get("total_assets", 0)
    liab   = fin.get("total_liabilities", 0)
    op_inc = fin.get("operating_income", 0)
    interest = fin.get("finance_cost_interest", 1)
    return (
        f"기업명: {info.get('company_name')} | 내부등급: {info.get('internal_credit_rating')} "
        f"| 총자산: {round(assets/1e8,1)}억 | 부채비율: {round(liab/assets*100,1) if assets else 'N/A'}% "
        f"| ICR: {round(op_inc/interest,2) if interest else 'N/A'}배"
    )


def _build_context(cases: list[dict], rules: list[dict]) -> str:
    case_text = "\n---\n".join(c["content"][:500] for c in cases)
    rule_text = "\n---\n".join(r["content"][:300] for r in rules)
    return f"[과거 심사 사례]\n{case_text}\n\n[규정]\n{rule_text}"


def _synthesize_items(company_data: dict, context: str) -> list[ReviewItem]:
    """의장 agent가 9개 항목을 합성 — TODO: 실제 7명 토론 결과로 교체"""
    prompt = f"""
당신은 여신심사 토론의 의장입니다. 아래 기업 데이터와 참조 문서를 바탕으로
9개 심사 항목에 대한 초안 의견을 JSON 배열로 작성하세요.

기업 데이터:
{str(company_data)[:2000]}

참조 문서:
{context[:2000]}

다음 9개 항목 각각에 대해 JSON 객체를 반환하세요:
{REVIEW_ITEMS}

각 항목 형식:
{{"item": "항목명", "opinion": "심사의견(2~3문장)", "grade": "상|중|하", "data_status": "정상|부족|누락"}}

반드시 JSON 배열만 반환하고 다른 텍스트는 쓰지 마세요.
"""
    import json
    raw = chat([{"role": "user", "content": prompt}], max_tokens=3000)
    try:
        parsed = json.loads(raw)
        return [ReviewItem(**item) for item in parsed]
    except Exception:
        # 파싱 실패 시 빈 항목 반환
        return [ReviewItem(item=name, opinion="생성 실패 — 재시도 필요") for name in REVIEW_ITEMS]
