"""
분석 라우터 — 프론트 직접 연동용 (새 API 형식)

POST /api/analysis/discuss   7명 토론 SSE 스트리밍
POST /api/analysis/reinforce 항목 보강 SSE 스트리밍
POST /api/analysis/hint      실시간 힌트 (동기)
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from models.schemas import DiscussRequest, ReinforceRequest, HintRequest
from services.discussion import run_discussion_stream
from services.reinforce import reinforce_stream
from services.hint import analyze_hint

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/discuss")
async def discuss(req: DiscussRequest):
    """7명 AI 토론 → 9개 항목 초안 생성 (SSE 스트리밍)."""
    return StreamingResponse(
        run_discussion_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/reinforce")
async def reinforce(req: ReinforceRequest):
    """외부 데이터 추적관 — 항목 보강 SSE 스트리밍."""
    return StreamingResponse(
        reinforce_stream(req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/hint")
async def hint(req: HintRequest):
    """실시간 힌트 — 동기 응답."""
    return analyze_hint(req.item_id, req.item_name, req.opinion_text)
