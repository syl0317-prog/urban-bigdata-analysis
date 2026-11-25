import os, re, sys, time, csv
import requests, pandas as pd

URL = "https://dapi.kakao.com/v2/local/search/address.json"
key = os.environ.get("KAKAO_REST_KEY")
if not key:
    sys.exit("KAKAO_REST_KEY 환경변수가 없습니다.")
H = {"Authorization": f"KakaoAK {key}"}

def dong_key(addr):
    m = re.match(r"^서울특별시 (\S+구) (\S+)", addr)
    return f"서울특별시 {m.group(1)} {m.group(2)}" if m else None

def query(q):
    for t in range(3):
        r = requests.get(URL, headers=H, params={"query": q}, timeout=10)
        if r.status_code == 200:
            docs = r.json().get("documents", [])
            return (float(docs[0]["x"]), float(docs[0]["y"])) if docs else None
        if r.status_code == 429:
            time.sleep(2 * (t + 1)); continue
        if r.status_code in (401, 403):
            sys.exit(f"인증/권한 오류 {r.status_code}: {r.text[:200]}")
        time.sleep(1)
    return None

df = pd.read_csv("tow_geocoded.csv", dtype=str)
fail = df["상태"] == "fail"
print("보강 대상:", fail.sum())

keys = {a: dong_key(a) for a in df.loc[fail, "주소"]}
cache = {}
for k in sorted({v for v in keys.values() if v}):
    cache[k] = query(k)
    time.sleep(0.1)
print("동 단위 검색:", len(cache), "곳, 실패", sum(v is None for v in cache.values()))

n = 0
for i in df.index[fail]:
    k = keys[df.at[i, "주소"]]
    res = cache.get(k)
    if res:
        df.at[i, "x경도"], df.at[i, "y위도"] = str(res[0]), str(res[1])
        df.at[i, "상태"], df.at[i, "사용주소"] = "ok_dong", k
        n += 1

df.to_csv("tow_geocoded_final.csv", index=False, encoding="utf-8-sig")
print(df["상태"].value_counts().to_string())
print(f"동 좌표로 보강 {n}건, 최종 실패 {(df['상태']=='fail').sum()}건")
