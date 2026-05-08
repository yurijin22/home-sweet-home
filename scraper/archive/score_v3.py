"""
v3 점수 — 사용자 가중치 반영 (★★★★ = 4 ~ ★ = 1)
- 자동 점수만 우선 산출 (수동 영역은 default 0.5)
- 28개 항목 × 가중치 → 정규화 점수
"""

import json, math


# 왕십리역, 과천역 좌표 (사용자 통근지)
WANGSIMNI = (37.5614, 127.0364)
GWACHEON = (37.4288, 126.9876)


def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a)) / 1000  # km


def score_subway_distance(amenities):
    """A1. 역세권 도보거리 (가장 가까운 역) — ★★★★"""
    subs = amenities.get('subway', [])
    if not subs:
        return 0
    nearest_m = subs[0]['distance_m']
    # 도보 80m/분 기준
    minutes = nearest_m / 80
    if minutes <= 5: return 1.0
    if minutes <= 8: return 0.85
    if minutes <= 10: return 0.7
    if minutes <= 13: return 0.5
    if minutes <= 18: return 0.25
    return 0.05


def score_subway_lines(amenities):
    """A2. 환승 노선 수 — ★★★ (반경 800m 내 역 개수로 추정)"""
    subs = amenities.get('subway', [])
    nearby = [s for s in subs if s['distance_m'] <= 800]
    n = len(nearby)
    # 같은 역 입구 중복 제거 어려움 — 개수 그대로
    if n >= 5: return 1.0  # 트리플+
    if n >= 3: return 0.7  # 더블
    if n >= 1: return 0.4
    return 0


def score_commute_filter(complex_lat, complex_lon):
    """통근 컷오프 + 왕십리 우선 점수
    - 컷오프 완화: 왕십리 14km / 과천 25km (직선거리 — 환승 가능 범위)
    - 둘 다 만족해야 통과
    """
    d_wangsimni = haversine(complex_lat, complex_lon, *WANGSIMNI)
    d_gwacheon = haversine(complex_lat, complex_lon, *GWACHEON)
    if d_wangsimni > 14 or d_gwacheon > 25:
        cutoff = False
    else:
        cutoff = True
    # 왕십리 가까움 점수 (사용자: 한쪽으로 몰기 = 왕십리 우선)
    if d_wangsimni <= 3: ws = 1.0
    elif d_wangsimni <= 5: ws = 0.85
    elif d_wangsimni <= 8: ws = 0.6
    elif d_wangsimni <= 12: ws = 0.3
    else: ws = 0.05
    return ws, cutoff, d_wangsimni, d_gwacheon


def score_household(hh):
    """B1. 세대수 — ★★★"""
    if hh >= 2000: return 1.0
    if hh >= 1500: return 0.85
    if hh >= 1000: return 0.7
    if hh >= 500: return 0.5
    if hh >= 300: return 0.35
    return 0.1


def score_year(year):
    """B2. 입주년도 — ★★"""
    age = 2026 - (year or 2026)
    if age <= 5: return 1.0
    if age <= 15: return 0.7
    if age <= 25: return 0.5
    if age <= 30: return 0.35
    return 0.2


def score_floor_area_ratio_conditional(year, far):
    """B3. 용적률 조건부 — ★★★
    - 신축: 중립 (0.5)
    - 25년+ 구축 + 용적률 200% 이하: 1.0
    - 25년+ 구축 + 용적률 250% 이하: 0.7
    - 30년+ 노후 + 용적률 300% 이상: 0.1 (페널티)
    """
    if not year or not far:
        return 0.5
    age = 2026 - year
    if age <= 15:
        return 0.6  # 신축은 용적률 자체가 중요하지 않음
    if age >= 30 and far >= 280:
        return 0.1  # 노후+재건축 불가 → 페널티
    if far <= 180: return 1.0
    if far <= 220: return 0.85
    if far <= 250: return 0.65
    if far <= 280: return 0.4
    return 0.2


