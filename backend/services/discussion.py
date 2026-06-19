"""
7명 AI 토론 오케스트레이션 — 실제 구현

토론 순서 (REVIEW_AGENTS.md):
  1. 의장 개회 + RAG 검색 (배정 심사역 과거 사례 + 규정)
  2. 수석 CPA / 산업 애널리스트 / 평판 리스크 탐지관 독립 분석
  3. 본부 수석 심사역 / 기업영업 RM 교차 평가
  4. 여신심사 검증관 반박 (필요시 재조사 루프, 최대 3회)
  5. 의장 합성 → 9개 항목 JSON 반환
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from models.schemas import DataStatus, Evidence, Grade, ReviewItem
from services.azure_clients import chat, rag_search

REVIEW_ITEMS = [
    "업체현황",
    "자금용도",
    "금리결정 적정성",
    "상환재원",
    "특이사항",
    "기술금융&ESG",
    "종합의견",
    "미이행 승인조건",
    "영업점장 특별의견",
]

# 각 agent의 system 프롬프트 (REVIEW_AGENTS.md 정의 기반)
_SYSTEM: dict[str, str] = {
    "의장": (
        "당신은 여신심사 토론의 의장입니다. 중립적으로 진행하며 최종 9개 항목을 합성합니다. "
        "검색 근거에 없는 수치를 지어내지 않습니다. 모든 출력은 초안 전제입니다."
    ),
    "수석 CPA": (
        "당신은 수석 CPA입니다. 재무제표 수치 기반으로 보수적으로 분석합니다. "
        "부채비율, ICR, 영업이익률을 핵심으로 분석하며 추정에는 전제를 명시합니다. "
        "근거 없는 수치를 생성하지 않습니다."
    ),
    "산업 애널리스트": (
        "당신은 산업 애널리스트입니다. 업종 전망, 기술력, ESG를 거시 맥락에서 분석합니다. "
        "재무 수치를 산업 맥락에서 재해석하며 근거 없는 단정을 하지 않습니다."
    ),
    "평판 리스크 탐지관": (
        "당신은 평판 리스크 탐지관입니다. 소송, 체납, 부정 뉴스, 지배구조 등 비재무 리스크를 탐지합니다. "
        "잠재 리스크를 먼저 가정하고 검증하는 방식으로 분석합니다."
    ),
    "본부 수석 심사역": (
        "당신은 본부 수석 심사역입니다. 규정과 여신 정책 관점에서 엄정하게 평가합니다. "
        "한도, 담보 적정성, 규정 적합성을 중점 검토하며 규정을 인용합니다."
    ),
    "기업영업 RM": (
        "당신은 기업영업 RM입니다. 현장 관점과 서류에 드러나지 않는 정성 정보를 보완합니다. "
        "자금 용도의 현실성과 고객 사업 실태를 분석합니다."
    ),
    "여신심사 검증관": (
        "당신은 여신심사 검증관입니다. 근거 없는 단정, 누락 항목, 모순을 집요하게 반박합니다. "
        "재조사를 명령할 수 있습니다. '근거가 무엇인가'를 반복적으로 추궁합니다."
    ),
}


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _summarize_company(company_data: dict) -> str:
    info = company_data.get("company_info", {})
    fin = company_data.get("financial_statements", {})
    assets = fin.get("total_assets", 0)
    liab = fin.get("total_liabilities", 0)
    op_inc = fin.get("operating_income", 0)
    interest = fin.get("finance_cost_interest", 1) or 1
    return (
        f"기업명: {info.get('company_name', 'N/A')} | "
        f"내부등급: {info.get('internal_credit_rating', 'N/A')} | "
        f"총자산: {round(assets / 1e8, 1)}억 | "
        f"부채비율: {round(liab / assets * 100, 1) if assets else 'N/A'}% | "
        f"ICR: {round(op_inc / interest, 2) if interest else 'N/A'}배"
    )


def _build_context(cases: list[dict], rules: list[dict]) -> str:
    case_text = "\n---\n".join(c["content"][:500] for c in cases) if cases else "해당 심사역 과거 사례 없음"
    rule_text = "\n---\n".join(r["content"][:300] for r in rules) if rules else "규정 문서 검색 결과 없음"
    return f"[과거 심사 사례]\n{case_text}\n\n[규정]\n{rule_text}"


async def _chat_async(system: str, user: str, max_tokens: int = 1200) -> str:
    """동기 chat()을 asyncio 스레드에서 실행."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return await asyncio.to_thread(chat, messages, max_tokens)


