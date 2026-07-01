#!/usr/bin/env python3
"""낙찰 사례 유사도 점수화 — 2개 타겟(미미삼 51㎡ / 극동건영벽산 84㎡) 각각 상위 15건."""
import csv, statistics as st, os

CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "auction_comps.csv")

# 우리 물건 2개
TARGETS = {
    "미미삼(월계 미륭·미성·삼호3차 51㎡)":
        dict(전용평=15.57, 감정가억=6.96, 층=3, 재건축="Y", 소형="Y", 구="노원"),
    "극동건영벽산(하계 84㎡)":
        dict(전용평=25.70, 감정가억=7.60, 층=10, 재건축="Y", 소형="N", 구="노원"),
}


def score(r, T):
    s, why = 0, []
    try: p = float(r["전용평"])
    except: p = None
    if p is not None:
        d = abs(p - T["전용평"])
        if d <= 2: s += 30; why.append("평수매우유사")
        elif d <= 5: s += 20; why.append("평수유사")
        elif d <= 10: s += 8
    try: g = float(r["감정가억"])
    except: g = None
    if g is not None:
        d = abs(g - T["감정가억"])
        if d <= 1: s += 25; why.append("감정가유사")
        elif d <= 2: s += 15; why.append("감정가근접")
        elif d <= 3.5: s += 5
    if T["재건축"] == "Y" and r.get("재건축", "").upper() == "Y":
        s += 20; why.append("재건축")
    if r.get("소형여부", "").upper() == T["소형"]:
        s += 10; why.append("소형일치" if T["소형"] == "Y" else "중형일치")
    if r.get("구") == T["구"]:
        s += 15; why.append("노원")
    try:
        f = int(r["층"])
        if abs(f - T["층"]) <= 2: s += 8; why.append("층유사")
        elif f <= 2 and T["층"] > 2: s -= 5; why.append("저층(감점)")
    except: pass
    if r.get("특수조건", "없음") not in ("없음", ""):
        s -= 15; why.append("특수물건(감점)")
    return s, why


def rate(r):
    try: return float(r["낙찰가율"])
    except: return None


def run(rows, label, T, topn=15):
    scored = [(score(r, T)[0], r, score(r, T)[1]) for r in rows]
    scored.sort(key=lambda x: -x[0])
    top = scored[:topn]
    print(f"\n{'='*92}\n■ {label}\n"
          f"   기준: 전용{T['전용평']}평 · 감정{T['감정가억']}억 · {T['층']}층 · "
          f"재건축{T['재건축']} · 소형{T['소형']} · {T['구']}\n{'='*92}")
    print(f"{'#':<3}{'점':<4}{'단지':<24}{'구':<5}{'전용':<6}{'감정':<6}{'낙찰율':<7}{'입찰':<5}{'매칭요인'}")
    for i, (s, r, why) in enumerate(top, 1):
        nm = (r['아파트명'] or '')[:11]
        print(f"{i:<3}{s:<4}{nm:<24}{r['구']:<5}{r['전용평']:<6}{r['감정가억']:<6}"
              f"{str(r['낙찰가율'])+'%':<7}{str(r['입찰자수'])+'명':<5}{','.join(why)}")
    rr = [rate(r) for _, r, _ in top if rate(r) is not None]
    if rr:
        print(f"\n  ▶ 상위 {len(top)}건 낙찰가율: 평균 {st.mean(rr):.1f}% · "
              f"중앙값 {st.median(rr):.1f}% · 범위 {min(rr):.0f}~{max(rr):.0f}%")
        print(f"  ▶ {label.split('(')[0]} 감정가 {T['감정가억']}억 적용 예상낙찰: "
              f"평균 {T['감정가억']*st.mean(rr)/100:.2f}억 · 중앙값 {T['감정가억']*st.median(rr)/100:.2f}억")
    return top, rr


def main():
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    print(f"총 {len(rows)}건 대상 유사도 분석")
    for label, T in TARGETS.items():
        run(rows, label, T)


if __name__ == "__main__":
    main()
