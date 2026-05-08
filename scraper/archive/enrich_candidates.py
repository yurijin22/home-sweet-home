"""
후보 25개 단지의 메타데이터 보강
- 네이버 부동산 /api/complexes/overview/{complex_no} 호출
- 입주년도, 평형 분포, 용적률, 전세가율, 재건축 정보 등 수집
- candidates_v2.json → candidates_enriched.json
"""

import asyncio, json
from playwright.async_api import async_playwright


async def fetch_overview(page, complex_no):
    captured = {}

    async def on_response(response):
        url = response.url
        if f'/api/complexes/overview/{complex_no}' in url:
            try:
                captured['overview'] = json.loads(await response.text())
            except:
                pass
        elif f'/api/complexes/single-markers' in url and f'markerId={complex_no}' in url:
            try:
                data = json.loads(await response.text())
                if isinstance(data, list):
                    for item in data:
                        if str(item.get('markerId')) == str(complex_no):
                            captured['marker'] = item
                            break
            except:
                pass

    page.on('response', on_response)
    await page.goto(
        f"https://new.land.naver.com/complexes/{complex_no}?a=APT",
        wait_until='networkidle', timeout=20000,
    )
    await page.wait_for_timeout(2000)
    page.remove_listener('response', on_response)
    return captured


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
            print(f"[{i}/{len(candidates)}] {c['name']} (no={cno})")
            try:
                meta = await fetch_overview(page, cno)
            except Exception as e:
                print(f"  실패: {e}")
                meta = {}

            ov = meta.get('overview', {})
            mk = meta.get('marker', {})

            # 입주년월
            use_ymd = ov.get('useApproveYmd', '')
            year = int(use_ymd[:4]) if use_ymd and len(use_ymd) >= 4 else None

            # 평형 정보 (pyeongs) - exclusiveArea가 string이라 float 변환
            def _f(v):
                try: return float(v)
                except: return 0.0
            pyeongs = ov.get('pyeongs', []) or []
            our_exclusive = [p for p in pyeongs if 54 <= _f(p.get('exclusiveArea')) <= 68]

            # 용적률, 건폐율 (marker에 있음)
            floor_area_ratio = mk.get('floorAreaRatio')  # 용적률
            building_coverage_ratio = mk.get('buildingCoverageRatio')  # 건폐율

            # 평당가 (단위가격)
            min_unit_price = mk.get('minDealUnitPrice')  # 만원/평
            max_unit_price = mk.get('maxDealUnitPrice')

            # 재건축 신호
            rebuild = ov.get('rebuildMembershipTransYn', 'N')

            # 전세가율
            lease_rate = ov.get('leasePerDealRate')

            enriched.append({
                **c,
                'year': year,
                'use_approve_ymd': use_ymd,
                'total_dong': ov.get('totalDongCount'),
                'pyeongs_count': len(pyeongs),
                'has_our_size': len(our_exclusive) > 0,
                'our_size_pyeongs': [
                    {
                        'name': p.get('pyeongName'),
                        'exclusive_area': p.get('exclusiveArea'),
                        'supply_area': p.get('supplyArea'),
                        'household': p.get('householdCountByPyeong'),
                    } for p in our_exclusive
                ],
                'floor_area_ratio': floor_area_ratio,
                'building_coverage_ratio': building_coverage_ratio,
                'unit_price_min': min_unit_price,
                'unit_price_max': max_unit_price,
                'rebuild_membership': rebuild,
                'lease_rate': lease_rate,
                'lat': ov.get('latitude'),
                'lon': ov.get('longitude'),
            })

            await page.wait_for_timeout(500)

        await context.close()
        await browser.close()

    with open('../data/candidates_enriched.json', 'w', encoding='utf-8') as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: ../data/candidates_enriched.json ({len(enriched)}개)")


if __name__ == '__main__':
    asyncio.run(main())
