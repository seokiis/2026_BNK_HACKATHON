"""
외부 데이터 리서치 통합 서비스.
DART + Bing Grounding 결과를 종합해 보완 근거를 생성한다.
"""
import json
from openai import AsyncAzureOpenAI
from config import get_settings
from services.dart_client import get_audit_opinion, get_recent_disclosures
from services.bing_grounding import search_industry_status


async def research_company(
    corp_code: str,
    industry_code: str,
    industry_name: str,
    company_name: str,
    financial_issues: list[str],
) -> dict:
    """
    기업에 대한 외부 리서치 수행.
    재무 문제가 있을 때 보완 가능한 근거를 찾는다.

    Returns:
        {
            "dart": {"audit_opinion": dict, "disclosures": list},
            "industry": dict,
            "supplementary_summary": str,
            "recommendation": str,
            "confidence": float
        }
    """
    # 1) DART + Bing 병렬 조회
    import asyncio
    audit, disclosures, industry = await asyncio.gather(
        get_audit_opinion(corp_code),
        get_recent_disclosures(corp_code),
        search_industry_status(industry_code, industry_name, company_name),
    )

    # 2) GPT로 종합 판단
    summary, recommendation, confidence = await _synthesize(
        company_name=company_name,
        financial_issues=financial_issues,
        audit=audit,
        disclosures=disclosures,
        industry=industry,
    )

    return {
        "dart": {"audit_opinion": audit, "disclosures": disclosures},
        "industry": industry,
        "supplementary_summary": summary,
        "recommendation": recommendation,
        "confidence": confidence,
    }


async def _synthesize(
    company_name: str,
    financial_issues: list[str],
    audit: dict,
    disclosures: list[dict],
    industry: dict,
) -> tuple[str, str, float]:
    s = get_settings()
    client = AsyncAzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
    )

    issues_text = ", ".join(financial_issues) if financial_issues else "해당 없음"
    disclosures_text = json.dumps(disclosures[:3], ensure_ascii=False) if disclosures else "[]"

    prompt = f"""당신은 BNK금융그룹 여신심사 지원 AI입니다.
아래 정보를 종합하여 반려 사유 보완 가능 여부를 판단하세요.

[기업명] {company_name}
[재무 문제] {issues_text}
[DART 감사의견] {audit.get("audit_opinion", "조회불가")} / 계속기업불확실성: {audit.get("going_concern", False)}
[최근 공시] {disclosures_text}
[산업현황] {industry.get("industry_status", "보통")} — {industry.get("outlook", "")}
[상환능력 영향] {industry.get("impact_on_repayment", "")}

다음을 JSON으로 반환하세요:
- supplementary_summary: 보완 근거 요약 (2~3문장, 심사역이 읽을 수준)
- recommendation: "조건부 승인 검토" 또는 "반려 유지"
- confidence: 0.0~1.0 (보완 근거의 신뢰도)

JSON만 반환하세요."""

    response = await client.chat.completions.create(
        model=s.azure_openai_chat_deployment,
        messages=[
            {"role": "system", "content": "여신심사 보조 AI. 사실 기반으로만 판단. AI가 지원하며 최종 결정은 심사역이 한다."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=400,
    )

    content = response.choices[0].message.content
    try:
        result = json.loads(content)
        return (
            result.get("supplementary_summary", ""),
            result.get("recommendation", "반려 유지"),
            float(result.get("confidence", 0.0)),
        )
    except (json.JSONDecodeError, ValueError):
        return content[:300], "반려 유지", 0.0
