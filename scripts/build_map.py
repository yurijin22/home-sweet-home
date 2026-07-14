"""
워치리스트 41개 단지 → 인터랙티브 지도 (folium).
docs/index.html 로 출력 → GitHub Pages에서 공개.
"""
import json
import re
from pathlib import Path
import folium
from folium.plugins import MarkerCluster, Search

ROOT = Path('/home/user/home-sweet-home')

# 데이터 로딩
with open(ROOT / 'data/watchlist.md') as f:
    wl = f.read()
with open(ROOT / 'data/budget_all_seoul.json') as f:
    bud = json.load(f)
with open(ROOT / 'data/molit_all_seoul.json') as f:
    mol = json.load(f)
with open(ROOT / 'data/commute_times.json') as f:
    com = json.load(f)
with open(ROOT / 'data/archive/coords_all.json') as f:
    coords = json.load(f)
with open(ROOT / 'data/archive/candidates_v3_scored.json') as f:
    scored = {c['name']: c for c in json.load(f)}
with open(ROOT / 'data/bubble_diag.json') as f:
    bubble = {(r['name'], r['cno']): r for r in json.load(f)}

# 워치리스트 단지 파싱
complexes = []
# 풀 포맷 (### 단지명)
for m in re.finditer(r'^###\s+(.+?)\n.*?complex_no:\s*(\d+).*?호가:\s*([\d.]+)억(.+?)(?=^###|\Z|^##)', wl, re.S | re.M):
    name = m.group(1).strip()
    cno = m.group(2)
    price = float(m.group(3))
    body = m.group(4)
    memo_m = re.search(r'메모:\s*(.+)', body)
    memo = memo_m.group(1).strip() if memo_m else ''
    complexes.append({'name': name, 'cno': cno, 'price_eok': price, 'memo': memo, 'tier': '상세'})

# 한줄 포맷 (- **#N 단지명**)
for m in re.finditer(r'-\s+\*\*#(\d+)\s+(.+?)\*\*\s+\(cno\s+(\d+)\)[^\n]*?호가\s+([\d.]+)억', wl):
    rank = int(m.group(1))
    name = m.group(2).strip()
    cno = m.group(3)
    price = float(m.group(4))
    bare = re.sub(r'\([^)]+\)$', '', name).strip()
    complexes.append({'name': bare, 'cno': cno, 'price_eok': price, 'rank': rank, 'tier': '관망'})

print(f"파싱된 단지 수: {len(complexes)}")

# 통합 정보 빌드
features = []
missing_coords = []
for c in complexes:
    name = c['name']
    cno = c['cno']
    info = bud.get(name, {})
    mol_info = mol.get(name, {})
    com_info = com.get(name, {})
    sco = scored.get(name, {})
    bub = bubble.get((name, cno), {})
    coord = coords.get(name)
    if not coord:
        # 부분일치 fallback
        match = next((k for k in coords if name in k or k in name), None)
        coord = coords.get(match) if match else None
    if not coord:
        missing_coords.append(name)
        continue
    region = info.get('region', '?')
    household = info.get('household', sco.get('household'))
    year = sco.get('year') or mol_info.get('year')
    real_price = mol_info.get('price_median')
    real_area = mol_info.get('area_typical')
    w = com_info.get('w')
    g = com_info.get('g')
    score = sco.get('total')
    run_up = bub.get('run_up_pct')
    asking_gap = bub.get('asking_gap_pct')
    recent_n = bub.get('recent_n')

    # 거품 등급 (색상)
    if run_up is None:
        bubble_tier = 'unknown'
        color = 'gray'
    elif run_up >= 15:
        bubble_tier = 'high'
        color = 'red'
    elif run_up >= 5:
        bubble_tier = 'mid'
        color = 'orange'
    else:
        bubble_tier = 'low'
        color = 'green'

    # 통근 우수 (왕십리 OR 과천 30분 이하)
    star = (w and w <= 30) or (g and g <= 30)

    features.append({
        'name': name, 'cno': cno, 'lat': coord['lat'], 'lon': coord['lon'],
        'region': region, 'household': household, 'year': year,
        'price_eok': c['price_eok'], 'real_price': real_price, 'real_area': real_area,
        'w': w, 'g': g, 'score': score,
        'run_up': run_up, 'asking_gap': asking_gap, 'recent_n': recent_n,
        'tier': c['tier'], 'memo': c.get('memo', ''),
        'bubble_tier': bubble_tier, 'color': color, 'star': star,
        'rank': c.get('rank'),
    })

print(f"좌표 매칭: {len(features)}개")
if missing_coords:
    print(f"좌표 결측: {missing_coords}")

# 지도 생성 — 서울 중심
m = folium.Map(
    location=[37.5665, 126.9780],
    zoom_start=11,
    tiles='OpenStreetMap',
    control_scale=True,
)

# 양 직장 마커
folium.Marker(
    [37.5614, 127.0381], popup='<b>왕십리역</b> (신부 직장)',
    icon=folium.Icon(color='blue', icon='briefcase', prefix='fa'),
).add_to(m)
folium.Marker(
    [37.4279, 126.9876], popup='<b>정부과천청사역</b> (신랑 직장)',
    icon=folium.Icon(color='blue', icon='briefcase', prefix='fa'),
).add_to(m)

