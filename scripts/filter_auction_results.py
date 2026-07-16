"""
경매 낙찰결과 → 예산권·최근 매각 필터 → 알림 다이제스트
입력: data/auction_results_{YYYY_MM_DD}.json  (fetch_auction_results.py 산출물)
출력: 표준출력 다이제스트 (이슈 본문용). 원본 JSON은 워크플로가 그대로 커밋(모델용 축적).

기준: config/auction_filter.json 의 면적 + 아래 가격창.
  - result == '매각' (실제 낙찰된 것)
  - 전용 54~85㎡
  - 낙찰가 6.0~12.0억 (예산권 비교사례)
  - 최근 N일(--days, 기본 3) 매각만 → 매일 중복 알림 최소화
유찰 건수는 참고로 요약만.
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
DATA = ROOT / 'data'
CFG_PATH = ROOT / 'config/auction_filter.json'

SALE_PRICE_MIN = 6.0   # 억 — 예산권 비교사례 하한
SALE_PRICE_MAX = 12.0  # 억 — 상한


def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def in_recent(sale_date, days, today):
    """sale_date(YYYY-MM-DD)가 오늘 기준 최근 days일 이내인가."""
    if not sale_date:
        return False
    try:
        d = datetime.strptime(sale_date, '%Y-%m-%d').date()
    except ValueError:
        return False
    return 0 <= (today - d).days <= days


def main():
    ap = argparse.ArgumentParser(description='경매 낙찰결과 예산권·최근 필터')
    ap.add_argument('--date', help='결과파일 날짜 YYYY_MM_DD (기본: 오늘 KST)')
    ap.add_argument('--days', type=int, default=3, help='최근 N일 매각만 (기본 3)')
    args = ap.parse_args()

    today = datetime.now(KST).date()
    date_tag = args.date or today.strftime('%Y_%m_%d')
    path = DATA / f'auction_results_{date_tag}.json'
    items = load_json(path)
    if items is None:
        print(f'ERROR: 결과 파일 없음 → {path}')
        return 1

    cfg = load_json(CFG_PATH, {})
    amin = cfg.get('area_m2_min', 54)
    amax = cfg.get('area_m2_max', 85)

    sold = [it for it in items if it.get('result') == '매각']
    yuchal = [it for it in items if it.get('result') == '유찰']

    hits = []
    for it in sold:
        area = it.get('area_m2')
        sp = it.get('sale_price_eok')
        if area is None or sp is None:
            continue
        if not (amin <= area <= amax):
            continue
        if not (SALE_PRICE_MIN <= sp <= SALE_PRICE_MAX):
            continue
        if not in_recent(it.get('sale_date'), args.days, today):
            continue
        hits.append(it)

    hits.sort(key=lambda x: (x.get('sale_date') or '', x.get('sale_price_eok') or 0), reverse=True)

    # 카운트/알림용 필터 결과 저장 (워크플로가 건수 판단에 사용)
    with open(DATA / f'auction_results_new_{date_tag}.json', 'w', encoding='utf-8') as f:
        json.dump(hits, f, ensure_ascii=False, indent=2)

    print(f'🔨 서울 경매 낙찰결과 — {today.isoformat()} (최근 {args.days}일)')
    print(f'   수집 {len(items)}건 (매각 {len(sold)} · 유찰 {len(yuchal)}) → 예산권 매각 {len(hits)}건')
    print()
    if hits:
        print('✅ 예산·조건 충족 낙찰결과')
        for it in hits:
            rate = it.get('sale_rate')
            rate_s = f'{rate}%' if rate is not None else '?'
            print(f"• {it.get('name')} ({it.get('gu')}구) | {it.get('area_m2')}㎡ "
                  f"{it.get('floor')}층 | 감정 {it.get('appraisal_eok')}억 → "
                  f"낙찰 {it.get('sale_price_eok')}억 (낙찰가율 {rate_s}) | 매각 {it.get('sale_date')}")
            print(f"    사건 {it.get('case_no')} ({it.get('court')})")
    else:
        print(f'(최근 {args.days}일 예산권 매각 없음)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
