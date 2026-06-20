"""
7명 AI 토론 오케스트레이션 — 실제 구현

토론 순서 (REVIEW_AGENTS.md):
  1. 의장 개회 + RAG 검색 (배정 심사역 과거 사례 + 규정)
  2. 수석 CPA / 산업 애널리스트 / 평판 리스크 탐지관 독립 분석
  3. 본부 수석 심사역 / 기업영업 RM 교차 평가
  4. 여신심사 검증관 반박 (필요시 재조사 루프, 최대 3회)
  5. 의장 합성 → 9개 항목 JSON 반환

SSE 이벤트 형식 (프론트 연동):
  {"type": "agent_message", "agent_idx": 0, "agent_name": "의장", "text": "...", "is_typing": false}
  {"type": "progress", "phase": "독립 분석 중...", "pct": 33}
  {"type": "items_ready", "items": [...]}
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncGenerator, Dict, List, Optional

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

# 9개 항목 id(1-based) → 프론트 표시명 (& 포함 버전)
ITEM_NAMES_DISPLAY = [
    "업체현황",
    "자금용도",
    "금리결정 적정성",
    "상환재원",
    "특이사항",
    "기술금융 & ESG",
    "종합의견",
    "미이행 승인조건",
    "영업점장 특별의견",
]

# 7명 agent 정의 (REVIEW_AGENTS.md)
AGENTS = [
    {"idx": 0, "name": "의장",            "role": "Lead Agent"},
    {"idx": 1, "name": "수석 CPA",        "role": "Financial Analyst"},
    {"idx": 2, "name": "산업 애널리스트",  "role": "Industry Analyst"},
    {"idx": 3, "name": "평판 리스크 탐지관", "role": "Non-Financial Analyst"},
    {"idx": 4, "name": "본부 수석 심사역", "role": "Underwriter"},
    {"idx": 5, "name": "기업영업 RM",      "role": "Relationship Manager"},
    {"idx": 6, "name": "여신심사 검증관",  "role": "Critic / Verifier"},
]

_AGENT_NAME_TO_KEY: dict[str, str] = {
    "수석 CPA": "cpa",
    "산업 애널리스트": "industry",
    "평판 리스크 탐지관": "reputation",
    "본부 수석 심사역": "underwriter",
    "기업영업 RM": "rm",
}


def _criticized_agents(critic_text: str) -> set[str]:
    """검증관 지적 텍스트에서 언급된 에이전트 키 반환. 미언급 시 전체 재조사."""
    found = {key for name, key in _AGENT_NAME_TO_KEY.items() if name in critic_text}
    return found if found else set(_AGENT_NAME_TO_KEY.values())


# 각 agent의 system 프롬프트 (REVIEW_AGENTS.md 정의 기반)
_SYSTEM: dict[str, str] = {
    "의장": (
        "당신은 여신심사 토론의 의장입니다. 중립적으로 진행하며 최종 9개 항목을 합성합니다. "
        "검색 근거에 없는 수치를 지어내지 않습니다. 모든 출력은 초안 전제입니다."
    ),
    "수석 CPA": (
        "당신은 수석 CPA입니다. 재무제표 수치 기반으로 보수적으로 분석합니다. "
        "부채비율, ICR(내규 1.50배), DSCR(내규 1.25배), 영업이익률을 핵심으로 분석하며 "
        "추정에는 전제를 명시합니다. 근거 없는 수치를 생성하지 않습니다."
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

# Mock 메시지 (Azure 미설정 시)
MOCK_MESSAGES = [
    (0, "한양정밀테크 여신심사를 개회합니다. 각 에이전트는 담당 항목을 신속히 분석해 주십시오."),
    (1, "재무: CAGR 19.8%, 영업이익률 7.2% 양호. DSCR 1.18배(기준 1.25 미달). 상환재원 '하' 등급."),
    (2, "산업: 자동차 부품 전기차 전환 과도기이나, OEM 수주 확정으로 리스크 상쇄. 자금용도 '상' 등급."),
    (3, "평판: 연체·소송·체납 없음. 신용정보원 미제출 → '데이터 누락' 라벨."),
    (4, "규정: DSCR 미달이 핵심. 최근 6개월 매출자료 & DSCR 재산출 의무화 제안."),
    (6, "이의: 수석 CPA의 DSCR 산출에서 확정 계약서 없이 추정치 기입. 규정 위반 소지. 재조사 요청."),
    (1, "재조사: 현대모비스 수주확인서(32.4억) 확인. DSCR 1.18 → 1.31로 개선."),
    (5, "현장 확인: 공장 가동률 82%, 대표 사업 의지 우수, 수주 서류 확인 완료."),
    (0, "합의 수렴. 9개 항목 합성 시작. 최종 권고: 조건부 승인 [AI 초안 — 최종 결정은 심사역]"),
]

PHASES = [
    "문서 파싱 중...",
    "토론 진행 중...",
    "독립 분석...",
    "독립 분석...",
    "독립 분석...",
    "교차 평가...",
    "교차 평가...",
    "검증 검토...",
    "항목 합성...",
]


# ---------------------------------------------------------------------------
# SSE 헬퍼
# ---------------------------------------------------------------------------

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _agent_msg(agent_idx: int, agent_name: str, text: str, is_typing: bool) -> str:
    return _sse({
        "type": "agent_message",
        "agent_idx": agent_idx,
        "agent_name": agent_name,
        "text": text,
        "is_typing": is_typing,
    })


# ---------------------------------------------------------------------------
# 내부 유틸
# ---------------------------------------------------------------------------

def _summarize_company(company_data: dict) -> str:
    info = company_data.get("company_info", {})
    fin = company_data.get("financial_statements", {})
    sales = company_data.get("sales_data", {}).get("annual_sales_by_year", {})
    collateral = company_data.get("collateral_auction_value", {})
    assets = fin.get("total_assets", 0) or 0
    liab = fin.get("total_liabilities", 0) or 0
    equity = assets - liab if assets else 0
    op_inc = fin.get("operating_income", 0) or 0
    interest = fin.get("finance_cost_interest", 1) or 1
    debt_ratio = round(liab / equity * 100, 1) if equity > 0 else "N/A"
    icr = round(op_inc / interest, 2) if interest else "N/A"

    lines = [
        f"기업명: {info.get('company_name', 'N/A')}",
        f"내부등급: {info.get('internal_credit_rating', 'N/A')}",
        f"업종코드: {info.get('industry_code', 'N/A')}",
        f"총자산: {round(assets / 1e8, 1)}억",
        f"총부채: {round(liab / 1e8, 1)}억",
        f"자기자본: {round(equity / 1e8, 1)}억",
        f"부채비율: {debt_ratio}%",
        f"영업이익: {round(op_inc / 1e8, 1)}억",
        f"ICR(이자보상배율): {icr}배",
    ]
    if sales:
        for yr, val in sorted(sales.items()):
            lines.append(f"매출액({yr}): {round(val / 1e8, 1)}억")
    if collateral:
        appr = collateral.get("collateral_appraisal_value", 0)
        rate = collateral.get("regional_auction_rate_1yr", 0)
        cnt = collateral.get("regional_auction_count_1yr", 0)
        if appr:
            lines.append(f"담보감정가: {round(appr / 1e8, 1)}억")
            lines.append(f"지역낙찰가율: {round(rate * 100, 1)}%")
            lines.append(f"지역낙찰건수: {cnt}건")
    return " | ".join(lines)


def _build_context(cases: list[dict], rules: list[dict]) -> str:
    case_text = "\n---\n".join(c["content"][:500] for c in cases) if cases else "해당 심사역 과거 사례 없음"
    rule_text = "\n---\n".join(r["content"][:300] for r in rules) if rules else "규정 문서 검색 결과 없음"
    return f"[과거 심사 사례]\n{case_text}\n\n[규정]\n{rule_text}"


async def _chat_async(system: str, user: str, max_tokens: int = 1200) -> str:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return await asyncio.to_thread(chat, messages, max_tokens)


async def _rag_async(query: str, top: int = 3, reviewer_filter: Optional[str] = None) -> list[dict]:
    return await asyncio.to_thread(rag_search, query, top, reviewer_filter)


def _parse_review_items(raw: str) -> list[ReviewItem]:
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return _default_items("JSON 파싱 실패 — 의장 재합성 필요")
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return _default_items("JSON 파싱 실패 — 의장 재합성 필요")

    items: list[ReviewItem] = []
    grade_map = {"상": Grade.HIGH, "중": Grade.MID, "하": Grade.LOW}
    status_map = {
        "정상": DataStatus.OK,
        "부족": DataStatus.LACK,
        "누락": DataStatus.MISSING,
    }

    for obj in parsed:
        if not isinstance(obj, dict):
            continue
        grade = grade_map.get(obj.get("grade", ""))
        data_status = status_map.get(obj.get("data_status", "정상"), DataStatus.OK)
        evidence_raw = obj.get("evidence", [])
        evidence: list[Evidence] = []
        if isinstance(evidence_raw, list):
            for ev in evidence_raw:
                if isinstance(ev, dict):
                    evidence.append(Evidence(
                        doc=ev.get("doc", ""),
                        quote=ev.get("quote", ""),
                        location=ev.get("location", ""),
                    ))
        reinforceable = grade in (Grade.MID, Grade.LOW) or data_status in (
            DataStatus.LACK, DataStatus.MISSING
        )
        items.append(ReviewItem(
            item=obj.get("item", ""),
            opinion=obj.get("opinion", ""),
            grade=grade,
            data_status=data_status,
            evidence=evidence,
            reinforceable=reinforceable,
        ))

    found_names = {i.item for i in items}
    for name in REVIEW_ITEMS:
        if name not in found_names:
            items.append(ReviewItem(item=name, opinion="합성 누락", data_status=DataStatus.MISSING))
    return items


def _default_items(reason: str) -> list[ReviewItem]:
    return [ReviewItem(item=name, opinion=reason, data_status=DataStatus.MISSING) for name in REVIEW_ITEMS]


def _items_to_frontend(items: list[ReviewItem]) -> list[dict]:
    """ReviewItem(내부 스키마) → 프론트 연동 형식 변환."""
    # 등급 표시 없는 항목 (자금용도=2, 영업점장 특별의견=9)
    NO_GRADE_NAMES = {"자금용도", "영업점장 특별의견"}
    # 자금용도·종합의견·영업점장 특별의견은 징구서류 배지 불필요 (sidebar 6개와 일치)
    NO_BADGE_NAMES = {"자금용도", "종합의견", "영업점장 특별의견"}

    result = []
    for i, item in enumerate(items):
        name = item.item
        # 프론트 표시명 (& 포함)
        display_name = ITEM_NAMES_DISPLAY[i] if i < len(ITEM_NAMES_DISPLAY) else name
        is_no_grade = name.replace("&", "& ").replace("기술금융& ESG", "기술금융 & ESG") in NO_GRADE_NAMES or name in NO_GRADE_NAMES

        # grade 변환
        grade_val = None
        if item.grade and not is_no_grade:
            grade_val = item.grade.value if hasattr(item.grade, "value") else str(item.grade)

        # doc_status 변환 — 자금용도도 징구서류 배지는 표시
        doc_status_val = None
        if name not in NO_BADGE_NAMES and item.data_status:
            raw_status = item.data_status.value if hasattr(item.data_status, "value") else str(item.data_status)
            # "정상" → "충족", "부족" → "부족", "누락" → "부족"
            doc_status_val = "충족" if raw_status == "정상" else "부족"

        result.append({
            "id": i + 1,
            "name": display_name,
            "grade": grade_val,
            "doc_status": doc_status_val,
            "show_doc_badge": name not in NO_BADGE_NAMES,
            "opinion": item.opinion,
            "evidence": [e.model_dump() for e in item.evidence],
            "can_reinforce_persuasion": grade_val in ("중", "하"),
            "can_reinforce_documents": doc_status_val == "부족",
        })
    return result


# ---------------------------------------------------------------------------
# 각 단계별 분석 함수
# ---------------------------------------------------------------------------

async def _analyze_cpa(company_data: dict, context: str) -> str:
    fin = company_data.get("financial_statements", {})
    info = company_data.get("company_info", {})
    sales = company_data.get("sales_data", {}).get("annual_sales_by_year", {})
    collateral = company_data.get("collateral_auction_value", {})
    prompt = (
        f"아래 기업의 재무 데이터를 분석하여 상환재원과 금리결정 적정성 관련 의견을 작성하세요.\n\n"
        f"기업정보:\n{json.dumps(info, ensure_ascii=False, default=str)[:800]}\n\n"
        f"재무제표:\n{json.dumps(fin, ensure_ascii=False, default=str)[:1000]}\n\n"
        f"연도별 매출액:\n{json.dumps(sales, ensure_ascii=False, default=str)[:500]}\n\n"
        f"담보·낙찰정보:\n{json.dumps(collateral, ensure_ascii=False, default=str)[:500]}\n\n"
        f"참조 컨텍스트:\n{context[:1200]}\n\n"
        "분석 항목: 부채비율, 이자보상배율(ICR), 영업이익률, 매출 추이(CAGR), DSCR, 담보 LTV\n"
        "표 사용 금지. 수치는 '항목: 수치 (내규기준 N — 판정)' 형식으로 한 줄씩 서술하세요.\n"
        "데이터 없는 수치는 추정하지 말고 '데이터 누락'으로 표시하세요.\n"
        "마지막 줄에 반드시 '요약: [핵심 판정 한 문장]' 형식으로 마무리하세요. (700자 이내)"
    )
    return await _chat_async(_SYSTEM["수석 CPA"], prompt, max_tokens=1600)


async def _analyze_industry(company_data: dict, context: str) -> str:
    info = company_data.get("company_info", {})
    loan = company_data.get("loan_request", {})
    prompt = (
        f"아래 기업의 업종 및 기술력을 분석하여 업체현황(산업), 기술금융&ESG, 자금용도 관련 의견을 작성하세요.\n\n"
        f"기업정보:\n{json.dumps(info, ensure_ascii=False, default=str)[:800]}\n\n"
        f"대출 요청:\n{json.dumps(loan, ensure_ascii=False, default=str)[:400]}\n\n"
        f"참조 컨텍스트:\n{context[:1200]}\n\n"
        "표 사용 금지. 데이터 없는 항목은 '데이터 누락'으로 표시하세요.\n"
        "마지막 줄에 반드시 '요약: [핵심 판정 한 문장]' 형식으로 마무리하세요. (500자 이내)"
    )
    return await _chat_async(_SYSTEM["산업 애널리스트"], prompt, max_tokens=1200)


async def _analyze_reputation(company_data: dict, context: str) -> str:
    info = company_data.get("company_info", {})
    prompt = (
        f"아래 기업의 비재무 리스크를 분석하여 특이사항 및 미이행 승인조건 관련 의견을 작성하세요.\n\n"
        f"기업정보:\n{json.dumps(info, ensure_ascii=False, default=str)[:800]}\n\n"
        f"참조 컨텍스트:\n{context[:1200]}\n\n"
        "표 사용 금지. 잠재 리스크를 우선 가정하고 검증하는 방식으로 서술하세요. "
        "근거 없는 단정은 하지 말고 '데이터 누락'으로 표시하세요.\n"
        "마지막 줄에 반드시 '요약: [핵심 판정 한 문장]' 형식으로 마무리하세요. (500자 이내)"
    )
    return await _chat_async(_SYSTEM["평판 리스크 탐지관"], prompt, max_tokens=1000)


async def _evaluate_underwriter(analyses: dict[str, str], context: str) -> str:
    prompt = (
        "아래 3명의 분석 결과를 규정·여신 정책 관점에서 검토하여 종합의견과 미이행 승인조건을 보완하세요.\n\n"
        f"[수석 CPA]\n{analyses['cpa'][:600]}\n\n"
        f"[산업 애널리스트]\n{analyses['industry'][:600]}\n\n"
        f"[평판 리스크 탐지관]\n{analyses['reputation'][:600]}\n\n"
        f"참조 규정:\n{context[:800]}\n\n"
        "표 사용 금지. 규정을 인용하며 엄정하게 평가하세요.\n"
        "마지막 줄에 반드시 '요약: [핵심 판정 한 문장]' 형식으로 마무리하세요. (400자 이내)"
    )
    return await _chat_async(_SYSTEM["본부 수석 심사역"], prompt, max_tokens=800)


async def _evaluate_rm(company_data: dict, analyses: dict[str, str]) -> str:
    loan = company_data.get("loan_request", {})
    prompt = (
        "아래 분석 결과에 현장 관점 정보를 보완하세요.\n\n"
        f"대출 요청:\n{json.dumps(loan, ensure_ascii=False, default=str)[:400]}\n\n"
        f"[수석 CPA]\n{analyses['cpa'][:400]}\n\n"
        f"[산업 애널리스트]\n{analyses['industry'][:400]}\n\n"
        "표 사용 금지. 영업점장 특별의견은 AI가 초안을 작성하지 않습니다. 현장 보완 의견만 작성하세요.\n"
        "마지막 줄에 반드시 '요약: [핵심 판정 한 문장]' 형식으로 마무리하세요. (300자 이내)"
    )
    return await _chat_async(_SYSTEM["기업영업 RM"], prompt, max_tokens=700)


async def _verify_critic(all_analyses: str) -> tuple[str, bool]:
    prompt = (
        f"아래 5명의 분석을 검토하여 근거 부족·논리 허점·누락 항목을 지적하세요.\n\n"
        f"{all_analyses[:2000]}\n\n"
        "표 사용 금지. 각 지적은 반드시 '에이전트명: 지적 내용' 형식으로 명시하세요 (예: '수석 CPA: DSCR 산출 근거 부족'). "
        "지적 사항이 없으면 '합의 충분 — 이의 없음'으로 응답하세요.\n"
        "마지막 줄에 반드시 '요약: [검증 결과 한 문장]' 형식으로 마무리하세요. (300자 이내)"
    )
    response = await _chat_async(_SYSTEM["여신심사 검증관"], prompt, max_tokens=700)
    is_resolved = "이의 없음" in response or "합의 충분" in response
    return response, is_resolved


async def _synthesize_chair(
    company_data: dict,
    context: str,
    analyses: dict[str, str],
    evaluations: dict[str, str],
    critic_opinion: str,
) -> list[ReviewItem]:
    company_summary = _summarize_company(company_data)
    prompt = (
        "당신은 여신심사 토론의 의장입니다. 7명의 분석을 종합하여 9개 심사 항목의 최종 초안을 JSON으로 작성하세요.\n\n"
        f"기업 요약:\n{company_summary}\n\n"
        f"[수석 CPA]\n{analyses.get('cpa','')[:800]}\n\n"
        f"[산업 애널리스트]\n{analyses.get('industry','')[:800]}\n\n"
        f"[평판 리스크 탐지관]\n{analyses.get('reputation','')[:600]}\n\n"
        f"[본부 수석 심사역]\n{evaluations.get('underwriter','')[:600]}\n\n"
        f"[기업영업 RM]\n{evaluations.get('rm','')[:400]}\n\n"
        f"[여신심사 검증관]\n{critic_opinion[:400]}\n\n"
        f"참조 컨텍스트:\n{context[:800]}\n\n"
        f"아래 9개 항목 각각에 대해 JSON 객체를 작성하세요:\n"
        f"{json.dumps(REVIEW_ITEMS, ensure_ascii=False)}\n\n"
        "출력 형식 (JSON 배열만, 다른 텍스트 없음):\n"
        '[\n  {"item": "항목명", "opinion": "심사의견 HTML (표 적극 활용, 마지막 줄에 요약: [한 문장] 필수)", "grade": "상|중|하", '
        '"data_status": "정상|부족|누락", "evidence": [{"doc": "문서명", "quote": "인용구", "location": ""}]},\n  ...\n]\n\n'
        "중요 규칙:\n"
        "- opinion에 HTML 표(<table class='op-table'>)를 적극 활용하세요. 특히 상환재원, 업체현황, 금리결정 적정성, 종합의견은 핵심 수치를 표로 정리해야 합니다.\n"
        "- 표 예시: <table class='op-table'><thead><tr><th>지표</th><th>수치</th><th>내규기준</th><th>판정</th></tr></thead><tbody>...</tbody></table>\n"
        "- 각 opinion 마지막 줄에 반드시 '요약: [핵심 판정 한 문장]' 형식으로 마무리하세요.\n"
        "- evidence의 doc은 실제 입력된 데이터 출처만 사용하세요: '재무제표(2024)', '부가세과세표준증명', '소득금액증명원', '담보감정평가서', '내부신용등급 조회' 등. 가상 문서명 금지.\n"
        "- evidence의 quote는 해당 데이터에서 가져온 실제 수치를 인용하세요.\n"
        "- 검색 근거에 없는 수치를 지어내지 마세요.\n"
        "- 자금용도의 opinion은 반드시 빈 문자열(\"\")로 설정하세요. grade는 null, data_status는 '정상'으로 설정하세요.\n"
        "- 영업점장 특별의견의 opinion은 반드시 빈 문자열(\"\")로 설정하세요.\n"
        "- 데이터가 없으면 data_status를 '누락'으로 설정하세요.\n"
        "- 반드시 JSON 배열만 반환하고 다른 텍스트는 절대 쓰지 마세요."
    )
    raw = await _chat_async(_SYSTEM["의장"], prompt, max_tokens=5000)
    return _parse_review_items(raw)


# ---------------------------------------------------------------------------
# 공개 API — 기존 cases 라우터용 (레거시 호환)
# ---------------------------------------------------------------------------

async def run_discussion(
    business_id: str,
    company_data: dict,
    reviewer: str,
) -> AsyncGenerator[str, None]:
    """
    7명 토론 실행. cases 라우터에서 호출하는 레거시 인터페이스.
    SSE 형식: `data: [에이전트명] 발언 내용\n\n`
    최종 결과: `data: RESULT:{JSON}\n\n`
    """
    yield f"data: [의장] 여신심사 토론을 개회합니다. 사업자번호 {business_id} 심사를 시작합니다.\n\n"

    company_summary = _summarize_company(company_data)
    try:
        rag_cases, rag_rules = await asyncio.gather(
            _rag_async(company_summary, top=3, reviewer_filter=reviewer),
            _rag_async("여신심사 규정 부채비율 이자보상배율 담보 신용등급", top=3),
        )
    except Exception:
        rag_cases, rag_rules = [], []

    context = _build_context(rag_cases, rag_rules)
    yield f"data: [의장] RAG 검색 완료 — 과거 사례 {len(rag_cases)}건, 규정 {len(rag_rules)}건 참조합니다.\n\n"

    analyses: dict[str, str] = {}
    evaluations: dict[str, str] = {}
    critic_opinion: str = ""
    criticized_keys: set[str] = set()

    for round_no in range(1, 4):
        if round_no > 1:
            yield f"data: [의장] 재조사 {round_no}회차를 시작합니다.\n\n"

        if round_no == 1 or "cpa" in criticized_keys:
            yield "data: [수석 CPA] 재무제표 분석을 시작합니다.\n\n"
            try:
                analyses["cpa"] = await _analyze_cpa(company_data, context)
            except Exception as e:
                analyses["cpa"] = f"재무 분석 오류: {e}"
            yield f"data: [수석 CPA] {analyses['cpa']}\n\n"

        if round_no == 1 or "industry" in criticized_keys:
            yield "data: [산업 애널리스트] 업종 및 기술력 분석을 시작합니다.\n\n"
            try:
                analyses["industry"] = await _analyze_industry(company_data, context)
            except Exception as e:
                analyses["industry"] = f"산업 분석 오류: {e}"
            yield f"data: [산업 애널리스트] {analyses['industry']}\n\n"

        if round_no == 1 or "reputation" in criticized_keys:
            yield "data: [평판 리스크 탐지관] 비재무 리스크 탐지를 시작합니다.\n\n"
            try:
                analyses["reputation"] = await _analyze_reputation(company_data, context)
            except Exception as e:
                analyses["reputation"] = f"리스크 탐지 오류: {e}"
            yield f"data: [평판 리스크 탐지관] {analyses['reputation']}\n\n"

        if round_no == 1 or "underwriter" in criticized_keys:
            yield "data: [본부 수석 심사역] 규정 적합성 및 종합의견 검토를 시작합니다.\n\n"
            try:
                evaluations["underwriter"] = await _evaluate_underwriter(analyses, context)
            except Exception as e:
                evaluations["underwriter"] = f"규정 검토 오류: {e}"
            yield f"data: [본부 수석 심사역] {evaluations['underwriter']}\n\n"

        if round_no == 1 or "rm" in criticized_keys:
            yield "data: [기업영업 RM] 현장 관점 정보를 보완합니다.\n\n"
            try:
                evaluations["rm"] = await _evaluate_rm(company_data, analyses)
            except Exception as e:
                evaluations["rm"] = f"현장 보완 오류: {e}"
            yield f"data: [기업영업 RM] {evaluations['rm']}\n\n"

        yield "data: [여신심사 검증관] 5명의 분석을 교차 검증합니다.\n\n"
        all_analyses = (
            f"[수석 CPA]\n{analyses.get('cpa', '')}\n\n"
            f"[산업 애널리스트]\n{analyses.get('industry', '')}\n\n"
            f"[평판 리스크 탐지관]\n{analyses.get('reputation', '')}\n\n"
            f"[본부 수석 심사역]\n{evaluations.get('underwriter', '')}\n\n"
            f"[기업영업 RM]\n{evaluations.get('rm', '')}"
        )
        try:
            critic_opinion, is_resolved = await _verify_critic(all_analyses)
        except Exception as e:
            critic_opinion = f"검증 오류: {e}"
            is_resolved = True
        yield f"data: [여신심사 검증관] {critic_opinion}\n\n"

        if not is_resolved:
            criticized_keys = _criticized_agents(critic_opinion)

        if is_resolved:
            yield f"data: [의장] 검증관 이의 없음 — {round_no}회차 토론으로 합의를 수렴합니다.\n\n"
            break
        if round_no < 3:
            yield "data: [의장] 검증관 지적 사항이 있습니다. 재조사를 진행합니다.\n\n"
            try:
                extra = await _rag_async(critic_opinion[:200], top=2)
                if extra:
                    context += "\n\n[재조사 추가 문서]\n" + "\n---\n".join(c["content"][:300] for c in extra)
            except Exception:
                pass
    else:
        yield "data: [의장] 최대 3회 루프 완료 — 현재 합의 수준으로 항목을 합성합니다.\n\n"

    yield "data: [의장] 7명 분석을 종합하여 9개 심사 항목을 합성합니다.\n\n"
    try:
        items = await _synthesize_chair(company_data, context, analyses, evaluations, critic_opinion)
    except Exception as e:
        items = _default_items(f"의장 합성 오류: {e}")

    yield "data: [의장] 심사 초안 생성이 완료되었습니다. (AI 생성 초안 — 최종 결정은 심사역이 합니다.)\n\n"
    yield f"data: RESULT:{json.dumps([i.model_dump() for i in items], ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# 공개 API — 프론트 직접 연동용 (새 /api/analysis/discuss 엔드포인트)
# ---------------------------------------------------------------------------

async def run_discussion_stream(req) -> AsyncGenerator[str, None]:
    """
    DiscussRequest를 받아 프론트 SSE 형식으로 스트리밍.

    Azure 설정 시: 실제 LLM 호출
    미설정 시: mock 메시지 + mock 항목 반환
    """
    from config import get_settings
    s = get_settings()
    use_azure = bool(s.azure_openai_endpoint and s.azure_openai_chat_deployment)

    if use_azure:
        # Azure 실제 토론
        yield _sse({"type": "progress", "phase": "RAG 컨텍스트 로딩...", "pct": 8})

        # DiscussRequest → company_data dict 변환
        fin_data: dict = {}
        if req.financial_statements:
            fin_data = req.financial_statements.model_dump()

        company_data = {
            "company_info": {
                "company_name": req.company.name,
                "business_id": req.company.business_no,
                "industry_code": req.company.industry,
                "founded_year": req.company.founded_year,
                "internal_credit_rating": req.company.internal_credit_rating,
                "dart_code": req.company.dart_code,
            },
            "loan_request": {
                "loan_amount": req.loan.amount,
                "loan_type": req.loan.type,
                "loan_term": req.loan.term,
                "collateral_type": req.loan.collateral_type,
                "purpose": req.loan.purpose,
            },
            "financial_statements": fin_data,
            "sales_data": req.sales_data.model_dump() if req.sales_data else {},
            "collateral_auction_value": req.collateral_auction_value.model_dump() if req.collateral_auction_value else {},
            "documents": [d.name for d in req.documents],
        }

        rag_query = f"{req.company.name} {req.company.industry} {req.loan.type} {req.loan.purpose}"
        try:
            rag_cases, rag_rules = await asyncio.gather(
                _rag_async(rag_query.strip(), top=3),
                _rag_async("여신심사 규정 부채비율 이자보상배율 DSCR 담보", top=3),
            )
        except Exception:
            rag_cases, rag_rules = [], []

        context = _build_context(rag_cases, rag_rules)
        yield _sse({"type": "progress", "phase": "토론 개회...", "pct": 15})

        # 의장 개회
        yield _agent_msg(0, "의장", "", True)
        doc_count = len(req.documents) if req.documents else 0
        doc_names = ", ".join(d.name for d in req.documents[:5]) if req.documents else "없음"
        fin = req.financial_statements
        fin_summary = (
            f"총자산 {round(fin.total_assets/1e8,1)}억 / 부채 {round(fin.total_liabilities/1e8,1)}억 / 영업이익 {round(fin.operating_income/1e8,1)}억"
            if fin and fin.total_assets else "재무정보 미확인"
        )
        chairman_open = await _chat_async(
            _SYSTEM["의장"],
            f"{req.company.name} 여신심사를 개회합니다.\n"
            f"접수 서류 {doc_count}건: {doc_names}.\n"
            f"재무 현황 요약: {fin_summary}.\n"
            f"RAG 검색 완료 — 과거 사례 {len(rag_cases)}건, 규정 {len(rag_rules)}건 참조.\n"
            f"각 에이전트는 담당 항목 분석을 시작해 주십시오.",
            max_tokens=200,
        )
        yield _agent_msg(0, "의장", chairman_open, False)

        analyses: dict[str, str] = {}
        evaluations: dict[str, str] = {}
        critic_opinion = ""
        criticized_keys: set[str] = set()

        # 최대 3라운드 토론 루프
        for round_no in range(1, 4):
            # 라운드 진행률 기준점 (round1: 0%, round2: +20%, round3: +13%)
            base = [0, 20, 33][round_no - 1]

            if round_no > 1:
                yield _sse({"type": "round", "round": round_no, "max": 3})
                yield _sse({"type": "progress", "phase": f"재조사 {round_no}회차...", "pct": 15 + base})
                yield _agent_msg(0, "의장", "", True)
                yield _agent_msg(0, "의장", f"검증관 지적 사항 접수 — {round_no}회차 재조사를 시작합니다.", False)

            # 5명 순차 분석
            agent_steps = [
                ("수석 CPA",          1, "독립 분석 중...",  20 + base),
                ("산업 애널리스트",    2, "독립 분석 중...",  28 + base),
                ("평판 리스크 탐지관", 3, "독립 분석 중...",  35 + base),
                ("본부 수석 심사역",   4, "교차 평가 중...",  41 + base),
                ("기업영업 RM",        5, "교차 평가 중...",  47 + base),
            ]
            agent_fns = {
                "수석 CPA":          ("cpa",         lambda: _analyze_cpa(company_data, context)),
                "산업 애널리스트":    ("industry",    lambda: _analyze_industry(company_data, context)),
                "평판 리스크 탐지관": ("reputation",  lambda: _analyze_reputation(company_data, context)),
                "본부 수석 심사역":   ("underwriter", lambda: _evaluate_underwriter(analyses, context)),
                "기업영업 RM":        ("rm",          lambda: _evaluate_rm(company_data, analyses)),
            }

            for name, idx, phase, pct in agent_steps:
                key, fn = agent_fns[name]
                if round_no > 1 and key not in criticized_keys:
                    continue
                yield _sse({"type": "progress", "phase": phase, "pct": min(pct, 78)})
                yield _agent_msg(idx, name, "", True)
                try:
                    result = await fn()
                except Exception as e:
                    result = f"[오류: {str(e)[:80]}]"
                if key in ("cpa", "industry", "reputation"):
                    analyses[key] = result
                else:
                    evaluations[key] = result
                yield _agent_msg(idx, name, result, False)
                await asyncio.sleep(0.1)

            # 검증관 반박
            yield _sse({"type": "progress", "phase": "검증관 반박 중...", "pct": min(53 + base, 83)})
            yield _agent_msg(6, "여신심사 검증관", "", True)
            all_txt = "\n\n".join(f"[{k}]\n{v}" for k, v in {**analyses, **evaluations}.items())
            try:
                critic_opinion, is_resolved = await _verify_critic(all_txt)
            except Exception as e:
                critic_opinion = f"검증 오류: {e}"
                is_resolved = True
            yield _agent_msg(6, "여신심사 검증관", critic_opinion, False)

            if not is_resolved:
                criticized_keys = _criticized_agents(critic_opinion)

            if is_resolved:
                yield _agent_msg(0, "의장", "", True)
                yield _agent_msg(0, "의장", f"검증관 이의 없음 — {round_no}회차 토론으로 합의를 수렴합니다.", False)
                break

            if round_no < 3:
                yield _agent_msg(0, "의장", "", True)
                yield _agent_msg(0, "의장", "검증관 지적 사항이 있습니다. 추가 자료를 검색하여 재조사를 진행합니다.", False)
                try:
                    extra = await _rag_async(critic_opinion[:200], top=2)
                    if extra:
                        context += "\n\n[재조사 추가 문서]\n" + "\n---\n".join(c["content"][:300] for c in extra)
                except Exception:
                    pass
        else:
            yield _agent_msg(0, "의장", "", True)
            yield _agent_msg(0, "의장", "최대 3회 루프 완료 — 현재 합의 수준으로 항목을 합성합니다.", False)

        # 의장 합성
        yield _sse({"type": "progress", "phase": "9개 항목 합성 중...", "pct": 90})
        yield _agent_msg(0, "의장", "", True)
        try:
            items = await _synthesize_chair(company_data, context, analyses, evaluations, critic_opinion)
        except Exception as e:
            items = _default_items(f"합성 오류: {e}")
        yield _agent_msg(0, "의장", "7명 분석 종합 완료. 9개 심사 항목 초안을 생성했습니다. [AI 초안 — 최종 결정은 심사역이 내립니다]", False)

        yield _sse({"type": "progress", "phase": "완료", "pct": 100})
        yield _sse({"type": "items_ready", "items": _items_to_frontend(items)})

    else:
        # Mock 모드
        total = len(MOCK_MESSAGES)
        for i, (agent_idx, text) in enumerate(MOCK_MESSAGES):
            pct = int((i + 1) / total * 88)
            phase = PHASES[min(i, len(PHASES) - 1)]
            yield _sse({"type": "progress", "phase": phase, "pct": pct})
            yield _agent_msg(agent_idx, AGENTS[agent_idx]["name"], "", True)
            await asyncio.sleep(0.7)
            yield _agent_msg(agent_idx, AGENTS[agent_idx]["name"], text, False)
            await asyncio.sleep(0.2)

        yield _sse({"type": "progress", "phase": "완료", "pct": 100})
        yield _sse({"type": "items_ready", "items": _items_to_frontend(_default_mock_items())})


def _default_mock_items() -> list[ReviewItem]:
    """Mock 항목 — ReviewItem 내부 스키마 형식."""
    return [
        ReviewItem(
            item="업체현황", grade=Grade.HIGH, data_status=DataStatus.OK,
            opinion=(
                "동사는 자동차 부품 제조를 주된 사업으로 영위하는 법인으로 사업영위기간 약 12년임. "
                "내부신용등급 A(양호)로 안정적인 재무 기반을 갖추고 있음."
                "<table class='op-table'><thead><tr><th>항목</th><th>2023</th><th>2024</th><th>2025</th></tr></thead>"
                "<tbody><tr><td>매출액</td><td>360억</td><td>373억</td><td>419억</td></tr>"
                "<tr><td>성장률</td><td>—</td><td>+3.6%</td><td>+12.4%</td></tr></tbody></table>"
                "요약: 매출 성장세와 A등급 신용도로 업체현황은 양호 수준으로 판단함."
            ),
            evidence=[
                Evidence(doc="재무제표(2024)", quote="총자산 713억, 총부채 117억, 영업이익 58억"),
                Evidence(doc="부가세과세표준증명", quote="최근1년 매출액 380억"),
                Evidence(doc="내부신용등급 조회", quote="내부등급 A"),
            ],
            reinforceable=False,
        ),
        ReviewItem(
            item="자금용도", grade=None, data_status=DataStatus.OK,
            opinion="",
            reinforceable=True,
        ),
        ReviewItem(
            item="금리결정 적정성", grade=Grade.MID, data_status=DataStatus.OK,
            opinion=(
                "금융채(변동) 6개월 기준금리 3.85% 적용, 가산금리 1.07% 부과 후 우대 반영 시 최종 적용금리 4.57% 신청."
                "<table class='op-table'><thead><tr><th>구분</th><th>금리</th><th>비고</th></tr></thead>"
                "<tbody><tr><td>기준금리</td><td>3.85%</td><td>금융채 6M</td></tr>"
                "<tr><td>가산금리</td><td>+1.07%</td><td>신용등급 A 기준</td></tr>"
                "<tr><td>우대금리</td><td>-0.35%</td><td>급여이체·적금 우대</td></tr>"
                "<tr><td style='font-weight:700'>최종 적용</td><td style='font-weight:700'>4.57%</td>"
                "<td>동종업종 평균 4.4~5.0%</td></tr></tbody></table>"
                "요약: 최종 금리 4.57%는 동종업종 평균 범위 내에 있어 적정 수준이나 우대 적용 근거 재확인 필요."
            ),
            evidence=[
                Evidence(doc="내부신용등급 조회", quote="A등급 — 가산금리 1.07%p 적용"),
            ],
            reinforceable=True,
        ),
        ReviewItem(
            item="상환재원", grade=Grade.LOW, data_status=DataStatus.LACK,
            opinion=(
                "이자보상배율(ICR)과 DSCR이 내규 기준에 미달함."
                "<table class='op-table'><thead><tr><th>지표</th><th>수치</th><th>내규기준</th><th>판정</th></tr></thead>"
                "<tbody><tr><td>부채비율</td><td>16.5%</td><td>200%</td>"
                "<td style='color:#2E7D32'>충족</td></tr>"
                "<tr><td>ICR</td><td>1.48배</td><td>1.50배</td>"
                "<td style='color:#C62828'>미달</td></tr>"
                "<tr><td>DSCR</td><td>1.18배</td><td>1.25배</td>"
                "<td style='color:#C62828'>미달</td></tr></tbody></table>"
                "수주확인서(32.4억) 반영 시 DSCR 1.31배로 기준 충족 예상. 최근 6개월 매출자료 징구 후 재산출 필요."
                "요약: ICR·DSCR 내규 미달로 상환재원 하 등급이나 수주 반영 시 개선 가능하여 조건부 징구 필요."
            ),
            evidence=[
                Evidence(doc="재무제표(2024)", quote="영업이익 58억, 이자비용 39억 → ICR 1.48배"),
                Evidence(doc="재무제표(2024)", quote="총부채 117억 / 자기자본 596억 → 부채비율 16.5%"),
            ],
            reinforceable=True,
        ),
        ReviewItem(
            item="특이사항", grade=Grade.HIGH, data_status=DataStatus.OK,
            opinion=(
                "심사일 현재 국세·지방세 체납 사실 없음 확인. 내부신용등급 A(양호)로 투자적격 등급. "
                "DART 공시 기준 최종 감사보고서 감사의견 '적정' 확인, 법적 이슈 없음.\n"
                "요약: 체납·법적 이슈 없이 신용등급 양호하여 특이사항 없음."
            ),
            evidence=[
                Evidence(doc="내부신용등급 조회", quote="A등급 — 투자적격"),
                Evidence(doc="국세·지방세 납세증명", quote="체납 없음 확인"),
            ],
            reinforceable=False,
        ),
        ReviewItem(
            item="기술금융&ESG", grade=Grade.MID, data_status=DataStatus.LACK,
            opinion=(
                "CNC 자동화 라인 도입으로 기술 경쟁력 향상 기대, 기술신용등급 T4 보유. "
                "태양광 350kW 설치 계획(ESG) 있으나 실행계획서 미제출로 확인 불가. TCF 재평가 신청 검토 권고.\n"
                "요약: 기술등급 T4 보유로 기술금융 적격이나 ESG 실행계획서 미제출로 데이터 부족 상태."
            ),
            evidence=[
                Evidence(doc="기술신용평가서", quote="기술등급 T4"),
            ],
            reinforceable=True,
        ),
        ReviewItem(
            item="종합의견", grade=Grade.MID, data_status=DataStatus.OK,
            opinion=(
                "내부신용등급 A(양호) 보유. DSCR 1.18배(내규 미달)가 핵심 쟁점이나, 수주확인서 반영 시 1.31배로 기준 충족 예상."
                "<table class='op-table'><thead><tr><th>핵심 쟁점</th><th>현재</th><th>보완 시</th></tr></thead>"
                "<tbody><tr><td>DSCR</td><td style='color:#C62828'>1.18배 (미달)</td>"
                "<td style='color:#2E7D32'>1.31배 (충족)</td></tr>"
                "<tr><td>ICR</td><td style='color:#E65100'>1.48배 (경계)</td>"
                "<td>수주 반영 시 개선</td></tr></tbody></table>"
                "조건부 승인 권고 — 최근 6개월 매출자료 징구 및 DSCR 재산출을 승인 조건으로 부과. "
                "[AI 초안 — 최종 결정은 심사역이 내립니다]"
                "요약: 신용도 양호하나 DSCR 미달로 조건부 승인을 권고하며 최종 결정은 심사역이 내립니다."
            ),
            evidence=[
                Evidence(doc="재무제표(2024)", quote="ICR 1.48배, DSCR 1.18배"),
                Evidence(doc="부가세과세표준증명", quote="매출 380억(최근 1년)"),
            ],
            reinforceable=True,
        ),
        ReviewItem(
            item="미이행 승인조건", grade=Grade.MID, data_status=DataStatus.LACK,
            opinion=(
                "기존 여신 승인조건 이행 여부: 신규 고객으로 당행 이행 이력 없음. "
                "신용정보원 타행 이력 미제출 — 타행 여신 이행 이력 확인 불가. "
                "NICE·KCB 거래조회서 징구를 조건부 승인 전제로 권고.\n"
                "요약: 타행 이행 이력 미확인 상태로 징구 서류 보완 후 재검토 필요."
            ),
            evidence=[],
            reinforceable=True,
        ),
        ReviewItem(
            item="영업점장 특별의견", grade=None, data_status=DataStatus.OK,
            opinion="",
            reinforceable=False,
        ),
    ]
