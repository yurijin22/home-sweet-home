"""
25개 단지 인근 시설 OSM 통합 수집
- 지하철역 (subway/station)
- 학교 (초/중/고)
- 공원 (park, 녹지)
- 대형마트 (supermarket, mall)
- 병원 (hospital)
- 악재 (cemetery, power tower, military)
- 인근 도로/철도 (소음원)
"""

import json, ssl, time, urllib.request, urllib.parse, math

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

MIRRORS = [
    "https://overpass.openstreetmap.fr/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def query_osm(lat, lon, radius=1500):
    """반경 1.5km 내 모든 관심 시설"""
    q = f"""
    [out:json][timeout:40];
    (
      // 지하철역
      node["railway"="subway_entrance"](around:{radius},{lat},{lon});
      node["station"="subway"](around:{radius},{lat},{lon});
      node["public_transport"="station"]["subway"="yes"](around:{radius},{lat},{lon});
      node["railway"="station"](around:{radius},{lat},{lon});
      // 학교
      node["amenity"="school"](around:{radius},{lat},{lon});
      way["amenity"="school"](around:{radius},{lat},{lon});
      // 공원/녹지
      node["leisure"~"park|garden"](around:{radius},{lat},{lon});
      way["leisure"~"park|garden"](around:{radius},{lat},{lon});
      // 마트
      node["shop"~"supermarket|mall|department_store"](around:{radius},{lat},{lon});
      way["shop"~"supermarket|mall|department_store"](around:{radius},{lat},{lon});
      // 병원
      node["amenity"~"hospital|clinic"](around:{radius},{lat},{lon});
      way["amenity"~"hospital|clinic"](around:{radius},{lat},{lon});
      // 악재
      node["landuse"="cemetery"](around:{radius},{lat},{lon});
      way["landuse"="cemetery"](around:{radius},{lat},{lon});
      node["power"="tower"](around:{radius},{lat},{lon});
      way["military"](around:{radius},{lat},{lon});
      // 도로 (소음원)
      way["highway"~"motorway|trunk|primary|secondary"](around:{radius},{lat},{lon});
      // 철도 (소음원)
      way["railway"~"rail|light_rail"](around:{radius},{lat},{lon});
    );
    out center tags;
    """
    data = urllib.parse.urlencode({'data': q}).encode('utf-8')
    last_err = None
    for url in MIRRORS:
        try:
            req = urllib.request.Request(url, data=data,
                                         headers={'User-Agent': 'home-sweet-home/1.0'})
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise last_err


def categorize(elements, clat, clon):
    """OSM elements → 카테고리별 + 거리"""
    cats = {
        'subway': [],   # 지하철역
        'school': {'pri': [], 'mid': [], 'high': []},  # 학교
        'park': [],
        'mart': [],
        'hospital': [],
        'cemetery': [],
        'power': [],
        'highway': [],  # 대로 (소음)
        'railway': [],
    }
    seen = set()  # name+coords로 중복 제거

    for e in elements:
        tags = e.get('tags', {})
        name = tags.get('name') or tags.get('name:ko') or '?'
        lat = e.get('lat') or e.get('center', {}).get('lat')
        lon = e.get('lon') or e.get('center', {}).get('lon')
        if not lat: continue
        key = (name, round(lat, 5), round(lon, 5))
        if key in seen: continue
        seen.add(key)
        d = haversine_m(clat, clon, lat, lon)

        # 분류
        if tags.get('railway') == 'subway_entrance' or tags.get('station') == 'subway' or \
           (tags.get('public_transport') == 'station' and tags.get('subway') == 'yes'):
            cats['subway'].append({'name': name, 'distance_m': round(d), 'lines': tags.get('subway:lines') or tags.get('line') or ''})
        elif tags.get('railway') == 'station':
            cats['subway'].append({'name': name, 'distance_m': round(d), 'lines': tags.get('line') or 'rail'})
        elif tags.get('amenity') == 'school':
            kind = 'pri' if '초등' in name else ('mid' if '중학' in name else ('high' if '고등' in name else 'mid'))
            cats['school'][kind].append({'name': name, 'distance_m': round(d)})
        elif tags.get('leisure') in ('park', 'garden'):
            area = tags.get('area') or ''
            cats['park'].append({'name': name, 'distance_m': round(d)})
        elif tags.get('shop') in ('supermarket', 'mall', 'department_store'):
            cats['mart'].append({'name': name, 'distance_m': round(d), 'type': tags.get('shop')})
        elif tags.get('amenity') in ('hospital', 'clinic'):
            cats['hospital'].append({'name': name, 'distance_m': round(d), 'type': tags.get('amenity')})
        elif tags.get('landuse') == 'cemetery':
            cats['cemetery'].append({'name': name, 'distance_m': round(d)})
        elif tags.get('power') == 'tower':
            cats['power'].append({'name': name, 'distance_m': round(d)})
        elif tags.get('highway') in ('motorway', 'trunk', 'primary', 'secondary'):
            cats['highway'].append({'name': name, 'distance_m': round(d), 'type': tags.get('highway')})
        elif tags.get('railway') in ('rail', 'light_rail'):
            cats['railway'].append({'name': name, 'distance_m': round(d)})

    # 정렬 + 상위 N개
    cats['subway'].sort(key=lambda x: x['distance_m'])
    cats['subway'] = cats['subway'][:5]
    for k in ['pri', 'mid', 'high']:
        cats['school'][k].sort(key=lambda x: x['distance_m'])
        cats['school'][k] = cats['school'][k][:3]
    for k in ['park', 'mart', 'hospital', 'cemetery', 'power']:
        cats[k].sort(key=lambda x: x['distance_m'])
        cats[k] = cats[k][:5]
    cats['highway'].sort(key=lambda x: x['distance_m'])
    cats['highway'] = cats['highway'][:3]
    cats['railway'].sort(key=lambda x: x['distance_m'])
    cats['railway'] = cats['railway'][:2]

    return cats


def main():
    with open('../data/candidates_enriched.json') as f:
        cands = json.load(f)

    out = {}
    for i, c in enumerate(cands, 1):
        name = c['name']
        lat, lon = c.get('lat'), c.get('lon')
        if not (lat and lon):
            print(f"[{i:>2}/25] {name} 좌표 없음")
            continue
        print(f"[{i:>2}/25] {name} ({lat:.4f},{lon:.4f})", flush=True)
        try:
            osm = query_osm(lat, lon, radius=1500)
            cats = categorize(osm.get('elements', []), lat, lon)
            out[name] = cats

            # 요약
            sub = cats['subway'][0] if cats['subway'] else None
            pri = cats['school']['pri'][0] if cats['school']['pri'] else None
            print(f"      지하철 {sub['name'] if sub else '-'} {sub['distance_m'] if sub else '-'}m / 초등 {pri['name'] if pri else '-'} {pri['distance_m'] if pri else '-'}m / 공원 {len(cats['park'])} / 마트 {len(cats['mart'])} / 병원 {len(cats['hospital'])} / 악재(묘지/송전) {len(cats['cemetery'])+len(cats['power'])}")
        except Exception as e:
            print(f"  실패: {type(e).__name__}: {e}")
            time.sleep(5)
        time.sleep(2)

    with open('../data/amenities_25.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n저장: ../data/amenities_25.json ({len(out)}개)")


if __name__ == '__main__':
    main()
