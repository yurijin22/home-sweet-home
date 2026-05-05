"""
기존 478개 + 신규 listings 합치고 v2 후보 필터 적용
- 신규 region에 대한 tier 매핑 추가
- 통근 직선거리 컷오프
"""

import json, re, math
from collections import defaultdict


WANGSIMNI = (37.5614, 127.0364)
GWACHEON = (37.4288, 126.9876)


# 신규 region tier 추가 (사용자 우선순위 "왕십리 우선")
TIERS = {
    # S — 왕십리 직주근접
    'S': ['성동_왕십리행당', '성동_마장금호', '성동_옥수응봉', '성동_성수',
          '동작_사당이수'],
    # A — 한쪽 직통
    'A': ['동대문_답십리', '동대문_청량리회기', '동대문_전농',
          '광진_자양구의', '광진_군자화양',
          '마포_공덕', '마포_망원합정',
          '성북_정릉안암', '성북_길음장위',
          '동작_노량진흑석',
          '서대문_북아현',
          '송파_삼전',
          '용산_이촌도원',
          '강남_도곡대치', '서초_방배',
          '영등포_여의도', '영등포_당산'],
    # B — 양쪽 환승
    'B': ['은평_녹번', '은평_응암수색',
          '강동_길동', '강동_둔촌', '강동_천호암사',
          '양천_신정', '양천_목동',
          '강북_수유',
          '서대문_홍은남가좌',
          '성북_돈암석관',
          '영등포_문래', '영등포_신길',
          '구로_신도림', '관악_봉천신림',
          '마포_상암'],
    # C — 멀음
    'C': ['강서_가양', '강서_화곡', '강서_방화발산', '강서_마곡등촌',
          '도봉_창동방학', '도봉_방학',
          '중랑_면목망우', '중랑_상봉묵동',
          '노원_월계공릉', '노원_중계하계', '노원_상계',
          '구로_오류항동', '구로_개봉',
          '금천_독산시흥'],
}
REGION_TIER = {r: t for t, rs in TIERS.items() for r in rs}


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def parse_price(s):
    s = s.replace(',', '').strip()
    m = re.match(r'(\d+)억(?:\s*(\d+))?', s)
    if not m: return None
    return int(m.group(1)) * 10000 + (int(m.group(2)) if m.group(2) else 0)


def is_region_noise(name, region):
    name_to_correct = [
        ('면목', '중랑_면목망우'), ('창동', '도봉_창동방학'),
        ('상계', '노원_상계'), ('월곡', '성북_길음장위'),
        ('등촌', '강서_가양'), ('가양', '강서_가양'),
    ]
    for kw, correct in name_to_correct:
        if kw in name and region != correct and correct in REGION_TIER:
            return True
    return False


def main():
    # 모든 listings 합치기
    seen_cno = {}
    files = [
        '../data/listings_2026_05_04.json',
        '../data/listings_additional_2026_05_04.json',
        '../data/listings_more_2026_05_05.json',
    ]
    total_loaded = 0
    for fp in files:
        try:
            with open(fp) as f:
                items = json.load(f)
            total_loaded += len(items)
            for item in items:
                cno = str(item['complex_no'])
                # 중복 시 region noise 아닌 쪽 우선
                if cno in seen_cno:
                    if is_region_noise(item['name'], item['region']):
                        continue
                    if is_region_noise(seen_cno[cno]['name'], seen_cno[cno]['region']):
                        seen_cno[cno] = item
                    # else: keep existing
                else:
                    seen_cno[cno] = item
        except FileNotFoundError:
            print(f"파일 없음: {fp}")

    print(f"전체 단지 (중복 제거 전): {total_loaded}")
    print(f"중복 제거 후: {len(seen_cno)}")

    # 필터 + 점수
    filtered = []
    by_region = defaultdict(int)
    for cno, c in seen_cno.items():
        if c['household'] < 300: continue
        tier = REGION_TIER.get(c['region'])
        if not tier: continue  # 매핑 없는 region 스킵 (또는 추가 필요)

        # 노이즈 단지
        if is_region_noise(c['name'], c['region']): continue

        affordable = [l for l in c['listings']
                      if 54 <= float(l['area']) <= 68
                      and parse_price(l['price'])
                      and parse_price(l['price']) <= 110000]
        if not affordable: continue

        min_p = min(parse_price(l['price']) for l in affordable)
        tier_s = {'S':4, 'A':3, 'B':2, 'C':1}[tier]
        hh_s = 2 if c['household']>=1000 else (1 if c['household']>=500 else 0)
        pr_s = 2 if min_p<=80000 else (1 if min_p<=90000 else 0)
        ct_s = 2 if len(affordable)>=10 else (1 if len(affordable)>=5 else 0)
        score = tier_s*3 + hh_s*2 + pr_s + ct_s

        filtered.append({
            'name': c['name'], 'region': c['region'], 'tier': tier,
            'household': c['household'], 'complex_no': cno,
            'min_price': min_p, 'count': len(affordable), 'score': score,
        })
        by_region[c['region']] += 1

    # 점수순 정렬
    tier_order = {'S':0, 'A':1, 'B':2, 'C':3}
    filtered.sort(key=lambda x: (tier_order[x['tier']], -x['score'], -x['household']))

    # 등급별 통계
    print(f"\n필터 통과 {len(filtered)}개")
    print(f"\nregion별 통과 단지 수:")
    for r in sorted(by_region.keys()):
        tier = REGION_TIER.get(r, '?')
        print(f"  [{tier}] {r:25s} {by_region[r]:>3}")

    # 매핑 없는 region (있을 경우)
    missing = set(c['region'] for c in seen_cno.values()) - set(REGION_TIER.keys())
    if missing:
        print(f"\n⚠ tier 매핑 없는 region:")
        for r in missing:
            print(f"   {r}")

    # 저장
    with open('../data/candidates_v2_full.json', 'w', encoding='utf-8') as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    print(f"\n저장: ../data/candidates_v2_full.json")

    # tier별 상위 N개로 후보 풀 압축 (v2와 동일 쿼터)
    quotas = {'S': 99, 'A': 25, 'B': 20, 'C': 8}
    selected = []
    by_tier = defaultdict(list)
    for c in filtered:
        by_tier[c['tier']].append(c)
    for tier in ['S', 'A', 'B', 'C']:
        items = by_tier[tier][:quotas[tier]]
        selected.extend(items)
        print(f"  Tier {tier}: {len(items)}개 선정 (후보 {len(by_tier[tier])}개 중)")

    print(f"\n최종 후보 풀: {len(selected)}개")
    with open('../data/candidates_v3_pool.json', 'w', encoding='utf-8') as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)
    print(f"저장: ../data/candidates_v3_pool.json")


if __name__ == '__main__':
    main()
