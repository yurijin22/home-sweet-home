"""
신혼집 시세 트래킹 — 매일 실행

운영:
- python3 track_prices.py            # 전체 21개 단지
- python3 track_prices.py --tier 1   # 매수 후보군만 (8개)
- python3 track_prices.py --tier 2   # 권역 대장만 (9개)

저장: ../data/track_YYYY_MM_DD.json
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from playwright.async_api import async_playwright

# Tier 1 — 매수 후보군 (자금 안전~한계선)
TIER_1 = [
    ("동서울한양", "337", "동대문_답십리"),
    ("동아에코빌", "3425", "성북_길음장위"),
    ("종암SK", "1191", "성북_길음장위"),
    ("월곡두산위브", "2990", "성북_길음장위"),
    ("길음뉴타운2단지푸르지오", "8082", "성북_길음장위"),
    ("답십리두산", "3271", "동대문_답십리"),
    ("장안래미안2차", "8802", "동대문_답십리"),
    ("길음뉴타운9단지래미안", "26160", "성북_길음장위"),
]

# Tier 2 — 권역 대장 (시장 시그널 + 5년차 갈아타기 dream)
TIER_2 = [
    ("롯데캐슬클라시아", "126062", "성북_길음장위"),
    ("래미안길음센터피스", "111330", "성북_길음장위"),
    ("래미안위브", "104202", "동대문_답십리"),
    ("래미안크레시티", "103797", "동대문_답십리"),
    ("답십리파크자이", "113059", "동대문_답십리"),
    ("래미안미드카운티", "111223", "동대문_답십리"),
    ("행당한진타운", "878", "성동_왕십리행당"),
    ("왕십리자이", "111002", "성동_왕십리행당"),
    ("사당롯데캐슬골든포레", "115936", "동작_사당이수"),
]

AREA_MIN = 54
AREA_MAX = 68


async def get_articles(page, complex_no):
    articles = []

    async def on_response(response):
        url = response.url
        if f'/api/articles/complex/{complex_no}' in url and 'tradeType=A1' in url:
            try:
                body = await response.text()
                data = json.loads(body)
                articles.extend(data.get('articleList', []))
            except Exception:
                pass

    page.on('response', on_response)
    await page.goto(
        f"https://new.land.naver.com/complexes/{complex_no}?a=APT&b=A1&e=RETAIL",
        wait_until='networkidle', timeout=20000,
    )
    await page.wait_for_timeout(1500)
    page.remove_listener('response', on_response)
    return articles


async def main(watch_list):
    today = date.today().strftime("%Y_%m_%d")
    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        for i, (name, complex_no, region) in enumerate(watch_list, 1):
            print(f"[{i}/{len(watch_list)}] {name} ({region})", flush=True)
            try:
                articles = await get_articles(page, complex_no)
                filtered = [
                    {
                        'price': a.get('dealOrWarrantPrc', ''),
                        'area': a.get('area2', 0),
                        'floor': a.get('floorInfo', ''),
                        'direction': a.get('direction', ''),
                        'desc': a.get('articleFeatureDesc', ''),
                        'article_no': a.get('articleNo', ''),
                    }
                    for a in articles
                    if AREA_MIN <= float(a.get('area2', 0) or 0) <= AREA_MAX
                ]
                results[name] = {
                    'region': region, 'complex_no': complex_no,
                    'date': today, 'listings': filtered, 'error': None,
                }
                print(f"  매물 {len(filtered)}건")
            except Exception as e:
                print(f"  ❌ 실패: {e}")
                results[name] = {
                    'region': region, 'complex_no': complex_no,
                    'date': today, 'listings': [], 'error': str(e),
                }
            await page.wait_for_timeout(400)

        await context.close()
        await browser.close()

    output_path = f"../data/track_{today}.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success = sum(1 for v in results.values() if not v.get('error'))
    total_listings = sum(len(v['listings']) for v in results.values())
    print(f"\n✅ 저장: {output_path}")
    print(f"성공: {success}/{len(watch_list)} 단지 / 매물 합계: {total_listings}건")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tier', type=str, default='all',
                        help="'1' (매수 후보), '2' (권역 대장), 'all' (전체)")
    args = parser.parse_args()

    if args.tier == '1':
        watch = TIER_1
    elif args.tier == '2':
        watch = TIER_2
    else:
        watch = TIER_1 + TIER_2

    print(f"트래킹 단지: {len(watch)}개\n")
    asyncio.run(main(watch))
