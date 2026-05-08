"""
나머지 구 + 기존 구 추가 포인트 스캔
"""
import asyncio, json, re, os
from playwright.async_api import async_playwright

DATA = '../data'

def norm(s):
    return re.sub(r'\(\d+\)', '', s).strip()

CENTERS = [
    # 종로구
    ("종로", 37.5910, 126.9820, 15),
    ("종로", 37.5798, 127.0025, 15),
    # 중구
    ("중구", 37.5638, 127.0122, 15),
    ("중구", 37.5600, 126.9974, 15),
    # 용산구
    ("용산", 37.5340, 127.0040, 15),
    ("용산", 37.5175, 126.9741, 15),
    ("용산", 37.5326, 126.9900, 15),
    # 강북 추가
    ("강북", 37.6550, 127.0170, 15),
    # 중랑구
    ("중랑", 37.6063, 127.0927, 15),
    ("중랑", 37.5932, 127.0927, 15),
    ("중랑", 37.6200, 127.0950, 15),
    # 서초구
    ("서초", 37.4866, 127.0004, 15),
    ("서초", 37.5000, 127.0290, 15),
    ("서초", 37.4700, 127.0400, 15),
    # 강남구
    ("강남", 37.5172, 127.0473, 15),
    ("강남", 37.4857, 127.0706, 15),
    ("강남", 37.5050, 127.0590, 15),
    # 송파구
    ("송파", 37.5145, 127.1059, 15),
    ("송파", 37.4938, 127.1241, 15),
    ("송파", 37.5133, 127.1004, 15),
    ("송파", 37.5000, 127.1150, 15),
    # 강동구
    ("강동", 37.5493, 127.1468, 15),
    ("강동", 37.5528, 127.1554, 15),
    ("강동", 37.5400, 127.1300, 15),
    # 노원 추가
    ("노원", 37.6620, 127.0760, 15),
    # 성북 추가
    ("성북", 37.6150, 127.0250, 15),
    # 마포 추가
    ("마포", 37.5700, 126.8800, 15),
    # 강서 추가
    ("강서", 37.5400, 126.8400, 15),
    ("강서", 37.5700, 126.8250, 15),
    # 은평 추가
    ("은평", 37.6100, 126.9050, 15),
    # 서대문 추가
    ("서대문", 37.5750, 126.9550, 15),
    # 동작 추가
    ("동작", 37.4900, 126.9600, 15),
    # 관악 추가
    ("관악", 37.4650, 126.9450, 15),
    ("관악", 37.4900, 126.9300, 15),
    # 영등포 추가
    ("영등포", 37.5400, 126.8850, 15),
    # 구로 추가
    ("구로", 37.4880, 126.8650, 15),
    # 양천 추가
    ("양천", 37.5350, 126.8700, 15),
]


async def scan_region(browser, gu_name, lat, lon, zoom):
    context = await browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        locale='ko-KR',
    )
    page = await context.new_page()
    markers = []

    async def on_resp(r):
        url = r.url
        try:
            if 'single-markers' in url:
                body = await r.text()
                data = json.loads(body)
                if isinstance(data, list):
                    markers.extend(data)
        except:
            pass

    page.on('response', on_resp)
    url = f"https://new.land.naver.com/complexes?ms={lat},{lon},{zoom}&a=APT&b=A1"
    try:
        await page.goto(url, wait_until='networkidle', timeout=25000)
        await page.wait_for_timeout(2000)
    except:
        pass
    await context.close()

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
    coords_path = os.path.join(DATA, 'coords_all.json')
    with open(coords_path) as f:
        all_coords = json.load(f)

    with open(os.path.join(DATA, 'budget_molit_6m.json')) as f:
        molit = json.load(f)

    coords_norm = {norm(k): v for k, v in all_coords.items()}
    print(f"기존 좌표: {len(all_coords)}개")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        total_new = 0
        for i, (gu_name, lat, lon, zoom) in enumerate(CENTERS):
            coords = await scan_region(browser, gu_name, lat, lon, zoom)
            new_count = 0
            molit_matched = 0
            for name, c in coords.items():
                n = norm(name)
                if name not in all_coords:
                    all_coords[name] = c
                    coords_norm[n] = c
                    new_count += 1
                if n in {norm(k) for k in molit}:
                    molit_matched += 1
            total_new += new_count
            print(f"[{i+1}/{len(CENTERS)}] {gu_name} lat={lat:.4f}: {len(coords)}개 (신규 {new_count}, MOLIT {molit_matched})")

        await browser.close()

    with open(coords_path, 'w', encoding='utf-8') as f:
        json.dump(all_coords, f, ensure_ascii=False, indent=2)

    coords_norm2 = {norm(k): v for k, v in all_coords.items()}
    molit_covered = sum(1 for k in molit if norm(k) in coords_norm2 or k in all_coords)
    print(f"\n완료 — 신규 {total_new}개, 총 {len(all_coords)}개")
    print(f"MOLIT 커버리지: {molit_covered}/{len(molit)} ({molit_covered/len(molit)*100:.1f}%)")


if __name__ == '__main__':
    asyncio.run(main())
