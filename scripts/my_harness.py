"""
나만의 경매 하네스 v1 (2026-07-30 재설계)
— 예측 없음. 팩트만. 걸릴 때만 알림. —

계층:
  1. 🚨 타깃 사건: 추적 중인 사건번호가 기일 잡혀 등장 → 무조건 알림
  2. 👀 워치 단지: 관심 단지에 경매 물건 등장 → 알림
  3. 🔍 조건 신건: 관심 구 + 전용 45~85 + 최저가 상한 → 실거래 팩트 첨부해 알림
매칭되는 것이 하나도 없으면 출력 없음(이슈 안 만듦).

시세는 예측하지 않는다. 최근 3개월 실거래 범위 + 최신 3건 + 세대수·연식만 병기.
(규칙: 데이터 없으면 "확인 필요" — 할루시네이션 금지)
"""
import argparse
import glob
import json
import re
import statistics as st
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
KST = timezone(timedelta(hours=9))

# ── 1. 추적 사건 (기일 뜨는 순간 최우선 알림) ─────────────────────
TARGET_CASES = {
    '2026타경10627': '⭐추적1호 한신·한진 107동 8층 (돈암, 🏠4509/1998) — 68㎡면 예산 정중앙',
    '2026타경65':    '⭐추적2호 브라운스톤돈암 101동 8층 (🏠1074/2004) — 60㎡ 최근 8.85, 예산 턱걸이',
}

# ── 2. 워치 단지 (이름 키워드 + 구) ──────────────────────────────
WATCH_COMPLEXES = [
    ('노원구', '장미',      '하계장미(시영6) — 매매 협상 병행 중'),
    ('노원구', '그린',      '중계그린 — 제2티켓 후보'),
    ('노원구', '학여울',    '학여울청구 — 무기한 백업'),
    ('성북구', '한신',      '한신·한진(돈암) 4509세대'),
    ('성북구', '한진',      '한신·한진(돈암) 4509세대'),
    ('성북구', '브라운스톤', '브라운스톤돈암'),
    ('노원구', '주공6',     '상계주공6 — 모델 검증용 관전'),
]

# ── 3. 조건 신건 필터 ────────────────────────────────────────────
FILTER_GU = {'노원구', '도봉구', '성북구', '동대문구', '성동구', '동작구'}
AREA_MIN, AREA_MAX = 45.0, 85.0
MINPRICE_MAX_EOK = 8.5     # 최저가 상한 (예산 8.8 - 부대비용 여유)

SLUG2GU = {
    'nowon': '노원구', 'dobong': '도봉구', 'seongbuk': '성북구',
    'dongdaemun': '동대문구', 'seongdong': '성동구', 'dongjak': '동작구',
    'gangbuk': '강북구', 'jungnang': '중랑구',
}


def load_json(p, default=None):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_trades():
    """관심 구 molit 실거래 전체 로드 → {구: [trade,...]}"""
    out = {}
    for slug, gu in SLUG2GU.items():
        items = []
        for f in glob.glob(str(DATA / 'molit_trade' / f'{slug}_*.json')):
            d = load_json(f, {})
            items += d.get('items', [])
        if items:
            out[gu] = items
    return out


def load_households():
    y = load_json(DATA / 'years_all.json', {}) or {}
    return y


def norm_case(s):
    """'2026타경10627' → ('2026','10627') — 형식 편차 흡수."""
    m = re.search(r'(\d{4})\s*타경\s*(\d+)', str(s))
    return (m.group(1), m.group(2)) if m else None


TARGET_KEYS = {norm_case(k): v for k, v in TARGET_CASES.items()}


def name_tokens(name):
    return re.sub(r'\(.*?\)|아파트|\d+단지', '', str(name)).strip()


def comps_for(item, trades, months=3):
    """같은 구 + 이름 토큰 + 면적 ±3㎡ 실거래 팩트.
    저장소 데이터가 오래됐을 수 있으므로 '데이터 내 최신 거래일' 기준 최근 N개월."""
    gu = item.get('gu', '')
    g = trades.get(gu)
    if not g:
        return None
    key = name_tokens(item.get('name', ''))
    if len(key) < 2:
        return None
    area = item.get('area_m2') or 0
    matched = [t for t in g
               if (key in t['name'] or t['name'] in key)
               and abs(t['area_m2'] - area) <= 3]
    if not matched:
        return None
    max_date = max(t['deal_date'] for t in matched)
    cutoff = (datetime.strptime(max_date, '%Y-%m-%d') - timedelta(days=months * 31)).strftime('%Y-%m-%d')
    hit = [t for t in matched if t['deal_date'] >= cutoff]
    if not hit:
        return None
    hit.sort(key=lambda t: t['deal_date'])
    ps = [t['price_10k'] / 10000 for t in hit]
    latest = hit[-3:]
    return {
        'n': len(hit), 'min': min(ps), 'med': st.median(ps), 'max': max(ps),
        'latest': [f"{t['deal_date'][5:]} {t['price_10k']/10000:.2f}억({t['floor']}층)" for t in latest],
        'data_upto': hit[-1]['deal_date'],
    }


