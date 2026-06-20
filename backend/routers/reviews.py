"""
심사 제출 라우터

POST /api/reviews/submit   심사역 제출
"""
import random
import string
from datetime import datetime, timezone

from fastapi import APIRouter

from models.schemas import SubmitRequest

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("/submit")
async def submit(req: SubmitRequest):
    """심사역이 최종 제출. 티켓 번호를 발급한다."""
    today = datetime.now(timezone.utc).strftime("%m%d")
    suffix = "".join(random.choices(string.digits, k=4))
    ticket_no = f"REQ-2026-{today}{suffix}"

    return {
        "ticket_no": ticket_no,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "company_name": req.company_name,
        "conclusion": req.conclusion,
        "item_count": len(req.items),
    }
