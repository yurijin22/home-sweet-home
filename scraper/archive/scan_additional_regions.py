import asyncio
import json
from playwright.async_api import async_playwright

# 아직 안 스캔한 지역들
REGIONS = [
    ("노원_월계공릉", 37.6247, 127.0625, 15),
    ("노원_중계하계", 37.6378, 127.0752, 15),
    ("도봉_창동방학", 37.6492, 127.0325, 15),
    ("성북_길음장위", 37.6052, 127.0228, 15),
    ("성북_돈암석관", 37.5988, 127.0134, 15),
    ("중랑_면목망우", 37.5787, 127.0836, 15),
    ("중랑_상봉묵동", 37.5942, 127.0785, 15),
    ("강서_화곡", 37.5511, 126.8498, 15),
    ("강서_방화발산", 37.5733, 126.8186, 15),
    ("구로_오류항동", 37.4973, 126.8451, 15),
    ("금천_독산시흥", 37.4636, 126.8990, 15),
    ("양천_신정", 37.5257, 126.8684, 15),
    ("광진_자양구의", 37.5434, 127.0848, 15),
]

HOUSEHOLD_MIN = 300
AREA_MIN = 54
AREA_MAX = 68
BUDGET_MIN = 70000
BUDGET_MAX = 110000

async def scrape_region(browser, region_name, lat, lon, zoom):
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        locale='ko-KR',
    )
    page = await context.new_page()
    marker_data = []
    
    async def on_response(response):
        url = response.url
        try:
            if 'single-markers' in url and 'APT' in url:
                body = await response.text()
                data = json.loads(body)
                if isinstance(data, list):
                    marker_data.extend(data)
        except:
            pass
    
    page.on('response', on_response)
    await page.goto(f"https://new.land.naver.com/complexes?ms={lat},{lon},{zoom}&a=APT&b=A1",
                   wait_until='networkidle', timeout=30000)
    await page.wait_for_timeout(2000)
    await context.close()
    return marker_data

async def get_articles_for_complex(page, complex_no):
    article_result = []
    total_count = 0
    
    async def on_response(response):
        nonlocal total_count
        url = response.url
        if f'/api/articles/complex/{complex_no}' in url and 'tradeType=A1' in url:
            try:
                body = await response.text()
                data = json.loads(body)
                article_result.extend(data.get('articleList', []))
                total_count = data.get('totalCount', 0)
            except:
                pass
    
    page.on('response', on_response)
    await page.goto(f"https://new.land.naver.com/complexes/{complex_no}?ms={complex_no}&a=APT&b=A1&e=RETAIL",
                   wait_until='networkidle', timeout=20000)
    await page.wait_for_timeout(1500)
    page.remove_listener('response', on_response)
    return article_result, total_count

async def main():
    all_results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        seen = set()
        all_markers = {}
        
        print("=== 추가 지역 스캔 ===\n")
        for region_name, lat, lon, zoom in REGIONS:
            print(f"[{region_name}]", end=' ', flush=True)
            markers = await scrape_region(browser, region_name, lat, lon, zoom)
            eligible = [
                m for m in markers
                if m.get('totalHouseholdCount', 0) >= HOUSEHOLD_MIN
                and m.get('markerType') == 'COMPLEX'
                and m.get('markerId') not in seen
            ]
            for m in eligible:
                seen.add(m['markerId'])
                all_markers[m['markerId']] = {**m, 'region': region_name}
            print(f"전체 {len(markers)}개 → 300세대+ {len(eligible)}개")
        
        print(f"\n총 {len(all_markers)}개 단지 매물 확인 중...\n")
        
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()
        
        for comp_no, info in all_markers.items():
            articles, total = await get_articles_for_complex(page, comp_no)
            filtered = [
                a for a in articles
                if AREA_MIN <= float(a.get('area2', 0) or 0) <= AREA_MAX
            ]
            if filtered:
                comp_name = info.get('complexName', '')
                household = info.get('totalHouseholdCount', 0)
                region = info.get('region', '')
                print(f"✅ {comp_name} | {region} | {household}세대 | 매물{len(filtered)}건")
                parsed = []
                for a in filtered:
                    price_str = a.get('dealOrWarrantPrc', '')
                    area2 = a.get('area2', 0)
                    floor = a.get('floorInfo', '')
                    desc = a.get('articleFeatureDesc', '')
                    print(f"   {area2}㎡ | {price_str} | {floor} | {desc[:30]}")
                    parsed.append({'price': price_str, 'area': area2, 'floor': floor, 'desc': desc})
                all_results.append({
                    'region': region, 'complex_no': comp_no,
                    'name': comp_name, 'household': household,
                    'total_listings': len(filtered), 'listings': parsed,
                })
            await page.wait_for_timeout(150)
        
        await context.close()
        await browser.close()
    
    with open('/tmp/naver_v5_results.json', 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 추가 결과: {len(all_results)}개 단지 ===")
    for r in sorted(all_results, key=lambda x: min([l['price'] for l in x['listings'] if l['price']], default='Z')):
        min_p = min([l['price'] for l in r['listings'] if l['price']], default='?')
        print(f"{r['name']} | {r['region']} | {r['household']}세대 | 최저:{min_p}")

asyncio.run(main())
