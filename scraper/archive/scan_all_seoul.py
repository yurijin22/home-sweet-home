"""
서울 전체 스캔 — 예산 11억 이하, 전용 54~68㎡, 300세대+ 매물 전수조사
기존 스캔 완료 지역 제외하고 미스캔 지역 추가 탐색
"""
import asyncio
import json
from playwright.async_api import async_playwright

# 기존 스캔 완료 지역 (listings_*.json, listings_additional_*.json 기준)
ALREADY_SCANNED_REGIONS = {
    '동작_사당이수','강동_길동','강동_둔촌','은평_녹번','영등포_문래','구로_신도림',
    '서대문_북아현','송파_삼전','강서_가양','동대문_답십리','마포_공덕',
    '노원_상계','강북_수유',
    '노원_월계공릉','노원_중계하계','도봉_창동방학','성북_길음장위','성북_돈암석관',
    '중랑_면목망우','중랑_상봉묵동','강서_화곡','강서_방화발산','구로_오류항목',
    '금천_독산시흥','양천_신정','광진_자양구의',
}

# 미스캔 지역 전체 (lat, lon, zoom)
NEW_REGIONS = [
    # 종로구
    ("종로_평창부암",    37.5940, 126.9680, 15),
    ("종로_혜화창신",    37.5798, 127.0025, 15),
    # 중구
    ("중구_신당황학",    37.5638, 127.0122, 15),
    # 용산구
    ("용산_한남보광",    37.5340, 127.0040, 15),
    ("용산_이촌서빙고",  37.5175, 126.9741, 15),
    # 성동구
    ("성동_금호행당",    37.5521, 127.0280, 15),
    ("성동_왕십리성수",  37.5614, 127.0364, 15),
    # 관악구
    ("관악_봉천신림",    37.4833, 126.9551, 15),
    # 서초구
    ("서초_방배서초",    37.4866, 127.0004, 15),
    # 강남구
    ("강남_개포일원",    37.4857, 127.0706, 15),
    # 송파구
    ("송파_가락문정",    37.4938, 127.1241, 15),
    ("송파_잠실풍납",    37.5133, 127.1004, 15),
    # 강동구
    ("강동_명일고덕",    37.5528, 127.1554, 15),
    # 마포구
    ("마포_합정망원",    37.5548, 126.9104, 15),
    ("마포_상암수색",    37.5793, 126.8871, 15),
    # 은평구
    ("은평_진관불광",    37.6286, 126.9183, 15),
    # 서대문구
    ("서대문_연희가좌",  37.5697, 126.9296, 15),
    # 영등포구
    ("영등포_대림도림",  37.4999, 126.8991, 15),
    ("영등포_당산여의",  37.5311, 126.9024, 15),
    # 동작구
    ("동작_노량진흑석",  37.5095, 126.9421, 15),
    ("동작_상도본동",    37.4968, 126.9445, 15),
    # 강서구
    ("강서_등촌공항",    37.5606, 126.8320, 15),
]

BUDGET_MAX = 110000
AREA_MIN   = 54
AREA_MAX   = 68
HOUSEHOLD_MIN = 300


async def get_articles_for_complex(page, complex_no):
    article_result = []
    async def on_response(response):
        url = response.url
        if f'/api/articles/complex/{complex_no}' in url and 'tradeType=A1' in url:
            try:
                body = await response.text()
                data = json.loads(body)
                article_result.extend(data.get('articleList', []))
            except:
                pass
    page.on('response', on_response)
    url = f"https://new.land.naver.com/complexes/{complex_no}?ms=37.5,127.0,15&a=APT&b=A1"
    try:
        await page.goto(url, wait_until='networkidle', timeout=20000)
        await page.wait_for_timeout(1500)
    except:
        pass
    page.remove_listener('response', on_response)
    return article_result


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
    url = f"https://new.land.naver.com/complexes?ms={lat},{lon},{zoom}&a=APT&b=A1"
    try:
        await page.goto(url, wait_until='networkidle', timeout=25000)
        await page.wait_for_timeout(2000)
    except:
        pass
    await context.close()
    return marker_data


