"""
DART OpenAPI 클라이언트.
감사보고서, 재무제표, 공시 목록을 조회한다.
"""
import os
from datetime import date, timedelta
import httpx

DART_BASE = "https://opendart.fss.or.kr/api"
DART_API_KEY = os.environ.get("DART_API_KEY", "")


async def get_audit_opinion(corp_code: str, bsns_year: str = "2024") -> dict:
    """
    감사보고서에서 감사의견을 추출.

    Returns:
        {
            "audit_opinion": "적정" | "한정" | "부적정" | "의견거절",
            "going_concern": bool,
            "auditor": str,
            "report_date": str
        }
    """
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": "11011",  # 사업보고서
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{DART_BASE}/fnlttAuditOpinion.json", params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "000" or not data.get("list"):
        return {
            "audit_opinion": "조회불가",
            "going_concern": False,
            "auditor": "",
            "report_date": "",
        }

    item = data["list"][0]
    opinion_text = item.get("opinion", "")
    going_concern = "계속기업" in item.get("emphasis", "") or "계속기업" in opinion_text

    return {
        "audit_opinion": _normalize_opinion(opinion_text),
        "going_concern": going_concern,
        "auditor": item.get("actvt_nm", ""),
        "report_date": item.get("rcept_dt", ""),
    }


def _normalize_opinion(raw: str) -> str:
    for keyword in ["적정", "한정", "부적정", "의견거절"]:
        if keyword in raw:
            return keyword
    return raw or "조회불가"


async def get_financial_statements(corp_code: str, bsns_year: str = "2024") -> dict:
    """
    DART 재무제표 조회 (교차검증용).

    Returns:
        {
            "total_assets": int,
            "total_liabilities": int,
            "revenue": int,
            "operating_income": int,
            "net_income": int,
            "debt_ratio": float,
            "icr": float
        }
    """
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": "11011",  # 사업보고서
        "fs_div": "OFS",        # 개별재무제표
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{DART_BASE}/fnlttSinglAcntAll.json", params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "000" or not data.get("list"):
        return {}

    accounts = {item["account_nm"]: _parse_amount(item.get("thstrm_amount", "0"))
                for item in data["list"]}

    total_assets = accounts.get("자산총계", 0)
    total_liabilities = accounts.get("부채총계", 0)
    equity = total_assets - total_liabilities
    operating_income = accounts.get("영업이익", 0)
    finance_cost = accounts.get("금융원가", accounts.get("이자비용", 1))

    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "revenue": accounts.get("매출액", 0),
        "operating_income": operating_income,
        "net_income": accounts.get("당기순이익", 0),
        "debt_ratio": round(total_liabilities / equity * 100, 1) if equity > 0 else 0.0,
        "icr": round(operating_income / finance_cost, 2) if finance_cost > 0 else 0.0,
    }


def _parse_amount(value: str) -> int:
    try:
        return int(value.replace(",", "").replace("-", "0"))
    except (ValueError, AttributeError):
        return 0


async def get_recent_disclosures(corp_code: str, months: int = 6) -> list[dict]:
    """
    최근 N개월 주요 공시 목록.

    Returns:
        [{"title": str, "date": str, "type": str, "url": str}]
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=30 * months)

    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de": start_date.strftime("%Y%m%d"),
        "end_de": end_date.strftime("%Y%m%d"),
        "pblntf_ty": "A",  # 정기공시
        "page_count": 10,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{DART_BASE}/list.json", params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "000" or not data.get("list"):
        return []

    return [
        {
            "title": item.get("report_nm", ""),
            "date": item.get("rcept_dt", ""),
            "type": item.get("pblntf_ty", ""),
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={item.get('rcept_no', '')}",
        }
        for item in data["list"][:10]
    ]


async def search_corp_code(company_name: str) -> str | None:
    """
    기업명으로 DART corp_code 검색.
    """
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_name": company_name,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{DART_BASE}/company.json", params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") == "000":
        return data.get("corp_code")
    return None
