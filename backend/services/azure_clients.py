from functools import lru_cache
from typing import Optional
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.core.credentials import AzureKeyCredential
from config import get_settings


@lru_cache
def get_openai_client() -> AzureOpenAI:
    s = get_settings()
    return AzureOpenAI(
        azure_endpoint=s.azure_openai_endpoint,
        api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version,
    )


@lru_cache
def get_search_client() -> SearchClient:
    s = get_settings()
    return SearchClient(
        endpoint=s.azure_search_endpoint,
        index_name=s.azure_search_index,
        credential=AzureKeyCredential(s.azure_search_key),
    )


def embed(text: str) -> list[float]:
    s = get_settings()
    client = get_openai_client()
    resp = client.embeddings.create(
        model=s.azure_openai_embedding_deployment,
        input=text[:6000],
    )
    return resp.data[0].embedding


def chat(messages: list[dict], max_tokens: int = 2000) -> str:
    s = get_settings()
    client = get_openai_client()
    resp = client.chat.completions.create(
        model=s.azure_openai_chat_deployment,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.3,
    )
    return resp.choices[0].message.content


def rag_search(query: str, top: int = 5, reviewer_filter: Optional[str] = None) -> list[dict]:
    """하이브리드 검색 (키워드 + 벡터). reviewer_filter로 특정 심사역 사례만 조회 가능."""
    search_client = get_search_client()
    vector_query = VectorizedQuery(
        vector=embed(query),
        k_nearest_neighbors=top,
        fields="snippet_vector",
    )
    filter_expr = f"snippet_parent_id eq 'loan-{reviewer_filter.replace(' ', '')}'" if reviewer_filter else None

    results = search_client.search(
        search_text=query,
        vector_queries=[vector_query],
        filter=filter_expr,
        select=["uid", "snippet", "snippet_parent_id"],
        top=top,
    )
    return [{"id": r["uid"], "content": r["snippet"]} for r in results]
