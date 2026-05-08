"""
서울 전체 격자 스캔 — 아파트 실매물 전수조사
조건: 전용 54~68㎡, 예산 7억~11억, 300세대+
zoom=15 격자(약 1km 간격) 840개 포인트
저장: data/scan_full.json  {단지명: {complex_no, region, household, min_price, count}}
"""
import asyncio, json, os, re
from playwright.async_api import async_playwright

DATA = '../data'
BUDGET_MIN  = 70000   # 7억 (만원)
BUDGET_MAX  = 110000  # 11억
AREA_MIN    = 54
AREA_MAX    = 68
HOUSEHOLD_MIN = 300
CONCURRENCY = 4

# 서울 격자 (zoom=15, 약 1km 간격)
def make_grid():
    points = []
    lat = 37.42
    while lat <= 37.70:
        lon = 126.77
        while lon <= 127.18:
            points.append((round(lat, 4), round(lon, 4)))
            lon = round(lon + 0.012, 4)
        lat = round(lat + 0.012, 4)
    return points

GRID = make_grid()


async def scan_point(context, lat, lon):
    """한 격자 포인트에서 단지 마커 + 매물 수집"""
    page = await context.new_page()
    markers = {}
    articles = {}

    async def on_resp(r):
        url = r.url
        try:
            if 'single-markers' in url and 'APT' in url:
                body = await r.text()
                data = json.loads(body)
                if isinstance(data, list):
                    for m in data:
                        cno = str(m.get('markerId', ''))
                        name = m.get('complexName', '')
                        hh = m.get('totalHouseHoldCount') or m.get('householdCount') or 0
                        if cno and name:
                            markers[cno] = {'name': name, 'household': int(hh or 0)}
            elif '/api/articles/complex/' in url and 'tradeType=A1' in url:
                cno = url.split('/api/articles/complex/')[1].split('?')[0]
                body = await r.text()
                articles[cno] = json.loads(body)
        except:
            pass

    page.on('response', on_resp)
    url = f"https://new.land.naver.com/complexes?ms={lat},{lon},15&a=APT&b=A1"
    try:
        await page.goto(url, wait_until='networkidle', timeout=25000)
        await page.wait_for_timeout(2000)
    except:
        pass
    await page.close()

    # 필터링
    results = {}
    for cno, minfo in markers.items():
        hh = minfo['household']
        if hh < HOUSEHOLD_MIN:
            continue
        name = minfo['name']
        arts = articles.get(cno, {})
        article_list = arts.get('articleList') or arts.get('articles') or []

        prices = []
        for a in article_list:
            # 면적 확인
            area = float(a.get('exclusiveArea') or a.get('area2') or 0)
            if not (AREA_MIN <= area <= AREA_MAX):
                continue
            # 가격 확인
            price_str = a.get('dealOrWarrantPrc') or a.get('price') or ''
            price_str = re.sub(r'[^\d]', '', str(price_str))
            if not price_str:
                continue
            price = int(price_str)
            if BUDGET_MIN <= price <= BUDGET_MAX:
                prices.append(price)

        if prices:
            results[name] = {
                'complex_no': cno,
                'household': hh,
                'min_price': min(prices),
                'count': len(prices),
            }

    return results


async def worker(sem, context, lat, lon, all_results, idx, total, lock, out_path):
    async with sem:
        found = await scan_point(context, lat, lon)
        async with lock:
            new = 0
            for name, info in found.items():
                if name not in all_results:
                    all_results[name] = info
                    new += 1
                elif info['min_price'] < all_results[name]['min_price']:
                    all_results[name]['min_price'] = info['min_price']
                    all_results[name]['count'] = max(all_results[name]['count'], info['count'])
            if idx % 20 == 0:
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)
            total_found = len(all_results)
            print(f"[{idx}/{total}] ({lat},{lon}) +{new}개 → 누적 {total_found}개", flush=True)


async def main():
    out_path = os.path.join(DATA, 'scan_full.json')
    if os.path.exists(out_path):
        with open(out_path) as f:
            all_results = json.load(f)
        print(f"기존 {len(all_results)}개 로드", flush=True)
    else:
        all_results = {}

    total = len(GRID)
    print(f"격자 {total}개 스캔 시작 (concurrency={CONCURRENCY})", flush=True)

    sem  = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )

        tasks = [
            worker(sem, context, lat, lon, all_results, i+1, total, lock, out_path)
            for i, (lat, lon) in enumerate(GRID)
        ]
        await asyncio.gather(*tasks)

        await context.close()
        await browser.close()

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(all_results)}개 단지 수집")
    print(f"저장: {out_path}")


if __name__ == '__main__':
    asyncio.run(main())
