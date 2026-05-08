"""
국토교통부 아파트 매매 실거래가 — 서울 25개 구 전수 수집
저장: data/molit_all_seoul.json  {단지명: {gu, year, area, price_median, price_min, trade_count}}
"""
import urllib.request
import urllib.parse
import json
import os
import time
from collections import defaultdict

# .env 파일 로드
env_path = os.path.join(os.path.dirname(__file__), "../.env")
if os.path.exists(env_path):
    for line in open(env_path):
        k, _, v = line.strip().partition("=")
        if k and v:
            os.environ.setdefault(k, v)

API_KEY = os.environ.get("MOLIT_API_KEY", "")
BASE_URL = "http://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

# 서울 25개 구 법정동 코드
SEOUL_GU = {
    "강남구": "11680", "강동구": "11740", "강북구": "11305", "강서구": "11500",
    "관악구": "11620", "광진구": "11215", "구로구": "11530", "금천구": "11545",
    "노원구": "11350", "도봉구": "11320", "동대문구": "11230", "동작구": "11590",
    "마포구": "11440", "서대문구": "11410", "서초구": "11650", "성동구": "11200",
    "성북구": "11290", "송파구": "11710", "양천구": "11470", "영등포구": "11560",
    "용산구": "11170", "은평구": "11380", "종로구": "11110", "중구": "11140",
    "중랑구": "11260",
}

# 최근 6개월
MONTHS = ["202411", "202412", "202501", "202502", "202503", "202504"]

AREA_MIN = 54
AREA_MAX = 84
PRICE_MIN = 70000  # 7억 (만원)
PRICE_MAX = 110000  # 11억


def fetch(gu_code, ym):
    params = urllib.parse.urlencode({
        "serviceKey": API_KEY,
        "LAWD_CD": gu_code,
        "DEAL_YMD": ym,
        "numOfRows": 1000,
        "pageNo": 1,
        "_type": "json",
    })
    url = f"{BASE_URL}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print(f"  오류: {e}")
        return None


def main():
    results = defaultdict(lambda: {"prices": [], "gu": "", "areas": []})

    total = len(SEOUL_GU) * len(MONTHS)
    done = 0

    for gu_name, gu_code in SEOUL_GU.items():
        for ym in MONTHS:
            done += 1
            print(f"[{done}/{total}] {gu_name} {ym}", flush=True)

            data = fetch(gu_code, ym)
            if not data:
                continue

            try:
                items = data["response"]["body"]["items"]["item"]
                if isinstance(items, dict):
                    items = [items]
            except (KeyError, TypeError):
                continue

            for item in items:
                try:
                    area = float(str(item.get("excluUseAr", 0) or 0))
                    if not (AREA_MIN <= area <= AREA_MAX):
                        continue

                    price_str = str(item.get("dealAmount", "")).replace(",", "").strip()
                    if not price_str:
                        continue
                    price = int(price_str)
                    if not (PRICE_MIN <= price <= PRICE_MAX):
                        continue

                    name = str(item.get("aptNm", "")).strip()
                    year = str(item.get("buildYear", "")).strip()
                    if not name:
                        continue

                    results[name]["prices"].append(price)
                    results[name]["gu"] = gu_name
                    results[name]["year"] = year
                    results[name]["areas"].append(area)
                except:
                    continue

            time.sleep(0.1)

    # 정리
    out = {}
    for name, d in results.items():
        prices = sorted(d["prices"])
        n = len(prices)
        median = prices[n // 2]
        out[name] = {
            "gu": d["gu"],
            "year": d.get("year", ""),
            "price_median": median,
            "price_min": prices[0],
            "price_max": prices[-1],
            "trade_count": n,
            "area_typical": round(sum(d["areas"]) / len(d["areas"]), 1),
        }

    out_path = "../data/molit_all_seoul.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(out)}개 단지")
    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
