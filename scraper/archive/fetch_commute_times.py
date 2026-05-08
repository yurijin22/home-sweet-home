"""
네이버 지도 대중교통 길찾기로 통근시간 수집
대상: candidates_v3_scored.json 전체 (56개)
출발지: 각 단지 → 왕십리역 / 정부과천청사역
"""
import asyncio, json, os, re
from playwright.async_api import async_playwright

DATA = '../data'

# 목적지 좌표
WANGSIMNI = {'name': '왕십리역', 'lat': 37.5614, 'lon': 127.0364}
GWACHEON   = {'name': '정부과천청사역', 'lat': 37.4297, 'lon': 126.9894}


async def get_transit_time(page, from_lat, from_lon, to_lat, to_lon, to_name):
    """네이버 지도 대중교통 길찾기 → 최소 소요시간(분) 반환"""
    captured = []

    async def on_resp(r):
        url = r.url
        try:
            if 'transit' in url and ('route' in url or 'path' in url or 'directions' in url):
                body = await r.text()
                if 'duration' in body or 'totalTime' in body or 'time' in body.lower():
                    captured.append(body)
        except:
            pass

    page.on('response', on_resp)

    url = (
        f"https://map.naver.com/v5/directions/"
        f"{from_lon},{from_lat},출발/"
        f"{to_lon},{to_lat},{to_name}/-/transit"
    )
    try:
        await page.goto(url, wait_until='networkidle', timeout=25000)
        await page.wait_for_timeout(4000)
    except:
        pass

    page.remove_listener('response', on_resp)

    # 페이지에서 소요시간 텍스트 추출 (inner_text 사용)
    try:
        content = await page.inner_text('body')
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        times = []
        for line in lines:
            # "1시간 20분" 형식
            m = re.match(r'^(\d+)시간\s*(\d+)분$', line)
            if m:
                t = int(m.group(1)) * 60 + int(m.group(2))
                if 5 <= t <= 180:
                    times.append(t)
                continue
            # "35분" 형식
            m = re.match(r'^(\d+)분$', line)
            if m:
                t = int(m.group(1))
                if 5 <= t <= 180:
                    times.append(t)
        if times:
            return times[0]  # 첫 번째 = 최단 경로 소요시간
    except:
        pass

    return None


async def main():
    # 기존 데이터 로드
    out_path = os.path.join(DATA, 'commute_times.json')
    if os.path.exists(out_path):
        with open(out_path) as f:
            results = json.load(f)
    else:
        results = {}

    # 대상 단지
    with open(os.path.join(DATA, 'candidates_v3_scored.json')) as f:
        scored = json.load(f)

    # coords도 로드
    with open(os.path.join(DATA, 'coords_all.json')) as f:
        coords = json.load(f)
    def norm(s):
        return re.sub(r'\(\d+\)', '', s).strip()
    coords_norm = {norm(k): v for k, v in coords.items()}

    def get_c(name):
        if name in coords: return coords[name]
        return coords_norm.get(norm(name))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        for item in scored:
            name = item['name']
            if name in results and results[name].get('w') and results[name].get('g'):
                print(f"[skip] {name}")
                continue

            c = get_c(name)
            if not c:
                print(f"[no coord] {name}")
                continue

            lat = c.get('lat') or c.get('latitude')
            lon = c.get('lon') or c.get('longitude') or c.get('lng')
            if not lat or not lon:
                continue

            # 왕십리
            t_w = await get_transit_time(page, lat, lon,
                                          WANGSIMNI['lat'], WANGSIMNI['lon'],
                                          WANGSIMNI['name'])
            await asyncio.sleep(1.5)

            # 과천
            t_g = await get_transit_time(page, lat, lon,
                                          GWACHEON['lat'], GWACHEON['lon'],
                                          GWACHEON['name'])
            await asyncio.sleep(1.5)

            results[name] = {'w': t_w, 'g': t_g}
            w_str = f"{t_w}분" if t_w else "?"
            g_str = f"{t_g}분" if t_g else "?"
            print(f"{name}: 왕십리 {w_str}, 과천 {g_str}")

            # 5개마다 저장
            if len(results) % 5 == 0:
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)

        await context.close()
        await browser.close()

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    ok = sum(1 for v in results.values() if v.get('w'))
    print(f"\n완료: {ok}/{len(results)}개 수집")
    print(f"저장: {out_path}")


if __name__ == '__main__':
    asyncio.run(main())
