"""
naver /api/complexes/{cno}/additions API로 학군 보강 시도
- JWT 1회 추출, Top 8 단지 순회
- additions 응답에 학교 정보 있으면 추출
- 단지간 2초 sleep으로 rate limit 회피
"""

import asyncio, json
from playwright.async_api import async_playwright


TOP_8 = [
    ('성현동아', '1045'),
    ('두산', '3271'),
    ('동서울한양', '337'),
    ('백련산힐스테이트1차', '27501'),
    ('창동주공3단지', '326'),
    ('주공8단지', '1635'),
    ('수유벽산1차', '1344'),
    ('동아한신', '1067'),
]


async def main():
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        # JWT 추출
        token_box = {}
        page.on('request', lambda r: token_box.setdefault('t', r.headers.get('authorization')) if '/api/complexes/' in r.url and 'authorization' in r.headers else None)
        await page.goto("https://new.land.naver.com/complexes/1045?a=APT",
                       wait_until='networkidle', timeout=20000)
        await page.wait_for_timeout(2500)
        token = token_box.get('t')
        if not token:
            print("토큰 추출 실패")
            return
        print(f"JWT OK\n")

        headers = {'Authorization': token, 'Referer': 'https://new.land.naver.com/'}

        # 첫 단지로 응답 스키마 확인
        for name, cno in TOP_8:
            try:
                r = await context.request.get(
                    f'https://new.land.naver.com/api/complexes/{cno}/additions',
                    params={'complexNo': cno},
                    headers=headers,
                )
                if r.status == 429:
                    print(f"[{name}] 429 — 30초 대기 후 재시도")
                    await asyncio.sleep(30)
                    r = await context.request.get(
                        f'https://new.land.naver.com/api/complexes/{cno}/additions',
                        params={'complexNo': cno},
                        headers=headers,
                    )
                if not r.ok:
                    print(f"[{name}] status {r.status}")
                    continue
                data = await r.json()
                results[name] = data

                # 첫 응답일 때 스키마 출력
                if name == TOP_8[0][0]:
                    print(f"=== {name} additions 스키마 ===")
                    print(f"keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    print(f"sample (1500): {json.dumps(data, ensure_ascii=False, indent=2)[:1500]}\n")
                else:
                    keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
                    print(f"[{name}] OK keys={keys}")
            except Exception as e:
                print(f"[{name}] 에러: {type(e).__name__}: {e}")

            await asyncio.sleep(2)

        await context.close()
        await browser.close()

    with open('../data/naver_additions_top8.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n저장: ../data/naver_additions_top8.json ({len(results)}개)")


if __name__ == '__main__':
    asyncio.run(main())
