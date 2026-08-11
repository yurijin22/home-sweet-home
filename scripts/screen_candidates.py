import json,glob,statistics as st
from collections import defaultdict
from datetime import datetime,timedelta
SLUG={'mapo':'마포','seongdong':'성동','yangcheon':'양천','gwangjin':'광진','seodaemun':'서대문',
 'yeongdeungpo':'영등포','dongjak':'동작','seongbuk':'성북','dongdaemun':'동대문',
 'nowon':'노원','dobong':'도봉','geumcheon':'금천'}
com=json.load(open('data/commute_times.json',encoding='utf-8'))
yrs=json.load(open('data/years_all.json',encoding='utf-8'))
bud=json.load(open('data/budget_all_seoul.json',encoding='utf-8'))
AMBIG={'두산','벽산','한신','한진','현대','삼성','삼호','미성','우방','극동','청구','동아','쌍용',
       '삼익','건영','대우','우성','롯데','신동아','서원','미륭','장미','한마을','삼환','청백'}
def tier(nm,gu):
    b=bud.get(nm)
    if b and b.get('region','').startswith(gu): return 1,b.get('household')
    if nm in AMBIG or len(nm)<=3: return None,None      # 충돌 위험 이름 → 배제
    if nm in com and nm in yrs: return 2,yrs[nm].get('household')
    return None,None
key=defaultdict(list)
for s,gu in SLUG.items():
    for f in sorted(glob.glob(f'data/molit_trade/{s}_*.json')):
        for t in json.load(open(f,encoding='utf-8')).get('items',[]):
            if 55<=t['area_m2']<95 and t['deal_type']!='직거래':
                key[(gu,t['name'],t['district'],round(t['area_m2']/5)*5)].append(t)
K=1.134
def acq(P):
    b=1.0 if P<=6 else (P*2/3-3 if P<=9 else 3.0); return max(0,P*b*1.1/100-0.02)
def cost(P,o):return acq(P)+(P*0.002 if o else 0)+P*(0.004 if P<=9 else 0.005)*1.1+0.023+0.10
def need(P,o):return P+cost(P,o)-min(P*0.70,6.0)
def pmt(l,y=30,r=0.045):
    n=y*12;i=r/12;return l*1e8*i/(1-(1+i)**-n)/1e4
E=2.91; rows=[]
for (gu,nm,dist,ab),v in key.items():
    mx=max(x['deal_date'] for x in v)
    if mx<'2026-01-01': continue
    cut=(datetime.strptime(mx,'%Y-%m-%d')-timedelta(days=100)).strftime('%Y-%m-%d')
    r=[x for x in v if x['deal_date']>=cut]
    if len(r)<3: continue
    tr,hh=tier(nm,gu)
    if not tr or not hh or hh<400: continue
    c=com.get(nm)
    if not c or c['w']>45 or c['g']>78: continue
    byr=int(st.median([x['build_year'] for x in r]))
    if byr<1995: continue
    med=st.median([x['price_10k']/10000 for x in r])
    lo=[x['price_10k']/10000 for x in r if (x['floor'] or 0)<=4]
    lom=st.median(lo) if lo else None
    entry=min(med*K,(lom*K if lom else 99))
    if entry>9.0: continue
    o=ab>=85
    y1a=(datetime.strptime(cut,'%Y-%m-%d')-timedelta(days=365)).strftime('%Y-%m-%d')
    y1b=(datetime.strptime(mx,'%Y-%m-%d')-timedelta(days=365)).strftime('%Y-%m-%d')
    pv=[x['price_10k']/10000 for x in v if y1a<=x['deal_date']<=y1b]
    g1=(med/st.median(pv)-1)*100 if len(pv)>=3 else None
    nd=need(entry,o)
    rows.append(dict(t=tr,gu=gu,nm=nm,dist=dist,ab=ab,byr=byr,hh=hh,w=c['w'],g=c['g'],n=len(r),
        med=med,lo=lom,entry=entry,g1=g1,need=nd,buf=E-nd,pmt=pmt(min(entry*0.7,6.0))))
rows.sort(key=lambda x:-x['buf'])
hdr=f"{'T':<2}{'단지':<21}{'동':<9}{'구':<4}{'㎡':>4}{'준공':>5}{'세대':>6}{'왕십':>4}{'과천':>4}{'건':>3}{'중앙':>6}{'저층':>6}{'진입':>6}{'필요자기':>7}{'완충':>7}{'월납':>6}{'1년':>7}"
def show(f,title):
    sel=[r for r in rows if f(r)]
    print(f'\n{title}  ({len(sel)}건)'); print(hdr)
    for r in sel:
        lo=('%.2f'%r['lo']) if r['lo'] else '—'
        g1=('%+.1f%%'%r['g1']) if r['g1'] is not None else '—'
        print(f"{r['t']:<2}{r['nm'][:21]:<21}{r['dist'][:9]:<9}{r['gu']:<4}{r['ab']:>4}{r['byr']:>5}{r['hh']:>6}"
              f"{r['w']:>4}{r['g']:>4}{r['n']:>3}{r['med']:>6.2f}{lo:>6}{r['entry']:>6.2f}{r['need']:>7.2f}"
              f"{r['buf']:>+7.2f}{r['pmt']:>5.0f}만{g1:>7}")
show(lambda r:r['buf']>=0.30,'★ A그룹 — 완충 3,000만 이상 (목표 충족)')
show(lambda r:0.10<=r['buf']<0.30,'○ B그룹 — 완충 1,000~3,000만 (빡빡)')
show(lambda r:r['buf']<0.10,'△ C그룹 — 완충 1,000만 미만 (권장 안 함)')
print('\nT=1: budget_all_seoul region으로 구 검증 완료  |  T=2: 이름 고유성 기준(충돌위험 이름 배제), 통근·세대수 재확인 권장')