# 조사로 확정한 세대수·연식 (years_all에 없거나 오매칭되는 워치 단지)
KNOWN_COMPLEX = {
    ('노원구', '장미'):      '🏠1,880세대 / 📅1989년 (하계 시영6)',
    ('노원구', '그린'):      '🏠3,481세대 / 📅1990년 (중계그린)',
    ('노원구', '학여울'):    '🏠1,476세대 / 📅1999년',
    ('성북구', '한신'):      '🏠4,509세대 / 📅1998년 (한신·한진 통합)',
    ('성북구', '한진'):      '🏠4,509세대 / 📅1998년 (한신·한진 통합)',
    ('성북구', '브라운스톤'): '🏠1,074세대 / 📅2004년',
    ('노원구', '주공6'):     '🏠2,646세대 / 📅1987년',
}


def household_line(item, years):
    """세대수·연식 — 확정값 우선, 다음 years_all 정확·최장 매칭, 없으면 '확인 필요'."""
    gu, name = item.get('gu', ''), str(item.get('name', ''))
    for (kgu, kw), line in KNOWN_COMPLEX.items():
        if kgu == gu and kw in name:
            return line
    key = name_tokens(name)
    if not key:
        return '🏠세대수 확인 필요 / 📅연식 확인 필요'
    if key in years:
        v = years[key]
        return f"🏠{v.get('household','?')}세대 / 📅{v.get('year','?')}년"
    cands = [(len(k), k, v) for k, v in years.items() if key == name_tokens(k)]
    if cands:
        _, _, v = max(cands)
        return f"🏠{v.get('household','?')}세대 / 📅{v.get('year','?')}년"
    return '🏠세대수 확인 필요 / 📅연식 확인 필요'


def fmt(item, years, trades, note=None):
    lines = []
    lines.append(f"**{item.get('name','?')}** — {item.get('gu','?')} {item.get('addr','')}")
    lines.append(f"- 사건: {item.get('case_no','?')} ({item.get('court','?')}) | 매각기일: **{item.get('sale_date','?')}**")
    ap, mn = item.get('appraisal_eok'), item.get('min_price_eok')
    lines.append(f"- 전용 {item.get('area_m2','?')}㎡ {item.get('floor','?')}층 | 감정 {ap}억 / 최저 {mn}억 (유찰 {item.get('fail_count',0)}회)")
    lines.append(f"- {household_line(item, years)}")
    c = comps_for(item, trades)
    if c:
        lines.append(f"- 실거래(최근 3개월, {c['n']}건, ~{c['data_upto']}): **{c['min']:.2f}~{c['max']:.2f}억** (중앙 {c['med']:.2f})")
        lines.append(f"- 최신 3건: {' / '.join(c['latest'])}")
    else:
        lines.append("- 실거래: 매칭 실패 — **확인 필요** (예측 안 함)")
    if item.get('special') and item['special'] != '없음':
        lines.append(f"- ⚠️ 특수조건: {item['special']}")
    if note:
        lines.append(f"- 📌 {note}")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', help='YYYY_MM_DD (기본 오늘 KST)')
    args = ap.parse_args()
    date = args.date or datetime.now(KST).strftime('%Y_%m_%d')

    raw = load_json(DATA / f'auction_raw_{date}.json', [])
    if not raw:
        print('')  # 수집 없음 → 조용히 종료
        return 0

    trades = load_trades()
    years = load_households()

    hits_target, hits_watch, hits_filter = [], [], []
    for it in raw:
        ck = norm_case(it.get('case_no', ''))
        if ck and ck in TARGET_KEYS:
            hits_target.append(fmt(it, years, trades, note=TARGET_KEYS[ck]))
            continue
        gu, nm = it.get('gu', ''), str(it.get('name', ''))
        watched = next((memo for wgu, kw, memo in WATCH_COMPLEXES if wgu == gu and kw in nm), None)
        if watched:
            hits_watch.append(fmt(it, years, trades, note=watched))
            continue
        try:
            area = float(it.get('area_m2') or 0)
            mn = float(it.get('min_price_eok') or 0)
        except (TypeError, ValueError):
            continue
        if gu in FILTER_GU and AREA_MIN <= area <= AREA_MAX and 0 < mn <= MINPRICE_MAX_EOK:
            hits_filter.append(fmt(it, years, trades))

    if not (hits_target or hits_watch or hits_filter):
        print('')  # 걸린 것 없음 → 이슈 안 만듦
        return 0

    out = [f"# 🔭 나의 경매 하네스 — {date.replace('_','-')}", '']
    if hits_target:
        out += ['## 🚨 추적 사건 등장 — 즉시 확인', ''] + [h + '\n' for h in hits_target]
    if hits_watch:
        out += ['## 👀 워치 단지 경매 등장', ''] + [h + '\n' for h in hits_watch]
    if hits_filter:
        out += [f'## 🔍 조건 부합 신건 ({len(hits_filter)}건)', ''] + [h + '\n' for h in hits_filter]
    out += ['---', '_예측 없음·팩트만. 실거래는 저장소 molit 데이터 기준 — 최신 아닐 수 있음(수집일 확인). 세대수 없으면 "확인 필요"._']
    print('\n'.join(out))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
