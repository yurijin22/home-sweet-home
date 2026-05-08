"""
Top 8 단지별 인근 학교 수집 (OpenStreetMap Overpass API)
- 위경도 기반 반경 1km 내 학교 (초/중/고)
- 학교알리미 학업성취도는 자동화 어려워서 단지별 학교 목록만 제공
"""

import json
import ssl
import urllib.request
import urllib.parse

# macOS Python SSL cert 우회 (Overpass는 공개 데이터)
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


TOP_8_NAMES = [
    "성현동아", "두산", "동서울한양", "백련산힐스테이트1차",
    "창동주공3단지", "주공8단지", "수유벽산1차", "동아한신",
]


def query_overpass(lat, lon, radius=1000):
    """반경 radius m 내 학교 검색"""
    query = f"""
    [out:json][timeout:25];
    (
      node["amenity"~"school|kindergarten"](around:{radius},{lat},{lon});
      way["amenity"~"school|kindergarten"](around:{radius},{lat},{lon});
    );
    out center tags;
    """
    url = "https://overpass-api.de/api/interpreter"
    data = urllib.parse.urlencode({'data': query}).encode('utf-8')
    req = urllib.request.Request(url, data=data,
                                 headers={'User-Agent': 'home-sweet-home/1.0'})
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CTX) as resp:
        return json.loads(resp.read().decode('utf-8'))


def extract_schools(osm_data, center_lat, center_lon):
    """학교만 추출 + 거리 계산"""
    import math
    schools = []
    for elem in osm_data.get('elements', []):
        tags = elem.get('tags', {})
        amenity = tags.get('amenity')
        name = tags.get('name') or tags.get('name:ko') or '?'

        if elem['type'] == 'node':
            lat, lon = elem['lat'], elem['lon']
        else:
            center = elem.get('center', {})
            lat, lon = center.get('lat'), center.get('lon')

        if not lat:
            continue

        # 단순 거리 계산 (Haversine 약식)
        dlat = (lat - center_lat) * 111000  # m
        dlon = (lon - center_lon) * 111000 * math.cos(math.radians(center_lat))
        dist = math.sqrt(dlat**2 + dlon**2)

        # 학교 종류 추정
        kind = ''
        if '초등' in name or 'elementary' in name.lower(): kind = '초'
        elif '중학' in name or 'middle' in name.lower(): kind = '중'
        elif '고등' in name or 'high' in name.lower(): kind = '고'
        elif amenity == 'kindergarten' or '유치' in name or '어린이집' in name: kind = '유'
        elif amenity == 'school': kind = '학'

        schools.append({
            'name': name, 'kind': kind, 'amenity': amenity,
            'distance_m': round(dist),
        })
    schools.sort(key=lambda s: s['distance_m'])
    return schools


def main():
    with open('../data/candidates_enriched.json') as f:
        enriched = json.load(f)
    by_name = {c['name']: c for c in enriched}

    results = {}
    for name in TOP_8_NAMES:
        c = by_name.get(name)
        if not c:
            print(f"[{name}] enriched에 없음")
            continue
        lat, lon = c.get('lat'), c.get('lon')
        if not (lat and lon):
            print(f"[{name}] 좌표 없음")
            continue

        print(f"\n=== {name} ({lat:.4f}, {lon:.4f}) ===")
        try:
            data = query_overpass(lat, lon, radius=1000)
        except Exception as e:
            print(f"  Overpass 실패: {e}")
            continue
        schools = extract_schools(data, lat, lon)

        # 초·중·고만 필터
        primary = [s for s in schools if s['kind'] == '초'][:3]
        middle = [s for s in schools if s['kind'] == '중'][:3]
        high = [s for s in schools if s['kind'] == '고'][:3]
        other = [s for s in schools if s['kind'] in ('학', '')][:3]

        for label, lst in [('초', primary), ('중', middle), ('고', high), ('기타학교', other)]:
            for s in lst:
                print(f"  [{label}] {s['name']:30s} {s['distance_m']:>4}m")

        results[name] = {
            'primary': primary, 'middle': middle, 'high': high, 'other': other,
        }

    with open('../data/schools_top8.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n저장: ../data/schools_top8.json")


if __name__ == '__main__':
    main()
