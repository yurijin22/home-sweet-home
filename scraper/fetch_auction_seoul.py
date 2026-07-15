"""
서울 아파트 경매 물건 수집 — 법원경매정보(courtauction.go.kr)
저장: data/auction_raw_{YYYY_MM_DD}.json  (원본 물건 리스트, 필터 전)

두 가지 모드:
  --mock   : 네트워크 없이 data/auction_mock_sample.json 을 그대로 raw로 복사 (필터 로직 테스트용)
  (기본)   : Playwright 로 courtauction.go.kr 실접속 → 서울 아파트 검색 결과 파싱

⚠️ 실접속(Playwright) 파트는 courtauction.go.kr 의 실제 응답 구조 확인이 필요합니다.
   법원경매정보는 공개 API가 없어 HTML/XHR 스크래핑이며, 사이트 개편 시 셀렉터가 바뀝니다.
   TODO 표시된 곳을 실제 응답 보고 채워야 동작합니다. (네트워크 열린 로컬 환경에서 진행)

수집 스키마(항목당):
  case_no, court, name, dong, ho, floor,
  area_m2, area_pyeong, appraisal_eok, min_price_eok,
  fail_count, sale_date, gu, special, url
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_DIR = ROOT / 'data'
MOCK_PATH = OUT_DIR / 'auction_mock_sample.json'

# 법원경매정보 물건검색 진입점 (개편 후 URL — 실제 확인 필요)
SEARCH_URL = 'https://www.courtauction.go.kr/pgj/index.on'


def _pyeong(area_m2):
    return round(area_m2 / 3.3058, 1) if area_m2 else None


async def fetch_real(headless=True):
    """courtauction.go.kr 실접속 파싱. 네트워크가 열린 환경에서만 동작.

    구현 전략(track_listings.py 와 동일 패턴):
      1) 물건검색 화면 진입 → 용도=아파트, 소재지=서울특별시 선택
      2) 페이지가 조회 결과를 가져오는 XHR(JSON)을 response 이벤트로 인터셉트
      3) 응답 JSON에서 물건 배열을 꺼내 위 스키마로 정규화
    """
    from playwright.async_api import async_playwright

    captured = []

    async def on_response(response):
        url = response.url
        # TODO: 실제 조회 XHR 경로 확인 후 조건 수정.
        #   개발자도구 Network 탭에서 "아파트/서울" 조회 시 뜨는 JSON 요청 URL 확인.
        #   예상 키워드: 'srchList', 'GaMul', 'ds_result' 등.
        if 'json' in (response.headers.get('content-type') or '') and 'srch' in url.lower():
            try:
                captured.append(await response.json())
            except Exception:
                pass

    items = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(locale='ko-KR')
        page = await context.new_page()
        page.on('response', on_response)
        try:
            await page.goto(SEARCH_URL, wait_until='networkidle', timeout=45000)
            # TODO: 검색 폼 조작 — 용도 '아파트', 소재지 '서울특별시' 선택 후 검색 클릭.
            #   await page.select_option(...); await page.click('검색 버튼 셀렉터')
            #   await page.wait_for_load_state('networkidle')
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f'[fetch_real] navigation error: {e}', file=sys.stderr)
        finally:
            await browser.close()

    # TODO: captured(원본 JSON) → 표준 스키마 매핑.
    #   실제 필드명 확인 후 아래 매핑 완성. (예시 필드명 — 반드시 실응답으로 교체)
    for payload in captured:
        rows = payload.get('data') or payload.get('resultList') or []
        for r in rows:
            area_m2 = _to_float(r.get('jgProByeol') or r.get('area'))
            items.append({
                'case_no': r.get('userCsNo') or r.get('caseNo'),
                'court': r.get('cortNm') or r.get('court'),
                'name': r.get('printSt') or r.get('bldNm') or r.get('name'),
                'dong': r.get('dong'), 'ho': r.get('ho'),
                'floor': _to_int(r.get('floor')),
                'area_m2': area_m2, 'area_pyeong': _pyeong(area_m2),
                'appraisal_eok': _won_to_eok(r.get('gamevalAmt')),
                'min_price_eok': _won_to_eok(r.get('minBidAmt')),
                'fail_count': _to_int(r.get('failCnt')) or 0,
                'sale_date': r.get('bidYmd') or r.get('saleDate'),
                'gu': _gu_from_addr(r.get('addr') or ''),
                'special': r.get('specialCd') or '없음',
                'url': SEARCH_URL,
            })
    return items


def _to_float(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


def _to_int(v):
    try:
        return int(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


def _won_to_eok(v):
    f = _to_float(v)
    return round(f / 100_000_000, 2) if f else None


def _gu_from_addr(addr):
    for token in addr.split():
        if token.endswith('구'):
            return token[:-1]
    return '?'


def load_mock():
    with open(MOCK_PATH, encoding='utf-8') as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description='서울 아파트 경매 물건 수집')
    ap.add_argument('--mock', action='store_true', help='네트워크 없이 목업 데이터 사용')
    ap.add_argument('--headful', action='store_true', help='브라우저 화면 표시(디버깅)')
    args = ap.parse_args()

    if args.mock:
        items = load_mock()
        print(f'[mock] {len(items)}건 로드')
    else:
        items = asyncio.run(fetch_real(headless=not args.headful))
        print(f'[real] {len(items)}건 수집')

    today = datetime.now(KST).strftime('%Y_%m_%d')
    out_path = OUT_DIR / f'auction_raw_{today}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f'saved: {out_path} ({len(items)}건)')


if __name__ == '__main__':
    main()
