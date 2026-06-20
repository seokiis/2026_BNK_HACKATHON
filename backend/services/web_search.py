"""
API 키 없는 웹 검색 서비스 (Google News RSS).
httpx + 표준 라이브러리만 사용 — 추가 패키지 없음.
"""
import xml.etree.ElementTree as ET
import httpx

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


async def search_company_news(company_name: str, max_results: int = 5) -> list[dict]:
    """
    기업명으로 Google 뉴스 RSS 검색.

    Returns:
        [{"title": str, "body": str, "url": str, "date": str}]
    """
    query = f"{company_name} 재무 뉴스"
    params = {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}

    async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS, follow_redirects=True) as client:
        resp = await client.get(_GOOGLE_NEWS_RSS, params=params)
        resp.raise_for_status()

    return _parse_rss(resp.text, max_results)


async def search_industry_news(industry_name: str, max_results: int = 3) -> list[dict]:
    """
    산업별 최신 동향 Google 뉴스 RSS 검색.

    Returns:
        [{"title": str, "body": str, "url": str, "date": str}]
    """
    query = f"{industry_name} 산업 동향 전망"
    params = {"q": query, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}

    async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS, follow_redirects=True) as client:
        resp = await client.get(_GOOGLE_NEWS_RSS, params=params)
        resp.raise_for_status()

    return _parse_rss(resp.text, max_results)


def _parse_rss(xml_text: str, max_results: int) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = root.findall(".//item")[:max_results]
    results = []
    for item in items:
        title = item.findtext("title", "").strip()
        # RSS description은 HTML 태그 포함 → 단순 제거
        raw_body = item.findtext("description", "")
        body = _strip_html(raw_body)[:300]
        results.append({
            "title": title,
            "body": body,
            "url": item.findtext("link", ""),
            "date": item.findtext("pubDate", "")[:16],
        })
    return results


def _strip_html(text: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", text).strip()


def format_web_results(company_news: list[dict], industry_news: list[dict]) -> str:
    """검색 결과를 LLM 프롬프트용 텍스트로 변환."""
    parts = []

    if company_news:
        headlines = "\n".join(
            f"- {n['title']} ({n['date']}): {n['body']}"
            for n in company_news[:3]
        )
        parts.append(f"[웹검색 자료 — 기업 뉴스]\n{headlines}")

    if industry_news:
        headlines = "\n".join(
            f"- {n['title']} ({n['date']}): {n['body']}"
            for n in industry_news[:2]
        )
        parts.append(f"[웹검색 자료 — 산업 동향]\n{headlines}")

    return "\n\n".join(parts)
