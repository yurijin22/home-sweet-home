"""
MOLIT 단지명으로 네이버부동산 검색 → 좌표 수집
search API: https://new.land.naver.com/api/search?query={name}
"""
import asyncio, json, re, os
from playwright.async_api import async_playwright

DATA = '../data'


def norm(s):
    return re.sub(r'\(\d+\)', '', s).strip()


async def search_complex(page, name, gu):
    """네이버부동산 검색으로 단지 좌표 찾기"""
    query = name.replace('(', '').replace(')', '')
    # gu 한글 → 구 suffix 추가
    if not gu.endswith('구'):
        gu = gu + '구'
    search_q = f"{gu} {query}"

    result = []
    async def on_response(response):
        url = response.url
        if '/api/search' in url and 'query=' in url:
            try:
                body = await response.text()
                data = json.loads(body)
                result.append(data)
            except:
                pass

    page.on('response', on_response)
    try:
        url = f"https://new.land.naver.com/?query={search_q}"
        await page.goto(url, wait_until='networkidle', timeout=15000)
        await page.wait_for_timeout(1000)
    except:
        pass
    page.remove_listener('response', on_response)

    # 결과에서 아파트 좌표 추출
    for r in result:
        items = r if isinstance(r, list) else r.get('complexes', r.get('items', []))
        if isinstance(items, list):
            for item in items:
                lat = item.get('latitude') or item.get('lat')
                lon = item.get('longitude') or item.get('lon') or item.get('lng')
                item_name = item.get('complexName') or item.get('name', '')
                if lat and lon and norm(item_name) == norm(name):
                    return {'lat': float(lat), 'lon': float(lon)}
    return None


async def search_via_autocomplete(page, name, gu):
    """네이버부동산 자동완성 API로 좌표 찾기"""
    if not gu.endswith('구'):
        gu = gu + '구'
    query = f"{gu} {name}"

    result_holder = []
    async def on_response(response):
        url = response.url
        try:
            if 'search' in url.lower() or 'suggest' in url.lower() or 'autocomplete' in url.lower():
                body = await response.text()
                if body.startswith('[') or body.startswith('{'):
                    result_holder.append(json.loads(body))
        except:
            pass

    page.on('response', on_response)
    try:
        # 검색 API 직접 호출
        resp = await page.evaluate(f"""
        async () => {{
            const r = await fetch('/api/search?query={query}&type=complex,address', {{
                headers: {{'Accept': 'application/json'}}
            }});
            return await r.json();
        }}
        """)
        result_holder.append(resp)
    except:
        pass
    page.remove_listener('response', on_response)

    for r in result_holder:
        items = r if isinstance(r, list) else []
        for item in items:
            lat = item.get('latitude') or item.get('lat')
            lon = item.get('longitude') or item.get('lon')
            item_name = item.get('complexName') or item.get('name', '')
            if lat and lon:
                n1, n2 = norm(item_name), norm(name)
                if n1 == n2 or n1 in n2 or n2 in n1:
                    return {'lat': float(lat), 'lon': float(lon)}
    return None


async def main():
    # 기존 좌표 로드
    coords_path = os.path.join(DATA, 'coords_all.json')
    with open(coords_path) as f:
        coords = json.load(f)
    coords_norm = {norm(k): v for k, v in coords.items()}

    # MOLIT 로드
    with open(os.path.join(DATA, 'budget_molit_6m.json')) as f:
        molit = json.load(f)

    # 좌표 없는 것들
    need_coords = [
        (name, molit[name]['gu'], molit[name]['median_price'])
        for name in molit
        if norm(name) not in coords_norm and name not in coords
    ]
    need_coords.sort(key=lambda x: -x[2])  # 가격 높은 순
    print(f"좌표 필요: {len(need_coords)}개 (가격 높은 순)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        # 먼저 네이버 부동산 접속해서 쿠키/세션 설정
        try:
            await page.goto('https://new.land.naver.com/', wait_until='networkidle', timeout=20000)
            await page.wait_for_timeout(2000)
        except:
            pass

        found = 0
        failed = 0
        for i, (name, gu, price) in enumerate(need_coords):
            coord = await search_via_autocomplete(page, name, gu)
            if coord:
                coords[name] = coord
                coords_norm[norm(name)] = coord
                found += 1
                price_str = f"{price//10000}억{(price%10000)//1000}천" if price%10000 else f"{price//10000}억"
                print(f"  [{i+1}/{len(need_coords)}] ✓ {name} ({gu}) {price_str}")
            else:
                failed += 1
                if i < 20 or i % 50 == 0:
                    print(f"  [{i+1}/{len(need_coords)}] ✗ {name} ({gu})")

            # 50개마다 저장
            if (i + 1) % 50 == 0:
                with open(coords_path, 'w', encoding='utf-8') as f:
                    json.dump(coords, f, ensure_ascii=False, indent=2)
                print(f"  → 중간 저장 ({len(coords)}개 총)")

        await context.close()
        await browser.close()

    # 최종 저장
    with open(coords_path, 'w', encoding='utf-8') as f:
        json.dump(coords, f, ensure_ascii=False, indent=2)

    print(f"\n완료 — 성공: {found}, 실패: {failed}")
    print(f"총 좌표: {len(coords)}개")


if __name__ == '__main__':
    asyncio.run(main())