async def main():
    results = {}

    # 기존 데이터 로드 (리스트 형식)
    import os
    seen_complex_nos = set()
    for fname in ['listings_2026_05_04.json', 'listings_additional_2026_05_04.json', 'listings_more_2026_05_05.json']:
        fpath = f'../data/{fname}'
        if os.path.exists(fpath):
            with open(fpath) as f:
                old = json.load(f)
                for item in old:
                    name = item.get('name', '')
                    cno = str(item.get('complex_no', ''))
                    seen_complex_nos.add(cno)
                    # 예산 내 단지만
                    listings = item.get('listings', [])
                    prices = []
                    for l in listings:
                        try:
                            p_str = l.get('price', '0').replace(',', '').replace(' ', '')
                            if '억' in p_str:
                                parts = p_str.split('억')
                                val = int(parts[0]) * 10000
                                if parts[1]:
                                    val += int(parts[1])
                                prices.append(val)
                        except:
                            pass
                    if name and prices and min(prices) <= BUDGET_MAX:
                        results[name] = {
                            'region': item.get('region', ''),
                            'complex_no': cno,
                            'household': item.get('household', 0),
                            'min_price': min(prices),
                            'count': len(listings),
                        }
    print(f"기존 데이터: {len(results)}개 단지 (예산 내)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 1단계: 미스캔 지역 마커 수집
        all_markers = {}
        seen = seen_complex_nos

        for region_name, lat, lon, zoom in NEW_REGIONS:
            print(f"[{region_name}] 스캔 중...", end=' ', flush=True)
            markers = await scrape_region(browser, region_name, lat, lon, zoom)
            eligible = [
                m for m in markers
                if m.get('totalHouseholdCount', 0) >= HOUSEHOLD_MIN
                and m.get('markerType') == 'COMPLEX'
                and str(m.get('markerId')) not in seen
            ]
            for m in eligible:
                mid = str(m['markerId'])
                seen.add(mid)
                all_markers[mid] = {**m, 'region': region_name}
            print(f"{len(eligible)}개 신규 단지")

        print(f"\n신규 단지 {len(all_markers)}개 매물 확인 중...\n")

        # 2단계: 단지별 매물 수집
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        new_results = {}
        for comp_no, info in all_markers.items():
            articles = await get_articles_for_complex(page, comp_no)
            filtered = [
                a for a in articles
                if AREA_MIN <= float(a.get('area2', 0) or 0) <= AREA_MAX
            ]
            if filtered:
                prices = []
                for a in filtered:
                    p_str = a.get('dealOrWarrantPrc', '0').replace(',', '').replace('억', '').strip()
                    try:
                        prices.append(int(float(p_str) * 10000) if '.' in p_str else int(p_str))
                    except:
                        pass
                if prices and min(prices) <= BUDGET_MAX:
                    comp_name = info.get('complexName', comp_no)
                    new_results[comp_name] = {
                        'region': info['region'],
                        'complex_no': comp_no,
                        'household': info.get('totalHouseholdCount', 0),
                        'min_price': min(prices),
                        'count': len(filtered),
                        'articles': filtered[:5],
                    }
                    print(f"  ✓ {comp_name} ({info['region']}) — {min(prices)//10000}억, {len(filtered)}건")

        await context.close()
        await browser.close()

    # 기존 + 신규 합산 저장
    results.update(new_results)

    # 예산 내 전체 목록 별도 저장
    budget_all = {
        name: data for name, data in results.items()
        if data.get('min_price', 999999) <= BUDGET_MAX
    }

    with open('../data/scan_all_seoul_new.json', 'w', encoding='utf-8') as f:
        json.dump(new_results, f, ensure_ascii=False, indent=2)

    with open('../data/budget_all_seoul.json', 'w', encoding='utf-8') as f:
        json.dump(budget_all, f, ensure_ascii=False, indent=2)

    print(f"\n완료 — 신규 {len(new_results)}개 / 예산 내 전체 {len(budget_all)}개")
    print("저장: data/scan_all_seoul_new.json, data/budget_all_seoul.json")


if __name__ == '__main__':
    asyncio.run(main())
