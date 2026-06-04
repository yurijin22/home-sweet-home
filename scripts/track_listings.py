"""
네이버부동산 매물 추적 (워치리스트 단지 → 일별 호가 저장)
실행 환경: GitHub Actions (Playwright 필요)
저장: data/track_{YYYY_MM_DD}.json
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

TARGETS_PATH = ROOT / 'config/tracking_targets.json'
OUT_DIR = ROOT / 'data'


async def fetch_complex(page, complex_no, name):
    """단지 매물 페이지 열고 articles API 인터셉트."""
    article_list = []
    captured = asyncio.Event()

    async def on_response(response):
        url = response.url
        if f'/api/articles/complex/{complex_no}' in url and 'tradeType=A1' in url:
            try:
                body = await response.text()
                data = json.loads(body)
                article_list.extend(data.get('articleList', []))
                captured.set()
            except Exception:
                pass

    page.on('response', on_response)
    url = f'https://new.land.naver.com/complexes/{complex_no}?ms=37.5,127.0,16&a=APT&b=A1&e=RETAIL'
    try:
        await page.goto(url, wait_until='networkidle', timeout=30000)
        try:
            await asyncio.wait_for(captured.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass
        await page.wait_for_timeout(2000)
    except Exception as e:
        return {'error': str(e), 'listings': []}
    finally:
        page.remove_listener('response', on_response)

    listings = []
    for a in article_list:
        listings.append({
            'price': a.get('dealOrWarrantPrc') or a.get('rentPrc'),
            'area': a.get('area2') or a.get('area1'),
            'floor': a.get('floorInfo'),
            'direction': a.get('direction'),
            'desc': a.get('articleFeatureDesc') or a.get('tagList'),
            'article_no': a.get('articleNo'),
        })
    return {'error': None, 'listings': listings}


async def main():
    from playwright.async_api import async_playwright

    with open(TARGETS_PATH) as f:
        targets = json.load(f)

    today = datetime.now(KST).strftime('%Y_%m_%d')
    out_path = OUT_DIR / f'track_{today}.json'
    print(f'targets: {len(targets)}, out: {out_path}')

    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
            locale='ko-KR',
            viewport={'width': 390, 'height': 844},
        )
        page = await context.new_page()
        for i, t in enumerate(targets, 1):
            name = t['name']
            cno = t['complex_no']
            print(f'[{i}/{len(targets)}] {name} (cno {cno})', flush=True)
            r = await fetch_complex(page, cno, name)
            results[name] = {
                'region': t.get('region', '?'),
                'complex_no': cno,
                'date': today,
                'listings': r['listings'],
                'error': r['error'],
            }
            await asyncio.sleep(0.5)
        await browser.close()

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    total_listings = sum(len(v['listings']) for v in results.values())
    print(f'done: {len(results)} complexes, {total_listings} listings')


if __name__ == '__main__':
    asyncio.run(main())