def score_parking(year):
    """B4. 주차대수 — ★★ (데이터 없어 입주년도로 추정: 신축일수록 세대당 1.0+)"""
    age = 2026 - (year or 2026)
    if age <= 10: return 1.0
    if age <= 20: return 0.7
    if age <= 30: return 0.4
    return 0.2


def score_brand(meta):
    """B5. 브랜드 — ★"""
    return 1.0 if meta.get('is_major_brand') else 0.4


def score_pyeong_diversity(meta):
    """B6. 평형 효율 (다양성으로 추정) — ★★"""
    n = meta.get('pyeongs_count', 0)
    if n >= 8: return 1.0
    if n >= 5: return 0.7
    if n >= 3: return 0.5
    return 0.3


def score_gap(gap_pct):
    """C1. 호가-실거래 갭 — ★ (작을수록 좋음, 너무 작으면 정직, 너무 크면 거품)"""
    if gap_pct is None: return 0.5
    if -5 <= gap_pct <= 10: return 1.0
    if gap_pct <= 20: return 0.6
    if gap_pct <= 30: return 0.3
    return 0.1


def score_trend(trend_pct):
    """C2. 5년 추세 — ★★★"""
    if trend_pct is None: return 0.4
    if trend_pct >= 5: return 1.0
    if trend_pct >= 1: return 0.7
    if trend_pct >= -1: return 0.5
    return 0.2


def score_lease_rate(lease_str):
    """C3. 전세가율 — ★ (시장 안정성 시그널)"""
    if not lease_str: return 0.5
    # '60~63%' or '46~47%' or '54%'
    import re
    nums = re.findall(r'\d+', lease_str)
    if not nums: return 0.5
    lr = sum(int(n) for n in nums) / len(nums)
    if lr >= 65: return 1.0
    if lr >= 55: return 0.75
    if lr >= 45: return 0.5
    return 0.3


def score_listing_count(count):
    """C4. 매물 수 — ★★"""
    if count >= 15: return 1.0
    if count >= 10: return 0.85
    if count >= 5: return 0.6
    if count >= 2: return 0.4
    return 0.2


def score_primary_school(amenities):
    """D1. 초등학교 거리 — ★★★★"""
    pri = amenities.get('school', {}).get('pri', [])
    if not pri: return 0.1
    nearest = pri[0]['distance_m']
    if nearest <= 200: return 1.0
    if nearest <= 350: return 0.85
    if nearest <= 500: return 0.7
    if nearest <= 700: return 0.5
    if nearest <= 1000: return 0.3
    return 0.1


def score_park(amenities):
    """E2. 공원·녹지 — ★★★"""
    parks = amenities.get('park', [])
    if not parks: return 0.1
    nearest = parks[0]['distance_m']
    if nearest <= 300: return 1.0
    if nearest <= 600: return 0.7
    if nearest <= 1000: return 0.5
    return 0.3


def score_mart_hospital(amenities):
    """E1. 마트·병원 — ★★"""
    marts = [m for m in amenities.get('mart', []) if m['distance_m'] <= 1000]
    hosps = [h for h in amenities.get('hospital', []) if h['distance_m'] <= 1000]
    has_mart = len(marts) > 0
    has_hosp = len(hosps) > 0
    if has_mart and has_hosp: return 1.0
    if has_mart or has_hosp: return 0.6
    return 0.2


def score_avoid_negative(amenities):
    """E4. 악재 회피 — ★★★★"""
    cems = [c for c in amenities.get('cemetery', []) if c['distance_m'] <= 1000]
    pwrs = [p for p in amenities.get('power', []) if p['distance_m'] <= 1000]
    total = len(cems) + len(pwrs)
    if total == 0: return 1.0
    if total <= 2: return 0.7
    if total <= 4: return 0.4
    return 0.2


