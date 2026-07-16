"""
서울 아파트 경매 '낙찰결과' 수집 — 법원경매정보(courtauction.go.kr) 매각결과검색.
저장: data/auction_results_{YYYY_MM_DD}.json  (정규화된 낙찰결과 리스트)

fetch_auction_seoul.py 와 동일한 WebSquare 구동 방식.
  법원경매정보는 공개 API가 없고 직접 XHR 재생은 IP 차단되므로, 반드시 UI 클릭 경로로
  조회 결과(selectDspslSchdRsltSrch XHR)를 인터셉트한다. 물건상세검색이 아니라
  '매각결과검색'(dspslRsltSrch) 화면을 구동해 이미 종료된 매각기일의 낙찰/유찰 결과를 받는다.
  서울 5개(또는 --court 지정) 지방법원을 순회하며 '건물>주거용건물>아파트'를 검색하고
  페이지네이션으로 전 페이지를 수집한다.
  ⚠️ 사이트 개편 시 폼 컨트롤 id(PFX 등)/XHR 경로가 바뀔 수 있다. 그때는
     개발자도구 Network 탭에서 조회 XHR과 폼 id를 다시 확인해 상수를 갱신할 것.

매각결과검색 화면에는 매각기일 입력 필드가 없다(최근 매각기일 결과가 최신순으로 반환된다).
따라서 특정 날짜(--date)는 수집 후 maeGiil 로 클라이언트 필터링한다.

수집 스키마(항목당):
  case_no, court, name, dong, floor, ho, area_m2, area_pyeong, gu,
  appraisal_eok(감정가), min_price_eok(최저가), sale_price_eok(낙찰가),
  sale_rate(낙찰가율 %, 감정가 대비), sale_rate_min(낙찰가율 %, 최저가 대비),
  fail_count(유찰횟수), result(매각/유찰/기타),
  bidders(입찰자수 — courtauction 공개 검색결과 미제공이라 항상 None),
  sale_date(매각기일), decision_date(매각결정기일), special, addr, url
"""
import argparse
import asyncio
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
OUT_DIR = ROOT / 'data'

INDEX_URL = 'https://www.courtauction.go.kr/pgj/index.on'
# 매각결과검색 실행 시 결과 리스트를 반환하는 XHR (POST/JSON)
SEARCH_XHR = 'selectDspslSchdRsltSrch'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

# 폼 컨트롤 id (매각결과검색 화면)
BTN_RESULT = '#mf_wfm_header_anc_dspslRsltSrch'          # 매각결과검색 진입
PFX = 'mf_wfm_mainFrame_sbx_dspslRsltSrch'               # select 프리픽스
BTN_SEARCH = '#mf_wfm_mainFrame_btn_dspslRsltSrch'       # 검색 실행
PAGER_ID = 'mf_wfm_mainFrame_pgl_gdsDtlSrchPage_page_'   # + N (결과 그리드 재사용)

SEOUL_COURTS = [
    '서울중앙지방법원', '서울동부지방법원', '서울서부지방법원',
    '서울남부지방법원', '서울북부지방법원',
]
MAX_PAGES = 30  # 법원당 페이지 상한 (10건/page)


def _resolve_courts(spec):
    """--court 인자(예: '북부' / '서울북부지방법원' / '북부,중앙')를 정식 법원명으로."""
    if not spec:
        return list(SEOUL_COURTS)
    out = []
    for token in re.split(r'[,\s]+', spec.strip()):
        if not token:
            continue
        hit = next((c for c in SEOUL_COURTS if token in c or c in token), None)
        if hit and hit not in out:
            out.append(hit)
        elif not hit:
            print(f'[warn] 알 수 없는 법원 "{token}" 무시', file=sys.stderr)
    return out or list(SEOUL_COURTS)


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
    """검색/페이지 클릭 후 새 selectDspslSchdRsltSrch 응답이 담길 때까지 대기."""
    waited = 0
    while latest.get('body') is None and waited < timeout_ms:
        await page.wait_for_timeout(300)
        waited += 300
    return latest.get('body')


