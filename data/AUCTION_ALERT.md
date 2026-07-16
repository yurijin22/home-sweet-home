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

## 매일 자동 알림 — GitHub Actions (설정됨)
`.github/workflows/auction_alert.yml` 이 **매일 08:00 KST** 자동 실행:
1. Playwright 설치 → `fetch_auction_seoul.py` 실접속 수집
2. `filter_auction_new.py` 로 서울 신건 필터 → 다이제스트 생성
3. **조건 충족 신건이 있으면 GitHub 이슈 자동 생성** (저장소 소유자에게 assign)
4. 수집 0건이면 "수집 실패 경고" 이슈 (IP차단/사이트개편 감지용)
5. 결과 JSON은 Actions artifact로 14일 보관

### ⚙️ 설정 — 별도 Secret 불필요 ✅
이슈 생성은 GitHub 내장 `GITHUB_TOKEN` 을 쓰므로 **추가 설정이 없습니다.**
알림을 폰으로 받으려면:
- **GitHub 모바일 앱** 설치 → 로그인 → 저장소 Watch(또는 소유자는 자동) →
  이슈 생성 시 **푸시 알림** 수신
- GitHub 계정 이메일로도 이슈 알림이 자동 발송됨 (계정 알림 설정에 따름)

### 실행 시점 조정
- `auction_alert.yml` 의 `cron: '0 23 * * *'` (UTC) = 08:00 KST. 시간 바꾸려면 이 값 수정.
- **수동 테스트**: Actions 탭 → "Seoul auction 신건 alert" → Run workflow.

### ⚠️ IP 차단 가능성
법원경매정보가 GitHub(Azure) 데이터센터 IP를 막을 수 있습니다.
첫 수동 실행에서 "수집 0건 경고" 메일이 오면 차단된 것 →
로컬 Mac cron 으로 폴백하거나, self-hosted runner 검토.

## 매일 자동 알림 — 로컬 Mac 폴백 (선택)
GitHub Actions가 IP 차단되면 Mac 에서 `launchd`/`cron` 으로 매일 실행:
```bash
# crontab -e 에 추가 (매일 08:00, Mac 켜져 있을 때만)
0 8 * * * cd ~/home-sweet-home && /usr/bin/python3 scraper/fetch_auction_seoul.py && /usr/bin/python3 scripts/filter_auction_new.py
```

## 소스 주의
- `courtauction.go.kr`(법원 공식)이 유일하게 정당한 무료 소스. 봇차단·세션토큰 있어 유지보수 필요.
- 호갱노노/모두의경매 등은 약관상 자동수집 금지 → 권장하지 않음.

## 지능형 하네스 (신건 추천 + 예측 보정)
- `scripts/auction_intel.py`: 신건별 **예상낙찰가(=감정가×k)** + 시세매칭·할인율·통근·세대수 스코어 → **🟢추천/🟡관심/⚪보류/⚫패스** 판정. 예측을 `data/auction_predictions.json`에 누적 저장.
- `scripts/calibrate_auction.py`: 오늘 낙찰 실측을 과거 예측과 `case_no`로 대조 → 오차 로그(`data/auction_calibration.jsonl`) + **k 자동 보정**(`data/auction_k.json`). 매일 정확도가 올라감.
- k 기준값 0.92 (comps 356건 평균 낙찰가율), 실측 누적분으로 rolling 보정.
- ⚠️ 호재·역세권거리·학군은 데이터 불완전 → 점수 미반영, "확인 필요"로 표기(할루시네이션 금지).