def score_rebuild_potential(year, far, rebuild_membership):
    """F1. 재건축 잠재 조건부 — ★★★★"""
    if not year:
        return 0.5
    age = 2026 - year
    if rebuild_membership == 'Y':
        return 1.0
    if age >= 30 and (far or 999) <= 200:
        return 1.0
    if age >= 25 and (far or 999) <= 220:
        return 0.85
    if age >= 25 and (far or 999) <= 250:
        return 0.6
    if age <= 15:
        return 0.5  # 신축은 비활성 (중립)
    if age >= 30 and (far or 0) >= 280:
        return 0.1  # 노후 + 재건축 불가 = 페널티
    return 0.4


def score_land_share(year, far, hh):
    """F3. 토지지분 (저용적률 + 노후 + 적은 세대로 추정) — ★"""
    if not year: return 0.5
    if not far: return 0.5
    age = 2026 - year
    score = 0.4
    if far <= 200: score += 0.3
    if age >= 30: score += 0.2
    if hh <= 1500: score += 0.1
    return min(score, 1.0)


def score_direction(meta):
    """G1. 방향 (남향 비율, 불완전) — ★★★★"""
    ratio = meta.get('south_ratio', 0)
    total = meta.get('listing_total', 0)
    # 표본 작으면 default 0.5
    if total < 3:
        return 0.5
    if ratio >= 0.5: return 1.0
    if ratio >= 0.3: return 0.7
    if ratio >= 0.1: return 0.5
    return 0.3  # 정보 부족


def score_noise(amenities):
    """G2. 소음 (대로/철도 거리) — ★★★★ (멀수록 좋음)"""
    hwys = amenities.get('highway', [])
    rails = amenities.get('railway', [])
    nearest_hwy = hwys[0]['distance_m'] if hwys else 9999
    nearest_rail = rails[0]['distance_m'] if rails else 9999
    nearest = min(nearest_hwy, nearest_rail)
    if nearest >= 800: return 1.0
    if nearest >= 500: return 0.7
    if nearest >= 300: return 0.5
    if nearest >= 150: return 0.3
    return 0.1


# 가중치 (사용자 등급)
WEIGHTS = {
    'A1_subway_dist': 4,
    'A2_subway_lines': 3,
    'A4_commute_wangsimni': 3,  # ★★★ "한쪽으로 몰기" — 왕십리 우선 (사용자 의도)
    'B1_household': 3,
    'B2_year': 2,
    'B3_far_cond': 3,
    'B4_parking': 2,
    'B5_brand': 1,
    'B6_pyeong_div': 2,
    'C1_gap': 1,
    'C2_trend': 3,
    'C3_lease': 1,
    'C4_listings': 2,
    'D1_primary': 4,
    # D2 학업성취도 (수동, 4)
    # D3 학원가 (수동, 2)
    'E1_mart_hosp': 2,
    'E2_park': 3,
    # E3 호재 (수동, 4.5)
    'E4_avoid_neg': 4,
    'F1_rebuild_cond': 4,
    # F2 정비사업 (수동, 2)
    'F3_land_share': 1,
    'G1_direction': 4,
    'G2_noise': 4,
    # G3 관리 (수동, 3)
}
TOTAL_WEIGHT = sum(WEIGHTS.values())  # 자동 부분만


