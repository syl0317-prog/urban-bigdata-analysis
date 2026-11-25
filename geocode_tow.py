"""견인 고유 주소 지오코딩 (카카오 로컬 API)

사용:
  export KAKAO_REST_KEY=발급받은키        # 키는 저장소에 올리지 말 것
  python3 geocode_tow.py                  # 전체 실행 (중단 후 다시 실행하면 이어서 진행)
  python3 geocode_tow.py --limit 100      # 100개만 시험
  python3 geocode_tow.py --daily 90000    # 하루 호출 한도 지정 (기본 90000)

입력: tow_unique_addresses.csv (주소, 자치구)
출력: tow_geocoded.csv (주소, 자치구, x경도, y위도, 상태, 사용주소)
      상태: ok / ok_retry(정리한 주소로 성공) / fail
"""
import os, re, sys, time, argparse, csv
import requests, pandas as pd

URL = "https://dapi.kakao.com/v2/local/search/address.json"
ap = argparse.ArgumentParser()
ap.add_argument("--inp", default="tow_unique_addresses.csv")
ap.add_argument("--out", default="tow_geocoded.csv")
ap.add_argument("--limit", type=int, default=None)
ap.add_argument("--daily", type=int, default=90000)
ap.add_argument("--sleep", type=float, default=0.05)
a = ap.parse_args()

key = os.environ.get("KAKAO_REST_KEY")
if not key:
    sys.exit("KAKAO_REST_KEY 환경변수가 없습니다.")
H = {"Authorization": f"KakaoAK {key}"}

def normalize(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"(\d)\s*번지", r"\1", s)
    s = re.sub(r"(동|가)(?=\d)(?!\d+가)", r"\1 ", s)    # 붙은 동/지번 분리 (성수동2가는 유지)
    s = re.sub(r"(로|길)(\d+)(길)", r"\1 \2\3", s)    # 장승배기로13길 -> 장승배기로 13길
    s = re.sub(r"^(\S+ \S+구) (\S+동) \2 ", r"\1 \2 ", s)  # '노량진동 노량진동' 중복 제거
    return s

calls = 0
def query(q):
    global calls
    for t in range(3):
        calls += 1
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

df = pd.read_csv(a.inp, dtype=str)
done = set()
if os.path.exists(a.out):
    done = set(pd.read_csv(a.out, dtype=str)["주소"])
todo = df[~df["주소"].isin(done)]
if a.limit: todo = todo.head(a.limit)
print(f"전체 {len(df)} / 완료 {len(done)} / 이번 대상 {len(todo)}")

new = not os.path.exists(a.out)
f = open(a.out, "a", newline="", encoding="utf-8-sig")
w = csv.writer(f)
if new: w.writerow(["주소", "자치구", "x경도", "y위도", "상태", "사용주소"])

n = 0
try:
    for addr, gu in zip(todo["주소"], todo["자치구"]):
        if calls >= a.daily:
            print("일일 한도 도달. 내일 같은 명령으로 이어서 실행하세요."); break
        res, state, used = query(addr), "ok", addr
        if res is None:
            alt = normalize(addr)
            if alt != addr:
                res, used = query(alt), alt
                state = "ok_retry"
        if res is None: state, res = "fail", ("", "")
        w.writerow([addr, gu, res[0], res[1], state, used])
        n += 1
        if n % 500 == 0:
            f.flush(); print(f"{n}건 처리, 호출 {calls}")
        time.sleep(a.sleep)
finally:
    f.close()

o = pd.read_csv(a.out, dtype=str)
print(o["상태"].value_counts().to_string())
print(f"누적 {len(o)}/{len(df)}, 실패율 {(o['상태']=='fail').mean():.1%}")