async def _rag_async(query: str, top: int = 3, reviewer_filter: Optional[str] = None) -> list[dict]:
    """동기 rag_search()를 asyncio 스레드에서 실행."""
    return await asyncio.to_thread(rag_search, query, top, reviewer_filter)


def _parse_review_items(raw: str) -> list[ReviewItem]:
    """LLM 응답에서 JSON 배열을 추출해 ReviewItem 리스트로 변환. 실패 시 기본값 반환."""
    # 코드 블록 또는 raw JSON 배열 추출
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return _default_items("JSON 파싱 실패 — 의장 재합성 필요")

    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return _default_items("JSON 파싱 실패 — 의장 재합성 필요")

    items: list[ReviewItem] = []
    for obj in parsed:
        if not isinstance(obj, dict):
            continue

        # grade 변환
        grade_str = obj.get("grade", "")
        grade_map = {"상": Grade.HIGH, "중": Grade.MID, "하": Grade.LOW}
        grade = grade_map.get(grade_str)

        # data_status 변환
        status_map = {
            "정상": DataStatus.OK,
            "부족": DataStatus.LACK,
            "누락": DataStatus.MISSING,
        }
        data_status = status_map.get(obj.get("data_status", "정상"), DataStatus.OK)

        # evidence 변환
        evidence_raw = obj.get("evidence", [])
        evidence: list[Evidence] = []
        if isinstance(evidence_raw, list):
            for ev in evidence_raw:
                if isinstance(ev, dict):
                    evidence.append(
                        Evidence(
                            doc=ev.get("doc", ""),
                            quote=ev.get("quote", ""),
                            location=ev.get("location", ""),
                        )
                    )

        reinforceable = grade in (Grade.MID, Grade.LOW) or data_status in (
            DataStatus.LACK,
            DataStatus.MISSING,
        )

        items.append(
            ReviewItem(
                item=obj.get("item", ""),
                opinion=obj.get("opinion", ""),
                grade=grade,
                data_status=data_status,
                evidence=evidence,
                reinforceable=reinforceable,
            )
        )

    # 항목 수가 부족하면 누락 항목 보충
    found_names = {i.item for i in items}
    for name in REVIEW_ITEMS:
        if name not in found_names:
            items.append(ReviewItem(item=name, opinion="합성 누락 — 재시도 필요", data_status=DataStatus.MISSING))

    return items


def _default_items(reason: str) -> list[ReviewItem]:
    return [ReviewItem(item=name, opinion=reason, data_status=DataStatus.MISSING) for name in REVIEW_ITEMS]


# ---------------------------------------------------------------------------
# 각 단계별 분석 함수
# ---------------------------------------------------------------------------

async def _analyze_cpa(company_data: dict, context: str) -> str:
    fin = company_data.get("financial_statements", {})
    info = company_data.get("company_info", {})
    prompt = f"""아래 기업의 재무 데이터를 분석하여 상환재원과 금리결정 적정성 관련 의견을 작성하세요.

기업정보:
{json.dumps(info, ensure_ascii=False, default=str)[:800]}

재무제표:
{json.dumps(fin, ensure_ascii=False, default=str)[:1000]}

참조 컨텍스트:
{context[:1200]}

분석 항목: 부채비율, 이자보상배율(ICR), 영업이익률, 매출 추이, DSCR
데이터 없는 수치는 추정하지 말고 "데이터 누락"으로 표시하세요.
분석 결과를 간결하게 작성하세요 (500자 이내)."""
    return await _chat_async(_SYSTEM["수석 CPA"], prompt, max_tokens=800)


