"""
Azure AI Foundry Web Search (Bing Grounding) 를 통한 실시간 산업현황·뉴스 검색.
Responses API + bing_grounding tool 을 활용한다.
openai >= 1.66.0, api_version 2025-04-01-preview 필요.
"""
import json
from openai import AsyncAzureOpenAI
from config import get_settings


async def search_industry_status(
    industry_code: str,
    industry_name: str,
    company_name: str,
) -> dict:
    """
    Azure AI Foundry Web Search로 산업현황 조회.

    Returns:
        {
            "industry_status": "호황" | "보통" | "침체",
            "key_indicators": {...},
            "outlook": str,
            "news": [{"title", "summary", "source_url", "date"}],
            "impact_on_repayment": str,
            "sources": [str]
        }
    """
    s = get_settings()
    client = AsyncAzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
    )

    prompt = f"""BNK금융그룹 산업 분석 전문가로서, {company_name}(업종: {industry_name}, 코드: {industry_code})의 최신 산업현황을 조사하세요.

다음 항목을 조사해 JSON으로 응답하세요:
1. industry_status: 산업 경기 상태 ("호황" / "보통" / "침체")
2. key_indicators: BSI지수, 수출증감률(YoY), 생산지수 추세 (조회된 값만)
3. outlook: 향후 1년 전망 요약 (2~3문장)
4. news: 최근 3개월 주요 뉴스 3건 (title, summary, source_url, date)
5. impact_on_repayment: 해당 산업 현황이 대출 상환 능력에 미치는 영향 (긍정/부정 + 근거)
6. sources: 참고한 출처 목록

JSON만 반환하세요. 마크다운 코드블록 없이."""

    response = await client.responses.create(
        model=s.azure_openai_chat_deployment,
        tools=[{
            "type": "bing_grounding",
            "bing_grounding": {
                "connection_id": s.bing_connection_id,
            },
        }],
        instructions="산업 분석 전문가. 웹 검색 결과 기반으로만 답변. 없는 수치는 생성 금지.",
        input=prompt,
    )

    content = response.output_text or ""

    # 응답에 포함된 URL 출처 수집
    sources = _extract_sources(response)

    try:
        result = json.loads(content)
        if sources:
            result["sources"] = list(dict.fromkeys(result.get("sources", []) + sources))
        return result
    except json.JSONDecodeError:
        return {
            "industry_status": "보통",
            "key_indicators": {},
            "outlook": content[:300],
            "news": [],
            "impact_on_repayment": "조회 결과 파싱 실패",
            "sources": sources,
        }


def _extract_sources(response) -> list[str]:
    urls = []
    for item in getattr(response, "output", []):
        for block in getattr(item, "content", []):
            for ann in getattr(block, "annotations", []):
                url = getattr(ann, "url", None)
                if url:
                    urls.append(url)
    return urls
