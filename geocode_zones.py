"""주차구역·보호구역 지오코딩 (카카오 로컬 API): python geocode_zones.py

입력
- 서울시 전동킥보드 주차구역 현황.csv (329곳)
- 어린이 보호구역 지정현황(2026.6월말 기준).xlsx  '어린이보호구역 지정현황' 시트 (1,630곳)
- 노인. 장애인보호구역 지정현황(2026.6월말 기준).hwpx  표 2개 (노인 196곳, 장애인 29곳)

출력 (utf-8-sig)
- parking_geocoded.csv       주차구역 + 위도/경도
- protect_zone_geocoded.csv  보호구역(구역유형: 어린이/노인/장애인) + 위도/경도
- geocode_failures.csv       좌표를 못 찾은 행
- geocode_cache.json         API 응답 캐시 (재실행 시 호출 절약, git 제외)

검색 순서: ① 주소검색 '서울특별시 {자치구} {주소}' → ② 키워드검색 같은 문자열
         → ③ 키워드검색 '{자치구} {시설명/상세위치}'
결과의 자치구가 원본 자치구와 다르면 버리고 다음 단계로 넘어간다.
좌표계: WGS84 (EPSG:4326)
"""
import json
import os
import re
import sys
import time
import zipfile

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.abspath(__file__))
P = lambda name: os.path.join(ROOT, name)

load_dotenv(P(".env"))
KEY = os.getenv("KAKAO_REST_API_KEY", "").strip()
if not KEY:
    sys.exit("KAKAO_REST_API_KEY가 없습니다. .env에 넣어주세요 (.env.example 참고).")
HEADERS = {"Authorization": f"KakaoAK {KEY}"}
URL = {
    "address": "https://dapi.kakao.com/v2/local/search/address.json",
    "keyword": "https://dapi.kakao.com/v2/local/search/keyword.json",
}

CACHE_PATH = P("geocode_cache.json")
cache = json.load(open(CACHE_PATH, encoding="utf-8")) if os.path.exists(CACHE_PATH) else {}


def norm(s):
    return re.sub(r"\s+", " ", str(s if pd.notna(s) else "")).strip()


def call(kind, query):
    """카카오 API 호출 (캐시 사용). 문서 리스트 반환."""
    k = f"{kind}|{query}"
    if k in cache:
        return cache[k]
    r = None
    for attempt in range(6):
        try:
            r = requests.get(URL[kind], headers=HEADERS, params={"query": query, "size": 5}, timeout=10)
        except requests.exceptions.RequestException as e:  # 연결 끊김·타임아웃 → 잠시 후 재시도
            print(f"  연결 오류, 재시도 {attempt + 1}/6: {type(e).__name__}", flush=True)
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 200:
            break
        if r.status_code in (429, 500, 502, 503):
            time.sleep(3 * (attempt + 1))
            continue
        sys.exit(f"API 오류 {r.status_code}: {r.text[:200]}")
    else:
        raise RuntimeError(f"6회 재시도 실패: {query}")
    docs = [
        {
            "x": d["x"], "y": d["y"],
            "addr": d.get("address_name", ""),
            "road": (d.get("road_address") or {}).get("address_name", "") if kind == "address" else d.get("road_address_name", ""),
            "place": d.get("place_name", ""),
        }
        for d in r.json().get("documents", [])
    ]
    cache[k] = docs
    time.sleep(0.05)
    return docs


def gu_of(doc):
    """결과 주소에서 자치구 추출 ('서울 강남구 ...' → '강남구')."""
    for a in (doc["addr"], doc["road"]):
        m = re.match(r"^서울(?:특별시)?\s+(\S+구)\b", a)
        if m:
            return m.group(1)
    return None


def clean_addr(gu, a):
    """주소 표기 정리: 중복 자치구, 괄호·쉼표 뒤 부가정보, 붙어 쓴 건물번호, '2 가' 띄어쓰기."""
    a = re.sub(rf"^(서울(특별)?시\s*)?{gu}\s*", "", a)
    a = re.split(r"[,(]", a)[0].strip()
    a = re.sub(r"(로|길)(\d)", r"\1 \2", a)          # 곰달래로53가길6 → 곰달래로53가길 6 / 목동남로98 → 목동남로 98
    a = re.sub(r"(\d) 가(\s|$)", r"\1가\2", a)        # 신문로 2가 → 신문로2가
    a = re.sub(r"(\d+가)\s+(\d+가길)", r"\1\2", a)
    return re.sub(r"\s+", " ", a).strip()


def clean_name(n):
    """상세위치에서 '앞/뒤/맞은편' 같은 꼬리말과 중복 반복을 제거하고 '/' 앞부분만 사용."""
    n = n.split("/")[0].strip()
    half = len(n) // 2
    if len(n) % 2 == 0 and n[:half] == n[half:]:
        n = n[:half]
    n = re.sub(r"\s*(바로\s*)?(앞|뒤|옆|맞은편|건너편)$", "", n)
    return n.strip()


