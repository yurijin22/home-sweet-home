"""
동 단위 세밀 스캔으로 MOLIT 단지 좌표 수집
각 gu별로 동 수준 center를 여러 개 생성해서 zoom=15로 스캔
"""
import asyncio, json, re, os
from playwright.async_api import async_playwright

DATA = '../data'


def norm(s):
    return re.sub(r'\(\d+\)', '', s).strip()


# 각 구의 주요 동 중심 좌표 (zoom=15, 반경 ~500m 커버)
DONG_CENTERS = [
    # 노원구 (162개 MOLIT)
    ("노원", 37.6554, 127.0568, 15),
    ("노원", 37.6477, 127.0714, 15),
    ("노원", 37.6634, 127.0614, 15),
    ("노원", 37.6751, 127.0545, 15),
    ("노원", 37.6400, 127.0647, 15),
    # 양천구 (151개)
    ("양천", 37.5170, 126.8665, 15),
    ("양천", 37.5267, 126.8549, 15),
    ("양천", 37.5088, 126.8648, 15),
    ("양천", 37.5195, 126.8780, 15),
    # 서대문구 (96개)
    ("서대문", 37.5794, 126.9368, 15),
    ("서대문", 37.5697, 126.9296, 15),
    ("서대문", 37.5870, 126.9520, 15),
    # 동대문구 (96개)
    ("동대문", 37.5845, 127.0434, 15),
    ("동대문", 37.5680, 127.0580, 15),
    ("동대문", 37.5760, 127.0520, 15),
    ("동대문", 37.5900, 127.0460, 15),
    # 성북구 (86개)
    ("성북", 37.6066, 127.0190, 15),
    ("성북", 37.5898, 127.0086, 15),
    ("성북", 37.6040, 127.0350, 15),
    # 도봉구 (83개)
    ("도봉", 37.6688, 127.0471, 15),
    ("도봉", 37.6560, 127.0380, 15),
    ("도봉", 37.6820, 127.0460, 15),
    # 영등포구 (77개)
    ("영등포", 37.5263, 126.8963, 15),
    ("영등포", 37.5155, 126.9052, 15),
    ("영등포", 37.5071, 126.8991, 15),
    ("영등포", 37.5311, 126.9024, 15),
    # 마포구 (72개)
    ("마포", 37.5638, 126.9010, 15),
    ("마포", 37.5548, 126.9104, 15),
    ("마포", 37.5793, 126.8871, 15),
    ("마포", 37.5428, 126.9501, 15),
    # 금천구 (51개)
    ("금천", 37.4600, 126.9001, 15),
    ("금천", 37.4548, 126.8998, 15),
    ("금천", 37.4660, 126.9004, 15),
    # 동작구 (50개)
    ("동작", 37.5124, 126.9393, 15),
    ("동작", 37.4968, 126.9445, 15),
    ("동작", 37.5095, 126.9421, 15),
    # 광진구 (39개)
    ("광진", 37.5385, 127.0823, 15),
    ("광진", 37.5485, 127.0823, 15),
    ("광진", 37.5432, 127.0706, 15),
    # 성동구 (22개)
    ("성동", 37.5569, 127.0365, 15),
    ("성동", 37.5521, 127.0280, 15),
    ("성동", 37.5614, 127.0364, 15),
    # 강북구 추가
    ("강북", 37.6398, 127.0256, 15),
    ("강북", 37.6300, 127.0350, 15),
    # 은평구
    ("은평", 37.6177, 126.9228, 15),
    ("은평", 37.6286, 126.9183, 15),
    # 강서구
    ("강서", 37.5509, 126.8496, 15),
    ("강서", 37.5606, 126.8320, 15),
    # 구로구
    ("구로", 37.4954, 126.8877, 15),
    ("구로", 37.5028, 126.8763, 15),
    # 관악구
    ("관악", 37.4784, 126.9516, 15),
    ("관악", 37.4833, 126.9551, 15),
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
            if 'single-markers' in url and ('APT' in url or 'a=APT' in url):
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
    molit_names = {norm(k) for k in molit if norm(k) not in coords_norm and k not in all_coords}
    print(f"수집 목표 MOLIT 단지: {len(molit_names)}개")
    print(f"기존 좌표: {len(all_coords)}개")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        total_new = 0
        for i, (gu_name, lat, lon, zoom) in enumerate(DONG_CENTERS):
            coords = await scan_region(browser, gu_name, lat, lon, zoom)
            new_count = 0
            molit_matched = 0
            for name, c in coords.items():
                n = norm(name)
                if name not in all_coords:
                    all_coords[name] = c
                    coords_norm[n] = c
                    new_count += 1
                if n in molit_names:
                    molit_matched += 1
            total_new += new_count
            print(f"[{i+1}/{len(DONG_CENTERS)}] {gu_name} lat={lat:.4f}: {len(coords)}개 수집 (신규 {new_count}, MOLIT매칭 {molit_matched})")

        await browser.close()

    # 저장
    with open(coords_path, 'w', encoding='utf-8') as f:
        json.dump(all_coords, f, ensure_ascii=False, indent=2)

    # MOLIT 커버리지 재확인
    coords_norm2 = {norm(k): v for k, v in all_coords.items()}
    molit_covered = sum(1 for k in molit if norm(k) in coords_norm2 or k in all_coords)
    print(f"\n완료 — 신규 좌표 {total_new}개")
    print(f"총 좌표: {len(all_coords)}개")
    print(f"MOLIT 커버리지: {molit_covered}/{len(molit)} ({molit_covered/len(molit)*100:.1f}%)")


if __name__ == '__main__':
    asyncio.run(main())