def _rows_of(body):
    d = (body or {}).get('data') or {}
    return d.get('dlt_srchResult') or [], _to_int((d.get('dma_pageInfo') or {}).get('totalCnt')) or 0


async def _search_court(page, latest, court):
    """법원 하나에 대해 아파트 매각결과 검색 후 전 페이지 원본 row 수집."""
    # 매각결과검색 폼은 검색 후에도 결과 그리드 위에 그대로 유지되므로 재진입 불필요.
    # (초기 진입은 fetch_real 에서 1회 수행) 폼 컨트롤이 살아있는지만 확인.
    await page.wait_for_selector(f'#{PFX}CortOfc', timeout=15000)
    await page.wait_for_timeout(800)
    # 법원 + 분류(건물>주거용건물>아파트) 재설정 (매 순회마다 확실히)
    await _set_select(page, PFX + 'CortOfc', court)
    await _set_select(page, PFX + 'LclLst', '건물')
    await _set_select(page, PFX + 'MclLst', '주거용건물')
    await _set_select(page, PFX + 'SclLst', '아파트')

    latest['body'] = None
    # 헤더 네비 오버레이가 검색 버튼 클릭을 가로채므로 JS click 으로 우회
    await page.eval_on_selector(BTN_SEARCH, "e=>e.click()")
    body = await _wait_result(page, latest)
    rows, total = _rows_of(body)
    collected = list(rows)
    if total > len(rows):
        npages = min(math.ceil(total / 10), MAX_PAGES)
        for pno in range(2, npages + 1):
            pager = page.locator(f'#{PAGER_ID}{pno}')
            if not await pager.count():
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


