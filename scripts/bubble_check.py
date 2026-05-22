"""
워치리스트 단지 거품 진단.

각 단지에 대해:
- 평단가(만원/㎡) 기준 36개월 추세 산출
- 직전 24개월 평균 vs 최근 6개월 평균 갭
- 현재 호가-최근 실거래 갭
"""
import json
import glob
import re
from collections import defaultdict
from statistics import mean, median
from pathlib import Path

ROOT = Path('/home/user/home-sweet-home')

REGION_TO_GU = {
    '성북': 'seongbuk', '도봉': 'dobong', '은평': 'eunpyeong',
    '구로': 'guro', '성동': 'seongdong', '동대문': 'dongdaemun',
    '동작': 'dongjak', '관악': 'gwanak', '중랑': 'jungnang',
    '노원': 'nowon', '서대문': 'seodaemun', '마포': 'mapo',
}

with open(ROOT / 'data/watchlist.md') as f:
    wl_text = f.read()

with open(ROOT / 'data/budget_all_seoul.json') as f:
    bud = json.load(f)

# 풀 포맷 ### 단지명 (관심/보류 상세) 추출
complexes = []
for m in re.finditer(r'^###\s+(.+?)\n.*?complex_no:\s*(\d+).*?호가:\s*([\d.]+)억', wl_text, re.S | re.M):
    name = m.group(1).strip()
    cno = m.group(2)
    price_eok = float(m.group(3))
    info = bud.get(name, {})
    region = info.get('region', '')
    gu_kr = region.split('_')[0] if region else ''
    complexes.append({
        'name': name, 'cno': cno, 'price_eok': price_eok,
        'region': region, 'gu': REGION_TO_GU.get(gu_kr),
    })

# 한줄 포맷 추출: - **#N 단지명** (cno 12345) | ...
for m in re.finditer(r'-\s+\*\*#\d+\s+(.+?)\*\*\s+\(cno\s+(\d+)\)[^\n]*?호가\s+([\d.]+)억', wl_text):
    name = m.group(1).strip()
    cno = m.group(2)
    price_eok = float(m.group(3))
    if any(c['cno'] == cno for c in complexes):
        continue
    # 한줄 포맷에서 단지명에 (1070세대) 같은 부가어 제거
    bare = re.sub(r'\([^)]+\)$', '', name).strip()
    info = bud.get(bare, {}) or bud.get(name, {})
    region = info.get('region', '')
    gu_kr = region.split('_')[0] if region else ''
    complexes.append({
        'name': bare, 'cno': cno, 'price_eok': price_eok,
        'region': region, 'gu': REGION_TO_GU.get(gu_kr),
    })

print(f"총 워치리스트 단지: {len(complexes)}")
print(f"  - 구 매핑 성공: {sum(1 for c in complexes if c['gu'])}")
print(f"  - 구 매핑 실패: {sum(1 for c in complexes if not c['gu'])}")

# 구별 36개월 거래 로딩 (필요한 구만)
needed_gus = set(c['gu'] for c in complexes if c['gu'])
trades_by_gu = defaultdict(list)
for gu in needed_gus:
    files = sorted((ROOT / 'data/molit_trade').glob(f'{gu}_*.json'))
    for fp in files:
        ym = fp.stem.split('_')[-1]
        with open(fp) as f:
            d = json.load(f)
        for it in d.get('items', []):
            it['ym'] = ym
            trades_by_gu[gu].append(it)
print(f"\n구별 거래 데이터: " + ", ".join(f"{g}={len(trades_by_gu[g])}건" for g in sorted(needed_gus)))

def find_trades(complex_name, gu):
    if not gu:
        return []
    pool = trades_by_gu[gu]
    variants = [
        complex_name,
        complex_name.replace(',', '·'),
        complex_name.replace(',', ''),
        complex_name.replace(',', ' '),
    ]
    for v in variants:
        hits = [t for t in pool if t['name'] == v]
        if hits:
            return hits
    # 부분 일치 (단지명이 거래기록 단지명에 포함 또는 반대)
    hits = [t for t in pool if (complex_name in t['name']) or (t['name'] in complex_name and len(t['name']) >= 3)]
    return hits

