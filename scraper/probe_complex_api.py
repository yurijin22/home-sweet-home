"""
네이버 부동산 단지 페이지 API 탐색
- complex_no 하나로 페이지 로드하면서 모든 API 응답 캡처
- 어떤 엔드포인트가 단지 메타데이터(입주년도, 평형, 용적률 등) 담고 있는지 확인
"""

import asyncio, json
from playwright.async_api import async_playwright

TEST_COMPLEX = "1045"  # 성현동아


async def main():
    captured = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            locale='ko-KR',
        )
        page = await context.new_page()

        async def on_response(response):
            url = response.url
            if TEST_COMPLEX in url and '/api/' in url:
                try:
                    body = await response.text()
                    data = json.loads(body)
                    captured.append({'url': url, 'sample': str(data)[:300], 'keys': list(data.keys()) if isinstance(data, dict) else type(data).__name__})
                except:
                    pass

        page.on('response', on_response)
        await page.goto(
            f"https://new.land.naver.com/complexes/{TEST_COMPLEX}?a=APT",
            wait_until='networkidle', timeout=20000,
        )
        await page.wait_for_timeout(3000)
        await context.close()
        await browser.close()

    print(f"\n캡처된 API 응답 {len(captured)}개:\n")
    for c in captured:
        print(f"URL: {c['url']}")
        print(f"  keys: {c['keys']}")
        print(f"  sample: {c['sample']}")
        print()


if __name__ == '__main__':
    asyncio.run(main())
