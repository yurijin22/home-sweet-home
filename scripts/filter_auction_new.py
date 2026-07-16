"""
경매 원본 → 서울·신건·예산 필터 → 알림용 다이제스트
입력: data/auction_raw_{YYYY_MM_DD}.json  (fetch_auction_seoul.py 산출물)
출력:
  data/auction_new_{YYYY_MM_DD}.json  (필터 통과 물건 + 사유)
  표준출력: 사람이 읽는 다이제스트 (알림 본문으로 사용)

필터 기준: config/auction_filter.json (편집 가능)
세대수(300+)는 data/budget_all_seoul.json 이름 매칭으로 보강(있으면).
"""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
DATA = ROOT / 'data'
CFG_PATH = ROOT / 'config/auction_filter.json'
BUDGET_PATH = DATA / 'budget_all_seoul.json'


def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def household_lookup():
    """단지명 → 세대수 (부분일치). 없으면 빈 dict."""
    budget = load_json(BUDGET_PATH, {}) or {}
    return {name: v.get('household') for name, v in budget.items()}


def match_household(name, table):
    """경매 물건명에 워치리스트 단지명이 포함되면 세대수 반환."""
    for cname, hh in table.items():
        if cname and cname in name:
            return hh, cname
    return None, None


def is_special(item, cfg):
    special = (item.get('special') or '').strip()
    if special and special != '없음':
        return True
    for kw in cfg['special_keywords']:
        if kw in (item.get('name') or '') or kw in special:
            return True
    return False


def evaluate(item, cfg, hh_table):
    """물건 하나 평가 → (통과여부, 사유리스트, 보강정보)."""
    reasons = []
    gu = (item.get('gu') or '?').replace('구', '')
    court = (item.get('court') or '').replace('지방법원', '').replace('법원', '')

    in_seoul = gu in cfg['seoul_gu'] or any(c in court for c in cfg['seoul_courts'])
    if not in_seoul:
        reasons.append(f'서울 아님(구={gu}, 법원={court})')

    area = item.get('area_m2')
    if area is None:
        reasons.append('전용면적 미상')
    elif not (cfg['area_m2_min'] <= area <= cfg['area_m2_max']):
        reasons.append(f'면적범위밖({area}㎡)')

    appr = item.get('appraisal_eok')
    if appr is None:
        reasons.append('감정가 미상')
    elif not (cfg['appraisal_eok_min'] <= appr <= cfg['appraisal_eok_max']):
        reasons.append(f'감정가범위밖({appr}억)')

    minp = item.get('min_price_eok')
    if minp is not None and minp > cfg['min_price_eok_max']:
        reasons.append(f'최저가초과({minp}억)')

    if cfg['require_new_only'] and (item.get('fail_count') or 0) != 0:
        reasons.append(f'신건아님(유찰{item.get("fail_count")}회)')

    special = is_special(item, cfg)
    if cfg['exclude_special'] and special:
        reasons.append(f'특수물건({item.get("special")})')

    hh, matched = match_household(item.get('name') or '', hh_table)
    if hh is not None and hh < cfg['household_min']:
        reasons.append(f'세대수부족({hh})')

    enrich = {'household': hh, 'matched_name': matched, 'special': special}
    return (len(reasons) == 0, reasons, enrich)


def _mmdd(d):
    """'2026-08-11' → '08-11'."""
    return d[5:] if d and len(d) >= 10 else (d or '?')


def _md_table(headers, aligns, rows):
    """마크다운 표 문자열."""
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join(aligns) + '|']
    out += ['| ' + ' | '.join(r) + ' |' for r in rows]
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser(description='경매 서울·신건·예산 필터')
    ap.add_argument('--date', help='YYYY_MM_DD (기본: 오늘 KST)')
    ap.add_argument('--raw', help='raw json 경로 직접 지정')
    args = ap.parse_args()

    date = args.date or datetime.now(KST).strftime('%Y_%m_%d')
    raw_path = Path(args.raw) if args.raw else DATA / f'auction_raw_{date}.json'
    items = load_json(raw_path)
    if items is None:
        print(f'ERROR: raw 파일 없음 → {raw_path}')
        print('먼저 실행: python scraper/fetch_auction_seoul.py [--mock]')
        return 1

    cfg = load_json(CFG_PATH)
    hh_table = household_lookup()

    passed, special_pool = [], []
    for it in items:
        ok, reasons, enrich = evaluate(it, cfg, hh_table)
        rec = {**it, '_reasons': reasons, '_household': enrich['household']}
        if ok:
            passed.append((it, enrich))
        elif enrich['special'] and len([r for r in reasons if '특수' not in r]) == 0:
            # 특수물건이라 걸린 것 외 다른 결격사유 없음 → 참고용 별도 풀
            special_pool.append((it, enrich))

    out_path = DATA / f'auction_new_{date}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump([{**it, '_household': en['household']} for it, en in passed],
                  f, ensure_ascii=False, indent=2)

    # ── 다이제스트 (알림 본문, GitHub 이슈 Markdown) ──
    lines = [f'## 📢 서울 경매 신건 — {date.replace("_", "-")}']
    summary = f'원본 **{len(items)}건** → 조건통과 **{len(passed)}건**'
    if special_pool:
        summary += f' · 특수물건 참고 {len(special_pool)}건'
    lines += [summary, '']

    if passed:
        lines.append('### ✅ 예산·조건 충족 신건')
        rows = []
        for it, en in sorted(passed, key=lambda x: x[0].get('appraisal_eok') or 0):
            hh = en['household']
            rows.append([
                str(it.get('name') or '?'), str(it.get('gu') or '?'),
                f"{it.get('area_m2')}㎡", f"{it.get('floor')}층",
                f"{it.get('appraisal_eok')}억", f"{hh}" if hh else "?",
                _mmdd(it.get('sale_date')), f"{it.get('case_no')} ({it.get('court')})",
            ])
        lines.append(_md_table(
            ['단지', '지역', '전용', '층', '감정가', '세대수', '매각기일', '사건'],
            [':--', ':--', '--:', '--:', '--:', '--:', ':-:', ':--'], rows))
    else:
        lines.append('_오늘 조건 충족 신건 없음_')

    if special_pool:
        lines += ['', '### ⚠️ 특수물건 (인수리스크 — 별도 검토)']
        rows = [[str(it.get('name') or '?'), str(it.get('gu') or '?'),
                 f"{it.get('area_m2')}㎡", str(it.get('special')), str(it.get('case_no'))]
                for it, en in special_pool]
        lines.append(_md_table(
            ['단지', '지역', '전용', '사유', '사건'],
            [':--', ':--', '--:', ':--', ':--'], rows))

    print('\n'.join(lines))
    print(f'saved: {out_path}', file=sys.stderr)   # 본문에 안 들어가게 stderr
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
