"""
보강 서비스 — 외부 데이터 추적관 역할.

REVIEW_AGENTS.md: 외부 데이터 추적관은 사용자가 "위험 상태 보강(persuasion)" 또는
"데이터 보강(documents)" 버튼을 눌렀을 때 호출된다.

- Azure OpenAI 설정 시: RAG 검색 + LLM 보강 워딩 생성
- 미설정 시: 항목별 mock 데이터 반환

징구서류 안내: submitted_documents(제출된 서류명 목록)와 항목별 필수 서류 목록을 비교하여
실제 미제출 서류만 안내한다.
"""
import asyncio
import json
from typing import AsyncGenerator

from services.dart_client import get_audit_opinion, get_recent_disclosures, get_financial_statements

# ---------------------------------------------------------------------------
# 항목별 필수 징구서류 (BNK 여신심사 기준)
# doc: 서류명 (시스템 내 표준명), purpose: 필요 이유
# ---------------------------------------------------------------------------
_REQUIRED_DOCS: dict[str, list[dict]] = {
    "업체현황": [
        {"doc": "사업자등록증",          "purpose": "업종·영업소 확인"},
        {"doc": "법인등기부등본",         "purpose": "법인 현황·임원 확인"},
        {"doc": "내부신용등급 조회서",     "purpose": "내부등급 산정 근거"},
    ],
    "자금용도": [
        {"doc": "여신신청서",             "purpose": "자금용도 및 신청금액 확인"},
        {"doc": "자금용도 소명서",         "purpose": "집행 계획 타당성 검증"},
    ],
    "금리결정 적정성": [
        {"doc": "내부신용등급 조회서",     "purpose": "가산금리 산정 근거"},
        {"doc": "우대금리 확인서",         "purpose": "우대 적용 요건 충족 확인"},
    ],
    "상환재원": [
        {"doc": "재무제표(최근 3개년)",    "purpose": "ICR·DSCR 산정"},
        {"doc": "부가세과세표준증명",       "purpose": "매출 현황 확인"},
        {"doc": "소득금액증명원",           "purpose": "실질 수익력 검증"},
        {"doc": "담보감정평가서",           "purpose": "LTV·담보 적정성"},
    ],
    "특이사항": [
        {"doc": "국세완납증명서",           "purpose": "국세 체납 여부 확인"},
        {"doc": "지방세완납증명서",         "purpose": "지방세 체납 여부 확인"},
        {"doc": "DART 감사보고서",          "purpose": "공시 기준 감사의견 확인"},
    ],
    "기술금융 & ESG": [
        {"doc": "기술신용평가서(TCB)",      "purpose": "기술등급 산정 근거"},
        {"doc": "ESG 실행계획서",           "purpose": "ESG 활동 계획 확인"},
    ],
    "기술금융&ESG": [
        {"doc": "기술신용평가서(TCB)",      "purpose": "기술등급 산정 근거"},
        {"doc": "ESG 실행계획서",           "purpose": "ESG 활동 계획 확인"},
    ],
    "미이행 승인조건": [
        {"doc": "신용정보원 거래조회서(NICE)", "purpose": "타행 여신 이행 이력 확인"},
        {"doc": "신용정보원 거래조회서(KCB)",  "purpose": "타행 여신 이행 이력 확인"},
    ],
}


