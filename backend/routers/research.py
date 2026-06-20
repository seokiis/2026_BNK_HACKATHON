"""
외부 리서치 API 라우터.
프론트에서 "산업분석" 버튼 클릭 시 호출.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["research"])


class ResearchRequest(BaseModel):
    company_id: str
    corp_code: str
    industry_code: str
    industry_name: str
    company_name: str
    financial_issues: list[str] = []


class ResearchResponse(BaseModel):
    dart_audit_opinion: str
    dart_going_concern: bool
    dart_disclosures: list[dict]
    industry_status: str
    industry_outlook: str
    industry_news: list[dict]
    supplementary_summary: str
    recommendation: str


@router.post("/research/external", response_model=ResearchResponse)
async def external_research(req: ResearchRequest) -> ResearchResponse:
    """외부 데이터 리서치 (DART + Bing Grounding)"""
    try:
        from services.external_research import research_company
        result = await research_company(
            corp_code=req.corp_code,
            industry_code=req.industry_code,
            industry_name=req.industry_name,
            company_name=req.company_name,
            financial_issues=req.financial_issues,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"외부 리서치 오류: {e}")

    return ResearchResponse(
        dart_audit_opinion=result["dart"]["audit_opinion"].get("audit_opinion", "조회불가"),
        dart_going_concern=result["dart"]["audit_opinion"].get("going_concern", False),
        dart_disclosures=result["dart"]["disclosures"],
        industry_status=result["industry"].get("industry_status", "보통"),
        industry_outlook=result["industry"].get("outlook", ""),
        industry_news=result["industry"].get("news", []),
        supplementary_summary=result["supplementary_summary"],
        recommendation=result["recommendation"],
    )
