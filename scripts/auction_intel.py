"""
신건 투자 추천 + 예상 낙찰가 예측 (하네스 코어)
입력: data/auction_raw_{날짜}.json (신건) + 보조데이터(molit 시세·통근·세대수) + data/auction_k.json
출력:
  - 표준출력: 추천 다이제스트 (Markdown, 이슈 본문용)
  - data/auction_predictions.json: {case_no: {예측정보}} 누적 (낙찰결과와 대조용)

예상낙찰 = 감정가 × k   (k = data/auction_k.json, 기본 0.92 = comps 356건 평균 낙찰가율)
스코어(데이터로 계산 가능한 것만, 할루시네이션 금지):
  · 예산적합 (예상낙찰 ≤ 9억 자력 / ≤ 11억 시댁포함)
  · 경매할인 (시세 대비 예상낙찰이 쌀수록 +)
  · 통근 (왕십리·과천 도보/대중교통 분)
  · 세대수 (300+), 입주연도(신축일수록 +)
  · 호재·역세권거리·학군 → 데이터 불완전 → "확인 필요" 표기(점수 미반영)
"""
import argparse
import glob
import json
import re
import statistics
from datetime import datetime, timezone, timedelta
from pathlib import Path

SLUG2GU = {
    'gangnam': '강남', 'gangdong': '강동', 'gangbuk': '강북', 'gangseo': '강서',
    'gwanak': '관악', 'gwangjin': '광진', 'guro': '구로', 'geumcheon': '금천',
    'nowon': '노원', 'dobong': '도봉', 'dongdaemun': '동대문', 'dongjak': '동작',
    'mapo': '마포', 'seodaemun': '서대문', 'seocho': '서초', 'seongdong': '성동',
    'seongbuk': '성북', 'songpa': '송파', 'yangcheon': '양천', 'yeongdeungpo': '영등포',
    'yongsan': '용산', 'eunpyeong': '은평', 'jongno': '종로', 'jung': '중', 'jungnang': '중랑',
}

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
DATA = ROOT / 'data'
CFG_PATH = ROOT / 'config/auction_filter.json'

BUDGET_SELF = 9.0    # 억 자력
BUDGET_MAX = 11.0    # 억 시댁 포함
DEFAULT_K = 0.92     # 감정가 기반 폴백 k (comps 356건 평균 낙찰가율, 감정 대비)
K_SISE_HOT = 0.98    # 감정<시세(저평가 신건 과열) → 시세의 98%
K_SISE_CONV = 0.95   # 감정≥시세(수렴) → 시세의 95%  (모델 v2: 정상물건 시세×0.95~1.0)


def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _norm(name):
    """단지명 정규화: 괄호·'아파트'·공백·특수문자 제거."""
    if not name:
        return ''
    s = re.sub(r'\(.*?\)', '', name)
    s = s.replace('아파트', '')
    s = re.sub(r'[\s,·.\-]', '', s)
    return s


def build_index(table):
    """{원본명: 값} → {정규화명: (원본명, 값)} (부분매칭용)."""
    idx = {}
    for k, v in table.items():
        nk = _norm(k)
        if nk:
            idx[nk] = (k, v)
    return idx


def match(name, idx):
    """신건 단지명 → 보조데이터 값 (양방향 부분매칭). 없으면 None.
    ⚠️ 흔한 이름 오매칭 방지: 3자 이상 + 정확일치 우선."""
    n = _norm(name)
    if not n or len(n) < 3:
        return None
    if n in idx:
        return idx[n][1]
    for nk, (orig, v) in idx.items():
        if len(nk) >= 4 and (nk in n or n in nk):
            return v
    return None


def _name_match(a, b):
    """이름 매칭: 완전일치 OR (한쪽이 다른쪽에 포함 + 짧은쪽 4자↑).
    '현대'·'우성' 같은 흔한 2~3자 토큰이 '청계현대'에 오매칭되는 것 방지."""
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and short in long


