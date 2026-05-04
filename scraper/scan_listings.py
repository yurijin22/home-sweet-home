import asyncio
import json
from playwright.async_api import async_playwright

REGIONS = [
    ("동작_사당이수",   37.4866, 126.9817, 15),
    ("강동_길동",       37.5389, 127.1380, 15),
    ("강동_둔촌",       37.5248, 127.1421, 15),
    ("은평_녹번",       37.6015, 126.9294, 15),
    ("영등포_문래",     37.5189, 126.8963, 15),
    ("구로_신도림",     37.5095, 126.8872, 15),
    ("서대문_북아현",   37.5558, 126.9568, 15),
    ("송파_삼전",       37.5038, 127.0956, 15),
    ("강서_가양",       37.5647, 126.8560, 15),
    ("동대문_답십리",   37.5688, 127.0589, 15),
    ("마포_공덕",       37.5440, 126.9520, 15),
    ("노원_상계",       37.6550, 127.0650, 15),
    ("강북_수유",       37.6383, 127.0252, 15),
]

BUDGET_MAX = 110000
BUDGET_MIN = 70000
AREA_MIN = 54
AREA_MAX = 68
HOUSEHOLD_MIN = 300

async def scrape_region(browser, region_name, lat, lon, zoom):
    """지역 페이지 탐색하며 단지 마커 API 인터셉트"""
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        locale='ko-KR',
    )
    page = await context.new_page()
    
    marker_data = []
    article_data = {}
    
    async def on_response(response):
        url = response.url
        try:
            if 'single-markers' in url and 'APT' in url:
                body = await response.text()
                data = json.loads(body)
                if isinstance(data, list):
                    marker_data.extend(data)
            elif '/api/articles/complex/' in url and 'tradeType=A1' in url:
                comp_no = url.split('/api/articles/complex/')[1].split('?')[0]
                body = await response.text()
                data = json.loads(body)
                article_data[comp_no] = data
        except:
            pass
    
    page.on('response', on_response)
    
    # 해당 지역 복잡 페이지로 이동
    url = f"https://new.land.naver.com/complexes?ms={lat},{lon},{zoom}&a=APT&b=A1"
    await page.goto(url, wait_until='networkidle', timeout=30000)
    await page.wait_for_timeout(2000)
    
    await context.close()
    return marker_data, article_data

async def get_articles_for_complex(page, complex_no):
    """단지 페이지 이동해서 매물 API 인터셉트"""
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
    
    comp_url = f"https://new.land.naver.com/complexes/{complex_no}?ms={complex_no}&a=APT&b=A1&e=RETAIL"
    await page.goto(comp_url, wait_until='networkidle', timeout=20000)
    await page.wait_for_timeout(1500)
    
    page.remove_listener('response', on_response)
    return article_result, total_count

async def main():
    all_results = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        seen_complexes = set()
        all_markers = {}  # complex_no -> marker info
        
        # 1단계: 각 지역에서 단지 마커 수집
        print("=== 1단계: 지역별 단지 마커 수집 ===\n")
        for region_name, lat, lon, zoom in REGIONS:
            print(f"[{region_name}] 탐색 중...", end=' ', flush=True)
            markers, _ = await scrape_region(browser, region_name, lat, lon, zoom)
            
            # 300세대 이상 아파트만
            eligible = [
                m for m in markers
                if m.get('totalHouseholdCount', 0) >= HOUSEHOLD_MIN
                and m.get('markerType') == 'COMPLEX'
                and m.get('markerId') not in seen_complexes
            ]
            
            for m in eligible:
                seen_complexes.add(m['markerId'])
                all_markers[m['markerId']] = {**m, 'region': region_name}
            
            print(f"전체 {len(markers)}개 → 300세대+ {len(eligible)}개 신규")
        
        print(f"\n총 대상 단지: {len(all_markers)}개\n")
        
        # 2단계: 각 단지 매물 확인
        print("=== 2단계: 매물 조회 ===\n")
        
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()
        
        for comp_no, info in all_markers.items():
            comp_name = info.get('complexName', '')
            household = info.get('totalHouseholdCount', 0)
            region = info.get('region', '')
            
            # 단지 페이지에서 매물 인터셉트
            articles, total = await get_articles_for_complex(page, comp_no)
            
            # 59㎡ 전후 + 예산 내 필터
            filtered = [
                a for a in articles
                if AREA_MIN <= float(a.get('area2', 0) or 0) <= AREA_MAX
            ]
            
            if filtered:
                print(f"✅ {comp_name} | {region} | {household}세대 | 매물 {len(filtered)}건")
                parsed = []
                for a in filtered:
                    price_str = a.get('dealOrWarrantPrc', '')
                    area2 = a.get('area2', 0)
                    floor = a.get('floorInfo', '')
                    desc = a.get('articleFeatureDesc', '')
                    print(f"   {area2}㎡ | {price_str} | {floor} | {desc}")
                    parsed.append({'price': price_str, 'area': area2, 'floor': floor, 'desc': desc})
                
                all_results.append({
                    'region': region,
                    'complex_no': comp_no,
                    'name': comp_name,
                    'household': household,
                    'total_listings': len(filtered),
                    'listings': parsed,
                })
            else:
                print(f"✗ {comp_name} | {household}세대 | 해당 면적 매물 없음")
            
            await page.wait_for_timeout(200)
        
        await context.close()
        await browser.close()
    
    with open('/tmp/naver_v4_results.json', 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n\n====== 최종 ======")
    print(f"실매물 있는 단지: {len(all_results)}개")
    for r in sorted(all_results, key=lambda x: -x['total_listings']):
        print(f"\n{r['name']} | {r['region']} | {r['household']}세대 | 매물 {r['total_listings']}건")
        for l in r['listings']:
            print(f"  {l['area']}㎡ | {l['price']} | {l['floor']}")

asyncio.run(main())
