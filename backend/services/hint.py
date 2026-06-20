"""
실시간 힌트 서비스 — 동기, 외부 호출 없음.

항목별 핵심 키워드 존재 여부와 의견 길이로 등급을 추정하고
누락 키워드 기반 힌트를 반환한다.
"""
import re
from typing import Optional

# 항목 id → 핵심 키워드 (9개 항목 기준)
ITEM_KEYWORDS: dict[int, list[str]] = {
    1: ["부채비율", "매출", "영업이익", "성장", "총자산", "신용등급"],
    2: ["수주", "자금집행", "계획", "용도", "매출대비"],
    3: ["DSCR", "신용등급", "LTV", "금리", "기준금리", "가산금리"],
    4: ["DSCR", "이자보상배율", "ICR", "영업현금흐름", "상환능력", "부채비율"],
    5: ["체납", "소송", "연체", "신용등급", "DART", "감사의견"],
    6: ["기술등급", "TCF", "ISO", "ESG", "탄소", "특허"],
    7: ["DSCR", "조건부", "승인", "종합", "리스크", "담보"],
    8: ["이행", "승인조건", "미이행", "신용정보원", "타행"],
    9: ["현장", "대표", "가동률", "방문", "수주"],
}

# 비현실 수치 패턴 검사
_UNREALISTIC_CHECKS = [
    (r"부채비율[\s:]*([0-9,]+)%", lambda v: float(v.replace(",", "")) > 500,
     "부채비율이 지나치게 높습니다. 합리적 범위 내 수치를 사용하세요."),
    (r"DSCR[\s:]*([0-9.]+)배", lambda v: float(v) > 20,
     "DSCR 수치가 비현실적입니다. 일반적으로 1~5배 범위입니다."),
    (r"이자보상배율[\s:]*([0-9.]+)배", lambda v: float(v) > 50,
     "이자보상배율이 비현실적으로 높습니다."),
]


def analyze_hint(item_id: int, item_name: str, text: str) -> dict:
    """
    Args:
        item_id: 1~9
        item_name: 항목명 (표시용)
        text: 작성된 의견 텍스트

    Returns:
        {"hint": str | None, "grade": "상"|"중"|"하", "warning": str | None}
    """
    keywords = ITEM_KEYWORDS.get(item_id, [])

    # 비현실 수치 경고
    warning: Optional[str] = None
    for pattern, is_bad, msg in _UNREALISTIC_CHECKS:
        m = re.search(pattern, text)
        if m:
            try:
                if is_bad(m.group(1)):
                    warning = msg
                    break
            except (ValueError, TypeError):
                pass

    # 키워드 충족 비율
    present = [kw for kw in keywords if kw in text]
    ratio = len(present) / len(keywords) if keywords else 1.0

    # 등급 계산
    if warning or ratio < 0.4 or len(text) < 100:
        grade = "하"
    elif ratio >= 0.7 and len(text) >= 200 and not warning:
        grade = "상"
    else:
        grade = "중"

    # 힌트: 가장 중요한 누락 키워드 제안
    missing = [kw for kw in keywords if kw not in text]
    hint: Optional[str] = None
    if missing and len(text.strip()) > 20:
        hint = f"'{missing[0]}'을(를) 추가하면 설득력이 높아집니다."

    return {"hint": hint, "grade": grade, "warning": warning}