# 단지 그룹 (거품 등급별 레이어)
groups = {
    'high': folium.FeatureGroup(name='🔴 거품 강함 (+15% 이상)', show=True),
    'mid': folium.FeatureGroup(name='🟡 거품 보통 (+5~15%)', show=True),
    'low': folium.FeatureGroup(name='🟢 안정/하락 (+5% 이하)', show=True),
    'unknown': folium.FeatureGroup(name='⚫ 거품 데이터 없음', show=True),
}

for f in features:
    star = '⭐ ' if f['star'] else ''
    real_str = f"{f['real_price']/10000:.1f}억 ({f['real_area']:.0f}㎡, {f['recent_n'] or 0}건)" if f['real_price'] else '확인 필요'
    run_up_str = f"{f['run_up']:+.1f}%" if f['run_up'] is not None else "?"
    gap_str = f"{f['asking_gap']:+.1f}%" if f['asking_gap'] is not None else "?"
    score_str = f"{f['score']:.1f}" if f['score'] else "?"
    memo_html = f"<div style='color:#666;font-size:11px;margin-top:4px;'>{f['memo']}</div>" if f['memo'] else ''
    rank_str = f"#{f['rank']} · " if f.get('rank') else ''
    naver_url = f"https://new.land.naver.com/complexes/{f['cno']}"

    popup_html = f"""
    <div style='font-family:-apple-system,sans-serif;font-size:13px;width:280px;'>
      <div style='font-size:15px;font-weight:bold;margin-bottom:6px;'>
        {star}{f['name']}
      </div>
      <div style='color:#888;font-size:11px;margin-bottom:8px;'>
        {rank_str}{f['region']} · {f['household']}세대 · {f['year']}년 · 점수 {score_str}
      </div>
      <table style='width:100%;border-collapse:collapse;font-size:12px;'>
        <tr><td style='padding:2px 4px;color:#666;'>호가</td><td style='padding:2px 4px;text-align:right;font-weight:bold;'>{f['price_eok']:.1f}억</td></tr>
        <tr><td style='padding:2px 4px;color:#666;'>최근 실거래</td><td style='padding:2px 4px;text-align:right;'>{real_str}</td></tr>
        <tr><td style='padding:2px 4px;color:#666;'>6m 상승률</td><td style='padding:2px 4px;text-align:right;color:{"#d44" if (f["run_up"] or 0) >= 15 else "#222"};'>{run_up_str}</td></tr>
        <tr><td style='padding:2px 4px;color:#666;'>호가-실거래갭</td><td style='padding:2px 4px;text-align:right;'>{gap_str}</td></tr>
        <tr><td style='padding:2px 4px;color:#666;'>왕십리 / 과천</td><td style='padding:2px 4px;text-align:right;'>{f['w'] or '?'}분 / {f['g'] or '?'}분</td></tr>
      </table>
      {memo_html}
      <div style='margin-top:8px;'>
        <a href='{naver_url}' target='_blank' style='display:inline-block;padding:6px 12px;background:#03c75a;color:white;text-decoration:none;border-radius:4px;font-size:12px;'>네이버부동산에서 보기 →</a>
      </div>
    </div>
    """

    icon = folium.Icon(color=f['color'], icon='home', prefix='fa') if not f['star'] else folium.Icon(color=f['color'], icon='star', prefix='fa')
    folium.Marker(
        [f['lat'], f['lon']],
        popup=folium.Popup(popup_html, max_width=320),
        tooltip=f"{star}{f['name']} · {f['price_eok']:.1f}억",
        icon=icon,
    ).add_to(groups[f['bubble_tier']])

for g in groups.values():
    g.add_to(m)
folium.LayerControl(collapsed=False).add_to(m)

# 범례
legend_html = """
<div style='position:fixed;bottom:20px;left:20px;z-index:9999;background:white;padding:12px;border-radius:8px;
            box-shadow:0 2px 8px rgba(0,0,0,0.15);font-family:-apple-system,sans-serif;font-size:12px;'>
  <div style='font-weight:bold;margin-bottom:6px;'>워치리스트 41개 단지</div>
  <div style='margin:2px 0;'>🔴 거품 강함 (+15% 이상)</div>
  <div style='margin:2px 0;'>🟡 거품 보통 (+5~15%)</div>
  <div style='margin:2px 0;'>🟢 안정 (+5% 이하)</div>
  <div style='margin:2px 0;'>⚫ 데이터 없음</div>
  <div style='margin:6px 0 2px 0;border-top:1px solid #eee;padding-top:6px;'>⭐ 통근 우수 (왕십리/과천 30분 이하)</div>
  <div style='margin:2px 0;color:#888;font-size:11px;'>핀 클릭 → 단지 상세 + 네이버부동산 링크</div>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# 출력
out = ROOT / 'docs/index.html'
out.parent.mkdir(exist_ok=True)
m.save(str(out))
print(f"\n✓ 지도 생성: {out}")
print(f"  거품 강함: {sum(1 for f in features if f['bubble_tier']=='high')}개")
print(f"  거품 보통: {sum(1 for f in features if f['bubble_tier']=='mid')}개")
print(f"  안정/하락: {sum(1 for f in features if f['bubble_tier']=='low')}개")
print(f"  데이터없음: {sum(1 for f in features if f['bubble_tier']=='unknown')}개")
print(f"  통근 우수(⭐): {sum(1 for f in features if f['star'])}개")