async def _analyze_industry(company_data: dict, context: str) -> str:
    info = company_data.get("company_info", {})
    loan = company_data.get("loan_request", {})
    prompt = f"""아래 기업의 업종 및 기술력을 분석하여 업체현황(산업), 기술금융&ESG, 자금용도 관련 의견을 작성하세요.

기업정보:
{json.dumps(info, ensure_ascii=False, default=str)[:800]}

대출 요청:
{json.dumps(loan, ensure_ascii=False, default=str)[:400]}

참조 컨텍스트 (과거 사례):
{context[:1200]}

분석: 업종 특성, 기술 경쟁력, ESG 리스크, 자금 용도의 산업 타당성
데이터 없는 항목은 "데이터 누락"으로 표시하세요.
분석 결과를 간결하게 작성하세요 (500자 이내)."""
    return await _chat_async(_SYSTEM["산업 애널리스트"], prompt, max_tokens=800)


async def _analyze_reputation(company_data: dict, context: str) -> str:
    info = company_data.get("company_info", {})
    prompt = f"""아래 기업의 비재무 리스크를 분석하여 특이사항 및 미이행 승인조건 관련 의견을 작성하세요.

기업정보:
{json.dumps(info, ensure_ascii=False, default=str)[:800]}

참조 컨텍스트:
{context[:1200]}

분석: 소송·체납 이력, 신용등급 하락 이력, 지배구조 리스크, 경영진 이력
잠재 리스크를 우선 가정하고 검증하는 방식으로 서술하세요.
근거 없는 단정은 하지 말고 "데이터 누락"으로 표시하세요 (500자 이내)."""
    return await _chat_async(_SYSTEM["평판 리스크 탐지관"], prompt, max_tokens=800)


async def _evaluate_underwriter(analyses: dict[str, str], context: str) -> str:
    prompt = f"""아래 3명의 분석 결과를 규정·여신 정책 관점에서 검토하여 종합의견과 미이행 승인조건을 보완하세요.

수석 CPA 분석:
{analyses['cpa'][:600]}

산업 애널리스트 분석:
{analyses['industry'][:600]}

평판 리스크 탐지관 분석:
{analyses['reputation'][:600]}

참조 규정:
{context[:800]}

검토: 규정 적합성, 한도·담보 적정성, 승인 전제조건 도출
규정을 인용하며 엄정하게 평가하세요 (400자 이내)."""
    return await _chat_async(_SYSTEM["본부 수석 심사역"], prompt, max_tokens=600)


async def _evaluate_rm(company_data: dict, analyses: dict[str, str]) -> str:
    loan = company_data.get("loan_request", {})
    prompt = f"""아래 분석 결과에 현장 관점 정보를 보완하세요.

대출 요청:
{json.dumps(loan, ensure_ascii=False, default=str)[:400]}

수석 CPA 분석:
{analyses['cpa'][:400]}

산업 애널리스트 분석:
{analyses['industry'][:400]}

현장 관점: 자금 용도의 현실성, 서류에 드러나지 않는 정성 정보 보완
영업점장 특별의견은 현장 담당자가 직접 작성해야 하므로 AI가 초안을 작성하지 않습니다.
보완 의견을 간결하게 작성하세요 (300자 이내)."""
    return await _chat_async(_SYSTEM["기업영업 RM"], prompt, max_tokens=500)


async def _verify_critic(all_analyses: str) -> tuple[str, bool]:
    """
    검증관이 분석을 반박한다.
    반환: (검증관 발언, 재조사_필요_여부)
    재조사 불필요 판단은 발언에 '합의' 또는 '이의 없음' 포함 시.
    """
    prompt = f"""아래 5명의 분석을 검토하여 근거 부족·논리 허점·누락 항목을 지적하세요.

{all_analyses[:2000]}

지적 사항이 없으면 "합의 충분 — 이의 없음"으로 응답하세요.
지적이 있으면 구체적으로 어떤 근거가 부족한지 명시하세요 (300자 이내)."""
    response = await _chat_async(_SYSTEM["여신심사 검증관"], prompt, max_tokens=500)
    is_resolved = "이의 없음" in response or "합의 충분" in response
    return response, is_resolved