def _build_doc_table(missing: list[dict]) -> str:
    """미제출 서류 목록을 HTML 표로 변환."""
    rows = "".join(
        f"<tr><td>{d['doc']}</td><td>{d['purpose']}</td><td>즉시</td></tr>"
        for d in missing
    )
    return (
        "<table class='op-table'>"
        "<thead><tr><th>서류명</th><th>필요 사유</th><th>제출 기한</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _get_missing_docs(item_name: str, submitted: list[str]) -> list[dict]:
    """필수 서류 중 제출되지 않은 목록 반환."""
    required = _REQUIRED_DOCS.get(item_name, [])
    submitted_lower = [s.lower() for s in submitted]
    return [
        d for d in required
        if not any(d["doc"].lower() in s or s in d["doc"].lower() for s in submitted_lower)
    ]


# ---------------------------------------------------------------------------
# Mock 보강 콘텐츠 — persuasion (설득력 보강)
# ---------------------------------------------------------------------------
_MOCK_PERSUASION: dict[str, str] = {
    "상환재원": (
        "<p><strong>[외부자료 보강 — AI Search 기반]</strong></p>"
        "<p>수주확인서(현대모비스 32.4억 원) 기반 2025년 DSCR 재산출:</p>"
        "<table class='op-table'>"
        "<thead><tr><th>시나리오</th><th>DSCR</th><th>영업현금흐름</th><th>판정</th></tr></thead>"
        "<tbody>"
        "<tr><td>현재 (2024 실적)</td><td>1.18배</td><td>8.7억</td><td style='color:#C62828'>미달</td></tr>"
        "<tr><td>수주 반영 (2025 예상)</td><td>1.31배</td><td>11.2억</td><td style='color:#2E7D32'>충족</td></tr>"
        "</tbody></table>"
        "<p>동종업종(금속부품 제조) DSCR 평균 1.22배 — 수주 반영 시 업종 평균 상회.</p>"
    ),
    "금리결정 적정성": (
        "<p><strong>[외부자료 보강]</strong> 동종업종 금리 벤치마크:</p>"
        "<table class='op-table'>"
        "<thead><tr><th>신용등급</th><th>LTV 구간</th><th>시중 평균</th><th>당행 제안</th><th>판정</th></tr></thead>"
        "<tbody>"
        "<tr><td>A</td><td>70~75%</td><td>4.4~5.0%</td><td>4.57%</td>"
        "<td style='color:#2E7D32'>범위 내</td></tr>"
        "</tbody></table>"
    ),
    "기술금융 & ESG": (
        "<p><strong>[외부자료 보강]</strong> TCF 재평가 근거:</p>"
        "<table class='op-table'>"
        "<thead><tr><th>평가 항목</th><th>현재</th><th>재평가 후</th><th>금리 영향</th></tr></thead>"
        "<tbody>"
        "<tr><td>기술신용등급</td><td>T4</td><td>T3 (CNC 자동화 가중)</td>"
        "<td>-0.3%p 우대 가능</td></tr>"
        "</tbody></table>"
    ),
    "기술금융&ESG": (
        "<p><strong>[외부자료 보강]</strong> TCF 재평가 근거:</p>"
        "<table class='op-table'>"
        "<thead><tr><th>평가 항목</th><th>현재</th><th>재평가 후</th><th>금리 영향</th></tr></thead>"
        "<tbody>"
        "<tr><td>기술신용등급</td><td>T4</td><td>T3 (CNC 자동화 가중)</td>"
        "<td>-0.3%p 우대 가능</td></tr>"
        "</tbody></table>"
    ),
    "미이행 승인조건": (
        "<p><strong>[외부자료 보강]</strong> 신규 고객으로 당행 이행 이력 없음. "
        "NICE·KCB 신용정보원 조회 결과 징구를 조건부 승인 전제로 권고.</p>"
    ),
    "종합의견": (
        "<p><strong>[보강]</strong> 유사 승인 사례(금속부품 제조, DSCR 1.2~1.3배) 6건 참조 시 "
        "조건부 승인 비율 83%. 핵심 조건: 최근 6개월 매출자료 및 수주확인서 원본 징구.</p>"
    ),
}

_NEW_GRADE: dict[str, str] = {
    "상환재원": "중",
    "금리결정 적정성": "상",
    "기술금융 & ESG": "상",
    "기술금융&ESG": "상",
    "미이행 승인조건": "중",
    "종합의견": "상",
}

# Mock 모드 외부자료 출처
_MOCK_SOURCES: dict[str, list[dict]] = {
    "상환재원": [
        {"type": "DART", "content": "[DART 재무] 부채비율 16.5% / ICR 1.48배 / 매출액 380억"},
        {"type": "DART", "content": "[DART 감사의견] 적정 (감사인: 삼정KPMG)"},
        {"type": "산업동향", "content": "자동차 부품 제조업 2025년 매출 성장률 전망 +9.2% — 전장부품·경량소재 수요 확대 (KIET 산업경제, 2025.01)"},
        {"type": "산업동향", "content": "완성차 업체 2025 국내 생산량 전년 대비 +6.8% 예상, OEM 부품사 수주 동반 증가 전망 (한국자동차산업협회)"},
    ],
    "금리결정 적정성": [
        {"type": "산업동향", "content": "한국은행 기준금리 동결 기조 유지 — 하반기 인하 가능성 시사 (2025.06 금통위)"},
        {"type": "산업동향", "content": "제조업 A등급 신규 대출 평균금리 4.4~5.0% 수준 유지 (금융통계정보시스템, 2025.Q1)"},
    ],
    "기술금융 & ESG": [
        {"type": "DART", "content": "[DART 공시] 연구개발비 지출 내역 — CNC 자동화 설비 투자 18억 (2024)"},
        {"type": "산업동향", "content": "정밀가공 제조업 스마트공장 전환 추세 — 자동화 설비 투자 기업 매출 평균 +15% 성장 (중소기업연구원, 2024)"},
        {"type": "산업동향", "content": "탄소중립 산업전환 지원 정책 확대 — ESG 실행 기업 금리우대 +0.3%p (산업부, 2025.04)"},
    ],
    "기술금융&ESG": [
        {"type": "DART", "content": "[DART 공시] 연구개발비 지출 내역 — CNC 자동화 설비 투자 18억 (2024)"},
        {"type": "산업동향", "content": "정밀가공 제조업 스마트공장 전환 추세 — 자동화 설비 투자 기업 매출 평균 +15% 성장 (중소기업연구원, 2024)"},
        {"type": "산업동향", "content": "탄소중립 산업전환 지원 정책 확대 — ESG 실행 기업 금리우대 +0.3%p (산업부, 2025.04)"},
    ],
    "미이행 승인조건": [
        {"type": "웹검색", "content": "NICE 기업신용평가 결과: AA등급 (2025.04 갱신), 연체이력 없음"},
        {"type": "웹검색", "content": "KCB 기업신용조회: 타행 여신 정상이행 확인"},
    ],
    "종합의견": [
        {"type": "DART", "content": "[DART 재무] 매출액 380억 (전년 대비 +12.4%), 영업이익 58억"},
        {"type": "산업동향", "content": "자동차 부품 제조업 2025년 전망: 전장부품 수요 증가 + 경량소재 전환 가속화로 업종 전체 매출 +9.2% 성장 예상 (KIET)"},
        {"type": "산업동향", "content": "부채비율 높은 기업도 산업 호황기 매출 확대로 DSCR 개선 사례 다수 — 업종 성장률 반영 시 상환능력 재평가 가능 (여신심사 실무 가이드)"},
        {"type": "DART", "content": "[DART 감사의견] 적정 / 계속기업 불확실성 없음"},
    ],
}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def reinforce_stream(req) -> AsyncGenerator[str, None]:
    """
    보강 SSE 스트림.

    이벤트 순서:
      step(active) → step(done) → step(active) → step(done) → complete | no_reinforce
    """
    from config import get_settings
    s = get_settings()
    use_azure = bool(s.azure_openai_endpoint and s.azure_openai_chat_deployment)

    if use_azure:
        # ── 1단계: 외부 자료 검색 (DART + 웹검색 병렬) ──
        dart_ctx = ""
        web_ctx = ""
        yield _sse({"type": "step", "step": "외부 자료 검색", "status": "active"})

        async def _fetch_dart() -> str:
            if not req.dart_code:
                return ""
            try:
                dart_audit, dart_disclosures, dart_fin = await asyncio.gather(
                    get_audit_opinion(req.dart_code),
                    get_recent_disclosures(req.dart_code, months=6),
                    get_financial_statements(req.dart_code),
                )
                parts = []
                if dart_audit.get("audit_opinion") not in ("조회불가", ""):
                    parts.append(
                        f"[DART 감사의견] {dart_audit['audit_opinion']}"
                        + (" ⚠️ 계속기업 불확실성 언급" if dart_audit.get("going_concern") else "")
                        + f" (감사인: {dart_audit.get('auditor', '')})"
                    )
                if dart_disclosures:
                    titles = ", ".join(d["title"] for d in dart_disclosures[:3])
                    parts.append(f"[DART 최근 공시] {titles}")
                if dart_fin.get("debt_ratio"):
                    parts.append(
                        f"[DART 재무] 부채비율 {dart_fin['debt_ratio']}% / "
                        f"ICR {dart_fin.get('icr', 'N/A')}배 / "
                        f"매출액 {round(dart_fin.get('revenue', 0) / 1e8, 1)}억"
                    )
                return "\n".join(parts)
            except Exception:
                return ""

        async def _fetch_web() -> str:
            try:
                from services.web_search import search_company_news, search_industry_news, format_web_results
                company_name = req.company_name or req.item_name
                industry_name = getattr(req, 'industry_name', '') or ""
                # 기업 뉴스 + 산업 동향 병렬 검색
                async def _noop():
                    return []
                company_news, industry_news = await asyncio.gather(
                    search_company_news(company_name, max_results=3),
                    search_industry_news(industry_name, max_results=3) if industry_name else _noop(),
                )
                return format_web_results(company_news, industry_news)
            except Exception:
                return ""

        dart_ctx, web_ctx = await asyncio.gather(_fetch_dart(), _fetch_web())
        yield _sse({
            "type": "step",
            "step": "외부 자료 검색",
            "status": "done",
            "dart_found": bool(dart_ctx),
            "web_found": bool(web_ctx),
        })

        # ── 2단계: 보강 워딩 생성 ──
        yield _sse({"type": "step", "step": "보강 워딩 생성", "status": "active"})
        try:
            from services.azure_clients import chat

            if req.reinforce_type == "documents":
                missing = _get_missing_docs(req.item_name, req.submitted_documents)
                if not missing:
                    yield _sse({"type": "step", "step": "보강 워딩 생성", "status": "done"})
                    yield _sse({"type": "no_reinforce", "reason": "제출된 서류가 모두 충족되어 있습니다."})
                    return

                missing_names = ", ".join(d["doc"] for d in missing)
                prompt = (
                    f"'{req.item_name}' 항목 심사에 필요한 서류 중 아직 제출되지 않은 서류가 있습니다.\n"
                    f"미제출 서류: {missing_names}\n"
                    f"현재 의견:\n{req.current_opinion[:400]}\n\n"
                    + (f"외부 자료 (DART 자료):\n{dart_ctx}\n\n" if dart_ctx else "")
                    + (f"외부 자료 (웹검색 자료):\n{web_ctx}\n\n" if web_ctx else "")
                    + "각 미제출 서류가 왜 필요한지 간단히 설명하는 징구 안내 HTML을 작성하세요. "
                    "표(op-table 클래스)를 사용해 서류명·필요사유·제출기한을 정리하세요. "
                    "서류명은 절대 변경하지 마세요."
                )
            else:
                prompt = (
                    f"'{req.item_name}' 항목의 현재 심사의견을 보강하세요.\n"
                    f"목적: 위험 상태를 완화하는 보강 워딩 (HTML 허용, 표 적극 활용)\n"
                    f"현재 의견:\n{req.current_opinion[:500]}\n\n"
                    + (f"외부 자료 (DART 자료):\n{dart_ctx}\n\n" if dart_ctx else "")
                    + (f"외부 자료 (웹검색 — 산업동향 포함):\n{web_ctx}\n\n" if web_ctx else "")
                    + "보강 시 핵심: 재무적 약점(부채비율 높음, DSCR 미달 등)이 있더라도 "
                    "산업 동향·업종 성장 전망·시장 확대 등 외부 환경으로 매출 확대 가능성을 근거로 제시하세요.\n"
                    "보강 HTML만 반환하세요. 수치는 DART 또는 웹검색 자료에서 확인된 것만 사용하세요."
                )

            content = chat(
                [
                    {"role": "system", "content": "당신은 외부 데이터 추적관입니다. AI가 지원하는 초안을 작성하며 최종 결정은 심사역이 내립니다."},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1000,
            )
            new_grade = "중" if req.reinforce_type == "documents" else "상"
            can_reinforce = False
        except Exception as e:
            content = f"<p>[보강 오류: {str(e)[:80]}]</p>"
            new_grade = "중"
            can_reinforce = True

        await asyncio.sleep(0.3)
        yield _sse({"type": "step", "step": "보강 워딩 생성", "status": "done"})

        # 외부자료 출처 정보 구성
        sources = []
        if dart_ctx:
            for line in dart_ctx.split("\n"):
                if line.strip():
                    sources.append({"type": "DART", "content": line.strip()})
        if web_ctx:
            for line in web_ctx.split("\n"):
                ln = line.strip()
                if not ln:
                    continue
                if "산업 동향" in ln or "산업동향" in ln:
                    # 섹션 헤더는 건너뛰기
                    continue
                # 산업 동향 섹션에 속한 항목 분류
                if "산업" in ln or "업종" in ln or "전망" in ln or "성장" in ln or "시장" in ln:
                    sources.append({"type": "산업동향", "content": ln.lstrip("- ")})
                else:
                    sources.append({"type": "웹검색", "content": ln.lstrip("- ")})

        yield _sse({
            "type": "complete",
            "reinforced_opinion": content,
            "new_grade": new_grade,
            "can_reinforce": can_reinforce,
            "sources": sources,
        })
        return

    # Mock 모드
    yield _sse({"type": "step", "step": "외부 기업정보 검색", "status": "active"})
    await asyncio.sleep(1.2)
    yield _sse({"type": "step", "step": "외부 기업정보 검색", "status": "done"})

    yield _sse({"type": "step", "step": "보강 워딩 생성", "status": "active"})
    await asyncio.sleep(1.5)
    yield _sse({"type": "step", "step": "보강 워딩 생성", "status": "done"})

    if req.reinforce_type == "documents":
        missing = _get_missing_docs(req.item_name, req.submitted_documents)
        if not missing:
            yield _sse({
                "type": "no_reinforce",
                "reason": f"'{req.item_name}' 항목의 필수 서류가 모두 제출되었습니다.",
            })
            return
        content = (
            f"<p><strong>[징구서류 안내]</strong> 아래 서류가 제출되지 않았습니다.</p>"
            + _build_doc_table(missing)
        )
        new_grade = "중"
    else:
        content = _MOCK_PERSUASION.get(req.item_name)
        if not content:
            yield _sse({
                "type": "no_reinforce",
                "reason": f"'{req.item_name}' 항목은 현재 보강할 내용이 없습니다.",
            })
            return
        new_grade = _NEW_GRADE.get(req.item_name, "중")

    sources = _MOCK_SOURCES.get(req.item_name, [])
    yield _sse({
        "type": "complete",
        "reinforced_opinion": content,
        "new_grade": new_grade,
        "can_reinforce": False,
        "sources": sources,
    })