def geocode(gu, address, name):
    steps = []
    if address:
        q = f"서울특별시 {gu} {address}"
        steps += [("주소검색", "address", q), ("키워드-주소", "keyword", q)]
        c = clean_addr(gu, address)
        if c and c != address:
            steps.append(("주소검색-정리", "address", f"서울특별시 {gu} {c}"))
    if name:
        steps.append(("키워드-시설명", "keyword", f"{gu} {name}"))
        c = clean_name(name)
        if c and c != name:
            steps.append(("키워드-시설명정리", "keyword", f"{gu} {c}"))
    for label, kind, q in steps:
        for d in call(kind, q):
            if gu_of(d) == gu:
                return {"위도": float(d["y"]), "경도": float(d["x"]), "지오코딩방법": label,
                        "매칭주소": d["road"] or d["addr"], "매칭장소": d["place"]}
    return {"위도": None, "경도": None, "지오코딩방법": "실패", "매칭주소": "", "매칭장소": ""}


# ---------- 입력 읽기 ----------
def load_parking():
    d = pd.read_csv(P("서울시 전동킥보드 주차구역 현황.csv"), encoding="cp949")
    d = d.rename(columns={"시군구명": "자치구"})
    for c in ["자치구", "주소", "상세위치"]:
        d[c] = d[c].map(norm)
    return d


def load_child():
    raw = pd.read_excel(P("어린이 보호구역 지정현황(2026.6월말 기준).xlsx"), sheet_name="어린이보호구역 지정현황", header=None)
    raw = raw[pd.to_numeric(raw[1], errors="coerce").notna()]  # 연번이 숫자인 행만 (합계·소계 제외)
    d = pd.DataFrame({
        "구역유형": "어린이", "연번": raw[1].astype(int), "자치구": raw[2].map(norm), "행정동": raw[3].map(norm),
        "주소": raw[4].map(norm), "시설명": raw[5].map(norm), "시설유형": raw[6].map(norm), "지정연도": raw[7],
    })
    return d


def load_elderly_disabled():
    xml = zipfile.ZipFile(P("노인. 장애인보호구역 지정현황(2026.6월말 기준).hwpx")).read("Contents/section0.xml").decode("utf-8")
    text = lambda frag: norm("".join(re.findall(r"<hp:t(?:\s[^>]*)?>(.*?)</hp:t>", frag, flags=re.S)))
    rows = []
    tables = [t for t in re.findall(r"<hp:tbl\b.*?</hp:tbl>", xml, flags=re.S) if "연번" in t]
    for kind, tbl in zip(["노인", "장애인"], tables):
        for tr in re.findall(r"<hp:tr\b.*?</hp:tr>", tbl, flags=re.S):
            cells = [re.sub(r"<[^>]+>", "", text(tc)) for tc in re.findall(r"<hp:tc\b.*?</hp:tc>", tr, flags=re.S)]
            if len(cells) >= 5 and cells[0].isdigit():
                rows.append({"구역유형": kind, "연번": int(cells[0]), "자치구": cells[1], "시설명": cells[2],
                             "주소": cells[3], "지정연도": cells[4]})
    return pd.DataFrame(rows)


def save_cache():
    json.dump(cache, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)


def run(df, name_col, label):
    out, n, t0 = [], len(df), time.time()
    for i, (_, r) in enumerate(df.iterrows(), 1):
        out.append(geocode(r["자치구"], r["주소"], r[name_col]))
        if i % 100 == 0 or i == n:
            save_cache()  # 중간 저장: 끊겨도 다음 실행 때 이어서
            print(f"  [{label}] {i}/{n}  경과 {time.time() - t0:.0f}초", flush=True)
    return pd.concat([df.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def report(label, df):
    ok = df["위도"].notna()
    print(f"\n[{label}] {ok.sum()}/{len(df)} 성공 ({ok.mean():.1%}), 실패 {(~ok).sum()}")
    print("  방법별:", df["지오코딩방법"].value_counts().to_dict())


if __name__ == "__main__":
    parking = load_parking()
    zones = pd.concat([load_child(), load_elderly_disabled()], ignore_index=True)
    print("입력: 주차구역", len(parking), "/ 보호구역", zones["구역유형"].value_counts().to_dict())

    try:
        parking = run(parking, "상세위치", "주차구역")
        zones = run(zones, "시설명", "보호구역")
    finally:
        save_cache()

    parking.to_csv(P("parking_geocoded.csv"), index=False, encoding="utf-8-sig")
    zones.to_csv(P("protect_zone_geocoded.csv"), index=False, encoding="utf-8-sig")

    report("주차구역", parking)
    for t, g in zones.groupby("구역유형", sort=False):
        report(f"보호구역-{t}", g)

    fail = pd.concat([
        parking.loc[parking["위도"].isna()].assign(데이터="주차구역").rename(columns={"상세위치": "시설명"}),
        zones.loc[zones["위도"].isna()].assign(데이터=lambda x: "보호구역-" + x["구역유형"]),
    ], ignore_index=True)[["데이터", "자치구", "주소", "시설명"]]
    fail.to_csv(P("geocode_failures.csv"), index=False, encoding="utf-8-sig")
    print("\n실패 목록 → geocode_failures.csv", len(fail), "건")
    if len(fail):
        print("실패 자치구 분포:", fail["자치구"].value_counts().to_dict())