async def _synthesize_chair(
    company_data: dict,
    context: str,
    analyses: dict[str, str],
    evaluations: dict[str, str],
    critic_opinion: str,
) -> list[ReviewItem]:
    """의장이 7명 의견을 종합하여 9개 항목 JSON을 생성한다."""
    company_summary = _summarize_company(company_data)

    prompt = f"""당신은 여신심사 토론의 의장입니다. 7명의 분석을 종합하여 9개 심사 항목의 최종 초안을 JSON으로 작성하세요.

기업 요약:
{company_summary}

[수석 CPA 분석]
{analyses['cpa'][:500]}

[산업 애널리스트 분석]
{analyses['industry'][:500]}

[평판 리스크 탐지관 분석]
{analyses['reputation'][:500]}

[본부 수석 심사역 평가]
{evaluations['underwriter'][:400]}

[기업영업 RM 보완]
{evaluations['rm'][:300]}

[여신심사 검증관 지적]
{critic_opinion[:300]}

[참조 컨텍스트]
{context[:600]}

아래 9개 항목 각각에 대해 JSON 객체를 작성하세요:
{json.dumps(REVIEW_ITEMS, ensure_ascii=False)}

출력 형식 (JSON 배열만, 다른 텍스트 없음):
[
  {{
    "item": "항목명",
    "opinion": "심사의견 (마크다운 허용, 2~4문장)",
    "grade": "상|중|하",
    "data_status": "정상|부족|누락",
    "evidence": [{{"doc": "문서명", "quote": "인용구", "location": ""}}]
  }},
  ...
]

중요 규칙:
- 검색 근거에 없는 수치를 지어내지 마세요.
- 영업점장 특별의견(항목 9)의 opinion은 반드시 빈 문자열("")로 설정하세요.
- 데이터가 없으면 data_status를 "누락"으로 설정하세요.
- 반드시 JSON 배열만 반환하고 다른 텍스트는 절대 쓰지 마세요."""

    raw = await _chat_async(_SYSTEM["의장"], prompt, max_tokens=3000)
    return _parse_review_items(raw)


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------

