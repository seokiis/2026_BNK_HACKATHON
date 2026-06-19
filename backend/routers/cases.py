"""
심사 케이스 라우터

Feature 1  POST   /cases                       케이스 생성 + 심사역 배정
Feature 4  POST   /cases/{id}/review           7명 토론 시작 (SSE 스트리밍)
Feature 4  GET    /cases/{id}/review           심사 결과 조회
Feature 8  PATCH  /cases/{id}/review/items     항목 편집
Feature 5,6 POST  /cases/{id}/review/reinforce 위험 상태 보강 / 데이터 보강
Feature 10 POST   /cases/{id}/review/summary   종합 의견 생성
Feature 11 GET    /cases/{id}/export           심사요청서 출력
Feature 13 POST   /cases/{id}/submit           심사역 제출
"""

import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from models.schemas import (
    CaseCreate, ReviewResult, ReviewItem,
    EditRequest, ReinforcementRequest,
)
from services.company import get_company, assign_reviewer
from services.discussion import run_discussion
from services.azure_clients import rag_search, chat

router = APIRouter(prefix="/cases", tags=["cases"])

# 인메모리 케이스 저장소 (TODO: SQLite로 교체)
_cases: dict[str, dict] = {}


# ── Feature 1: 케이스 생성 ──────────────────────────────────────────────────
@router.post("", status_code=201)
def create_case(body: CaseCreate):
    company = get_company(body.business_id)
    if not company:
        raise HTTPException(404, f"사업자번호 {body.business_id} 데이터 없음")

    case_id = str(uuid.uuid4())
    reviewer = assign_reviewer(body.business_id)
    _cases[case_id] = {
        "case_id":     case_id,
        "business_id": body.business_id,
        "loan_type":   body.loan_type,
        "reviewer":    reviewer,
        "company":     company,
        "review":      None,
    }
    return {"case_id": case_id, "reviewer": reviewer, "company_name": company["company_info"]["company_name"]}


# ── Feature 4: 7명 토론 시작 (SSE) ──────────────────────────────────────────
@router.post("/{case_id}/review")
async def start_review(case_id: str):
    case = _get_case(case_id)
    case["review"] = ReviewResult(case_id=case_id, status="running").model_dump()

    async def stream():
        items = []
        async for chunk in run_discussion(
            business_id=case["business_id"],
            company_data=case["company"],
            reviewer=case["reviewer"],
        ):
            yield chunk
            if chunk.startswith("data: RESULT:"):
                import json
                raw = chunk.removeprefix("data: RESULT:").strip()
                items = [ReviewItem(**i) for i in json.loads(raw)]

        case["review"]["items"] = [i.model_dump() for i in items]
        case["review"]["status"] = "done"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Feature 4: 심사 결과 조회 ────────────────────────────────────────────────
@router.get("/{case_id}/review")
def get_review(case_id: str):
    case = _get_case(case_id)
    if not case["review"]:
        raise HTTPException(404, "심사 결과 없음 — POST /review 먼저 호출")
    return case["review"]


# ── Feature 8: 항목 편집 ────────────────────────────────────────────────────
@router.patch("/{case_id}/review/items")
def edit_item(case_id: str, body: EditRequest):
    review = _get_review(case_id)
    for item in review["items"]:
        if item["item"] == body.item:
            item["opinion"] = body.opinion
            return {"ok": True}
    raise HTTPException(404, f"항목 '{body.item}' 없음")


# ── Feature 5,6: 위험 상태 보강 / 데이터 보강 ──────────────────────────────
@router.post("/{case_id}/review/reinforce")
def reinforce(case_id: str, body: ReinforcementRequest):
    """
    외부 데이터 추적관 역할 — RAG로 외부자료 검색 후 보강 워딩 생성
    mode: 'risk' → 위험 상태 보강 (중/하 항목)
          'data' → 데이터 보강 (부족/누락 항목)
    """
    case   = _get_case(case_id)
    review = _get_review(case_id)

    target = next((i for i in review["items"] if i["item"] == body.item), None)
    if not target:
        raise HTTPException(404, f"항목 '{body.item}' 없음")

    query = f"{body.item} {case['company']['company_info'].get('company_name','')} 보강 근거"
    refs  = rag_search(query, top=3)
    context = "\n".join(r["content"][:400] for r in refs)

    mode_label = "위험 상태를 완화하는" if body.mode == "risk" else "누락·부족 데이터를 보완하는"
    prompt = f"""
아래 심사 항목의 현재 의견을 참고하여, {mode_label} 보강 문장을 2~3문장으로 작성하세요.
근거 없는 수치를 만들지 마세요. 참조 문서에 있는 내용만 사용하세요.

항목: {body.item}
현재 의견: {target['opinion']}

참조 문서:
{context}

보강 문장만 반환하세요.
"""
    reinforced = chat([{"role": "user", "content": prompt}], max_tokens=500)

    target["opinion"] = target["opinion"] + "\n\n[보강] " + reinforced
    return {"reinforced": reinforced}


# ── Feature 10: 종합 의견 생성 ──────────────────────────────────────────────
@router.post("/{case_id}/review/summary")
def generate_summary(case_id: str):
    review = _get_review(case_id)
    items_text = "\n".join(
        f"[{i['item']}] (등급:{i.get('grade','미정')}) {i['opinion'][:200]}"
        for i in review["items"]
    )
    prompt = f"""
다음 9개 심사 항목 의견을 종합하여 최종 여신심사 종합의견을 3~5문장으로 작성하세요.
AI가 최종 결정을 내리는 것이 아니라 심사역 검토를 위한 초안임을 전제로 하세요.

{items_text}

종합의견만 반환하세요.
"""
    summary = chat([{"role": "user", "content": prompt}], max_tokens=600)
    review["summary"] = summary
    return {"summary": summary}


# ── Feature 11: 심사요청서 출력 ─────────────────────────────────────────────
@router.get("/{case_id}/export")
def export_review(case_id: str):
    case   = _get_case(case_id)
    review = _get_review(case_id)
    return {
        "business_id": case["business_id"],
        "company_name": case["company"]["company_info"]["company_name"],
        "loan_type": case["loan_type"],
        "reviewer": case["reviewer"],
        "items": review["items"],
        "summary": review.get("summary", ""),
    }


# ── Feature 13: 심사역 제출 (등급·데이터 라벨 제거) ───────────────────────
@router.post("/{case_id}/submit")
def submit_to_reviewer(case_id: str):
    case   = _get_case(case_id)
    review = _get_review(case_id)
    stripped = [
        {"item": i["item"], "opinion": i["opinion"]}
        for i in review["items"]
    ]
    return {
        "message": f"{case['reviewer']}에게 제출 완료",
        "business_id": case["business_id"],
        "items": stripped,
        "summary": review.get("summary", ""),
    }


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────
def _get_case(case_id: str) -> dict:
    case = _cases.get(case_id)
    if not case:
        raise HTTPException(404, f"케이스 {case_id} 없음")
    return case


def _get_review(case_id: str) -> dict:
    case = _get_case(case_id)
    if not case.get("review"):
        raise HTTPException(404, "심사 결과 없음 — POST /review 먼저 호출")
    return case["review"]
