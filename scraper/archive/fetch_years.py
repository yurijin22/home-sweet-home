"""
275개 실매물 단지의 입주연도·세대수 수집
budget_all_seoul.json의 complex_no → Naver Land overview API
저장: data/years_all.json  {name: {year, household, complex_no}}
"""
import asyncio, json, os
from playwright.async_api import async_playwright

DATA = '../data'
CONCURRENCY = 4


async def fetch_overview(context, complex_no):
    page = await context.new_page()
    captured = {}

    async def on_resp(r):
        if f'/api/complexes/overview/{complex_no}' in r.url:
            try:
                captured['ov'] = json.loads(await r.text())
            except:
                pass

    page.on('response', on_resp)
    try:
        await page.goto(
            f"https://new.land.naver.com/complexes/{complex_no}?a=APT",
            wait_until='networkidle', timeout=20000,
        )
        await page.wait_for_timeout(1500)
    except:
        pass
    page.remove_listener('response', on_resp)
    await page.close()
    return captured.get('ov', {})


async def worker(sem, context, name, complex_no, results, idx, total):
    async with sem:
        ov = await fetch_overview(context, complex_no)
        use_ymd = ov.get('useApproveYmd', '')
        year = int(use_ymd[:4]) if use_ymd and len(use_ymd) >= 4 else None
        hh = ov.get('totalHouseHoldCount') or ov.get('householdCount')
        results[name] = {
            'complex_no': complex_no,
            'year': year,
            'household': hh,
        }
        status = f"year={year}, hh={hh}" if year else "no data"
        print(f"[{idx}/{total}] {name}: {status}", flush=True)


async def main():
    out_path = os.path.join(DATA, 'years_all.json')
    if os.path.exists(out_path):
        with open(out_path) as f:
            results = json.load(f)
    else:
        results = {}

    with open(os.path.join(DATA, 'budget_all_seoul.json')) as f:
        budget = json.load(f)

    todos = [
        (name, info['complex_no'])
        for name, info in budget.items()
        if info.get('complex_no') and name not in results
    ]
    print(f"수집 대상: {len(todos)}개 (기존 {len(results)}개 skip)", flush=True)

    if not todos:
        print("모두 완료됨", flush=True)
        return

    total = len(todos) + len(results)
    sem = asyncio.Semaphore(CONCURRENCY)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )

        tasks = []
        for i, (name, cno) in enumerate(todos, len(results) + 1):
            tasks.append(worker(sem, context, name, cno, results, i, total))

        # batch in chunks to save periodically
        chunk = 20
        for start in range(0, len(tasks), chunk):
            await asyncio.gather(*tasks[start:start + chunk])
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"  → 중간저장 ({len(results)}개)", flush=True)

        await context.close()
        await browser.close()

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    ok = sum(1 for v in results.values() if v.get('year'))
    print(f"\n완료: {ok}/{len(results)}개 year 수집")
    print(f"저장: {out_path}")


if __name__ == '__main__':
    asyncio.run(main())
