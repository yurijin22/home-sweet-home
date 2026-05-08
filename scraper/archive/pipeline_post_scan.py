"""
스캔 후 통합 파이프라인:
1. 신규 단지 식별 (v2_full 중 enriched에 없는 것)
2. 신규 단지만 enrich (overview API)
3. 신규 단지만 prices (실거래가 + KAB)
4. 신규 단지만 amenities (OSM)
5. brand/direction 다시 (전체)
6. v3 점수 재계산 (전체)
"""

import asyncio, json, ssl, time, urllib.request, urllib.parse, math, re
from playwright.async_api import async_playwright

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def _f(v):
    try: return float(v)
    except: return 0.0


# === 1. 신규 단지 추출 ===
def find_new_candidates():
    with open('../data/candidates_v3_pool.json') as f:
        pool = json.load(f)
    try:
        with open('../data/candidates_enriched.json') as f:
            existing = {c['complex_no']: c for c in json.load(f)}
    except FileNotFoundError:
        existing = {}
    new = [c for c in pool if c['complex_no'] not in existing]
    print(f"풀 {len(pool)}개 중 신규 {len(new)}개 처리 예정")
    return pool, new, existing


# === 2. 신규 enrich ===
async def enrich_new(new_cands):
    if not new_cands:
        return []
    enriched = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        for i, c in enumerate(new_cands, 1):
            cno = c['complex_no']
            cap = {}
            async def on_response(response, _cno=cno, _cap=cap):
                url = response.url
                try:
                    if f'/api/complexes/overview/{_cno}' in url:
                        _cap['ov'] = await response.json()
                    elif f'/api/complexes/single-markers' in url and f'markerId={_cno}' in url:
                        data = await response.json()
                        if isinstance(data, list):
                            for item in data:
                                if str(item.get('markerId')) == str(_cno):
                                    _cap['mk'] = item
                                    break
                except: pass
            page.on('response', on_response)
            try:
                await page.goto(f"https://new.land.naver.com/complexes/{cno}?a=APT",
                               wait_until='networkidle', timeout=20000)
                await page.wait_for_timeout(2000)
            except: pass
            page.remove_listener('response', on_response)

            ov = cap.get('ov', {})
            mk = cap.get('mk', {})
            year_str = ov.get('useApproveYmd', '')
            year = int(year_str[:4]) if year_str and len(year_str) >= 4 else None
            pyeongs = ov.get('pyeongs', []) or []
            our = [p for p in pyeongs if 54 <= _f(p.get('exclusiveArea')) <= 68]

            enriched.append({
                **c,
                'year': year, 'use_approve_ymd': year_str,
                'total_dong': ov.get('totalDongCount'),
                'pyeongs_count': len(pyeongs),
                'has_our_size': len(our) > 0,
                'our_size_pyeongs': [{
                    'name': p.get('pyeongName'), 'exclusive_area': p.get('exclusiveArea'),
                    'supply_area': p.get('supplyArea'), 'household': p.get('householdCountByPyeong'),
                } for p in our],
                'floor_area_ratio': mk.get('floorAreaRatio'),
                'building_coverage_ratio': mk.get('buildingCoverageRatio'),
                'unit_price_min': mk.get('minDealUnitPrice'),
                'unit_price_max': mk.get('maxDealUnitPrice'),
                'rebuild_membership': ov.get('rebuildMembershipTransYn', 'N'),
                'lease_rate': ov.get('leasePerDealRate'),
                'lat': ov.get('latitude'),
                'lon': ov.get('longitude'),
            })
            if i % 10 == 0:
                print(f"  enrich {i}/{len(new_cands)}")
            await page.wait_for_timeout(400)
        await context.close()
        await browser.close()
    return enriched


