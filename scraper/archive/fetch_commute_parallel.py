"""
629개 미수집 단지 통근시간 병렬 수집 (4 contexts)
왕십리역 + 정부과천청사역
"""
import asyncio, json, os, re
from playwright.async_api import async_playwright

DATA = '../data'
CONCURRENCY = 4

WANGSIMNI = {'name': '왕십리역',      'lat': 37.5614, 'lon': 127.0364}
GWACHEON   = {'name': '정부과천청사역', 'lat': 37.4297, 'lon': 126.9894}


async def get_transit_time(page, from_lat, from_lon, to_lat, to_lon, to_name):
    url = (
        f"https://map.naver.com/v5/directions/"
        f"{from_lon},{from_lat},출발/"
        f"{to_lon},{to_lat},{to_name}/-/transit"
    )
    try:
        await page.goto(url, wait_until='networkidle', timeout=25000)
        await page.wait_for_timeout(3500)
    except:
        pass

    try:
        content = await page.inner_text('body')
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        times = []
        for line in lines:
            m = re.match(r'^(\d+)시간\s*(\d+)분$', line)
            if m:
                t = int(m.group(1)) * 60 + int(m.group(2))
                if 5 <= t <= 180:
                    times.append(t)
                continue
            m = re.match(r'^(\d+)분$', line)
            if m:
                t = int(m.group(1))
                if 5 <= t <= 180:
                    times.append(t)
        if times:
            return times[0]
    except:
        pass
    return None


async def worker(sem, browser, name, lat, lon, results, idx, total, lock, out_path):
    async with sem:
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()
        try:
            t_w = await get_transit_time(page, lat, lon,
                                          WANGSIMNI['lat'], WANGSIMNI['lon'],
                                          WANGSIMNI['name'])
            await asyncio.sleep(1)
            t_g = await get_transit_time(page, lat, lon,
                                          GWACHEON['lat'], GWACHEON['lon'],
                                          GWACHEON['name'])
        except Exception as e:
            t_w, t_g = None, None
        finally:
            await context.close()

        w_str = f"{t_w}분" if t_w else "?"
        g_str = f"{t_g}분" if t_g else "?"
        print(f"[{idx}/{total}] {name}: 왕십리 {w_str}, 과천 {g_str}", flush=True)

        async with lock:
            results[name] = {'w': t_w, 'g': t_g}
            if idx % 10 == 0:
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)


async def main():
    out_path = os.path.join(DATA, 'commute_times.json')
    if os.path.exists(out_path):
        with open(out_path) as f:
            results = json.load(f)
    else:
        results = {}

    # Load all complexes with coords
    with open(os.path.join(DATA, 'coords_all.json')) as f:
        coords = json.load(f)

    with open(os.path.join(DATA, 'budget_all_seoul.json')) as f:
        budget = json.load(f)
    with open(os.path.join(DATA, 'budget_molit_6m.json')) as f:
        molit = json.load(f)

    def norm(s): return re.sub(r'\(\d+\)', '', s).strip()
    coords_norm = {norm(k): v for k, v in coords.items()}
    def get_c(name):
        if name in coords: return coords[name]
        return coords_norm.get(norm(name))

    all_names = list(budget.keys()) + [n for n in molit.keys() if n not in budget]
    todos = []
    for name in all_names:
        if results.get(name, {}).get('w') and results.get(name, {}).get('g'):
            continue
        c = get_c(name)
        if not c: continue
        lat = c.get('lat') or c.get('latitude')
        lon = c.get('lon') or c.get('longitude') or c.get('lng')
        if lat and lon:
            todos.append((name, float(lat), float(lon)))

    print(f"수집 대상: {len(todos)}개 (기존 {len(results)}개 skip)", flush=True)
    total = len(todos)

    sem  = asyncio.Semaphore(CONCURRENCY)
    lock = asyncio.Lock()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        tasks = [
            worker(sem, browser, name, lat, lon, results, i+1, total, lock, out_path)
            for i, (name, lat, lon) in enumerate(todos)
        ]
        await asyncio.gather(*tasks)
        await browser.close()

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    ok = sum(1 for v in results.values() if v.get('w'))
    print(f"\n완료: {ok}/{len(results)}개 수집")
    print(f"저장: {out_path}")


if __name__ == '__main__':
    asyncio.run(main())
