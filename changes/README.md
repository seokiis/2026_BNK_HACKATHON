# changes/ 폴더 — 구현 명세 목록

> 이 폴더의 문서를 읽고 구현하세요. **기존 코드를 수정하지 않고** 새 파일을 추가합니다.

## 문서 목록

| 파일 | 내용 | 우선순위 |
|------|------|---------|
| `01_demo_input_data.md` | 실험용 기업 4개 JSON 데이터 생성 | 1 (먼저) |
| `02_dart_bing_grounding.md` | DART API + Bing Grounding 연동 서비스 | 2 (다음) |

## 구현 순서

1. **01번** 먼저: `data/demo_companies.json` 생성 (단순 JSON, 의존성 없음)
2. **02번** 다음: 백엔드 서비스 4개 파일 + config 수정 + 라우터 등록

## 원칙

- 기존 `data/sample_company_data.json` 절대 수정 금지
- 기존 서비스 파일 수정 최소화 (config.py 필드 추가, main.py 라우터 등록만)
- API 키는 `.env`에만 저장, 코드에 하드코딩 금지
- Azure 기술 활용을 극대화 (Bing Grounding = Azure 점수)
