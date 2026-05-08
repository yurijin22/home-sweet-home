"""
신혼집 후보 지도 생성기
- 통근 등시선: 왕십리·과천 기준 30/40/50분 권역
- 지하철 1~9호선 + 개통예정
- 단지 마커 (클릭 시 상세 팝업 + 네이버 길찾기)
"""
import json, re, os

def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def norm_name(s):
    return re.sub(r'\(\d+\)', '', s).strip()

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')

coords       = load_json(os.path.join(DATA, 'coords_all.json'))
budget_59    = load_json(os.path.join(DATA, 'budget_all_seoul.json'))
budget_84    = load_json(os.path.join(DATA, 'listings_84sqm.json'))
molit        = load_json(os.path.join(DATA, 'budget_molit_6m.json'))
subway       = load_json(os.path.join(DATA, 'subway_lines.json'))
amenities    = load_json(os.path.join(DATA, 'amenities_25.json'))
scored_list  = load_json(os.path.join(DATA, 'candidates_v3_scored.json'))
enriched_list= load_json(os.path.join(DATA, 'candidates_enriched.json'))
preds_list   = load_json(os.path.join(DATA, 'predictions_2027.json'))

# commute_times (없으면 빈 dict)
commute_path = os.path.join(DATA, 'commute_times.json')
commute = load_json(commute_path) if os.path.exists(commute_path) else {}

# years_all (없으면 빈 dict) — 275개 실매물 단지 입주연도
years_path = os.path.join(DATA, 'years_all.json')
years_all = load_json(years_path) if os.path.exists(years_path) else {}

# 인덱스
coords_norm   = {norm_name(k): v for k, v in coords.items()}
scored_idx    = {s['name']: s  for s in scored_list}
enriched_idx  = {e['name']: e  for e in enriched_list}
preds_idx     = {p['name']: p  for p in preds_list}


def get_coord(name):
    if name in coords: return coords[name]
    return coords_norm.get(norm_name(name))

def fmt_price(p):
    if p >= 10000:
        eok  = p // 10000
        chun = (p % 10000) // 1000
        return f"{eok}억 {chun}천" if chun else f"{eok}억"
    return f"{p}만"

def build_tags(name):
    """초품아·공원·호재·재건축 태그 리스트 반환"""
    tags = []
    am = amenities.get(name, {})

    # 초품아
    pri = am.get('school', {}).get('pri', [])
    if pri and pri[0]['distance_m'] < 300:
        tags.append('🏫 초품아')
    elif pri and pri[0]['distance_m'] < 600:
        tags.append(f"🏫 초교 {pri[0]['distance_m']}m")

    # 공원
    parks = am.get('park', [])
    if parks and parks[0]['distance_m'] < 500:
        tags.append(f"🌳 공원 {parks[0]['distance_m']}m")

    # 마트
    marts = am.get('mart', [])
    if marts and marts[0]['distance_m'] < 500:
        tags.append(f"🛒 마트 {marts[0]['distance_m']}m")

    # 악재
    noise = am.get('railway', []) or am.get('highway', [])
    if noise and noise[0]['distance_m'] < 300:
        tags.append('🚨 소음주의')
    cem = am.get('cemetery', [])
    if cem and cem[0]['distance_m'] < 500:
        tags.append('⚠️ 묘지인근')

    # 호재/재건축
    p = preds_idx.get(name, {})
    bd = p.get('breakdown', {})
    if bd.get('rebuild', 0) >= 3:
        s = scored_idx.get(name, {})
        far = s.get('far', 0)
        tags.append(f"🔨 재건축({far}%)")
    hojae = bd.get('hojae_level', '')
    if hojae and '★★★★' in hojae:
        tags.append('📈 GTX/신노선 호재')

    return tags


# ── 마커 통합 ──────────────────────────────────────────
markers = {}

