# 서울 경매 신건 알림 — 사용법

신혼부부 예산·조건에 맞는 **서울 아파트 경매 신건**을 매일 긁어서 요약·알림.

## 구성
| 파일 | 역할 |
|------|------|
| `scraper/fetch_auction_seoul.py` | 법원경매정보 수집 → `data/auction_raw_{날짜}.json` |
| `scripts/filter_auction_new.py` | 서울·신건·예산 필터 → `data/auction_new_{날짜}.json` + 다이제스트 |
| `config/auction_filter.json` | 필터 기준(면적·감정가·세대수 등) — 편집 가능 |
| `data/auction_mock_sample.json` | 네트워크 없이 테스트용 목업 |

## 필터 기준 (config/auction_filter.json)
- 전용 54~85㎡ · 감정가 7.0~11.5억 · 신건(유찰 0회)만
- 특수물건(지분·대항력·유치권 등) 제외 → 별도 "참고" 목록으로 표시
- 세대수 300+ (물건명이 `budget_all_seoul.json` 단지와 매칭될 때만 적용)
- 서울 25개 구 / 서울권 법원(중앙·동부·서부·남부·북부)

## 실행

### 1) 목업으로 로직 확인 (네트워크 불필요)
```bash
python scraper/fetch_auction_seoul.py --mock
python scripts/filter_auction_new.py
```

### 2) 실데이터 수집 (네트워크 열린 로컬에서)
```bash
python scraper/fetch_auction_seoul.py     # courtauction.go.kr 실접속
python scripts/filter_auction_new.py
```

## ⚠️ 실접속 전 완성 필요 (한 번만)
`fetch_auction_seoul.py` 의 `fetch_real()` 에 **TODO** 3곳이 있습니다.
법원경매정보는 공개 API가 없어, 실제 조회 시 뜨는 XHR(JSON) 구조를 확인해 채워야 해요:
1. **조회 XHR URL** — 개발자도구 Network 탭에서 "용도=아파트, 소재지=서울" 검색 시 뜨는 JSON 요청 경로
2. **검색 폼 조작** — 용도/소재지 선택 + 검색 버튼 셀렉터
3. **응답 필드 매핑** — 사건번호·감정가·최저가·면적·유찰횟수 실제 키명

로컬 Claude에게 "fetch_auction_seoul.py 의 fetch_real TODO를 실제 사이트 보고 완성해줘"
라고 하면, 네트워크가 열린 환경에서 사이트를 열어 셀렉터를 확인하고 채워줍니다.

## 매일 자동 알림 (선택)
네트워크가 열린 환경(로컬 상시 실행 PC 또는 웹환경 도메인 허용 시)에서:
- **GitHub Actions**: `track_listings.py` 처럼 cron 워크플로로 매일 실행 → 결과를 이슈/커밋
- **Claude Code Routine**: 매일 아침 세션을 띄워 위 2개 실행 → 다이제스트를 푸시/메일 발송
- 다이제스트(표준출력)를 그대로 알림 본문으로 사용

## 소스 주의
- `courtauction.go.kr`(법원 공식)이 유일하게 정당한 무료 소스. 봇차단·세션토큰 있어 유지보수 필요.
- 호갱노노/모두의경매 등은 약관상 자동수집 금지 → 권장하지 않음.
