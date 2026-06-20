from __future__ import annotations

from enum import Enum
from typing import List, Optional
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
    evidence: List[Evidence] = []
    reinforceable: bool = False


class ReviewResult(BaseModel):
    case_id: str
    items: List[ReviewItem] = []
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


# ---------------------------------------------------------------------------
# 새 API 형식 Request 모델 (/api/analysis/*, /api/reviews/*)
# ---------------------------------------------------------------------------

class FinancialStatements(BaseModel):
    total_assets: float = 0
    total_liabilities: float = 0
    operating_income: float = 0
    finance_cost_interest: float = 1
    fiscal_year: str = ""
    annual_revenue: float = 0


class CompanyInfo(BaseModel):
    name: str
    business_no: str = ""
    industry: str = ""
    founded_year: str = ""
    internal_credit_rating: str = "N/A"
    dart_code: str = ""


class LoanInfo(BaseModel):
    amount: str = ""
    type: str = ""
    term: str = ""
    collateral_type: str = ""
    purpose: str = ""


class DocumentInfo(BaseModel):
    name: str
    type: str = ""


class SalesData(BaseModel):
    annual_sales_by_year: dict = {}


class CollateralData(BaseModel):
    collateral_appraisal_value: float = 0
    regional_auction_rate_1yr: float = 0
    regional_auction_count_1yr: int = 0


class DiscussRequest(BaseModel):
    company: CompanyInfo
    loan: LoanInfo
    documents: List[DocumentInfo] = []
    financial_statements: Optional[FinancialStatements] = None
    sales_data: Optional[SalesData] = None
    collateral_auction_value: Optional[CollateralData] = None


class ReinforceRequest(BaseModel):
    item_id: int
    item_name: str
    reinforce_type: str          # "persuasion" | "documents"
    current_opinion: str = ""
    submitted_documents: List[str] = []  # 이미 제출된 서류명 목록
    dart_code: str = ""          # DART 법인코드 (보강 시 실시간 조회용)
    company_name: str = ""       # 웹검색용 기업명
    industry_name: str = ""      # 웹검색용 업종명 (산업 동향 조사)


class HintRequest(BaseModel):
    item_id: int
    item_name: str
    opinion_text: str


class SubmitRequest(BaseModel):
    company_name: str
    items: List[dict] = []
    conclusion: str = "conditional"
