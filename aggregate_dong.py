import glob, os, sys
import numpy as np, pandas as pd, geopandas as gpd
from scipy.spatial import cKDTree

CRS_M = 5186
BUS = "서울시버스정류소위치정보(20260902).xlsx"
SUBWAY = "전체_도시철도역사정보_20260630.xlsx"
POP = "250_ORGN_CT_IN_SE_20261017.csv"

dong = gpd.read_file("seoul_hjd_boundary.geojson")
dong["행정동코드"] = dong["adm_cd2"].str[:8]
dong = dong[["행정동코드", "adm_nm", "sggnm", "geometry"]].rename(columns={"adm_nm": "행정동명", "sggnm": "자치구"})
dong["행정동"] = dong["행정동명"].str.split().str[-1]
print("행정동", len(dong))

def points(df, x, y):
    d = df.dropna(subset=[x, y]).copy()
    d[x] = pd.to_numeric(d[x], errors="coerce"); d[y] = pd.to_numeric(d[y], errors="coerce")
    d = d.dropna(subset=[x, y])
    return gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d[x], d[y]), crs=4326)

def assign(gdf):
    j = gpd.sjoin(gdf, dong[["행정동코드", "geometry"]], how="left", predicate="within")
    return j[~j.index.duplicated(keep="first")]

addr = pd.read_csv("tow_geocoded_final.csv", dtype=str)
addr = addr[addr["상태"].isin(["ok", "ok_dong"])][["주소", "x경도", "y위도", "상태"]]
tow = pd.read_csv("tow_clean.csv", dtype=str)
tow = tow[tow["플래그_오신고"] != "True"]
tow = tow.merge(addr, on="주소", how="left")
print("견인(오신고 제외)", len(tow), "/ 좌표 없음", tow["x경도"].isna().sum())
tg = assign(points(tow, "x경도", "y위도"))
print("행정동 배정 실패", tg["행정동코드"].isna().sum())
tg = tg.dropna(subset=["행정동코드"])

park = assign(points(pd.read_csv("parking_geocoded.csv", dtype=str), "경도", "위도"))
prot = assign(points(pd.read_csv("protect_zone_geocoded.csv", dtype=str), "경도", "위도"))
bus = assign(points(pd.read_excel(BUS), "X좌표", "Y좌표"))
sub = pd.read_excel(SUBWAY).drop_duplicates(subset=["역사명", "역위도", "역경도"])
sub = assign(points(sub, "역경도", "역위도"))
sub = sub.dropna(subset=["행정동코드"])

def to_m(g): return g.to_crs(CRS_M).geometry
pk = to_m(points(pd.read_csv("parking_geocoded.csv", dtype=str), "경도", "위도"))
tree = cKDTree(np.c_[pk.x, pk.y])
tm = to_m(tg)
tg["주차구역거리m"], _ = tree.query(np.c_[tm.x, tm.y])
tg[["번호", "신고일", "자치구", "주소", "위치유형", "행정동코드", "상태", "주차구역거리m"]].to_csv(
    "tow_with_dong.csv", index=False, encoding="utf-8-sig")

g = dong[["행정동코드", "행정동명", "자치구", "행정동"]].set_index("행정동코드")
g["견인건수"] = tg.groupby("행정동코드").size()
for c in ["보도", "횡단보도", "차도", "버스정류장·택시승강장", "보호구역", "점자블록·교통약자시설", "지하철역 출입구"]:
    g["견인_" + c] = tg[tg["위치유형"] == c].groupby("행정동코드").size()
g["평균주차구역거리m"] = tg.groupby("행정동코드")["주차구역거리m"].mean()
g["주차구역수"] = park.dropna(subset=["행정동코드"]).groupby("행정동코드").size()
g["보호구역수"] = prot.dropna(subset=["행정동코드"]).groupby("행정동코드").size()
g["버스정류소수"] = bus.dropna(subset=["행정동코드"]).groupby("행정동코드").size()
g["지하철역수"] = sub.groupby("행정동코드").size()
cnt = [c for c in g.columns if c.endswith("수") or c.startswith("견인")]
g[cnt] = g[cnt].fillna(0).astype(int)
vul = ["견인_횡단보도", "견인_버스정류장·택시승강장", "견인_보호구역", "견인_점자블록·교통약자시설", "견인_지하철역 출입구"]
g["취약위치견인비율"] = (g[vul].sum(axis=1) / g["견인건수"].replace(0, np.nan)).round(4)

def read_full_pop(files):
    """OA-23016 [내국인] 행정동별 서울 생활인구(250m) 일별 CSV들 → 행정동별 (일자×시간) 평균.
    서울에 머문 내국인 전체(경기·인천 거주 통근자 포함). 헤더는 쉼표, 본문은 파일마다 ';' 또는 ','."""
    parts = []
    for f in files:
        with open(f, encoding="cp949") as fh:
            cols = [c.strip('"') for c in fh.readline().strip().split(",")]
            line = fh.readline()
        sep = ";" if line.count(";") > line.count(",") else ","
        d = pd.read_csv(f, encoding="cp949", sep=sep, skiprows=1, header=None, dtype=str, usecols=range(4))
        d.columns = cols[:4]
        parts.append(d)
    p = pd.concat(parts)
    p["행정동코드"] = p["행정동코드"].str.strip()
    p["v"] = pd.to_numeric(p["생활인구합계"].str.strip(), errors="coerce")
    print(f"생활인구(전체 내국인): 파일 {len(files)}개, 일자 {p['일자'].nunique()}일")
    return p.groupby("행정동코드")["v"].mean()


# 생활인구: 전체 내국인(OA-23016, pop_full_*/) 우선, 없으면 서울 거주자 한정 파일(OA-22851)
FULL = sorted(glob.glob("pop_full_*/250_LOCAL_RESD_ADMDONG_*.csv"))
pop_mean = None
if FULL:
    pop_mean = read_full_pop(FULL)
elif os.path.exists(POP):
    p = pd.read_csv(POP, dtype=str, encoding="cp949", index_col=False,
                    usecols=["일자", "시각", "행정동코드", "거주지코드", "생활인구합계"])
    p["행정동코드"] = p["행정동코드"].str.strip()
    p["v"] = pd.to_numeric(p["생활인구합계"].str.rstrip("."), errors="coerce")
    hourly = p.groupby(["행정동코드", "시각"])["v"].sum()
    pop_mean = hourly.groupby("행정동코드").mean()
    print("※ 서울 거주자 한정 생활인구(", POP, ") 사용 — 통근자 제외")
else:
    print("※ 생활인구 파일이 없어 인구 보정을 건너뜁니다.")
if pop_mean is not None:
    g["생활인구_평균"] = pop_mean.round(1)
    g["견인_1만명당"] = (g["견인건수"] / g["생활인구_평균"] * 10000).round(2)
    print("생활인구 매칭", g["생활인구_평균"].notna().sum(), "/ 427")

g.reset_index().to_csv("dong_stats.csv", index=False, encoding="utf-8-sig")
print(g.describe().T[["count", "mean", "min", "max"]].round(2).to_string())
print("저장: dong_stats.csv, tow_with_dong.csv")
