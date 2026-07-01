#!/usr/bin/env python3
"""미미삼(2025타경12415)과 낙찰 사례 유사도 점수화."""
import csv, sys

# 우리 물건 (미미삼 19동 307호)
TARGET = dict(전용평=15.57, 대지평=14.56, 감정가억=6.96, 층=3, 재건축="Y", 소형="Y", 구="노원")

def score(r):
    s, why = 0, []
    try: p=float(r["전용평"])
    except: p=None
    if p is not None:
        d=abs(p-TARGET["전용평"])
        if d<=2: s+=30; why.append("평수매우유사")
        elif d<=5: s+=20; why.append("평수유사")
        elif d<=10: s+=8
    try: g=float(r["감정가억"])
    except: g=None
    if g is not None:
        d=abs(g-TARGET["감정가억"])
        if d<=1: s+=25; why.append("감정가유사")
        elif d<=2: s+=15; why.append("감정가근접")
        elif d<=3.5: s+=5
    if r.get("재건축","").upper()=="Y": s+=20; why.append("재건축")
    if r.get("소형여부","").upper()=="Y": s+=10; why.append("소형")
    if r.get("구")==TARGET["구"]: s+=15; why.append("노원")
    try:
        f=int(r["층"])
        if 3<=f<=8: s+=8; why.append("중층")
        elif f<=2: s-=5; why.append("저층(감점)")
    except: pass
    if r.get("특수조건","없음") not in ("없음",""): s-=15; why.append("특수물건(감점)")
    return s, why

def main():
    rows=list(csv.DictReader(open("data/auction_comps.csv")))
    scored=[]
    for r in rows:
        s,why=score(r)
        scored.append((s,r,why))
    scored.sort(key=lambda x:-x[0])
    print(f"총 {len(rows)}건 | 미미삼 유사도 순위\n")
    print(f"{'순위':<3}{'점수':<5}{'단지':<20}{'낙찰가율':<7}{'입찰자':<5}{'매칭요인'}")
    for i,(s,r,why) in enumerate(scored[:20],1):
        print(f"{i:<3}{s:<5}{r['아파트명'][:18]:<20}{r['낙찰가율']+'%':<7}{r['입찰자수']+'명':<5}{','.join(why)}")
    # 상위 유사군 낙찰가율 통계
    top=[float(r['낙찰가율']) for s,r,why in scored if s>=60]
    if top:
        import statistics as st
        print(f"\n=== 유사도 60점+ {len(top)}건 낙찰가율 ===")
        print(f"평균 {st.mean(top):.0f}% | 중앙값 {st.median(top):.0f}% | 범위 {min(top):.0f}~{max(top):.0f}%")
        print(f"→ 미미삼 감정가 6.96억 적용: {6.96*st.mean(top)/100:.2f}억 (평균 기준)")

if __name__=="__main__": main()