# === 3. 신규 가격 수집 ===
async def collect_prices_new(new_cands):
    if not new_cands:
        return []
    out = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        for i, c in enumerate(new_cands, 1):
            cno = c['complex_no']
            cap = {'overview': None, 'real': [], 'summary': []}
            async def on_response(response, _cno=cno, _cap=cap):
                url = response.url
                try:
                    if f'/api/complexes/overview/{_cno}' in url:
                        _cap['overview'] = await response.json()
                    elif f'/api/complexes/{_cno}/prices/real' in url:
                        _cap['real'].append(await response.json())
                    elif f'/api/complexes/{_cno}/prices' in url and 'type=summary' in url:
                        _cap['summary'].append(await response.json())
                except: pass
            page.on('response', on_response)
            try:
                await page.goto(f"https://new.land.naver.com/complexes/{cno}?a=APT&tab=H",
                               wait_until='networkidle', timeout=20000)
                await page.wait_for_timeout(2500)
            except: pass
            page.remove_listener('response', on_response)

            ov = cap.get('overview') or {}
            pyeongs = ov.get('pyeongs', []) or []
            target = next((p for p in pyeongs if 54 <= _f(p.get('exclusiveArea')) <= 68), None)
            target_no = target.get('pyeongNo') if target else None

            real, summ = None, None
            for r in cap['real']:
                if r.get('areaNo') == target_no: real = r; break
            if not real and cap['real']: real = cap['real'][0]
            for s in cap['summary']:
                if s.get('areaNo') == target_no: summ = s; break
            if not summ and cap['summary']: summ = cap['summary'][0]

            txs = []
            if real:
                for month in real.get('realPriceOnMonthList', []) or []:
                    for t in month.get('realPriceList', []) or []:
                        txs.append({
                            'date': t.get('formattedTradeYearMonth'),
                            'price': t.get('dealPrice'), 'floor': t.get('floor'),
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
            out.append({**c, 'pyeong_no': target_no, 'transactions': txs,
                        'transaction_count': len(txs), 'kab_summary': kab})
            if i % 10 == 0:
                print(f"  prices {i}/{len(new_cands)}")
            await asyncio.sleep(1.5)
        await context.close()
        await browser.close()
    return out


# === 4. 신규 OSM amenity ===
def collect_osm_new(new_enriched):
    if not new_enriched:
        return {}

    MIRRORS = ["https://overpass.openstreetmap.fr/api/interpreter",
               "https://overpass-api.de/api/interpreter",
               "https://overpass.kumi.systems/api/interpreter"]

    def haversine_m(lat1, lon1, lat2, lon2):
        R = 6371000
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dp = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
        a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
        return 2*R*math.asin(math.sqrt(a))

    def query_osm(lat, lon, radius=1500):
        q = f"""[out:json][timeout:40];
        (node["railway"="subway_entrance"](around:{radius},{lat},{lon});
         node["station"="subway"](around:{radius},{lat},{lon});
         node["public_transport"="station"]["subway"="yes"](around:{radius},{lat},{lon});
         node["railway"="station"](around:{radius},{lat},{lon});
         node["amenity"="school"](around:{radius},{lat},{lon});
         way["amenity"="school"](around:{radius},{lat},{lon});
         node["leisure"~"park|garden"](around:{radius},{lat},{lon});
         way["leisure"~"park|garden"](around:{radius},{lat},{lon});
         node["shop"~"supermarket|mall|department_store"](around:{radius},{lat},{lon});
         way["shop"~"supermarket|mall|department_store"](around:{radius},{lat},{lon});
         node["amenity"~"hospital|clinic"](around:{radius},{lat},{lon});
         way["amenity"~"hospital|clinic"](around:{radius},{lat},{lon});
         node["landuse"="cemetery"](around:{radius},{lat},{lon});
         way["landuse"="cemetery"](around:{radius},{lat},{lon});
         node["power"="tower"](around:{radius},{lat},{lon});
         way["highway"~"motorway|trunk|primary|secondary"](around:{radius},{lat},{lon});
         way["railway"~"rail|light_rail"](around:{radius},{lat},{lon});
        ); out center tags;"""
        data = urllib.parse.urlencode({'data': q}).encode('utf-8')
        for url in MIRRORS:
            try:
                req = urllib.request.Request(url, data=data, headers={'User-Agent': 'hsh/1.0'})
                with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                    return json.loads(r.read().decode('utf-8'))
            except Exception as e:
                time.sleep(3)
        return {'elements': []}

    def categorize(elements, clat, clon):
        cats = {'subway':[], 'school':{'pri':[],'mid':[],'high':[]}, 'park':[], 'mart':[],
                'hospital':[], 'cemetery':[], 'power':[], 'highway':[], 'railway':[]}
        seen = set()
        for e in elements:
            tags = e.get('tags', {})
            name = tags.get('name') or tags.get('name:ko') or '?'
            lat = e.get('lat') or e.get('center', {}).get('lat')
            lon = e.get('lon') or e.get('center', {}).get('lon')
            if not lat: continue
            key = (name, round(lat,5), round(lon,5))
            if key in seen: continue
            seen.add(key)
            d = haversine_m(clat, clon, lat, lon)
            if tags.get('railway')=='subway_entrance' or tags.get('station')=='subway' or \
               (tags.get('public_transport')=='station' and tags.get('subway')=='yes'):
                cats['subway'].append({'name': name, 'distance_m': round(d), 'lines': tags.get('subway:lines') or tags.get('line') or ''})
            elif tags.get('railway')=='station':
                cats['subway'].append({'name': name, 'distance_m': round(d), 'lines': tags.get('line') or 'rail'})
            elif tags.get('amenity')=='school':
                kind = 'pri' if '초등' in name else ('mid' if '중학' in name else ('high' if '고등' in name else 'mid'))
                cats['school'][kind].append({'name': name, 'distance_m': round(d)})
            elif tags.get('leisure') in ('park','garden'):
                cats['park'].append({'name': name, 'distance_m': round(d)})
            elif tags.get('shop') in ('supermarket','mall','department_store'):
                cats['mart'].append({'name': name, 'distance_m': round(d), 'type': tags.get('shop')})
            elif tags.get('amenity') in ('hospital','clinic'):
                cats['hospital'].append({'name': name, 'distance_m': round(d), 'type': tags.get('amenity')})
            elif tags.get('landuse')=='cemetery':
                cats['cemetery'].append({'name': name, 'distance_m': round(d)})
            elif tags.get('power')=='tower':
                cats['power'].append({'name': name, 'distance_m': round(d)})
            elif tags.get('highway') in ('motorway','trunk','primary','secondary'):
                cats['highway'].append({'name': name, 'distance_m': round(d), 'type': tags.get('highway')})
            elif tags.get('railway') in ('rail','light_rail'):
                cats['railway'].append({'name': name, 'distance_m': round(d)})
        cats['subway'].sort(key=lambda x: x['distance_m']); cats['subway']=cats['subway'][:5]
        for k in ['pri','mid','high']:
            cats['school'][k].sort(key=lambda x: x['distance_m']); cats['school'][k]=cats['school'][k][:3]
        for k in ['park','mart','hospital','cemetery','power']:
            cats[k].sort(key=lambda x: x['distance_m']); cats[k]=cats[k][:5]
        cats['highway'].sort(key=lambda x: x['distance_m']); cats['highway']=cats['highway'][:3]
        cats['railway'].sort(key=lambda x: x['distance_m']); cats['railway']=cats['railway'][:2]
        return cats

    out = {}
    for i, c in enumerate(new_enriched, 1):
        name = c['name']
        lat, lon = c.get('lat'), c.get('lon')
        if not (lat and lon): continue
        try:
            osm = query_osm(lat, lon, 1500)
            out[name] = categorize(osm.get('elements', []), lat, lon)
            if i % 5 == 0:
                print(f"  osm {i}/{len(new_enriched)}")
        except Exception as e:
            print(f"  osm 실패 {name}: {e}")
        time.sleep(2)
    return out


async def main():
    pool, new_cands, existing_enriched_map = find_new_candidates()

    # 신규 enrich
    print("\n=== 신규 enrich ===")
    new_enriched = await enrich_new(new_cands)
    # 합치기
    all_enriched = list(existing_enriched_map.values()) + new_enriched
    with open('../data/candidates_enriched.json', 'w', encoding='utf-8') as f:
        json.dump(all_enriched, f, ensure_ascii=False, indent=2)
    print(f"enriched 저장 ({len(all_enriched)}개)")

    # 신규 가격
    print("\n=== 신규 가격 ===")
    new_prices = await collect_prices_new(new_cands)
    try:
        with open('../data/candidates_with_prices.json') as f:
            existing_prices = json.load(f)
        existing_map = {c['complex_no']: c for c in existing_prices}
    except FileNotFoundError:
        existing_map = {}
    for p in new_prices:
        existing_map[p['complex_no']] = p
    all_prices = list(existing_map.values())
    with open('../data/candidates_with_prices.json', 'w', encoding='utf-8') as f:
        json.dump(all_prices, f, ensure_ascii=False, indent=2)
    print(f"prices 저장 ({len(all_prices)}개)")

    # 신규 OSM
    print("\n=== 신규 OSM ===")
    new_osm = collect_osm_new(new_enriched)
    try:
        with open('../data/amenities_25.json') as f:
            existing_osm = json.load(f)
    except FileNotFoundError:
        existing_osm = {}
    existing_osm.update(new_osm)
    with open('../data/amenities_25.json', 'w', encoding='utf-8') as f:
        json.dump(existing_osm, f, ensure_ascii=False, indent=2)
    print(f"amenities 저장 ({len(existing_osm)}개)")

    print("\n=== 완료 — 다음: enrich_meta.py + analyze_prices.py + score_v3.py 재실행 ===")


if __name__ == '__main__':
    asyncio.run(main())
