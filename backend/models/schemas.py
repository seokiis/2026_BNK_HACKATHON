from enum import Enum
from typing import Optional
from pydantic import BaseModel


class Grade(str, Enum):
    HIGH = "상"
    MID  = "중"
    LOW  = "하"


class DataStatus(str, Enum):
    OK      = "정상"
    LACK    = "부족"
    MISSING = "누락"


class Evidence(BaseModel):
    doc: str
    quote: str
    location: str = ""


class ReviewItem(BaseModel):
    item: str
    opinion: str = ""
    grade: Optional[Grade] = None
    data_status: DataStatus = DataStatus.OK
    evidence: list[Evidence] = []
    reinforceable: bool = False


class ReviewResult(BaseModel):
    case_id: str
    items: list[ReviewItem] = []
    summary: str = ""
    status: str = "pending"  # pending | running | done | error


class CaseCreate(BaseModel):
    business_id: str          # 사업자등록번호
    loan_type: str = "시설 및 운전자금 종합여신"


class ReinforcementRequest(BaseModel):
    item: str                 # 보강 대상 항목명
    mode: str                 # "risk" | "data"


class EditRequest(BaseModel):
    item: str
    opinion: str
