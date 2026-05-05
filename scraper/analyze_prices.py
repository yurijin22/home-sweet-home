"""
가격 분석 — 호가 vs 실거래가 vs KAB 시세
- 호가-실거래 갭 (협상 여지)
- 실거래가 6개월 추세
- 가성비 점수
"""
import json
from datetime import date
from collections import defaultdict


def fmt(p):
    if p is None: return '-'
    return f"{p/10000:.1f}억"


def parse_md(date_str):
    """'2025.11.30' → (2025, 11)"""
    if not date_str: return None
    parts = date_str.split('.')
    return (int(parts[0]), int(parts[1]))


def main():
    with open('../data/candidates_with_prices.json') as f:
        data = json.load(f)

    rows = []
    for c in data:
        txs = c['transactions']
        kab = c['kab_summary']

        # 최근 6개월 실거래
        cutoff = (2025, 11)  # 2026년 5월 기준 6개월 전
        recent = [t for t in txs if t.get('date') and parse_md(t['date']) and parse_md(t['date']) >= cutoff]
        recent_avg = sum(t['price'] for t in recent) / len(recent) if recent else None
        recent_min = min((t['price'] for t in recent), default=None)
        recent_max = max((t['price'] for t in recent), default=None)

        # 전체 거래 (5년치)
        all_avg = sum(t['price'] for t in txs) / len(txs) if txs else None

        # 시간 추세 — 가장 오래된 vs 최근 6개월 평균
        sorted_txs = sorted(txs, key=lambda t: parse_md(t['date']) or (0,0))
        old_5 = sorted_txs[:5]
        new_5 = sorted_txs[-5:]
        old_avg = sum(t['price'] for t in old_5) / len(old_5) if old_5 else None
        new_avg = sum(t['price'] for t in new_5) / len(new_5) if new_5 else None
        trend_pct = ((new_avg - old_avg) / old_avg * 100) if old_avg and new_avg else None

        # 호가-실거래 갭
        offer_min = c['min_price']  # 호가 최저
        gap_pct = ((offer_min - recent_avg) / recent_avg * 100) if recent_avg else None

        rows.append({
            'name': c['name'],
            'tier': c['tier'],
            'household': c['household'],
            'offer_min': offer_min,
            'kab_avg': kab.get('kab_avg'),
            'kab_change': kab.get('kab_change'),  # 직전 대비 변동
            'lease_rate': kab.get('lease_rate'),
            'recent_avg': recent_avg,
            'recent_min': recent_min,
            'recent_max': recent_max,
            'all_avg': all_avg,
            'trend_pct': trend_pct,  # 5년 추세
            'gap_pct': gap_pct,
            'tx_count': len(txs),
            'recent_count': len(recent),
        })

    # 출력
    print(f"\n{'단지':24s} {'호가':>6s} {'실거래':>7s} {'KAB':>6s} {'갭%':>5s}  {'5년추세':>7s}  {'전세가율':>8s}  {'거래':>3s}")
    print('=' * 90)
    for r in rows:
        offer = fmt(r['offer_min'])
        recent = fmt(r['recent_avg'])
        kab = fmt(r['kab_avg'])
        gap = f"{r['gap_pct']:+.1f}" if r['gap_pct'] is not None else '-'
        trend = f"{r['trend_pct']:+.0f}%" if r['trend_pct'] is not None else '-'
        lease = r['lease_rate'] or '-'
        print(f"{r['name'][:23]:24s} {offer:>6s} {recent:>7s} {kab:>6s} {gap:>5s}  {trend:>7s}  {lease:>8s}  {r['tx_count']:>3}")

    # 갭 큰 순 (협상 여지)
    print("\n=== 호가-실거래 갭 큰 순 (TOP 10) — 협상 여지 ===")
    sorted_gap = sorted([r for r in rows if r['gap_pct'] is not None], key=lambda r: -r['gap_pct'])
    for r in sorted_gap[:10]:
        print(f"  {r['name']:25s} 호가 {fmt(r['offer_min']):>6s} vs 실거래 {fmt(r['recent_avg']):>7s}  → {r['gap_pct']:+.1f}%")

    # 추세 강한 순
    print("\n=== 5년 추세 ===")
    sorted_trend = sorted([r for r in rows if r['trend_pct'] is not None], key=lambda r: -r['trend_pct'])
    print("\n  상승 TOP 5:")
    for r in sorted_trend[:5]:
        print(f"    {r['name']:25s} {r['trend_pct']:+.0f}%  (현 KAB {fmt(r['kab_avg'])})")
    print("\n  하락 TOP 5:")
    for r in sorted_trend[-5:]:
        print(f"    {r['name']:25s} {r['trend_pct']:+.0f}%  (현 KAB {fmt(r['kab_avg'])})")

    # JSON 저장
    with open('../data/price_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("\n저장: ../data/price_analysis.json")


if __name__ == '__main__':
    main()
