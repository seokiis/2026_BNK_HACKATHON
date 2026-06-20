"""
RAG 서비스 — Azure AI Search 우선, 미설정 시 로컬 JSON 폴백.

search_similar_cases()는 discussion.py 및 reinforce.py에서 공통으로 사용한다.
"""
import json
from pathlib import Path
from typing import Optional

from services.azure_clients import rag_search

_LOCAL_DATA: Optional[dict] = None


def _load_local_data() -> dict:
    global _LOCAL_DATA
    if _LOCAL_DATA is None:
        data_path = Path(__file__).parent.parent.parent / "data" / "bnk_loan_output.json"
        try:
            with open(data_path, encoding="utf-8") as f:
                _LOCAL_DATA = json.load(f)
        except Exception:
            _LOCAL_DATA = {}
    return _LOCAL_DATA


async def search_similar_cases(query: str, top_k: int = 3) -> str:
    """
    유사 심사 사례 검색.
    Azure AI Search 설정 시 하이브리드 검색, 미설정 시 로컬 JSON 폴백.
    """
    # Azure AI Search 시도
    results = rag_search(query, top=top_k)
    if results:
        return "\n---\n".join(r.get("content", "")[:600] for r in results[:top_k])

    # 로컬 JSON 폴백 (bnk_loan_output.json 첫 top_k건)
    data = _load_local_data()
    sample = list(data.values())[:top_k]
    parts = []
    for s in sample:
        if not isinstance(s, dict):
            continue
        parts.append(
            f"업종: {s.get('업종그룹', '')}\n"
            f"승인결과: {s.get('승인결과', '')}\n"
            f"상환재원: {s.get('상환재원(1006,1007)', '')[:300]}\n"
            f"종합의견: {s.get('종합의견(2015,2009,7001,2006)', '')[:300]}"
        )
    return "\n---\n".join(parts) if parts else "유사 사례 없음"
