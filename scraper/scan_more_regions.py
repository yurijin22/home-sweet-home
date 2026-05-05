"""
서울 빠진 region 추가 스캔 (1차/2차 외)
- 핵심: 성동구(왕십리 본진), 양천 목동, 동대문 청량리/회기, 광진, 동작 노량진/흑석, 마포 망원,
  성북 정릉/안암, 영등포 여의도/신길, 강남/서초 예산 검증, 용산 등
- 단지 마커 → 300세대+ 필터 → 평형 54~68 + 11억 이하 매물 조회
"""

import asyncio, json
from playwright.async_api import async_playwright

REGIONS = [
    # S급 — 신부 직장 본진 (왕십리)
    ("성동_왕십리행당",  37.5614, 127.0364, 15),
    ("성동_마장금호",    37.5510, 127.0410, 15),
    ("성동_옥수응봉",    37.5407, 127.0125, 15),
    ("성동_성수",        37.5444, 127.0557, 15),
    # 학군 핵심
    ("양천_목동",        37.5267, 126.8755, 15),
    # 동대문 추가
    ("동대문_청량리회기", 37.5870, 127.0535, 15),
    ("동대문_전농",      37.5821, 127.0566, 15),
    # 광진 추가
    ("광진_군자화양",    37.5520, 127.0735, 15),
    # 동작 추가
    ("동작_노량진흑석",  37.5114, 126.9530, 15),
    # 마포 추가
    ("마포_망원합정",    37.5530, 126.9120, 15),
    ("마포_상암",        37.5790, 126.8910, 15),
    # 성북 추가
    ("성북_정릉안암",    37.5965, 127.0220, 15),
    # 영등포 추가
    ("영등포_여의도",    37.5219, 126.9245, 15),
    ("영등포_당산",      37.5347, 126.9019, 15),
    ("영등포_신길",      37.5127, 126.9123, 15),
    # 서대문/은평 추가
    ("서대문_홍은남가좌", 37.5848, 126.9266, 15),
    ("은평_응암수색",    37.5874, 126.9046, 15),
    # 강서 추가
    ("강서_마곡등촌",    37.5537, 126.8423, 15),
    # 관악
    ("관악_봉천신림",    37.4830, 126.9407, 15),
    # 강동 추가
    ("강동_천호암사",    37.5390, 127.1265, 15),
    # 예산 검증 — 강남/서초/용산
    ("강남_도곡대치",    37.4866, 127.0500, 15),
    ("서초_방배",        37.4823, 126.9892, 15),
    ("용산_이촌도원",    37.5189, 126.9657, 15),
    # 도봉/구로 추가
    ("도봉_방학",        37.6664, 127.0440, 15),
    ("구로_개봉",        37.4942, 126.8580, 15),
]

BUDGET_MAX = 110000
AREA_MIN = 54
AREA_MAX = 68
HOUSEHOLD_MIN = 300


async def scrape_region(browser, region, lat, lon, zoom):
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        locale='ko-KR',
    )
    page = await context.new_page()
    markers = []

    async def on_response(response):
        url = response.url
        if 'single-markers' in url and 'APT' in url:
            try:
                body = await response.text()
                data = json.loads(body)
                if isinstance(data, list):
                    markers.extend(data)
            except: pass

    page.on('response', on_response)
    url = f"https://new.land.naver.com/complexes?ms={lat},{lon},{zoom}&a=APT&b=A1"
    try:
        await page.goto(url, wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(2500)
    except: pass
    await context.close()
    return markers


async def fetch_articles(page, complex_no):
    arts = []
    async def on_response(response):
        url = response.url
        if f'/api/articles/complex/{complex_no}' in url and 'tradeType=A1' in url:
            try:
                body = await response.text()
                data = json.loads(body)
                arts.extend(data.get('articleList', []))
            except: pass
    page.on('response', on_response)
    try:
        await page.goto(
            f"https://new.land.naver.com/complexes/{complex_no}?a=APT&b=A1&e=RETAIL",
            wait_until='networkidle', timeout=20000,
        )
        await page.wait_for_timeout(1500)
    except: pass
    page.remove_listener('response', on_response)
    return arts


async def main():
    # 기존 단지 (중복 제거용)
    seen = set()
    for fp in ['../data/listings_2026_05_04.json', '../data/listings_additional_2026_05_04.json']:
        with open(fp) as f:
            for item in json.load(f):
                seen.add(str(item['complex_no']))

    print(f"기존 단지 {len(seen)}개 (중복 스킵)\n")

    all_markers = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 1단계: 새 region 마커 수집
        print("=== 1단계 마커 ===")
        for region, lat, lon, zoom in REGIONS:
            markers = await scrape_region(browser, region, lat, lon, zoom)
            new = [m for m in markers
                   if m.get('totalHouseholdCount', 0) >= HOUSEHOLD_MIN
                   and m.get('markerType') == 'COMPLEX'
                   and str(m.get('markerId')) not in seen
                   and str(m.get('markerId')) not in all_markers]
            for m in new:
                all_markers[str(m['markerId'])] = {**m, 'region': region}
            print(f"  [{region:18s}] {len(markers)}개 → 신규 300세대+ {len(new)}개")

        print(f"\n신규 단지 총 {len(all_markers)}개\n")

        # 2단계: 매물 조회
        print("=== 2단계 매물 조회 ===")
        results = []
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        for i, (cno, info) in enumerate(all_markers.items(), 1):
            cn = info.get('complexName', '')
            hh = info.get('totalHouseholdCount', 0)
            region = info.get('region', '')
            try:
                arts = await fetch_articles(page, cno)
            except Exception as e:
                print(f"  [{i}/{len(all_markers)}] {cn} 실패: {e}")
                continue

            filtered = [
                {'price': a.get('dealOrWarrantPrc', ''),
                 'area': a.get('area2', 0),
                 'floor': a.get('floorInfo', ''),
                 'desc': a.get('articleFeatureDesc', ''),
                 'direction': a.get('direction', '')}
                for a in arts
                if AREA_MIN <= float(a.get('area2', 0) or 0) <= AREA_MAX
            ]
            if filtered:
                print(f"  [{i:>3}/{len(all_markers)}] ✓ {cn:25s} | {region:18s} | {hh:>4}세대 | {len(filtered):>3}매물")
                results.append({
                    'region': region, 'complex_no': cno, 'name': cn,
                    'household': hh, 'total_listings': len(filtered),
                    'listings': filtered,
                })

            await page.wait_for_timeout(150)

        await context.close()
        await browser.close()

    with open('../data/listings_more_2026_05_05.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n저장: ../data/listings_more_2026_05_05.json ({len(results)}개)")


if __name__ == '__main__':
    asyncio.run(main())
