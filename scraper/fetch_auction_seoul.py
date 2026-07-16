"""
서울 아파트 경매 물건 수집 — 법원경매정보(courtauction.go.kr)
저장: data/auction_raw_{YYYY_MM_DD}.json  (원본 물건 리스트, 필터 전)

두 가지 모드:
  --mock   : 네트워크 없이 data/auction_mock_sample.json 을 그대로 raw로 복사 (필터 로직 테스트용)
  (기본)   : Playwright 로 courtauction.go.kr 실접속 → 서울 아파트 검색 결과 파싱

⚙️ 실접속(Playwright) 구현 완료 — courtauction.go.kr(WebSquare) 물건상세검색 UI를 구동한다.
   법원경매정보는 공개 API가 없고 직접 XHR 재생은 IP 차단되므로, 반드시 UI 클릭 경로로
   조회 결과(searchControllerMain XHR)를 인터셉트한다. 서울 5개 지방법원을 순회하며
   '건물>주거용건물>아파트'를 검색하고 페이지네이션으로 전 페이지를 수집한다.
   ⚠️ 사이트 개편 시 폼 컨트롤 id(PFX 등)/XHR 경로가 바뀔 수 있다. 그때는
      개발자도구 Network 탭에서 조회 XHR과 폼 id를 다시 확인해 상수를 갱신할 것.

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

# 법원경매정보(courtauction.go.kr) — WebSquare 기반, 공개 API 없음.
INDEX_URL = 'https://www.courtauction.go.kr/pgj/index.on'
# 물건상세검색 실행 시 결과 리스트를 반환하는 XHR (POST/JSON)
SEARCH_XHR = 'searchControllerMain'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

# 폼 컨트롤 id 프리픽스 (물건상세검색 화면)
PFX = 'mf_wfm_mainFrame_sbx_'
BTN_DETAIL = '#mf_wfm_header_anc_auctnGdsMain'   # 물건상세검색 진입
BTN_SEARCH = '#mf_wfm_mainFrame_btn_gdsDtlSrch'  # 검색 실행
PAGER_ID = 'mf_wfm_mainFrame_pgl_gdsDtlSrchPage_page_'  # + N (2,3,...)

# 서울 소재 아파트를 관할하는 5개 지방법원. 시/도(서울)만 걸면 서울중앙 1곳으로
# 자동 한정되고, 법원=전체는 지역 필터가 풀려 전국이 잡히므로 법원별로 순회한다.
SEOUL_COURTS = [
    '서울중앙지방법원', '서울동부지방법원', '서울서부지방법원',
    '서울남부지방법원', '서울북부지방법원',
]
MAX_PAGES = 30  # 법원당 페이지 상한 (10건/page → 최대 300건, 안전 상한)


def _pyeong(area_m2):
    return round(area_m2 / 3.3058, 1) if area_m2 else None


async def _set_select(page, sid, value):
    """WebSquare 커스텀 select: visibility 무시하고 값 세팅 + change 이벤트."""
    await page.eval_on_selector(
        f'#{sid}',
        "(e,v)=>{e.value=v;e.dispatchEvent(new Event('change',{bubbles:true}));"
        "e.dispatchEvent(new Event('input',{bubbles:true}));}",
        value,
    )
    await page.wait_for_timeout(1500)


async def _wait_result(page, latest, timeout_ms=15000):
    """검색/페이지 클릭 후 새 searchControllerMain 응답이 담길 때까지 대기."""
    waited = 0
    while latest.get('body') is None and waited < timeout_ms:
        await page.wait_for_timeout(300)
        waited += 300
    return latest.get('body')


def _rows_of(body):
    d = (body or {}).get('data') or {}
    return d.get('dlt_srchResult') or [], _to_int(d.get('dma_pageInfo', {}).get('totalCnt')) or 0


async def _search_court(page, latest, court):
    """법원 하나에 대해 아파트 검색 후 전 페이지 원본 row 수집."""
    # 이전 검색 결과 화면에서 상세검색 폼으로 복귀 (폼 컨트롤 재확보)
    await page.locator(BTN_DETAIL).click(timeout=10000)
    await page.wait_for_selector(f'#{PFX}rletLclLst', timeout=15000)
    await page.wait_for_timeout(1500)
    # 분류(건물>주거용건물>아파트) + 법원 재설정 (매 순회마다 확실히)
    await _set_select(page, PFX + 'rletLclLst', '건물')
    await _set_select(page, PFX + 'rletMclLst', '주거용건물')
    await _set_select(page, PFX + 'rletSclLst', '아파트')
    await _set_select(page, PFX + 'rletCortOfc', court)

    latest['body'] = None
    await page.locator(BTN_SEARCH).click(timeout=8000)
    body = await _wait_result(page, latest)
    rows, total = _rows_of(body)
    collected = list(rows)
    if total > len(rows):
        import math
        npages = min(math.ceil(total / 10), MAX_PAGES)
        for pno in range(2, npages + 1):
            pager = page.locator(f'#{PAGER_ID}{pno}')
            if not await pager.count():
                # 페이지 그룹(10개) 밖 → 현재 구현 상한. 남은 건수 로그.
                print(f'[fetch_real] {court}: 페이저 {pno} 없음(그룹밖) — '
                      f'{total}건 중 {len(collected)}건까지만 수집', file=sys.stderr)
                break
            latest['body'] = None
            await pager.click(timeout=8000)
            body = await _wait_result(page, latest)
            more, _ = _rows_of(body)
            collected.extend(more)
    print(f'[fetch_real] {court}: {len(collected)}건 (신고 total {total})', file=sys.stderr)
    return collected


async def fetch_real(headless=True):
    """courtauction.go.kr 물건상세검색으로 서울 아파트 경매 물건 수집.

    네트워크가 열린 환경에서만 동작(법원경매정보는 공개 API 없음).
    직접 XHR 재생은 IP 차단되므로 반드시 UI 클릭 경로로만 응답을 받는다.
    서울 5개 지방법원을 순회하며 아파트 물건을 페이지네이션으로 수집 → 표준 스키마 정규화.
    매각기일 기본 창(대략 향후 2주)이 UI에서 자동 적용된다.
    """
    from playwright.async_api import async_playwright

    latest = {'body': None}

    async def on_response(response):
        if SEARCH_XHR in response.url and response.request.method == 'POST':
            try:
                latest['body'] = await response.json()
            except Exception:
                pass

    raw = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(locale='ko-KR', user_agent=UA)
        page = await context.new_page()
        page.on('response', on_response)
        try:
            await page.goto(INDEX_URL, wait_until='domcontentloaded', timeout=60000)
            await page.wait_for_timeout(3500)
            await page.locator(BTN_DETAIL).click(timeout=10000)
            await page.wait_for_timeout(4000)
            for court in SEOUL_COURTS:
                try:
                    raw.extend(await _search_court(page, latest, court))
                except Exception as e:
                    print(f'[fetch_real] {court} 검색 실패: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[fetch_real] navigation error: {e}', file=sys.stderr)
        finally:
            await browser.close()

    # 원본 row → 표준 스키마. docid 로 중복 제거(중복사건/여러 법원 노출 대비).
    items, seen = [], set()
    for r in raw:
        key = r.get('docid') or (r.get('srnSaNo'), r.get('maemulSer'))
        if key in seen:
            continue
        seen.add(key)
        items.append(_normalize(r))
    return items


def _normalize(r):
    """물건상세검색 원본 row → 수집 스키마."""
    dong, floor, ho = _parse_buld(r.get('buldList') or '')
    # 면적: areaList 우선, 없으면 convAddr('[집합건물 ... 84.93㎡]')에서 보강
    area_m2 = _parse_area(r.get('areaList') or '') or _parse_area(r.get('convAddr') or '')
    gu = (r.get('hjguSigu') or '').strip()
    if gu.endswith('구'):  # '서초구'→'서초', '중구'→'중' (필터/포맷에서 '구' 재부착)
        gu = gu[:-1]
    special = (r.get('mulBigo') or '').strip() or '없음'
    sano = r.get('saNo') or ''
    return {
        'case_no': r.get('srnSaNo') or r.get('printCsNo', '').split('<br/>')[0],
        'court': (r.get('jiwonNm') or '').replace('지방법원', '').replace('법원', ''),
        'name': (r.get('buldNm') or '').strip() or None,
        'dong': dong, 'ho': ho, 'floor': floor,
        'area_m2': area_m2, 'area_pyeong': _pyeong(area_m2),
        'appraisal_eok': _won_to_eok(r.get('gamevalAmt')),
        'min_price_eok': _won_to_eok(r.get('minmaePrice')),
        'fail_count': _to_int(r.get('yuchalCnt')) or 0,
        'sale_date': _fmt_ymd(r.get('maeGiil')),
        'gu': gu or '?',
        'special': special,
        'addr': (r.get('printSt') or '').strip(),
        # 개편 사이트는 물건 딥링크 URL이 없어 사건번호로 검색 안내
        'url': f'{INDEX_URL} (사건 {r.get("srnSaNo") or sano})',
    }


def _parse_buld(s):
    """'128동 26층2602호' / '에프동 14층1407호' / '4층410호' → (dong, floor, ho)."""
    import re
    dong = None
    m = re.search(r'(\S+?)동', s)
    if m:
        dong = m.group(1)
    floor = None
    m = re.search(r'(\d+)층', s)
    if m:
        floor = int(m.group(1))
    ho = None
    m = re.search(r'(\d+)호', s)
    if m:
        ho = m.group(1)
    return dong, floor, ho


def _parse_area(s):
    """'철근콘크리트구조  84.93㎡' → 84.93."""
    import re
    m = re.search(r'([\d.]+)\s*㎡', s)
    return float(m.group(1)) if m else None


def _fmt_ymd(v):
    """'20260723' → '2026-07-23'."""
    s = str(v or '')
    if len(s) >= 8 and s[:8].isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:8]}'
    return None


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
        # mock은 실데이터(auction_raw_{날짜}.json)를 덮지 않도록 별도 경로로 저장
        out_path = OUT_DIR / 'auction_raw_mock.json'
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
