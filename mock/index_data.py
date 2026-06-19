"""
mock 데이터 → Azure AI Search 인덱싱 스크립트

처리 대상:
  - compony-dictionary.json  : 조항(6개) 단위로 분할 → 인덱싱
  - bnk-loan-output.json     : 기업(500개) 단위로 분할 → 인덱싱
  - sample-company-data.json : 인덱싱 제외 (백엔드 직접 조회용)

기존 인덱스 스키마(loan-knowledge-source-index):
  uid, snippet_parent_id, blob_url, snippet, snippet_vector
"""

import json
import os
import time
import requests
from pathlib import Path

# ── 설정 ────────────────────────────────────────────────────────────────────
MOCK_DIR = Path(__file__).parent

OPENAI_ENDPOINT    = os.environ["AZURE_OPENAI_ENDPOINT"]
OPENAI_API_KEY     = os.environ["AZURE_OPENAI_API_KEY"]
EMBEDDING_DEPLOY   = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")

SEARCH_ENDPOINT = os.environ["AZURE_SEARCH_ENDPOINT"]
SEARCH_KEY      = os.environ["AZURE_SEARCH_KEY"]
SEARCH_INDEX    = os.environ.get("AZURE_SEARCH_INDEX", "loan-knowledge-source-index")

BATCH_SIZE   = 50   # AI Search 업로드 배치 크기
MAX_CHARS    = 6000  # 임베딩 입력 최대 글자 수 (8191 토큰 안전 여유)


