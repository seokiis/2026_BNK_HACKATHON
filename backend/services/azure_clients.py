from __future__ import annotations

from functools import lru_cache
from typing import Generator, List, Optional

try:
    from openai import AzureOpenAI
    from azure.search.documents import SearchClient
    from azure.search.documents.models import VectorizedQuery
    from azure.core.credentials import AzureKeyCredential
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False

from config import get_settings


@lru_cache
def get_openai_client() -> Optional[object]:
    s = get_settings()
    if not s.azure_openai_endpoint or not AZURE_AVAILABLE:
        return None
    try:
        return AzureOpenAI(
            azure_endpoint=s.azure_openai_endpoint,
            api_key=s.azure_openai_api_key or None,
            api_version=s.azure_openai_api_version,
        )
    except Exception:
        return None


@lru_cache
def get_search_client() -> Optional[object]:
    s = get_settings()
    if not s.azure_search_endpoint or not AZURE_AVAILABLE:
        return None
    try:
        return SearchClient(
            endpoint=s.azure_search_endpoint,
            index_name=s.azure_search_index,
            credential=AzureKeyCredential(s.azure_search_key or ""),
        )
    except Exception:
        return None


def embed(text: str) -> list[float]:
    s = get_settings()
    client = get_openai_client()
    if not client:
        return []
    resp = client.embeddings.create(
        model=s.azure_openai_embedding_deployment,
        input=text[:6000],
    )
    return resp.data[0].embedding


def chat(messages: list[dict], max_tokens: int = 2000) -> str:
    s = get_settings()
    client = get_openai_client()
    if not client:
        return "[Azure OpenAI 미설정 — mock 모드]"
    resp = client.chat.completions.create(
        model=s.azure_openai_chat_deployment,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def stream_chat(messages: List[dict], max_tokens: int = 2000) -> Generator[str, None, None]:
    """SSE 스트리밍용 — 토큰 단위로 yield한다."""
    s = get_settings()
    client = get_openai_client()
    if not client:
        yield "[Azure OpenAI 미설정 — mock 모드]"
        return
    stream = client.chat.completions.create(
        model=s.azure_openai_chat_deployment,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.3,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content


def rag_search(query: str, top: int = 5, reviewer_filter: Optional[str] = None) -> List[dict]:
    """하이브리드 검색 (키워드 + 벡터). 클라이언트 미설정 시 빈 리스트 반환."""
    search_client = get_search_client()
    if not search_client or not AZURE_AVAILABLE:
        return []

    try:
        vector = embed(query)
        kwargs: dict = {
            "search_text": query,
            "select": ["uid", "snippet", "snippet_parent_id"],
            "top": top,
        }
        if vector:
            vector_query = VectorizedQuery(
                vector=vector,
                k_nearest_neighbors=top,
                fields="snippet_vector",
            )
            kwargs["vector_queries"] = [vector_query]
        if reviewer_filter:
            kwargs["filter"] = (
                f"snippet_parent_id eq 'loan-{reviewer_filter.replace(' ', '')}'"
            )

        results = search_client.search(**kwargs)
        return [{"id": r["uid"], "content": r["snippet"]} for r in results]
    except Exception:
        return []
