"""
서울 25개 구 전체 아파트 마커 수집 → 단지명-좌표 매핑
각 구의 중심좌표로 zoom=13 스캔 → 단지 lat/lon 수집
"""
import asyncio, json, os
from playwright.async_api import async_playwright

# 서울 25개 구 중심 좌표
GU_CENTERS = [
    ("종로", 37.5910, 126.9820, 13),
    ("중구", 37.5638, 126.9974, 13),
    ("용산", 37.5326, 126.9900, 13),
    ("성동", 37.5569, 127.0365, 13),
    ("광진", 37.5385, 127.0823, 13),
    ("동대문", 37.5845, 127.0434, 13),
    ("중랑", 37.6063, 127.0927, 13),
    ("성북", 37.6066, 127.0190, 13),
    ("강북", 37.6398, 127.0256, 13),
    ("도봉", 37.6688, 127.0471, 13),
    ("노원", 37.6542, 127.0568, 13),
    ("은평", 37.6177, 126.9228, 13),
    ("서대문", 37.5794, 126.9368, 13),
    ("마포", 37.5638, 126.9010, 13),
    ("양천", 37.5170, 126.8665, 13),
    ("강서", 37.5509, 126.8496, 13),
    ("구로", 37.4954, 126.8877, 13),
    ("금천", 37.4600, 126.9001, 13),
    ("영등포", 37.5263, 126.8963, 13),
    ("동작", 37.5124, 126.9393, 13),
    ("관악", 37.4784, 126.9516, 13),
    ("서초", 37.4836, 127.0324, 13),
    ("강남", 37.5172, 127.0473, 13),
    ("송파", 37.5145, 127.1059, 13),
    ("강동", 37.5493, 127.1468, 13),
]


async def scan_gu(browser, gu_name, lat, lon, zoom):
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        locale='ko-KR',
    )
    page = await context.new_page()
    markers = []

    async def on_response(response):
        url = response.url
        try:
            if 'single-markers' in url and 'APT' in url:
                body = await response.text()
                data = json.loads(body)
                if isinstance(data, list):
                    markers.extend(data)
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

    # 마커에서 좌표 추출
    coords = {}
    for m in markers:
        name = m.get('complexName', '')
        lat_m = m.get('latitude') or m.get('lat')
        lon_m = m.get('longitude') or m.get('lon') or m.get('lng')
        if name and lat_m and lon_m:
            try:
                coords[name] = {'lat': float(lat_m), 'lon': float(lon_m)}
            except:
                pass
    return coords


async def main():
    # 기존 coords 로드
    existing_path = '../data/coords_all.json'
    if os.path.exists(existing_path):
        with open(existing_path) as f:
            all_coords = json.load(f)
    else:
        all_coords = {}

    print(f"기존 좌표: {len(all_coords)}개")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        total_new = 0
        for gu_name, lat, lon, zoom in GU_CENTERS:
            print(f"[{gu_name}] 스캔 중...", end=' ', flush=True)
            coords = await scan_gu(browser, gu_name, lat, lon, zoom)
            new_count = sum(1 for k in coords if k not in all_coords)
            all_coords.update(coords)
            total_new += new_count
            print(f"{len(coords)}개 수집 (신규 {new_count}개)")

            # 진행중 저장
            with open(existing_path, 'w', encoding='utf-8') as f:
                json.dump(all_coords, f, ensure_ascii=False, indent=2)

        await browser.close()

    print(f"\n완료 — 전체 좌표 {len(all_coords)}개 (신규 {total_new}개)")
    print(f"저장: {existing_path}")


if __name__ == '__main__':
    asyncio.run(main())
