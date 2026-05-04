# 🏠 Home Sweet Home — 내집마련 리서치 봇

예비 신혼부부 아파트 매물 트래킹 프로젝트

## 조건

| 항목 | 기준 |
|---|---|
| 예산 | 9억 (자력) ~ 11억 (시댁 포함) |
| 타입 | 전용 59㎡ 전후 (54~68㎡) |
| 세대수 | 300세대 이상 |
| 역세권 | 도보 10분 이내 |
| 우선순위 | 투자가치 > 통근 > 가격 |

**직장:** 신부 왕십리 / 신랑 과천 (양방향 통근 고려)

## 스크래퍼 구조

```
scraper/
├── scan_listings.py          # 지역별 전수 스캔 (처음 한 번)
├── scan_additional_regions.py # 추가 지역 스캔
└── track_prices.py           # 선정 단지 일별 트래킹

data/
├── listings_2026_05_04.json  # 전수 스캔 결과
└── track_YYYY_MM_DD.json     # 일별 트래킹 기록
```

## 사용법

### 1. 환경 설정

```bash
pip install playwright
playwright install chromium
```

### 2. 전수 스캔 (처음 한 번)

```bash
python3 scraper/scan_listings.py
```

→ `data/listings_YYYY_MM_DD.json` 생성

### 3. 트래킹 단지 설정

`scraper/track_prices.py` 의 `WATCH_LIST` 에 단지 추가:

```python
WATCH_LIST = [
    ("성현동아", "XXXXX", "동작_사당이수"),
    ("서대문센트럴아이파크", "YYYYY", "은평_녹번"),
]
```

complex_no는 스캔 결과 JSON에서 확인

### 4. 일별 트래킹 실행

```bash
python3 scraper/track_prices.py
```

자동화 (매일 오전 9시):
```bash
# crontab -e
0 9 * * * cd /path/to/home-sweet-home && python3 scraper/track_prices.py
```

## 현재까지 찾은 후보 단지

| 단지 | 지역 | 세대수 | 실매물 최저가 | 지하철 |
|---|---|---|---|---|
| 성현동아 | 동작 사당 | 1,261 | 10.8억 | 사당역 4호선 (과천 직통) |
| 두산 | 동대문 답십리 | 739 | 10.5억 | 답십리역 5호선 (왕십리 5분) |
| 서대문센트럴아이파크 | 은평 녹번 | 827 | 8.7억 | 녹번역 3호선 |
| 백련산힐스테이트2차 | 은평 녹번 | 1,148 | 8.4억 | 홍제역 3호선 |
| 새절역두산위브트레지움 | 은평 녹번 | 424 | 10.7억 | 새절역 6호선 |
| 길동우성 | 강동 길동 | 811 | 11.0억 | 길동역 5호선 |
| 라인 | 강서 가양 | 317 | 9.0억 | 가양역 9호선 |
| 등촌주공5단지 | 강서 가양 | 1,045 | 11.0억 | 염창역 9호선 (재건축) |

> 네이버 부동산 실매물 기준 (2026-05-04 스캔)
> 호가 기준이며 실거래가는 이보다 낮을 수 있음

## 데이터 출처

- **네이버 부동산** (new.land.naver.com) — 현재 매물 호가
- Playwright 브라우저 자동화로 수집