LATEST_YM = '202604'
def ym_diff(ym1, ym2):
    y1, m1 = int(ym1[:4]), int(ym1[4:])
    y2, m2 = int(ym2[:4]), int(ym2[4:])
    return (y2 - y1) * 12 + (m2 - m1)

results = []
for c in complexes:
    trades = find_trades(c['name'], c['gu'])
    if not trades:
        results.append({**c, 'status': 'no_data', 'reason': 'no_trade_match'})
        continue
    for t in trades:
        try:
            t['ppm2'] = t['price_10k'] / t['area_m2']
        except (KeyError, ZeroDivisionError, TypeError):
            t['ppm2'] = None
    valid = [t for t in trades if t.get('ppm2')]
    if not valid:
        results.append({**c, 'status': 'no_data', 'reason': 'no_valid_price'})
        continue
    typical_area = median([t['area_m2'] for t in valid])
    recent = [t for t in valid if 0 <= ym_diff(t['ym'], LATEST_YM) < 6]
    older = [t for t in valid if 6 <= ym_diff(t['ym'], LATEST_YM) < 30]
    recent_ppm2 = median([t['ppm2'] for t in recent]) if recent else None
    older_ppm2 = median([t['ppm2'] for t in older]) if older else None
    asking_ppm2 = c['price_eok'] * 10000 / typical_area if typical_area else None
    run_up = (recent_ppm2 / older_ppm2 - 1) * 100 if (recent_ppm2 and older_ppm2) else None
    asking_gap = (asking_ppm2 / recent_ppm2 - 1) * 100 if (asking_ppm2 and recent_ppm2) else None
    results.append({
        **c,
        'status': 'ok',
        'typical_area': round(typical_area, 1),
        'recent_ppm2': round(recent_ppm2) if recent_ppm2 else None,
        'older_ppm2': round(older_ppm2) if older_ppm2 else None,
        'asking_ppm2': round(asking_ppm2) if asking_ppm2 else None,
        'run_up_pct': round(run_up, 1) if run_up is not None else None,
        'asking_gap_pct': round(asking_gap, 1) if asking_gap is not None else None,
        'recent_n': len(recent), 'older_n': len(older),
    })

with open(ROOT / 'data/bubble_diag.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

ok = [r for r in results if r['status'] == 'ok' and r.get('run_up_pct') is not None]
no = [r for r in results if r['status'] != 'ok' or r.get('run_up_pct') is None]
ok.sort(key=lambda x: -(x.get('run_up_pct') or -999))

print(f"\n=== 거품 진단 ({len(ok)}개 매칭, {len(no)}개 데이터부족) ===")
print(f"run_up%: 직전 24개월(2023.10~2025.09) → 최근 6개월(2025.10~2026.04) 평단가 변동")
print(f"호가갭%: 현재 호가 평단가 vs 최근 6개월 실거래 평단가\n")
print(f"{'단지':<22}{'구':<9}{'호가억':>6}{'면적':>5}{'최근':>7}{'이전':>7}{'상승%':>7}{'호가갭%':>7}{'(6m/24m)':>10}")
for r in ok:
    print(f"{r['name'][:20]:<22}{r['gu'][:7]:<9}{r['price_eok']:>6.1f}"
          f"{r['typical_area']:>5.0f}{(r['recent_ppm2'] or 0):>7}{(r['older_ppm2'] or 0):>7}"
          f"{(r['run_up_pct'] or 0):>+6.1f}%{(r['asking_gap_pct'] or 0):>+6.1f}%"
          f"  {r['recent_n']}/{r['older_n']}")

if no:
    print(f"\n=== 데이터 부족 ({len(no)}개) ===")
    for r in no:
        print(f"  {r['name']} ({r.get('gu','no_gu')}): {r.get('reason','no_match')}")