# ── 헬퍼 ────────────────────────────────────────────────────────────────────
def get_embedding(text: str) -> list[float]:
    url = (f"{OPENAI_ENDPOINT}/openai/deployments/{EMBEDDING_DEPLOY}"
           f"/embeddings?api-version={OPENAI_API_VERSION}")
    resp = requests.post(
        url,
        headers={"api-key": OPENAI_API_KEY, "Content-Type": "application/json"},
        json={"input": text[:MAX_CHARS]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def push_to_search(docs: list[dict]):
    url = (f"{SEARCH_ENDPOINT}/indexes/{SEARCH_INDEX}"
           f"/docs/index?api-version=2024-11-01-preview")
    resp = requests.post(
        url,
        headers={"api-key": SEARCH_KEY, "Content-Type": "application/json"},
        json={"value": docs},
        timeout=60,
    )
    if resp.status_code not in (200, 207):
        raise RuntimeError(f"Search 업로드 실패: {resp.status_code} {resp.text[:300]}")
    results = resp.json().get("value", [])
    failed = [r for r in results if not r.get("status")]
    if failed:
        print(f"  ⚠️  일부 실패: {len(failed)}건")


def upload_in_batches(all_docs: list[dict], label: str):
    total = len(all_docs)
    for i in range(0, total, BATCH_SIZE):
        batch = all_docs[i: i + BATCH_SIZE]
        print(f"  업로드 {i+1}~{min(i+len(batch), total)} / {total}")
        push_to_search(batch)
        if i + BATCH_SIZE < total:
            time.sleep(0.3)
    print(f"  ✅ {label} 완료: {total}개 문서")


# ── 변환 함수 ────────────────────────────────────────────────────────────────
def article_to_text(article: dict) -> str:
    parts = [f"{article['id']} {article['title']}"]

    if "content" in article:
        parts.append(article["content"])

    for rule in article.get("rules", []):
        line = f"[{rule.get('rule_id', '')}] {rule.get('name', '')}"
        if "condition" in rule:
            line += f" | 조건: {rule['condition']}"
        if "threshold" in rule:
            line += f" | 임계치: {rule['threshold']}"
        if "action" in rule:
            line += f" | 조치: {rule['action']}"
        parts.append(line)

    for doc in article.get("required_documents", []):
        parts.append(f"[{doc.get('doc_id','')}] {doc.get('name','')}: {doc.get('detail','')}")

    if "critical_rule" in article:
        cr = article["critical_rule"]
        parts.append(f"핵심규칙: {cr.get('name','')} | 조건: {cr.get('condition','')} | 조치: {cr.get('action','')}")

    for cov in article.get("covenants", []):
        line = f"[{cov.get('covenant_id','')}] {cov.get('name','')}"
        if "formula" in cov:
            line += f" | 산식: {cov['formula']}"
        if "threshold" in cov:
            line += f" | 임계치: {cov['threshold']}{cov.get('unit','')}"
        if "condition" in cov:
            line += f" | 조건: {cov['condition']}"
        if "critical_action" in cov:
            line += f" | 위반시: {cov['critical_action']}"
        parts.append(line)

    if "exception_clause" in article:
        ec = article["exception_clause"]
        parts.append(f"예외조항: {ec.get('name','')} | {ec.get('condition','')} → {ec.get('action','')}")

    return "\n".join(parts)


def fmt_억(won: int) -> str:
    """원 단위 숫자를 억원 단위 문자열로 변환"""
    if not won:
        return "0억원"
    return f"{round(won / 1e8, 1)}억원"


def merged_to_text(biz_id: str, company: dict, review: dict) -> str:
    """서류 수치 + 심사의견을 하나의 검색 문서로 합성"""
    parts = [
        f"사업자등록번호: {biz_id}",
        f"업종그룹: {review.get('업종그룹', '')}",
        f"전담심사역: {review.get('전담심사역', '')}",
        f"대출유형: {review.get('대출유형', '')}",
        f"승인결과: {review.get('승인결과', '')}",
    ]

    # ── 서류 수치 ──────────────────────────────────────────────────
    info = company.get("company_info", {})
    fin  = company.get("financial_statements", {})
    vat  = company.get("vat_tax_certificate", {})
    inc  = company.get("income_certificate", {})
    sal  = company.get("sales_data", {}).get("annual_sales_by_year", {})
    col  = company.get("collateral_auction_value", {})

    # 파생 재무 비율 계산
    assets      = fin.get("total_assets", 0)
    liabilities = fin.get("total_liabilities", 0)
    op_income   = fin.get("operating_income", 0)
    interest    = fin.get("finance_cost_interest", 0)
    debt_ratio  = round(liabilities / assets * 100, 1) if assets else None
    icr         = round(op_income / interest, 2) if interest else None

    doc_lines = [
        "\n[입력 서류 수치]",
        f"기업명: {info.get('company_name', '')}",
        f"내부신용등급: {info.get('internal_credit_rating', '')} | CSS신용등급: {info.get('css_credit_rating', '')}",
        f"산업분류코드: {info.get('industry_code', '')}",
        f"총자산: {fmt_억(assets)} | 총부채: {fmt_억(liabilities)}",
        f"부채비율: {debt_ratio}%" if debt_ratio is not None else "부채비율: 산출불가",
        f"영업이익: {fmt_억(op_income)} | 금융비용(이자): {fmt_억(interest)}",
        f"이자보상배율(ICR): {icr}배" if icr is not None else "이자보상배율: 산출불가",
        f"최근1년매출(부가세증명): {fmt_억(vat.get('annual_revenue_1yr', 0))}",
        f"사업영위기간: {vat.get('business_period_months', '')}개월",
        f"대표이사 과세급여: {fmt_억(inc.get('taxable_salary', 0))} ({inc.get('income_type', '')})",
        f"연도별매출: 2023년 {fmt_억(sal.get('2023',0))} / 2024년 {fmt_억(sal.get('2024',0))} / 2025년 {fmt_억(sal.get('2025',0))}",
        f"담보 감정평가액: {fmt_억(col.get('collateral_appraisal_value', 0))}",
        f"지역 낙찰가율: {round(col.get('regional_auction_rate_1yr', 0)*100, 1)}% | 낙찰건수: {col.get('regional_auction_count_1yr', '')}건",
    ]
    parts.extend(doc_lines)

    # ── 심사의견 ───────────────────────────────────────────────────
    parts.append("\n[심사의견]")
    for field in [
        "업체현황(2011)", "자금용도(2012)", "금리결정적정성(2013)",
        "상환재원(1006,1007)", "특이사항(1009,2016)", "기술금융 및 ESG(2014)",
        "종합의견(2015,2009,7001,2006)", "미이행승인조건(1102)",
    ]:
        if review.get(field):
            parts.append(f"\n[{field}]\n{review[field]}")

    if review.get("핵심태그"):
        parts.append(f"\n핵심태그: {review['핵심태그']}")

    return "\n".join(parts)


# ── 메인 ─────────────────────────────────────────────────────────────────────
def index_dictionary():
    print("\n[1/2] compony-dictionary.json 인덱싱")
    with open(MOCK_DIR / "compony-dictionary.json", encoding="utf-8") as f:
        data = json.load(f)

    docs = []
    articles = data.get("articles", [])
    for i, article in enumerate(articles):
        print(f"  임베딩 생성: {article['id']} {article['title']} ({i+1}/{len(articles)})")
        text = article_to_text(article)
        vector = get_embedding(text)
        docs.append({
            "@search.action": "mergeOrUpload",
            "uid": f"dict-article-{i+1}",
            "snippet_parent_id": "company-dictionary",
            "blob_url": "mock/compony-dictionary.json",
            "snippet": text,
            "snippet_vector": vector,
        })
        time.sleep(0.1)

    upload_in_batches(docs, "규정 사전")


def index_loan_output():
    print("\n[2/2] bnk-loan-output.json + sample-company-data.json 합산 인덱싱")
    with open(MOCK_DIR / "bnk-loan-output.json", encoding="utf-8") as f:
        reviews = json.load(f)
    with open(MOCK_DIR / "sample-company-data.json", encoding="utf-8") as f:
        companies = json.load(f)

    items = list(reviews.items())
    total = len(items)
    docs = []
    missing = 0

    for i, (biz_id, review) in enumerate(items):
        company = companies.get(biz_id, {})
        if not company:
            missing += 1

        text = merged_to_text(biz_id, company, review)
        vector = get_embedding(text)
        docs.append({
            "@search.action": "mergeOrUpload",
            "uid": f"loan-{biz_id}",
            "snippet_parent_id": f"loan-{review.get('전담심사역','unknown').replace(' ','')}",
            "blob_url": "mock/merged-loan-case.json",
            "snippet": text,
            "snippet_vector": vector,
        })

        if (i + 1) % 10 == 0 or (i + 1) == total:
            print(f"  임베딩 생성 중: {i+1}/{total}")

        if len(docs) == BATCH_SIZE:
            print(f"  업로드 {i - BATCH_SIZE + 2}~{i+1} / {total}")
            push_to_search(docs)
            docs = []
            time.sleep(0.3)

    if docs:
        print(f"  업로드 나머지 {len(docs)}건")
        push_to_search(docs)

    print(f"  ✅ 합산 인덱싱 완료: {total}개 문서 (서류 미매핑: {missing}건)")


if __name__ == "__main__":
    print("=== AI Search 인덱싱 시작 ===")
    print(f"대상 인덱스: {SEARCH_INDEX}")
    index_dictionary()
    index_loan_output()
    print("\n=== 완료 ===")
    print("AZURE_SEARCH_INDEX=loan-knowledge-source-index 확인 완료")