def add_marker(name, price_raw, household, region, source):
    c = get_coord(name)
    if not c: return
    lat = c.get('lat') or c.get('latitude')
    lon = c.get('lon') or c.get('longitude') or c.get('lng')
    if not lat or not lon: return

    s  = scored_idx.get(name, {})
    e  = enriched_idx.get(name, {})
    ct = commute.get(name, {})
    tags = build_tags(name)

    y = years_all.get(name, {})
    cno = (s.get('complex_no') or e.get('complex_no') or
           y.get('complex_no') or budget_59.get(name, {}).get('complex_no') or '')
    markers[name] = {
        'name': name,
        'lat': lat, 'lon': lon,
        'price': fmt_price(price_raw),
        'price_raw': price_raw,
        'household': household or s.get('household', 0) or y.get('household') or 0,
        'year': s.get('year') or e.get('year') or y.get('year') or 0,
        'far': s.get('far', 0),
        'commute_w': ct.get('w'),   # 왕십리 분
        'commute_g': ct.get('g'),   # 과천 분
        'tags': tags,
        'pred': preds_idx.get(name, {}).get('pred_change', 0),
        'region': region,
        'source': source,
        'complex_no': str(cno) if cno else '',
    }

for name, info in budget_59.items():
    add_marker(name, info['min_price'], info.get('household', 0), info.get('region',''), '실매물')

for name, info in budget_84.items():
    if name in markers:
        if info['min_price'] < markers[name]['price_raw']:
            markers[name]['price_raw'] = info['min_price']
            markers[name]['price'] = fmt_price(info['min_price'])
    else:
        add_marker(name, info['min_price'], info.get('household',0), info.get('region',''), '실매물')

for name, info in molit.items():
    if name not in markers:
        add_marker(name, info['median_price'], 0, info.get('gu',''), '실거래가')

apt_list = list(markers.values())
n_listing = sum(1 for m in apt_list if m['source'] == '실매물')
n_molit   = sum(1 for m in apt_list if m['source'] == '실거래가')
n_commute = sum(1 for m in apt_list if m.get('commute_w'))
print(f"마커: {len(apt_list)}개 (실매물 {n_listing}, 실거래가 {n_molit}, 통근시간 {n_commute}개)")

# ── HTML ────────────────────────────────────────────────
html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>신혼집 후보 지도</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif; height:100vh; display:flex; flex-direction:column; }}

