from pydantic import BaseModel
from typing import Optional, List


class CompanyInfo(BaseModel):
    name: str
    business_no: str = ""
    industry: str = ""
    founded_year: str = ""


class LoanInfo(BaseModel):
    amount: str = ""
    type: str = ""
    term: str = ""
    collateral_type: str = ""
    purpose: str = ""


class DocumentInfo(BaseModel):
    name: str
    type: str = ""


class DiscussRequest(BaseModel):
    company: CompanyInfo
    loan: LoanInfo
    documents: List[DocumentInfo] = []


class ReinforceRequest(BaseModel):
    item_id: int
    item_name: str
    reinforce_type: str  # "persuasion" | "documents"
    current_opinion: str = ""


class HintRequest(BaseModel):
    item_id: int
    item_name: str
    opinion_text: str


class ReviewItem(BaseModel):
    id: int
    name: str
    grade: Optional[str] = None
    doc_status: Optional[str] = None
    show_doc_badge: bool = True
    opinion: str = ""
    evidence: List[dict] = []
    can_reinforce_persuasion: bool = False
    can_reinforce_documents: bool = False


class SubmitRequest(BaseModel):
    company_name: str
    items: List[dict] = []
    conclusion: str = "conditional"
