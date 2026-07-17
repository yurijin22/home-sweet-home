"""
국토부 아파트 실거래가 — 25개 구 × 36개월 전수 수집.
저장: data/molit_trade/{gu}_{YYYYMM}.json

기존 수집된 파일은 건너뛰고, 누락된 구·달만 보충 수집.
면적·가격 필터 없이 모든 거래 수집 (소형 평형 진단용).
"""
import urllib.request
import urllib.parse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

env_path = ROOT / '.env'
if env_path.exists():
    for line in env_path.read_text().splitlines():
        k, _, v = line.partition('=')
        if k and v and k not in os.environ:
            os.environ[k] = v

API_KEY = os.environ.get('MOLIT_API_KEY', '')
if not API_KEY:
    print('ERROR: MOLIT_API_KEY not set', file=sys.stderr)
    sys.exit(1)

BASE_URL = 'http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev'

SEOUL_GU = {
    'gangnam':      ('강남구', '11680'),
    'gangdong':     ('강동구', '11740'),
    'gangbuk':      ('강북구', '11305'),
    'gangseo':      ('강서구', '11500'),
    'gwanak':       ('관악구', '11620'),
    'gwangjin':     ('광진구', '11215'),
    'guro':         ('구로구', '11530'),
    'geumcheon':    ('금천구', '11545'),
    'nowon':        ('노원구', '11350'),
    'dobong':       ('도봉구', '11320'),
    'dongdaemun':   ('동대문구', '11230'),
    'dongjak':      ('동작구', '11590'),
    'mapo':         ('마포구', '11440'),
    'seodaemun':    ('서대문구', '11410'),
    'seocho':       ('서초구', '11650'),
    'seongdong':    ('성동구', '11200'),
    'seongbuk':     ('성북구', '11290'),
    'songpa':       ('송파구', '11710'),
    'yangcheon':    ('양천구', '11470'),
    'yeongdeungpo': ('영등포구', '11560'),
    'yongsan':      ('용산구', '11170'),
    'eunpyeong':    ('은평구', '11380'),
    'jongno':       ('종로구', '11110'),
    'jung':         ('중구', '11140'),
    'jungnang':     ('중랑구', '11260'),
}

MONTHS = [
    '202305','202306','202307','202308','202309','202310','202311','202312',
    '202401','202402','202403','202404','202405','202406','202407','202408',
    '202409','202410','202411','202412',
    '202501','202502','202503','202504','202505','202506','202507','202508',
    '202509','202510','202511','202512',
    '202601','202602','202603','202604',
]

OUT_DIR = ROOT / 'data' / 'molit_trade'
OUT_DIR.mkdir(parents=True, exist_ok=True)


def fetch_month(lawd_cd, deal_ymd, max_retry=3):
    """한 달치 거래 — page 페이지네이션 처리."""
    items_all = []
    page = 1
    while True:
        params = urllib.parse.urlencode({
            'serviceKey': API_KEY,
            'LAWD_CD': lawd_cd,
            'DEAL_YMD': deal_ymd,
            'numOfRows': 1000,
            'pageNo': page,
            '_type': 'json',
        })
        url = f'{BASE_URL}?{params}'
        last_err = None
        for attempt in range(max_retry):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    data = json.loads(r.read().decode())
                break
            except Exception as e:
                last_err = e
                time.sleep(2 ** attempt)
        else:
            print(f'  fetch fail {lawd_cd} {deal_ymd} p{page}: {last_err}')
            return None

        body = data.get('response', {}).get('body', {})
        items = body.get('items', {}).get('item', [])
        if isinstance(items, dict):
            items = [items]
        items_all.extend(items)
        total = int(body.get('totalCount', 0) or 0)
        if len(items_all) >= total or not items:
            break
        page += 1
        time.sleep(0.05)
    return items_all


def normalize_item(raw):
    """국토부 응답 → 우리 포맷."""
    try:
        price = int(str(raw.get('dealAmount', '')).replace(',', '').strip() or 0)
        area = float(raw.get('excluUseAr', 0) or 0)
        return {
            'name': str(raw.get('aptNm', '')).strip(),
            'district': str(raw.get('umdNm', '')).strip(),
            'jibun': str(raw.get('jibun', '')).strip(),   # 지번 — 경매 주소와 정확 매칭용
            'area_m2': area,
            'floor': int(raw.get('floor', 0) or 0),
            'price_10k': price,
            'deal_date': f"{raw.get('dealYear')}-{int(raw.get('dealMonth',0)):02d}-{int(raw.get('dealDay',0)):02d}",
            'build_year': str(raw.get('buildYear', '')).strip(),
            'deal_type': str(raw.get('dealingGbn', '') or '').strip() or '거래',
        }
    except Exception:
        return None


def main():
    only_missing = '--missing-only' in sys.argv
    target_gu = None
    for a in sys.argv:
        if a.startswith('--gu='):
            target_gu = a.split('=', 1)[1]

    tasks = []
    for slug, (gu_name, lawd_cd) in SEOUL_GU.items():
        if target_gu and slug != target_gu:
            continue
        for ym in MONTHS:
            fp = OUT_DIR / f'{slug}_{ym}.json'
            if only_missing and fp.exists():
                continue
            tasks.append((slug, gu_name, lawd_cd, ym, fp))

    print(f'fetch tasks: {len(tasks)}')
    for i, (slug, gu_name, lawd_cd, ym, fp) in enumerate(tasks, 1):
        print(f'[{i}/{len(tasks)}] {slug} ({gu_name}) {ym}', flush=True)
        items_raw = fetch_month(lawd_cd, ym)
        if items_raw is None:
            continue
        normalized = [n for n in (normalize_item(r) for r in items_raw) if n and n['name']]
        prices = [it['price_10k'] for it in normalized]
        out = {
            'items': normalized,
            'total_count': len(items_raw),
            'filtered_count': len(normalized),
            'query': {'lawd_cd': lawd_cd, 'deal_ymd': ym, 'asset_type': 'apartment', 'deal_type': 'trade'},
            'summary': {
                'median_price_10k': sorted(prices)[len(prices)//2] if prices else 0,
                'min_price_10k': min(prices) if prices else 0,
                'max_price_10k': max(prices) if prices else 0,
                'sample_count': len(prices),
            },
        }
        fp.write_text(json.dumps(out, ensure_ascii=False, indent=2))
        time.sleep(0.1)

    print('done')


if __name__ == '__main__':
    main()
