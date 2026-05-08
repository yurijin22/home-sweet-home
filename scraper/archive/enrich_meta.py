"""
단지 추가 메타데이터 — 자동 가능한 항목만
- 브랜드 추출 (단지명 기반)
- 매물 평균 방향 (listings 데이터)
- 평형 다양성 (pyeongs)
- 주차대수 (네이버 단지 API에 있다면)
"""

import json, re

MAJOR_BRANDS = {
    '래미안': '래미안 (삼성)', '자이': '자이 (GS)', '아이파크': '아이파크 (HDC)',
    '푸르지오': '푸르지오 (대우)', '롯데캐슬': '롯데캐슬 (롯데)',
    '힐스테이트': '힐스테이트 (현대)', '더샵': '더샵 (포스코)',
    '이편한세상': '이편한세상 (DL)', 'e편한세상': 'e편한세상 (DL)',
    '센트럴': '-', '두산위브': '위브 (두산)', '쌍용예가': '예가 (쌍용)',
    'SK뷰': 'SK뷰 (SK)', '아너스빌': '아너스빌 (금호)',
    '센텀': '-', '월드메르디앙': '월드메르디앙', '한라비발디': '비발디 (한라)',
    '코오롱하늘채': '하늘채 (코오롱)', '한신휴플러스': '휴플러스 (한신)',
    '벽산': '벽산 (벽산)', '동아': '동아 (동아건설)', '대우': '대우 (대우)',
    '한진': '한진 (한진중공업)', '한신': '한신 (한신공영)',
    '주공': '주공 (LH)', '에코빌': '에코빌',
    '브라운스톤': '브라운스톤 (이수건설)',
}


def extract_brand(name):
    """단지명에서 브랜드 키워드 추출"""
    for kw, label in MAJOR_BRANDS.items():
        if kw in name:
            return label
    return '?'


def is_major_brand(name):
    majors = ['래미안', '자이', '아이파크', '푸르지오', '롯데캐슬',
              '힐스테이트', '더샵', '이편한세상', 'e편한세상', 'SK뷰']
    return any(b in name for b in majors)


def main():
    # 후보 풀 (56)
    with open('../data/candidates_v3_pool.json') as f:
        pool = json.load(f)
    pool_cnos = {c['complex_no'] for c in pool}
    with open('../data/candidates_enriched.json') as f:
        cands = [c for c in json.load(f) if c['complex_no'] in pool_cnos]

    # 매물 데이터 (전체 listings)
    listings_data = {}
    for fp in ['../data/listings_2026_05_04.json', '../data/listings_additional_2026_05_04.json',
               '../data/listings_more_2026_05_05.json']:
        try:
            with open(fp) as f:
                for item in json.load(f):
                    listings_data.setdefault(item['complex_no'], item)
        except FileNotFoundError:
            pass

    out = []
    for c in cands:
        cno = c['complex_no']
        listings_item = listings_data.get(cno, {})
        listings = listings_item.get('listings', [])

        # 브랜드
        brand = extract_brand(c['name'])
        is_major = is_major_brand(c['name'])

        # 매물 방향 (54-68만)
        our_listings = [l for l in listings if 54 <= float(l.get('area', 0) or 0) <= 68]
        directions = [l.get('desc', '') for l in our_listings]
        # 방향 키워드 추출
        from collections import Counter
        dirs = Counter()
        for desc in directions:
            for d in ['남향', '남동향', '남서향', '동향', '서향', '북향', '북동향', '북서향']:
                if d in desc:
                    dirs[d] += 1
        south_count = dirs.get('남향', 0) + dirs.get('남동향', 0) + dirs.get('남서향', 0)
        south_ratio = south_count / len(our_listings) if our_listings else 0

        # 평형 다양성
        pyeongs_count = c.get('pyeongs_count', 0)

        out.append({
            'name': c['name'],
            'complex_no': cno,
            'brand': brand,
            'is_major_brand': is_major,
            'south_ratio': round(south_ratio, 2),
            'south_count': south_count,
            'listing_total': len(our_listings),
            'directions': dict(dirs),
            'pyeongs_count': pyeongs_count,
        })

    with open('../data/meta_extra.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"{'단지':24s} {'브랜드':22s} {'메이저':>4s} {'남향비율':>6s} ({'남향수':>3s}/{'총':>3s})  {'평형'}")
    print('=' * 90)
    for o in out:
        major = '✓' if o['is_major_brand'] else ''
        print(f"{o['name'][:23]:24s} {o['brand'][:21]:22s} {major:>4s} {o['south_ratio']:>6.0%}  ({o['south_count']:>3}/{o['listing_total']:>3})  {o['pyeongs_count']}타입")

    print(f"\n저장: ../data/meta_extra.json")


if __name__ == '__main__':
    main()
