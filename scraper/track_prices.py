"""
단지별 시세 트래킹 스크립트
- 매일 실행하면 listings_YYYY_MM_DD.json 으로 저장
- 이전 날짜와 비교해서 가격 변동 감지

실행: python3 track_prices.py
"""

import asyncio
import json
from datetime import date
from playwright.async_api import async_playwright

# 트래킹할 단지 목록 (네이버 부동산 complex_no)
WATCH_LIST = [
    # (단지명, complex_no, 지역)
    ("성현동아", "1045", "동작_사당이수"),
    ("두산", "3271", "동대문_답십리"),
    ("서대문센트럴아이파크", "179137", "은평_녹번"),
    ("백련산힐스테이트2차", "27502", "은평_녹번"),
    ("새절역두산위브트레지움", "169317", "은평_녹번"),
    ("길동우성", "1290", "강동_길동"),
    ("라인", "6", "강서_가양"),
    ("등촌주공5단지", "13", "강서_가양"),
]

AREA_MIN = 54
AREA_MAX = 68
BUDGET_MAX = 130000  # 13억까지 트래킹 (급매 포착용)


async def get_articles(page, complex_no):
    articles = []

    async def on_response(response):
        url = response.url
        if f'/api/articles/complex/{complex_no}' in url and 'tradeType=A1' in url:
            try:
                body = await response.text()
                data = json.loads(body)
                articles.extend(data.get('articleList', []))
            except:
                pass

    page.on('response', on_response)
    await page.goto(
        f"https://new.land.naver.com/complexes/{complex_no}?a=APT&b=A1&e=RETAIL",
        wait_until='networkidle', timeout=20000
    )
    await page.wait_for_timeout(1500)
    page.remove_listener('response', on_response)
    return articles


async def main():
    today = date.today().strftime("%Y_%m_%d")
    results = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        for name, complex_no, region in WATCH_LIST:
            print(f"\n[{name}] {region}")
            articles = await get_articles(page, complex_no)

            filtered = [
                {
                    'price': a.get('dealOrWarrantPrc', ''),
                    'area': a.get('area2', 0),
                    'floor': a.get('floorInfo', ''),
                    'desc': a.get('articleFeatureDesc', ''),
                    'article_no': a.get('articleNo', ''),
                }
                for a in articles
                if AREA_MIN <= float(a.get('area2', 0) or 0) <= AREA_MAX
            ]

            print(f"  매물 {len(filtered)}건")
            for f in filtered:
                print(f"  {f['area']}㎡ | {f['price']} | {f['floor']}")

            results[name] = {
                'region': region,
                'complex_no': complex_no,
                'date': today,
                'listings': filtered,
            }

            await page.wait_for_timeout(300)

        await context.close()
        await browser.close()

    # 저장
    output_path = f"../data/track_{today}.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료: {output_path}")
    print(f"총 {sum(len(v['listings']) for v in results.values())}개 매물 기록")


if __name__ == '__main__':
    asyncio.run(main())