async def fetch_real(courts, headless=True):
    """courtauction.go.kr 매각결과검색으로 서울 아파트 낙찰결과 수집.

    네트워크가 열린 환경에서만 동작(법원경매정보는 공개 API 없음).
    직접 XHR 재생은 IP 차단되므로 반드시 UI 클릭 경로로만 응답을 받는다.
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
            await page.eval_on_selector(BTN_RESULT, "e=>e.click()")
            await page.wait_for_timeout(4000)
            for court in courts:
                try:
                    raw.extend(await _search_court(page, latest, court))
                except Exception as e:
                    print(f'[fetch_real] {court} 검색 실패: {e}', file=sys.stderr)
        except Exception as e:
            print(f'[fetch_real] navigation error: {e}', file=sys.stderr)
        finally:
            await browser.close()

    # 원본 row → 표준 스키마. docid 로 중복 제거.
    items, seen = [], set()
    for r in raw:
        key = r.get('docid') or (r.get('srnSaNo'), r.get('maemulSer'))
        if key in seen:
            continue
        seen.add(key)
        items.append(_normalize(r))
    return items


def _normalize(r):
    """매각결과검색 원본 row → 수집 스키마."""
    dong, floor, ho = _parse_buld(r.get('buldList') or '')
    area_m2 = _parse_area(r.get('areaList') or '') or _parse_area(r.get('convAddr') or '')
    gu = (r.get('hjguSigu') or '').strip()
    if gu.endswith('구'):
        gu = gu[:-1]
    special = (r.get('mulBigo') or '').strip() or '없음'

    appraisal = _to_float(r.get('gamevalAmt'))
    min_price = _to_float(r.get('minmaePrice'))
    sale_price = _to_float(r.get('maeAmt'))
    sold = bool(sale_price and sale_price > 0)
    if sold:
        result = '매각'
    elif r.get('mulStatcd') == '03':
        result = '유찰'
    else:
        result = '기타'  # 변경/취하/정지 등

    return {
        'case_no': r.get('srnSaNo') or (r.get('printCsNo') or '').split('<br/>')[0],
        'court': (r.get('jiwonNm') or '').replace('지방법원', '').replace('법원', ''),
        'name': (r.get('buldNm') or '').strip() or None,
        'dong': dong, 'floor': floor, 'ho': ho,
        'area_m2': area_m2, 'area_pyeong': _pyeong(area_m2),
        'gu': gu or '?',
        'appraisal_eok': _won_to_eok(appraisal),
        'min_price_eok': _won_to_eok(min_price),
        'sale_price_eok': _won_to_eok(sale_price) if sold else None,
        # 낙찰가율: 매각가/감정가 (표준 매각가율). 참고로 최저가 대비도 함께 제공.
        'sale_rate': round(sale_price / appraisal * 100, 1) if sold and appraisal else None,
        'sale_rate_min': round(sale_price / min_price * 100, 1) if sold and min_price else None,
        'fail_count': _to_int(r.get('yuchalCnt')) or 0,
        'result': result,
        # 입찰자수(응찰자수): courtauction 공개 매각결과검색 피드에 없음 → None.
        # 상용 서비스(지지옥션·탱크옥션 등)만 매각기일조서 기반으로 별도 제공.
        'bidders': None,
        'sale_date': _fmt_ymd(r.get('maeGiil')),
        'decision_date': _fmt_ymd(r.get('maegyuljGiil')),
        'special': special,
        'addr': (r.get('printSt') or '').strip(),
        'url': f'{INDEX_URL} (사건 {r.get("srnSaNo") or r.get("saNo") or ""})',
    }


def _parse_buld(s):
    """'809동 6층601호' / '4층410호' → (dong, floor, ho)."""
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
    m = re.search(r'([\d.]+)\s*㎡', s)
    return float(m.group(1)) if m else None


def _fmt_ymd(v):
    """'20260714' → '2026-07-14'."""
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


def _apply_date_or_fallback(items, date, fallback=True):
    """--date 로 매각기일 필터. 결과가 0건이고 fallback=True면 법원별 최신 매각기일로 대체.

    매각결과검색은 각 법원의 최근 매각기일 결과만 반환하므로, 요청 날짜에 매각기일이
    없던 법원(예: 요일이 안 맞는 경우)은 그 법원이 실제로 가진 가장 최근 매각기일로 대체한다.
    """
    hit = [it for it in items if it['sale_date'] == date]
    print(f'[filter] 매각기일 {date}: {len(hit)}건', file=sys.stderr)
    if hit or not fallback:
        return hit
    # 법원별 최신 매각기일로 폴백
    out = []
    for court in sorted({it['court'] for it in items}):
        crows = [it for it in items if it['court'] == court and it['sale_date']]
        if not crows:
            continue
        latest = max(it['sale_date'] for it in crows)
        picked = [it for it in crows if it['sale_date'] == latest]
        out.extend(picked)
        print(f'[fallback] {court}: 요청 {date} 결과 없음 → 최신 매각기일 {latest}로 대체 '
              f'({len(picked)}건)', file=sys.stderr)
    return out


def main():
    ap = argparse.ArgumentParser(description='서울 아파트 경매 낙찰결과 수집')
    ap.add_argument('--date', help='매각기일 필터 YYYY-MM-DD (예: 2026-07-15). 생략 시 수집된 최근 결과 전체')
    ap.add_argument('--court', help='법원 지정 (예: "북부" 또는 "북부,중앙"). 생략 시 서울 5개 전체')
    ap.add_argument('--result', choices=['매각', '유찰'], help='매각결과 유형 필터')
    ap.add_argument('--no-fallback', action='store_true',
                    help='--date 결과가 0건이어도 최신 매각기일로 대체하지 않음')
    ap.add_argument('--headful', action='store_true', help='브라우저 화면 표시(디버깅)')
    args = ap.parse_args()

    courts = _resolve_courts(args.court)
    print(f'[real] 대상 법원: {", ".join(courts)}', file=sys.stderr)
    items = asyncio.run(fetch_real(courts, headless=not args.headful))
    print(f'[real] {len(items)}건 수집 (필터 전)')

    if args.date:
        items = _apply_date_or_fallback(items, args.date, fallback=not args.no_fallback)
        print(f'[filter] 최종 {len(items)}건')
    if args.result:
        items = [it for it in items if it['result'] == args.result]
        print(f'[filter] 결과={args.result}: {len(items)}건')

    date_tag = (args.date or datetime.now(KST).strftime('%Y-%m-%d')).replace('-', '_')
    out_path = OUT_DIR / f'auction_results_{date_tag}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    print(f'saved: {out_path} ({len(items)}건)')


if __name__ == '__main__':
    main()