def main():
    with open('../data/candidates_enriched.json') as f:
        enriched = {c['name']: c for c in json.load(f)}
    with open('../data/price_analysis.json') as f:
        prices = {p['name']: p for p in json.load(f)}
    with open('../data/meta_extra.json') as f:
        meta = {m['name']: m for m in json.load(f)}
    with open('../data/amenities_25.json') as f:
        amen = json.load(f)
    with open('../data/candidates_v3_pool.json') as f:
        v2 = json.load(f)

    rows = []
    for c in v2:
        name = c['name']
        e = enriched.get(name, {})
        p = prices.get(name, {})
        m = meta.get(name, {})
        a = amen.get(name, {})

        scores = {
            'A1_subway_dist': score_subway_distance(a),
            'A2_subway_lines': score_subway_lines(a),
            'B1_household': score_household(c['household']),
            'B2_year': score_year(e.get('year')),
            'B3_far_cond': score_floor_area_ratio_conditional(e.get('year'), e.get('floor_area_ratio')),
            'B4_parking': score_parking(e.get('year')),
            'B5_brand': score_brand(m),
            'B6_pyeong_div': score_pyeong_diversity(m),
            'C1_gap': score_gap(p.get('gap_pct')),
            'C2_trend': score_trend(p.get('trend_pct')),
            'C3_lease': score_lease_rate(p.get('lease_rate') or e.get('lease_rate', '')),
            'C4_listings': score_listing_count(c['count']),
            'D1_primary': score_primary_school(a),
            'E1_mart_hosp': score_mart_hospital(a),
            'E2_park': score_park(a),
            'E4_avoid_neg': score_avoid_negative(a),
            'F1_rebuild_cond': score_rebuild_potential(e.get('year'), e.get('floor_area_ratio'), e.get('rebuild_membership')),
            'F3_land_share': score_land_share(e.get('year'), e.get('floor_area_ratio'), c['household']),
            'G1_direction': score_direction(m),
            'G2_noise': score_noise(a),
        }
        # 통근 컷오프 + 왕십리 점수
        if e.get('lat') and e.get('lon'):
            ws_score, cutoff_ok, d_ws, d_gc = score_commute_filter(e['lat'], e['lon'])
            scores['A4_commute_wangsimni'] = ws_score
        else:
            ws_score, cutoff_ok, d_ws, d_gc = 0.5, True, None, None
            scores['A4_commute_wangsimni'] = 0.5

        # 가중 합산
        weighted = sum(scores[k] * WEIGHTS[k] for k in scores)
        normalized = weighted / TOTAL_WEIGHT * 100  # 100점 만점

        rows.append({
            'name': name,
            'tier': c['tier'],
            'household': c['household'],
            'year': e.get('year'),
            'far': e.get('floor_area_ratio'),
            'min_price': c['min_price'],
            'd_wangsimni_km': round(d_ws, 1) if d_ws else None,
            'd_gwacheon_km': round(d_gc, 1) if d_gc else None,
            'commute_ok': cutoff_ok,
            'subway_dist_m': a.get('subway', [{}])[0].get('distance_m') if a.get('subway') else None,
            'pri_school_m': a.get('school', {}).get('pri', [{}])[0].get('distance_m') if a.get('school', {}).get('pri') else None,
            'park_m': a.get('park', [{}])[0].get('distance_m') if a.get('park') else None,
            'noise_m': min((a.get('highway', [{}])[0].get('distance_m', 9999) if a.get('highway') else 9999),
                          (a.get('railway', [{}])[0].get('distance_m', 9999) if a.get('railway') else 9999)),
            'avoid_neg_count': len(a.get('cemetery', [])) + len(a.get('power', [])),
            'scores': {k: round(v, 2) for k, v in scores.items()},
            'total': round(normalized, 1),
        })

    rows.sort(key=lambda r: -r['total'])

    # 출력
    print(f"\n{'#':>2}  {'단지':24s}  {'등급':3s}  {'세대':>5s}  {'역m':>5s}  {'초m':>5s}  {'공원m':>5s}  {'소음m':>5s}  {'악재':>3s}  {'왕':>4s}  {'과':>4s}  {'점수':>5s}")
    print('=' * 120)
    for i, r in enumerate(rows, 1):
        cut = '' if r['commute_ok'] else ' [컷]'
        print(f"{i:>2}  {r['name'][:23]:24s}  {r['tier']:3s}  {r['household']:>5}  {r['subway_dist_m'] or '-':>5}  {r['pri_school_m'] or '-':>5}  {r['park_m'] or '-':>5}  {r['noise_m']:>5}  {r['avoid_neg_count']:>3}  {r['d_wangsimni_km'] or '-':>4}  {r['d_gwacheon_km'] or '-':>4}  {r['total']:>5}{cut}")

    with open('../data/candidates_v3_scored.json', 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\n저장: ../data/candidates_v3_scored.json")


if __name__ == '__main__':
    main()
