"""
예측 하네스 보정 — 오늘 낙찰결과를 과거 예측과 대조해 오차 기록 + k 자동 보정.
입력: data/auction_results_{날짜}.json (오늘 낙찰) + data/auction_predictions.json (누적 예측)
출력:
  - data/auction_calibration.jsonl: 대조 기록 append (case_no, 예측, 실제, 오차)
  - data/auction_k.json: 보정된 k (예상낙찰 = 감정 × k)
  - 표준출력: 보정 요약 (예측 정확도)

k 보정 = (선험 0.92 × W + Σ 실측 낙찰가율) / (W + n)   # W=30, comps 356건 평균 0.92를 prior로
"""
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
DATA = ROOT / 'data'
PRIOR_K = 0.92
PRIOR_W = 30


def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def load_rates_from_log():
    """calibration.jsonl 의 실측 낙찰가율(actual/감정) 목록."""
    p = DATA / 'auction_calibration.jsonl'
    rates = []
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get('actual_rate'):
                    rates.append(rec['actual_rate'])
            except json.JSONDecodeError:
                pass
    return rates


def main():
    ap = argparse.ArgumentParser(description='예측 하네스 보정')
    ap.add_argument('--date', help='YYYY_MM_DD (기본 오늘 KST)')
    ap.add_argument('--stamp', help='기록 시각 YYYY-MM-DD')
    args = ap.parse_args()

    date = args.date or datetime.now(KST).strftime('%Y_%m_%d')
    stamp = args.stamp or date.replace('_', '-')
    results = load_json(DATA / f'auction_results_{date}.json')
    if results is None:
        print(f'낙찰결과 없음 → {date} · 보정 스킵')
        return 0
    preds = load_json(DATA / 'auction_predictions.json', {}) or {}

    new_records = []
    for r in results:
        if r.get('result') != '매각':
            continue
        cno = r.get('case_no')
        appr = r.get('appraisal_eok')
        actual = r.get('sale_price_eok')
        if not (appr and actual):
            continue
        actual_rate = round(actual / appr, 4)
        pred_rec = preds.get(cno)
        rec = {
            'case_no': cno, 'name': r.get('name'), 'gu': r.get('gu'),
            'appraisal_eok': appr, 'actual_sale_eok': actual,
            'actual_rate': actual_rate, 'sale_date': r.get('sale_date'),
            'logged_at': stamp,
        }
        if pred_rec and pred_rec.get('pred_sale_eok'):
            pred = pred_rec['pred_sale_eok']
            rec['pred_sale_eok'] = pred
            rec['err_eok'] = round(actual - pred, 2)
            rec['err_pct'] = round((actual - pred) / actual * 100, 1) if actual else None
            rec['matched'] = True
        else:
            rec['matched'] = False   # 예측 없던 물건(과거분) → k 보정엔 사용, 오차는 없음
        new_records.append(rec)

    # append (dedup by case_no+sale_date 는 아카이브에서 처리, 여기선 로그 누적)
    if new_records:
        with open(DATA / 'auction_calibration.jsonl', 'a', encoding='utf-8') as f:
            for rec in new_records:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')

    # k 보정
    rates = load_rates_from_log()
    n = len(rates)
    k_new = round((PRIOR_K * PRIOR_W + sum(rates)) / (PRIOR_W + n), 4) if n else PRIOR_K
    with open(DATA / 'auction_k.json', 'w', encoding='utf-8') as f:
        json.dump({'k': k_new, 'n': n, 'prior_k': PRIOR_K,
                   'updated': stamp}, f, ensure_ascii=False, indent=2)

    matched = [r for r in new_records if r.get('matched')]
    print(f'🔧 예측 보정 — {stamp}')
    print(f'   오늘 매각 {len(new_records)}건 (예측대조 {len(matched)}건) · 누적 실측 {n}건')
    print(f'   보정된 k = {k_new} (예상낙찰 = 감정가 × {k_new})')
    if matched:
        mae = round(sum(abs(r['err_pct']) for r in matched if r.get('err_pct') is not None)
                    / max(len(matched), 1), 1)
        print(f'   예측 MAE(오차율) ≈ {mae}%')
        for r in matched:
            print(f"   · {r['name']}: 예측 {r['pred_sale_eok']}억 vs 실제 "
                  f"{r['actual_sale_eok']}억 (오차 {r['err_pct']}%)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
