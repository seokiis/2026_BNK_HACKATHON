# 구현 명세 01: 실험용 Input 데이터 생성

> 이 파일을 읽고 구현하세요. 기존 코드는 수정하지 않습니다.

---

## 목표

`data/sample_company_data.json`과 동일한 구조로 **데모용 기업 4개**를 만든다.
기존 500개 데이터에 학습되지 않은 새로운 기업을 넣어 실제 동작을 검증한다.

---

## 파일 위치

```
data/demo_companies.json
```

---

## 데이터 구조 (기존과 동일)

```json
{
  "사업자등록번호(10자리)": {
    "company_info": {
      "company_name": "str",
      "internal_credit_rating": "str (AAA~D)",
      "css_credit_rating": "str",
      "industry_code": "str (C10, C26, G45 등)",
      "dart_code": "str (실제 DART corp_code 사용)"
    },
    "income_certificate": {
      "issue_date": "YYYY-MM-DD",
      "taxable_salary": "int (원)",
      "income_type": "Business"
    },
    "vat_tax_certificate": {
      "issue_date": "YYYY-MM-DD",
      "annual_revenue_1yr": "int (원)",
      "business_period_months": "int (개월)"
    },
    "financial_statements": {
      "fiscal_year": "2024",
      "total_assets": "int",
      "total_liabilities": "int",
      "operating_income": "int",
      "finance_cost_interest": "int"
    },
    "sales_data": {
      "annual_sales_by_year": {
        "2023": "int",
        "2024": "int",
        "2025": "int"
      }
    },
    "collateral_auction_value": {
      "collateral_appraisal_value": "int",
      "regional_auction_rate_1yr": "float (0~1)",
      "regional_auction_count_1yr": "int"
    }
  }
}
```

---

## 4개 시나리오

### 시나리오 1: 재무 양호 → 승인

| 항목 | 값 |
|------|-----|
| 기업명 | 한양정밀테크 |
| 사업자번호 | 1234567890 |
| 내부등급 | A |
| 업종코드 | C29 (기계·장비 제조) |
| dart_code | 00164742 (실제 존재하는 기업 아무거나 OK) |
| 부채비율 | ~80% (total_liabilities / (total_assets - total_liabilities)) |
| ICR | 3.5배 (operating_income / finance_cost_interest) |
| 매출 추세 | 3년 연속 성장 |
| 담보 낙찰가율 | 0.82 |

### 시나리오 2: 재무 불량 + 산업 호황 → 조건부 승인 기대

| 항목 | 값 |
|------|-----|
| 기업명 | 동진반도체소재 |
| 사업자번호 | 2345678901 |
| 내부등급 | BB+ |
| 업종코드 | C26 (반도체·전자부품) |
| dart_code | 00401731 |
| 부채비율 | ~250% (내규 200% 초과 → 반려 트리거) |
| ICR | 1.2배 (기준 미달 경계) |
| 매출 추세 | 3년 연속 성장 (반도체 호황 반영) |
| 담보 낙찰가율 | 0.78 |

> **핵심**: 재무만 보면 반려지만, DART·Bing으로 산업 호황 근거를 찾아 보완 가능

### 시나리오 3: 재무 불량 + 산업 침체 → 반려

| 항목 | 값 |
|------|-----|
| 기업명 | 삼원건설개발 |
| 사업자번호 | 3456789012 |
| 내부등급 | BB- |
| 업종코드 | F41 (건설업) |
| dart_code | 00128884 |
| 부채비율 | ~300% |
| ICR | 0.8배 (내규 금지 수준) |
| 매출 추세 | 3년 연속 하락 |
| 담보 낙찰가율 | 0.65 (내규 75% 미만 → LTV 차감) |

### 시나리오 4: 재무 경계선 + 뉴스 긍정 → 조건부 승인 기대

| 항목 | 값 |
|------|-----|
| 기업명 | 남해바이오팜 |
| 사업자번호 | 4567890123 |
| 내부등급 | BBB |
| 업종코드 | C21 (의약품 제조) |
| dart_code | 00359273 |
| 부채비율 | ~195% (200% 바로 아래, 미묘) |
| ICR | 1.6배 (기준 1.5배 간신히 초과) |
| 매출 추세 | 2023 하락, 2024-2025 회복 |
| 담보 낙찰가율 | 0.77 |

> **핵심**: 숫자는 경계선인데, 바이오 정부 지원 뉴스가 긍정 근거

---

## 구현 시 주의

1. 숫자를 대충 넣지 말고, 위 부채비율·ICR 조건에 맞게 **역산**해서 넣을 것
   - 부채비율 = total_liabilities / (total_assets - total_liabilities) × 100
   - ICR = operating_income / finance_cost_interest
2. `dart_code`는 실제 DART에서 조회 가능한 기업코드를 사용해도 되고, 가상이어도 됨
3. 기존 `sample_company_data.json`은 절대 수정하지 않음
4. 새 파일 `data/demo_companies.json`으로 별도 생성