def match_sise(name, gu, area, molit):
    """시세 매칭 — 이름 + 같은 구 + 면적 근접(±7㎡)이 모두 맞아야만 인정.
    (흔한 단지명이 엉뚱한 구/평형에 잘못 붙는 것 방지)"""
    n = _norm(name)
    if not n or len(n) < 3 or not gu:
        return None
    gu = gu.replace('구', '')
    best = None
    for cn, v in molit.items():
        cnn = _norm(cn)
        if not _name_match(cnn, n):
            continue
        if (v.get('gu') or '').replace('구', '') != gu:
            continue
        at = v.get('area_typical')
        if at and area and abs(at - area) > 7:
            continue
        gap = abs((at or area) - area) if area else 0
        if best is None or gap < best[0]:
            best = (gap, v)
    return best[1] if best else None


def load_trade():
    """molit_trade/*.json → [{gu, district, norm, area, price_eok, date}]. (법정동 단위 실거래)
    최근 12개월 거래만 사용 (옛 저가거래가 시세를 왜곡하지 않도록)."""
    cutoff = (datetime.now(KST) - timedelta(days=365)).strftime('%Y-%m-%d')
    recs = []
    for fp in glob.glob(str(DATA / 'molit_trade' / '*.json')):
        slug = Path(fp).stem.rsplit('_', 1)[0]
        gu = SLUG2GU.get(slug)
        if not gu:
            continue
        try:
            raw = json.load(open(fp, encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            continue
        rows = raw.get('items', []) if isinstance(raw, dict) else raw
        for r in rows:
            date = r.get('deal_date') or ''
            if date and date < cutoff:      # 최근 12개월만
                continue
            recs.append({
                'gu': gu, 'district': (r.get('district') or '').strip(),
                'norm': _norm(r.get('name')), 'area': r.get('area_m2') or 0,
                'price_eok': (r.get('price_10k') or 0) / 10000, 'date': date,
            })
    return recs


def extract_dongs(addr):
    """경매 주소에서 법정동 토큰 추출 ('...관악구 봉천동 ...' → ['봉천동'])."""
    return re.findall(r'([가-힣]{1,4}동)', addr or '')


def match_sise_trade(name, gu, dongs, area, trade):
    """실거래(molit_trade) 기반 시세 — 같은 구+법정동+이름+면적(±5㎡) 최근거래 중앙값.
    법정동이 특정되므로 오매칭이 거의 없음. 없으면 None."""
    n = _norm(name)
    if not n or len(n) < 2 or not gu:
        return None
    gu = gu.replace('구', '')
    dongset = set(dongs or [])
    prices = []
    for r in trade:
        if r['gu'] != gu:
            continue
        if dongset and r['district'] not in dongset:
            continue
        if not _name_match(r['norm'], n):
            continue
        if area and r['area'] and abs(r['area'] - area) > 5:
            continue
        prices.append(r['price_eok'])
    if len(prices) < 1:
        return None
    return round(statistics.median(prices), 2)


def get_k():
    d = load_json(DATA / 'auction_k.json', {})
    return float(d.get('k', DEFAULT_K)), int(d.get('n', 0))


def evaluate(it, k, molit_idx, commute_idx, years_idx, trade):
    """신건 하나 → (점수, 판정, 근거dict, 예측dict)."""
    name = it.get('name') or ''
    appr = it.get('appraisal_eok')
    area = it.get('area_m2')

    # 시세: 실거래(법정동 단위) 우선 → 없으면 molit_all(구+면적) 폴백
    sise = match_sise_trade(name, it.get('gu'), extract_dongs(it.get('addr')), area, trade)
    if sise is None:
        sise_row = match_sise(name, it.get('gu'), area, molit_idx)
        sise = round(sise_row['price_median'] / 10000, 2) if sise_row else None

    # 경매 메커니즘 반영: 낙찰가 ≥ 최저가(신건이면 최저=감정).
    minp = it.get('min_price_eok')
    pred, basis, outcome = None, '-', None
    if sise and appr:
        # 시세 기반(모델 v2). 전망은 감정 vs 시세로 판정:
        #   감정 ≤ 시세 → 이번 회차 낙찰(최저 위로 올려침), 낙찰 ≈ 시세×0.98 (최저 하한)
        #   감정 > 시세 → 이번 회차 유찰 → 다음 회차(최저 20%↓)에서 시세×0.95 근처
        basis = '시세'
        floor = minp or appr
        if appr <= sise:
            pred = max(floor, round(sise * K_SISE_HOT, 2))
            outcome = '낙찰예상'
        else:
            pred = max(round(sise * K_SISE_CONV, 2), round(floor * 0.8, 2))
            outcome = '유찰예상'
    elif appr:
        # 시세 미상 → 신건 낙찰은 최저가(감정) 이상. 시세 없이는 숫자 예측 불가 → 하한만 제시.
        pred = minp or appr
        basis = '감정'
        outcome = '시세확인'
    discount = round((sise - pred) / sise * 100, 1) if (sise and pred) else None
    commute = match(name, commute_idx)
    yr = match(name, years_idx)
    household = (yr or {}).get('household') if yr else it.get('_household')
    year = (yr or {}).get('year') if yr else None

    score, why = 0, []
    # 예산 적합
    if pred is not None:
        if pred <= BUDGET_SELF:
            score += 3; why.append(f'예산자력({pred}억)')
        elif pred <= BUDGET_MAX:
            score += 1; why.append(f'예산시댁({pred}억)')
        else:
            score -= 2; why.append(f'예산초과({pred}억)')
    # 경매 할인 (시세 대비)
    if discount is not None:
        if discount >= 10:
            score += 3; why.append(f'할인{discount}%')
        elif discount >= 3:
            score += 1; why.append(f'할인{discount}%')
        elif discount <= -3:
            score -= 1; why.append(f'시세초과{discount}%')
    # 통근
    if commute:
        w, g = commute.get('w'), commute.get('g')
        if w is not None and w <= 40:
            score += 1; why.append(f'왕십리{w}분')
        if g is not None and g <= 50:
            score += 1; why.append(f'과천{g}분')
    # 세대수
    if household and household >= 300:
        score += 1; why.append(f'{household}세대')
    # 입주연도
    if year and year >= 2005:
        score += 1; why.append(f'{year}년')

    if score >= 6:
        verdict = '🟢 추천'
    elif score >= 4:
        verdict = '🟡 관심'
    elif score >= 2:
        verdict = '⚪ 보류'
    else:
        verdict = '⚫ 패스'

    need = []
    if sise is None:
        need.append('시세')
    if not commute:
        need.append('통근')
    need.append('호재/역세권/학군')  # 데이터 불완전 → 항상 수동확인

    pred_rec = {
        'case_no': it.get('case_no'), 'name': name, 'gu': it.get('gu'),
        'area_m2': area, 'appraisal_eok': appr, 'min_price_eok': minp,
        'pred_sale_eok': pred, 'basis': basis, 'outcome': outcome,
        'sise_eok': sise, 'discount_pct': discount, 'sale_date': it.get('sale_date'),
        'predicted_at': None,  # 워크플로에서 날짜 스탬프
    }
    return score, verdict, {
        'pred': pred, 'basis': basis, 'outcome': outcome, 'sise': sise, 'discount': discount,
        'commute': commute, 'household': household, 'year': year,
        'why': why, 'need': need,
    }, pred_rec


def main():
    ap = argparse.ArgumentParser(description='신건 투자 추천 + 예상낙찰 예측')
    ap.add_argument('--date', help='YYYY_MM_DD (기본 오늘 KST)')
    ap.add_argument('--raw', help='신건 raw json 경로')
    ap.add_argument('--stamp', help='예측 저장 시각 스탬프 YYYY-MM-DD')
    args = ap.parse_args()

    date = args.date or datetime.now(KST).strftime('%Y_%m_%d')
    raw_path = Path(args.raw) if args.raw else DATA / f'auction_raw_{date}.json'
    items = load_json(raw_path)
    if items is None:
        print(f'ERROR: 신건 raw 없음 → {raw_path}')
        return 1

    cfg = load_json(CFG_PATH, {})
    amin, amax = cfg.get('area_m2_min', 54), cfg.get('area_m2_max', 85)
    k, kn = get_k()
    molit_idx = load_json(DATA / 'molit_all_seoul.json', {}) or {}   # 원본 dict (match_sise가 구/면적 검증)
    trade = load_trade()   # molit_trade 실거래(법정동 단위) — 시세 매칭 1순위
    commute_idx = build_index(load_json(DATA / 'commute_times.json', {}) or {})
    years_idx = build_index(load_json(DATA / 'years_all.json', {}) or {})

    # 예산·면적·신건 1차 통과만 추천 대상
    cand = []
    for it in items:
        area = it.get('area_m2')
        appr = it.get('appraisal_eok')
        if area is None or appr is None:
            continue
        if not (amin <= area <= amax):
            continue
        if appr > 13:            # 예산권 한참 초과(감정 13억+) → 후보 제외(노이즈 컷)
            continue
        if (it.get('fail_count') or 0) != 0:
            continue
        sp = (it.get('special') or '').strip()
        if sp and sp != '없음':
            continue
        cand.append(it)

    scored = []
    preds = load_json(DATA / 'auction_predictions.json', {}) or {}
    for it in cand:
        s, v, info, pred_rec = evaluate(it, k, molit_idx, commute_idx, years_idx, trade)
        scored.append((s, v, it, info))
        if pred_rec['case_no']:
            pred_rec['predicted_at'] = args.stamp or date.replace('_', '-')
            preds[pred_rec['case_no']] = pred_rec
    with open(DATA / 'auction_predictions.json', 'w', encoding='utf-8') as f:
        json.dump(preds, f, ensure_ascii=False, indent=2)

    scored.sort(key=lambda x: x[0], reverse=True)

    # ── 추천 다이제스트 (Markdown) ──
    lines = [f'## 🏠 신건 투자 추천 — {date.replace("_", "-")}',
             f'대상 {len(cand)}건 · 예상낙찰 = **시세×0.95~0.98**(시세 매칭 시) / 감정×{k}(폴백, 실측 {kn}건 보정)', '']
    if scored:
        lines.append('| 판정 | 단지 | 지역 | 전용 | 감정/최저 | 예상낙찰 | 전망 | 기준 | 시세 | 근거 |')
        lines.append('|:-:|:--|:--|--:|--:|--:|:-:|:-:|--:|:--|')
        for s, v, it, info in scored:
            sise = f"{info['sise']}억" if info['sise'] is not None else '?'
            appr = it.get('appraisal_eok'); minp = it.get('min_price_eok')
            aminp = f"{appr}/{minp}억" if minp and minp != appr else f"{appr}억"
            outc = info.get('outcome') or '-'
            lines.append(
                f"| {v} | {it.get('name')} | {it.get('gu')} | {it.get('area_m2')}㎡ "
                f"| {aminp} | **{info['pred']}억** | {outc} | {info['basis']} | {sise} "
                f"| {', '.join(info['why']) or '-'} |")
        lines += ['', '> 예상낙찰 **기준=시세**면 실거래 기반(정확), **감정**이면 시세 미매칭 폴백(±0.5억 오차 가능).',
                  '> ⚠️ 호재·역세권거리·학군 등은 데이터 미보유 → 직접 확인.']
    else:
        lines.append('_오늘 추천 대상 신건 없음_')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
