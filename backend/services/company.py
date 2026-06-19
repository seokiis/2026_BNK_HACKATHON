import json
from pathlib import Path
from functools import lru_cache
from typing import Optional

MOCK_DIR = Path(__file__).parent.parent.parent / "mock"

# 심사역 배정 규칙: 산업코드 앞자리로 구분 (목데이터 기준)
_REVIEWER_MAP = {
    "C": "심사역 A",   # 제조업
    "G": "심사역 B",   # 도소매
    "F": "심사역 B",   # 건설
    "L": "심사역 B",   # 부동산
}
_DEFAULT_REVIEWER = "심사역 A"


@lru_cache
def _load_company_data() -> dict:
    with open(MOCK_DIR / "sample-company-data.json", encoding="utf-8") as f:
        return json.load(f)


def get_company(business_id: str) -> Optional[dict]:
    return _load_company_data().get(business_id)


def assign_reviewer(business_id: str) -> str:
    company = get_company(business_id)
    if not company:
        return _DEFAULT_REVIEWER
    industry_code = company.get("company_info", {}).get("industry_code", "")
    prefix = industry_code[0].upper() if industry_code else ""
    return _REVIEWER_MAP.get(prefix, _DEFAULT_REVIEWER)