async def run_discussion(
    business_id: str,
    company_data: dict,
    reviewer: str,
) -> AsyncGenerator[str, None]:
    """
    7명 토론을 실행하고 진행 상황을 SSE 문자열로 스트리밍한다.

    SSE 형식: `data: [에이전트명] 발언 내용\n\n`
    최종 결과: `data: RESULT:{JSON}\n\n`

    Args:
        business_id: 사업자등록번호
        company_data: 구조화된 기업·재무 데이터 딕셔너리
        reviewer: 배정 심사역 이름 (RAG 필터에 사용)
    """
    # ------------------------------------------------------------------
    # 1단계: 의장 개회 + RAG 검색
    # ------------------------------------------------------------------
    yield f"data: [의장] 여신심사 토론을 개회합니다. 사업자번호 {business_id} 심사를 시작합니다.\n\n"

    company_summary = _summarize_company(company_data)

    # RAG: 배정 심사역 과거 사례 + 규정 병렬 검색
    try:
        rag_cases, rag_rules = await asyncio.gather(
            _rag_async(company_summary, top=3, reviewer_filter=reviewer),
            _rag_async("여신심사 규정 부채비율 이자보상배율 담보 신용등급", top=3),
        )
    except Exception:
        rag_cases, rag_rules = [], []

    context = _build_context(rag_cases, rag_rules)

    yield (
        f"data: [의장] RAG 검색 완료 — "
        f"과거 사례 {len(rag_cases)}건, 규정 {len(rag_rules)}건 참조합니다.\n\n"
    )

    # ------------------------------------------------------------------
    # 토론 루프 (최대 3회, 합의 수렴 시 조기 종료)
    # ------------------------------------------------------------------
    analyses: dict[str, str] = {}
    evaluations: dict[str, str] = {}
    critic_opinion: str = ""

    for round_no in range(1, 4):
        if round_no > 1:
            yield f"data: [의장] 재조사 {round_no}회차를 시작합니다.\n\n"

        # ---------------------------------------------------------------
        # 2단계: 3명 독립 분석 (순차 — SSE 스트리밍 순서 보장)
        # ---------------------------------------------------------------
        yield "data: [수석 CPA] 재무제표 분석을 시작합니다.\n\n"
        try:
            cpa_result = await _analyze_cpa(company_data, context)
        except Exception as e:
            cpa_result = f"재무 분석 오류: {e}"
        analyses["cpa"] = cpa_result
        yield f"data: [수석 CPA] {cpa_result}\n\n"

        yield "data: [산업 애널리스트] 업종 및 기술력 분석을 시작합니다.\n\n"
        try:
            industry_result = await _analyze_industry(company_data, context)
        except Exception as e:
            industry_result = f"산업 분석 오류: {e}"
        analyses["industry"] = industry_result
        yield f"data: [산업 애널리스트] {industry_result}\n\n"

        yield "data: [평판 리스크 탐지관] 비재무 리스크 탐지를 시작합니다.\n\n"
        try:
            reputation_result = await _analyze_reputation(company_data, context)
        except Exception as e:
            reputation_result = f"리스크 탐지 오류: {e}"
        analyses["reputation"] = reputation_result
        yield f"data: [평판 리스크 탐지관] {reputation_result}\n\n"

        # ---------------------------------------------------------------
        # 3단계: 2명 교차 평가
        # ---------------------------------------------------------------
        yield "data: [본부 수석 심사역] 규정 적합성 및 종합의견 검토를 시작합니다.\n\n"
        try:
            underwriter_result = await _evaluate_underwriter(analyses, context)
        except Exception as e:
            underwriter_result = f"규정 검토 오류: {e}"
        evaluations["underwriter"] = underwriter_result
        yield f"data: [본부 수석 심사역] {underwriter_result}\n\n"

        yield "data: [기업영업 RM] 현장 관점 정보를 보완합니다.\n\n"
        try:
            rm_result = await _evaluate_rm(company_data, analyses)
        except Exception as e:
            rm_result = f"현장 보완 오류: {e}"
        evaluations["rm"] = rm_result
        yield f"data: [기업영업 RM] {rm_result}\n\n"

        # ---------------------------------------------------------------
        # 4단계: 검증관 반박
        # ---------------------------------------------------------------
        yield "data: [여신심사 검증관] 5명의 분석을 교차 검증합니다.\n\n"

        all_analyses = (
            f"[수석 CPA]\n{analyses['cpa']}\n\n"
            f"[산업 애널리스트]\n{analyses['industry']}\n\n"
            f"[평판 리스크 탐지관]\n{analyses['reputation']}\n\n"
            f"[본부 수석 심사역]\n{evaluations['underwriter']}\n\n"
            f"[기업영업 RM]\n{evaluations['rm']}"
        )

        try:
            critic_opinion, is_resolved = await _verify_critic(all_analyses)
        except Exception as e:
            critic_opinion = f"검증 오류: {e}"
            is_resolved = True  # 오류 시 강제 종료

        yield f"data: [여신심사 검증관] {critic_opinion}\n\n"

        if is_resolved:
            yield f"data: [의장] 검증관 이의 없음 — {round_no}회차 토론으로 합의를 수렴합니다.\n\n"
            break

        # 재조사 필요 시 다음 루프에서 보강 컨텍스트 반영
        if round_no < 3:
            yield "data: [의장] 검증관 지적 사항이 있습니다. 재조사를 진행합니다.\n\n"
            # 재조사 컨텍스트: 검증관 지적 사항을 추가 RAG 쿼리로 보강
            try:
                extra_cases = await _rag_async(critic_opinion[:200], top=2)
                if extra_cases:
                    extra_text = "\n---\n".join(c["content"][:300] for c in extra_cases)
                    context = context + f"\n\n[재조사 추가 문서]\n{extra_text}"
            except Exception:
                pass
    else:
        yield "data: [의장] 최대 3회 루프 완료 — 현재 합의 수준으로 항목을 합성합니다.\n\n"

    # ------------------------------------------------------------------
    # 5단계: 의장 합성 → 9개 항목 JSON
    # ------------------------------------------------------------------
    yield "data: [의장] 7명 분석을 종합하여 9개 심사 항목을 합성합니다.\n\n"

    try:
        items = await _synthesize_chair(company_data, context, analyses, evaluations, critic_opinion)
    except Exception as e:
        items = _default_items(f"의장 합성 오류: {e}")

    yield "data: [의장] 심사 초안 생성이 완료되었습니다. (AI 생성 초안 — 최종 결정은 심사역이 합니다.)\n\n"

    yield f"data: RESULT:{json.dumps([i.model_dump() for i in items], ensure_ascii=False)}\n\n"
