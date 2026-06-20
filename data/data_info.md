# 📁 데이터 파일 정보 (Data Info)

---

## 1. sample_company_data.json

**설명:** 500개 기업의 정형 입력 데이터. 사업자등록번호를 Key로 한 기업 원천 정보.

**용도:** 여신심사 에이전트의 입력 소스

**구조:**
```json
{
  "사업자등록번호(10자리)": {
    "company_info": {
      "company_name": "str (기업명)",
      "internal_credit_rating": "str (내부신용등급: AAA~D)",
      "css_credit_rating": "str (CSS신용등급)",
      "industry_code": "str (산업분류코드: C10, C26, G45 등)",
      "dart_code": "str (DART법인코드)"
    },
    "income_certificate": {
      "issue_date": "str (발급일자: YYYY-MM-DD)",
      "taxable_salary": "int (과세대상급여액, 원)",
      "income_type": "str (소득종류: Employment/Business/Other)"
    },
    "vat_tax_certificate": {
      "issue_date": "str (발급일자)",
      "annual_revenue_1yr": "int (최근1년 매출액, 원)",
      "business_period_months": "int (사업영위기간, 개월)"
    },
    "financial_statements": {
      "fiscal_year": "str (결산연도)",
      "total_assets": "int (총자산, 원)",
      "total_liabilities": "int (총부채, 원)",
      "operating_income": "int (영업이익, 원)",
      "finance_cost_interest": "int (금융비용/이자, 원)"
    },
    "sales_data": {
      "annual_sales_by_year": {
        "2023": "int",
        "2024": "int",
        "2025": "int"
      }
    },
    "collateral_auction_value": {
      "collateral_appraisal_value": "int (담보물 감정평가액, 원)",
      "regional_auction_rate_1yr": "float (지역 낙찰가율, 0~1)",
      "regional_auction_count_1yr": "int (지역 낙찰건수)"
    }
  }
}
```

**레코드 수:** 500개 기업

---

## 2. company_dictionary.json

**설명:** BNK 여신지원본부 내규(제1조~제6조)를 JSON으로 구조화한 심사 규칙 사전.

**용도:** 에이전트가 승인/반려 판정 시 참조하는 규칙 엔진의 기준 데이터

**구조:**
```json
{
  "title": "지침 명칭",
  "department": "소관부서",
  "revision_date": "개정일",
  "articles": [
    {
      "id": "제N조",
      "title": "조항명",
      "rules": [
        {
          "rule_id": "N-N",
          "name": "규칙명",
          "condition": "적용 조건",
          "threshold": "임계치 (숫자)",
          "action": "판정 행위"
        }
      ]
    }
  ],
  "decision_logic_summary": {
    "reject_conditions": ["반려 조건 목록"],
    "approve_conditions": ["승인 조건 목록"],
    "conditional_approve": ["조건부 승인 사유"]
  }
}
```

**핵심 규칙 요약:**
| 조항 | 임계치 | 판정 |
|------|--------|------|
| 제3조 | 내부등급 < BBB- | 취급제한 |
| 제5조 | 부채비율 > 200% | 반려 (예외: 매출성장 시 참작) |
| 제5조 | 이자보상배율 < 1.0배 | 여신취급 금지 |
| 제5조 | 이자보상배율 < 1.5배 | 기준 미달 |
| 제6조 | 낙찰가율 < 75% | LTV 10%p 차감 |
| 제6조 | 낙찰건수 < 5건 | 통계 신뢰도 부족 |

---

## 3. bnk_loan_output.json

**설명:** 500개 기업에 대한 최종 여신 심사의견서. 내규 적용 결과 + 9대 영역별 한국어 정성 서술.

**용도:** 여신심사 최종 출력물. 여신시스템 이관용 보고서.

**구조:**
```json
{
  "사업자등록번호(10자리)": {
    "업종그룹": "str (외감 제조업 / 부동산개발/건설 / 서비스업 등)",
    "전담심사역": "str (심사역 A 또는 심사역 B)",
    "대출유형": "str (시설 및 운전자금 종합여신)",
    "승인결과": "str (승인 / 반려)",
    "업체현황(2011)": "str (업체개요 + 대표자현황 정성 서술)",
    "자금용도(2012)": "str (신청금액 + 자금용도 정합성 + @대출잔액표)",
    "금리결정적정성(2013)": "str (기준금리 + 우대조건 + @우대금리표)",
    "상환재원(1006,1007)": "str (ICR/부채비율 분석 + @현금흐름표 + 담보분석)",
    "특이사항(1009,2016)": "str (조세체납 + 신용등급 + DART공시)",
    "기술금융 및 ESG(2014)": "str (기술력/ESG 평가 또는 해당없음)",
    "종합의견(2015,2009,7001,2006)": "str (최종 결론 및 승인/반려 근거)",
    "미이행승인조건(1102)": "str (승인조건 부과 내역)",
    "핵심태그": "str (세미콜론 구분 키워드)"
  }
}
```

**통계:**
| 항목 | 값 |
|------|-----|
| 총 기업 수 | 500 |
| 승인 | 189건 (37.8%) |
| 반려 | 311건 (62.2%) |
| 파일 크기 | 1.71 MB |

---

## 📊 파일 간 관계도

```
sample_company_data.json (입력)
        │
        ▼
company_dictionary.json (규칙) ──→ 판정 엔진
        │
        ▼
bnk_loan_output.json (출력)
```

**흐름:** 입력 데이터 → 내규 규칙 적용 → 9대 영역별 심사의견서 생성