#hd {{
  padding:8px 14px; background:#fff; border-bottom:3px solid #1565C0;
  display:flex; align-items:center; gap:10px; flex-wrap:wrap;
  box-shadow:0 2px 6px rgba(0,0,0,.1); position:relative; z-index:1000;
}}
#hd h1 {{ font-size:14px; font-weight:700; color:#1565C0; white-space:nowrap; }}
.sep {{ color:#ddd; }}
.leg {{ display:flex; gap:10px; align-items:center; font-size:11px; color:#555; }}
.li {{ display:flex; align-items:center; gap:3px; }}
.dot {{ width:9px; height:9px; border-radius:50%; border:1px solid rgba(0,0,0,.2); }}
.ctrls {{ display:flex; gap:5px; margin-left:auto; align-items:center; flex-wrap:wrap; }}
.btn {{
  padding:4px 11px; border-radius:20px; border:1.5px solid #bbb;
  background:#fff; color:#555; cursor:pointer; font-size:11px; font-weight:600;
  transition:all .15s;
}}
.btn.on {{ color:#fff; border-color:transparent; }}
#b-sub.on {{ background:#1565C0; }}
#b-gtx.on {{ background:#E65100; }}
#b-apt.on {{ background:#6A1B9A; }}
#b-mo.on  {{ background:#795548; }}
#b-iso.on {{ background:#2E7D32; }}

#map {{ flex:1; }}
#bar {{ padding:4px 14px; background:#F5F5F5; font-size:11px; color:#888; border-top:1px solid #E0E0E0; }}

/* ── 팝업 ── */
.pu {{ font-family:'Apple SD Gothic Neo','Malgun Gothic',sans-serif; min-width:220px; }}
.pu-name  {{ font-size:15px; font-weight:700; color:#1A237E; margin-bottom:6px; }}
.pu-price {{ font-size:18px; font-weight:800; color:#B71C1C; margin-bottom:4px; }}
.pu-commute {{
  display:flex; gap:6px; margin:6px 0;
}}
.pu-ct {{
  flex:1; background:#E3F2FD; border-radius:6px; padding:5px 8px;
  text-align:center; font-size:12px;
}}
.pu-ct .min {{ font-size:16px; font-weight:700; color:#0D47A1; }}
.pu-ct .lbl {{ font-size:10px; color:#666; margin-top:1px; }}
.pu-ct.no-data {{ background:#F5F5F5; }}
.pu-ct.no-data .min {{ font-size:12px; color:#aaa; }}
.pu-row {{ font-size:12px; color:#555; margin:2px 0; }}
.pu-row b {{ color:#333; }}
.pu-tags {{ margin:6px 0; display:flex; flex-wrap:wrap; gap:4px; }}
.pu-tag {{ padding:2px 7px; border-radius:12px; font-size:11px; background:#EDE7F6; color:#4527A0; }}
.pu-tag.warn {{ background:#FFF3E0; color:#E65100; }}
.pu-links {{ margin-top:8px; display:flex; gap:6px; }}
.pu-link {{
  flex:1; padding:7px 0; border-radius:7px; font-size:12px; font-weight:600;
  text-align:center; text-decoration:none;
}}
.pu-lw {{ background:#1976D2; color:#fff; }}
.pu-lg {{ background:#388E3C; color:#fff; }}

/* 등시선 범례 */
.iso-leg {{
  position:absolute; bottom:30px; left:10px; z-index:900;
  background:rgba(255,255,255,.93); border-radius:8px; padding:10px 14px;
  font-size:11px; box-shadow:0 2px 8px rgba(0,0,0,.15); display:none; line-height:1.8;
}}
.iso-leg.show {{ display:block; }}
.iso-leg b {{ font-size:12px; display:block; margin-bottom:4px; }}
.ir {{ display:flex; align-items:center; gap:6px; }}
.il {{ width:22px; height:3px; border-radius:2px; display:inline-block; }}
</style>
</head>
<body>
<div id="hd">
  <h1>🏠 신혼집 후보 | 11억 이하</h1>
  <span class="sep">|</span>
  <div class="leg">
    <div class="li"><div class="dot" style="background:#6A1B9A"></div>실매물 ({n_listing})</div>
    <div class="li"><div class="dot" style="background:#795548"></div>실거래가 ({n_molit})</div>
  </div>
  <div class="ctrls">
    <button class="btn on" id="b-sub" onclick="tog('sub')">지하철</button>
    <button class="btn on" id="b-gtx" onclick="tog('gtx')">개통예정</button>
    <button class="btn on" id="b-apt" onclick="tog('apt')">실매물</button>
    <button class="btn on" id="b-mo"  onclick="tog('mo')">실거래가</button>
    <button class="btn on" id="b-iso" onclick="tog('iso')">통근권역</button>
  </div>
</div>

<div id="map">
  <div class="iso-leg" id="iso-leg">
    <b>통근 등시선 (근사치)</b>
    <div class="ir"><span class="il" style="background:#1B5E20"></span>왕십리 30분</div>
    <div class="ir"><span class="il" style="background:#388E3C;opacity:.7"></span>왕십리 40분</div>
    <div class="ir"><span class="il" style="background:#81C784;opacity:.7"></span>왕십리 50분</div>
    <div class="ir"><span class="il" style="background:#0D47A1"></span>과천 30분</div>
    <div class="ir"><span class="il" style="background:#1976D2;opacity:.7"></span>과천 40분</div>
    <div class="ir"><span class="il" style="background:#64B5F6;opacity:.7"></span>과천 50분</div>
  </div>
</div>

<div id="bar">총 <b>{len(apt_list)}</b>개 단지 | 마커 클릭 → 단지 상세 + 길찾기</div>

<script>
const subwayData = {json.dumps(subway, ensure_ascii=False)};
const aptData    = {json.dumps(apt_list, ensure_ascii=False)};

const map = L.map('map', {{ center:[37.535,127.005], zoom:12, preferCanvas:false }});

L.tileLayer('https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution:'&copy; OpenStreetMap &copy; CARTO', subdomains:'abcd', maxZoom:19
}}).addTo(map);

// 등시선
const WANGSIMNI = [37.5614, 127.0364];
const GWACHEON  = [37.4297, 126.9894];
const isoCircles = [];
[
  [WANGSIMNI, '#1B5E20', 4500, null],
  [WANGSIMNI, '#388E3C', 7200, '7,4'],
  [WANGSIMNI, '#81C784', 9800, '3,5'],
  [GWACHEON,  '#0D47A1', 4500, null],
  [GWACHEON,  '#1976D2', 7200, '7,4'],
  [GWACHEON,  '#64B5F6', 9800, '3,5'],
].forEach(([center, color, radius, dash]) => {{
  isoCircles.push(L.circle(center, {{
    radius, color, fillColor: color, fillOpacity: 0.05,
    weight: 2, opacity: 0.6, dashArray: dash
  }}));
}});

// 지하철
const lSub = L.layerGroup();
const lGtx = L.layerGroup();
subwayData.current.forEach(line => {{
  L.polyline(line.stations.map(s=>[s.lat,s.lon]),
    {{color:line.color, weight:3.5, opacity:0.75}}).addTo(lSub);
  line.stations.forEach(s => {{
    L.circleMarker([s.lat,s.lon], {{
      radius:3.5, color:'#fff', fillColor:line.color, fillOpacity:1, weight:1.5
    }}).bindTooltip(`<b style="color:${{line.color}}">${{line.name}}</b> ${{s.name}}`,
      {{permanent:false, direction:'top'}}).addTo(lSub);
  }});
}});
subwayData.planned.forEach(line => {{
  L.polyline(line.stations.map(s=>[s.lat,s.lon]),
    {{color:line.color, weight:3, opacity:0.9, dashArray:'8,5'}}).addTo(lGtx);
  line.stations.forEach(s => {{
    L.circleMarker([s.lat,s.lon], {{
      radius:4, color:line.color, fillColor:'#fff', fillOpacity:1, weight:2
    }}).bindTooltip(`<b style="color:${{line.color}}">${{line.name}}</b> ${{s.name}}`,
      {{permanent:false, direction:'top'}}).addTo(lGtx);
  }});
}});

// 아파트 마커
const lApt = L.markerClusterGroup({{ maxClusterRadius:35, disableClusteringAtZoom:14 }});
const lMo  = L.markerClusterGroup({{ maxClusterRadius:35, disableClusteringAtZoom:14 }});

aptData.forEach(apt => {{
  if (!apt.lat || !apt.lon) return;
  const isListing = apt.source === '실매물';
  const color = isListing ? '#6A1B9A' : '#795548';

  // 팝업 빌드
  const encName = encodeURIComponent(apt.name);
  const fromStr = `${{apt.lon.toFixed(6)}},${{apt.lat.toFixed(6)}},${{encName}}`;
  const naverW = `https://map.naver.com/v5/directions/${{fromStr}}/127.0364,37.5614,왕십리역/-/transit`;
  const naverG = `https://map.naver.com/v5/directions/${{fromStr}}/126.9894,37.4297,정부과천청사역/-/transit`;
  const naverLand = apt.complex_no
    ? `https://new.land.naver.com/complexes/${{apt.complex_no}}?a=APT`
    : `https://new.land.naver.com/complexes?ms=${{apt.lat.toFixed(4)}},${{apt.lon.toFixed(4)}},17&a=APT`;

  const wHtml = apt.commute_w
    ? `<div class="pu-ct"><div class="min">${{apt.commute_w}}분</div><div class="lbl">→ 왕십리</div></div>`
    : `<div class="pu-ct no-data"><div class="min">?</div><div class="lbl">→ 왕십리</div></div>`;
  const gHtml = apt.commute_g
    ? `<div class="pu-ct"><div class="min">${{apt.commute_g}}분</div><div class="lbl">→ 과천</div></div>`
    : `<div class="pu-ct no-data"><div class="min">?</div><div class="lbl">→ 과천</div></div>`;

  const tagsHtml = apt.tags.map(t => {{
    const isWarn = t.includes('🚨') || t.includes('⚠️');
    return `<span class="pu-tag${{isWarn ? ' warn' : ''}}">${{t}}</span>`;
  }}).join('');

  const yearStr  = apt.year  ? `${{apt.year}}년 입주` : '';
  const hhStr    = apt.household > 0 ? `${{apt.household.toLocaleString()}}세대` : '';
  const predStr  = apt.pred  ? `1년 후 +${{apt.pred}}% 예상` : '';
  const srcBadge = apt.source === '실매물'
    ? `<span style="font-size:10px;background:#EDE7F6;color:#4527A0;padding:1px 6px;border-radius:10px">실매물</span>`
    : `<span style="font-size:10px;background:#EFEBE9;color:#4E342E;padding:1px 6px;border-radius:10px">실거래가</span>`;

  const popup = `<div class="pu">
    <div class="pu-name">${{apt.name}} ${{srcBadge}}</div>
    <div class="pu-price">${{apt.price}}</div>
    <div class="pu-commute">${{wHtml}}${{gHtml}}</div>
    ${{yearStr || hhStr ? `<div class="pu-row">${{[yearStr,hhStr].filter(Boolean).join(' &nbsp;·&nbsp; ')}}</div>` : ''}}
    ${{predStr ? `<div class="pu-row" style="color:#2E7D32;font-weight:600">${{predStr}}</div>` : ''}}
    ${{tagsHtml ? `<div class="pu-tags">${{tagsHtml}}</div>` : ''}}
    <div class="pu-links">
      <a class="pu-link pu-lw" href="${{naverW}}" target="_blank">길찾기 → 왕십리</a>
      <a class="pu-link pu-lg" href="${{naverG}}" target="_blank">길찾기 → 과천</a>
    </div>
    <div style="margin-top:6px;text-align:center">
      <a href="${{naverLand}}" target="_blank" style="font-size:11px;color:#1565C0;text-decoration:none">📋 네이버 부동산 매물 보기</a>
    </div>
  </div>`;

  const m = L.circleMarker([apt.lat, apt.lon], {{
    radius: 7, color:'#fff', fillColor: color, fillOpacity: 0.9, weight: 1.5
  }}).bindPopup(popup, {{maxWidth:280}});

  (isListing ? lApt : lMo).addLayer(m);
}});

// 레이어 초기화
const lIso = L.layerGroup(isoCircles);
[lSub, lGtx, lApt, lMo, lIso].forEach(l => l.addTo(map));
document.getElementById('iso-leg').classList.add('show');

const layerMap = {{ sub:lSub, gtx:lGtx, apt:lApt, mo:lMo, iso:lIso }};
function tog(name) {{
  const btn = document.getElementById('b-' + name);
  if (map.hasLayer(layerMap[name])) {{
    map.removeLayer(layerMap[name]); btn.classList.remove('on');
    if (name==='iso') document.getElementById('iso-leg').classList.remove('show');
  }} else {{
    layerMap[name].addTo(map); btn.classList.add('on');
    if (name==='iso') document.getElementById('iso-leg').classList.add('show');
  }}
}}
</script>
</body>
</html>"""

with open(os.path.join(BASE, 'map_final.html'), 'w', encoding='utf-8') as f:
    f.write(html)
print(f"저장 완료: map_final.html")
