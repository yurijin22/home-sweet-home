"""
실거래가 + KAB 시세 수집 (v4 - 페이지 로드 + 리스너)
- 단지별로 페이지를 차례차례 로드 (네이버가 직접 호출하는 API를 캡처)
- 첫 응답에서 areaNo 확인, 우리 평형(54-68㎡)이 아니면 추가 호출
- Rate limit 회피를 위해 단지간 1.5초 대기
"""

import asyncio, json
from playwright.async_api import async_playwright


def _f(v):
    try: return float(v)
    except: return 0.0


async def fetch_one(page, complex_no):
    captures = {'overview': None, 'real': [], 'summary': []}

    async def on_response(response):
        url = response.url
        try:
            if f'/api/complexes/overview/{complex_no}' in url:
                captures['overview'] = await response.json()
            elif f'/api/complexes/{complex_no}/prices/real' in url:
                captures['real'].append(await response.json())
            elif f'/api/complexes/{complex_no}/prices' in url and 'type=summary' in url:
                captures['summary'].append(await response.json())
        except: pass

    page.on('response', on_response)
    try:
        await page.goto(
            f"https://new.land.naver.com/complexes/{complex_no}?a=APT&tab=H",
            wait_until='networkidle', timeout=20000,
        )
        await page.wait_for_timeout(2500)
    except: pass
    page.remove_listener('response', on_response)
    return captures


def pick_best(real_responses, summary_responses, target_pyeong_no):
    """우리 평형에 맞는 응답 고르기"""
    real = None
    for r in real_responses:
        if r.get('areaNo') == target_pyeong_no:
            real = r; break
    if not real and real_responses:
        real = real_responses[0]  # fallback to first

    summ = None
    for s in summary_responses:
        if s.get('areaNo') == target_pyeong_no:
            summ = s; break
    if not summ and summary_responses:
        summ = summary_responses[0]

    return real, summ


async def main():
    with open('../data/candidates_v2.json') as f:
        candidates = json.load(f)

    enriched = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        for i, c in enumerate(candidates, 1):
            cno = c['complex_no']
            cap = await fetch_one(page, cno)

            ov = cap.get('overview') or {}
            pyeongs = ov.get('pyeongs', []) or []
            target = next((p for p in pyeongs if 54 <= _f(p.get('exclusiveArea')) <= 68), None)
            target_no = target.get('pyeongNo') if target else None

            real, summ = pick_best(cap['real'], cap['summary'], target_no)
            real_area = real.get('areaNo') if real else None

            txs = []
            if real:
                for month in real.get('realPriceOnMonthList', []) or []:
                    for t in month.get('realPriceList', []) or []:
                        txs.append({
                            'date': t.get('formattedTradeYearMonth'),
                            'price': t.get('dealPrice'),
                            'floor': t.get('floor'),
                        })

            mp = (summ or {}).get('marketPrice', {}) or {}
            kab = {
                'kab_upper': mp.get('dealUpperPriceLimit'),
                'kab_avg': mp.get('dealAveragePrice'),
                'kab_lower': mp.get('dealLowPriceLimit'),
                'kab_change': mp.get('dealAveragePriceChangeAmount'),
                'lease_rate': mp.get('leasePerDealRate'),
                'base_date': mp.get('baseYearMonthDay'),
            }

            ok = '✓' if txs else '✗'
            match = '=' if real_area == target_no else f'(want {target_no} got {real_area})'
            print(f"[{i:>2}/25] {ok} {c['name']:25s} 거래 {len(txs):>3}건  KAB {kab.get('kab_avg', '-')}만 {match}")

            enriched.append({
                **c,
                'pyeong_no': target_no,
                'real_area_no': real_area,
                'transactions': txs,
                'transaction_count': len(txs),
                'kab_summary': kab,
            })

            await asyncio.sleep(1.5)  # rate limit 회피

        await context.close()
        await browser.close()

    with open('../data/candidates_with_prices.json', 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"\n저장: ../data/candidates_with_prices.json")


if __name__ == '__main__':
    asyncio.run(main())
