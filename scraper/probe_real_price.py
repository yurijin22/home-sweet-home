"""
실거래가 API 탐색 - 네이버 부동산 단지 시세/실거래가 페이지의 응답 캡처
"""
import asyncio, json
from playwright.async_api import async_playwright

TEST = "1045"  # 성현동아


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
            if '/api/' in url and ('price' in url.lower() or 'real' in url.lower() or 'transaction' in url.lower() or 'history' in url.lower()):
                try:
                    body = await response.text()
                    data = json.loads(body)
                    captured.append({'url': url, 'sample': str(data)[:500],
                                     'keys': list(data.keys()) if isinstance(data, dict) else f'list[{len(data)}]'})
                except:
                    pass

        page.on('response', on_response)

        # 시세/실거래가 탭 직접 호출
        urls_to_try = [
            f"https://new.land.naver.com/complexes/{TEST}?a=APT&tab=H",
            f"https://new.land.naver.com/complexes/{TEST}?a=APT&tab=B",
            f"https://new.land.naver.com/complexes/{TEST}?a=APT&tab=R",
        ]
        for u in urls_to_try:
            print(f"GO: {u}")
            try:
                await page.goto(u, wait_until='networkidle', timeout=20000)
                await page.wait_for_timeout(2500)
            except Exception as e:
                print(f"  err: {e}")

        await context.close()
        await browser.close()

    print(f"\n캡처 {len(captured)}건:\n")
    for c in captured:
        print(f"{c['url']}")
        print(f"  keys: {c['keys']}")
        print(f"  sample: {c['sample']}")
        print()


if __name__ == '__main__':
    asyncio.run(main())
