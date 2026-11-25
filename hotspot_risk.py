"""6단계: 공간 자기상관(Moran's I), 핫스팟(Getis-Ord Gi*), 위험 지수, 지도
python hotspot_risk.py

입력: dong_stats.csv, tow_with_dong.csv(aggregate_dong.py가 생성), seoul_hjd_boundary.geojson
출력:
- risk_index.csv        행정동 427개: 위험 지수 구성요소·점수·순위, Gi* z/p/분류
- risk_candidates.csv   위험 지역 후보 상위 30개 동
- figures/map_count_vs_rate.png   건수 기준 vs 생활인구 보정 기준 (나란히)
- figures/map_hotspot_gi.png      Gi* 핫스팟·콜드스팟
- figures/map_risk_index.png      위험 지수

위험 지수 (0~100, 높을수록 위험) = 세 구성요소 백분위의 가중 평균 × 100 (노출 0.5, 취약 0.25, 주차 0.25)
  ① 노출: 생활인구 1만 명당 견인 건수(견인_1만명당)
  ② 취약 위치: 견인 중 횡단보도·버스정류장·보호구역·점자블록·지하철 출입구 비율
     (건수가 적은 동의 비율이 튀지 않도록 서울 평균 쪽으로 축소: (취약+k·p0)/(n+k), k=50)
  ③ 주차구역 부족: 견인 지점에서 가장 가까운 주차구역까지 평균 거리
     (동 대표점으로 찍힌 ok_dong 좌표는 거리 왜곡이 있어 제외)
  노출에 절반을 주는 이유: 주차구역 329곳이 강남·서초·노원 등에 몰려 있어, 같은 비중이면
  견인이 적은 외곽 동이 '주차구역이 멀다'는 이유만으로 상위에 오른다(동일 가중 시 상위 30개 동의
  1만 명당 견인 순위 중앙값 126위). 노출 0.5로 두면 중앙값 65위. 동일 가중·기하평균과의 순위
  상관과 구성요소를 하나씩 뺀 결과를 민감도로 함께 출력한다.
"""
import os
import warnings

import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from esda.moran import Moran
from esda.getisord import G_Local
from libpysal.weights import Queen

warnings.filterwarnings("ignore")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
np.random.seed(42)
PERM = 9999
K_SHRINK = 50
VUL = ["견인_횡단보도", "견인_버스정류장·택시승강장", "견인_보호구역", "견인_점자블록·교통약자시설", "견인_지하철역 출입구"]

# 색 (dataviz 기본 팔레트: 순차=파랑 한 색조, 발산=빨강↔파랑 + 회색 중립)
SURFACE, INK, INK2, MUTED, EDGE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#fcfcfb"
SEQ5 = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
GI_COLORS = {"핫스팟 99%": "#b42a2a", "핫스팟 95%": "#e34948", "핫스팟 90%": "#f2a3a2",
             "유의하지 않음": "#f0efec",
             "콜드스팟 90%": "#9ec5f4", "콜드스팟 95%": "#3987e5", "콜드스팟 99%": "#184f95"}

# ---------- 데이터 ----------
dong = gpd.read_file("seoul_hjd_boundary.geojson")
dong["행정동코드"] = dong["adm_cd2"].str[:8]
st = pd.read_csv("dong_stats.csv", dtype={"행정동코드": str})
g = dong[["행정동코드", "geometry"]].merge(st, on="행정동코드", how="inner").to_crs(5186)
g = g.sort_values("행정동코드").reset_index(drop=True)
assert len(g) == 427, len(g)

tw = pd.read_csv("tow_with_dong.csv", dtype={"행정동코드": str}, usecols=["행정동코드", "상태", "주차구역거리m"])
dist_ok = tw[tw["상태"] == "ok"].groupby("행정동코드")["주차구역거리m"].mean()
g["주차구역거리m_정밀"] = g["행정동코드"].map(dist_ok)

# ---------- 위험 지수 ----------
n = g["견인건수"].astype(float)
vul = g[VUL].sum(axis=1).astype(float)
p0 = vul.sum() / n.sum()
g["취약위치비율_보정"] = (vul + K_SHRINK * p0) / (n + K_SHRINK)

comp = {"노출": "견인_1만명당", "취약위치": "취약위치비율_보정", "주차부족": "주차구역거리m_정밀"}
for k, col in comp.items():
    g[f"백분위_{k}"] = g[col].rank(pct=True)
WEIGHTS = {"노출": 0.5, "취약위치": 0.25, "주차부족": 0.25}
has = g["견인건수"] > 0

def index_of(weights, geometric=False):
    P = g[[f"백분위_{k}" for k in weights]]
    wv = np.array(list(weights.values())) / sum(weights.values())
    s = np.exp((np.log(P) * wv).sum(axis=1)) if geometric else (P * wv).sum(axis=1)
    return pd.Series(np.where(has, s * 100, np.nan), index=g.index)

g["위험지수"] = index_of(WEIGHTS).round(1)
g["위험지수_순위"] = g["위험지수"].rank(ascending=False, method="min")
g["건수_순위"] = g["견인건수"].rank(ascending=False, method="min")
g["보정_순위"] = g["견인_1만명당"].rank(ascending=False, method="min")

# ---------- 공간 가중치 · Moran's I ----------
w = Queen.from_dataframe(g, use_index=False, silence_warnings=True)
islands = w.islands
w.transform = "r"
print(f"공간가중치(Queen): 동 {w.n}개, 평균 이웃 {w.mean_neighbors:.1f}, 고립 동 {len(islands)}")

def moran(col):
    y = g[col].fillna(g[col].median()).values
    m = Moran(y, w, permutations=PERM)
    return m.I, m.p_sim, m.z_sim

print("\n[Moran's I] (순열 %d회)" % PERM)
moran_res = {}
for col in ["견인건수", "견인_1만명당", "위험지수"]:
    I, p, z = moran(col)
    moran_res[col] = (I, p, z)
    print(f"  {col:10s} I={I:.3f}  z={z:.2f}  p={p:.4f}")

# ---------- Getis-Ord Gi* (견인_1만명당) ----------
wb = Queen.from_dataframe(g, use_index=False, silence_warnings=True)
gi = G_Local(g["견인_1만명당"].values, wb, transform="B", star=True, permutations=PERM, seed=42)
g["Gi_z"] = gi.Zs
g["Gi_p"] = gi.p_sim

def gi_class(z, p):
    for conf, a in ((99, 0.01), (95, 0.05), (90, 0.10)):
        if p <= a:
            return f"{'핫스팟' if z > 0 else '콜드스팟'} {conf}%"
    return "유의하지 않음"

g["Gi_분류"] = [gi_class(z, p) for z, p in zip(g["Gi_z"], g["Gi_p"])]
print("\n[Gi* 분류 — 견인_1만명당]")
print(g["Gi_분류"].value_counts().reindex(GI_COLORS.keys()).fillna(0).astype(int).to_string())

# 다중검정 보정: 427개 동을 각각 검정하므로 Benjamini-Hochberg FDR 5%로 한 번 더 거른다
pv = np.sort(g["Gi_p"].values)
m_tests = len(pv)
passed = pv <= 0.05 * np.arange(1, m_tests + 1) / m_tests
fdr_cut = pv[passed].max() if passed.any() else 0.0
g["Gi_FDR유의"] = g["Gi_p"] <= fdr_cut
print(f"  FDR 5% 기준 유의확률 컷 {fdr_cut:.4f} → 핫스팟 {int((g['Gi_FDR유의'] & (g['Gi_z'] > 0)).sum())}개, "
      f"콜드스팟 {int((g['Gi_FDR유의'] & (g['Gi_z'] < 0)).sum())}개 동")

# ---------- 민감도 ----------
s1 = g.loc[has, "위험지수"]
top30 = set(g.nsmallest(30, "위험지수_순위")["행정동코드"])

def compare(name, s):
    t30 = set(g.loc[s.rank(ascending=False) <= 30, "행정동코드"])
    print(f"  {name:28s} 순위 상관 {s1.rank().corr(s[has].rank()):.3f} · 상위30 겹침 {len(top30 & t30)}/30")

print("\n[위험 지수 민감도] 기준: 가중 평균 0.5/0.25/0.25")
compare("동일 가중 평균 1:1:1", index_of({"노출": 1, "취약위치": 1, "주차부족": 1}))
compare("가중 기하평균 0.5/0.25/0.25", index_of(WEIGHTS, geometric=True))
for drop in comp:
    compare(f"'{drop}' 제외", index_of({k: v for k, v in WEIGHTS.items() if k != drop}))
tt = g[g["행정동코드"].isin(top30)]
print(f"  상위30: 1만 명당 견인 순위 중앙값 {tt['보정_순위'].median():.0f}위 · 핫스팟(90%↑) 소속 {tt['Gi_분류'].str.startswith('핫').sum()}개 동")

# ---------- 저장 ----------
out_cols = ["행정동코드", "행정동명", "자치구", "행정동", "견인건수", "생활인구_평균", "견인_1만명당",
            "취약위치비율_보정", "주차구역거리m_정밀", "주차구역수", "보호구역수",
            "백분위_노출", "백분위_취약위치", "백분위_주차부족", "위험지수",
            "위험지수_순위", "건수_순위", "보정_순위", "Gi_z", "Gi_p", "Gi_분류", "Gi_FDR유의"]
res = g[out_cols].copy()
for c in ["취약위치비율_보정", "백분위_노출", "백분위_취약위치", "백분위_주차부족", "Gi_z", "Gi_p"]:
    res[c] = res[c].round(4)
res["주차구역거리m_정밀"] = res["주차구역거리m_정밀"].round(0)
res.sort_values("위험지수_순위").to_csv("risk_index.csv", index=False, encoding="utf-8-sig")
cand = res.sort_values("위험지수_순위").head(30)
cand[["위험지수_순위", "행정동명", "위험지수", "견인건수", "건수_순위", "견인_1만명당", "보정_순위",
      "취약위치비율_보정", "주차구역거리m_정밀", "Gi_분류", "Gi_FDR유의"]].to_csv("risk_candidates.csv", index=False, encoding="utf-8-sig")

# ---------- 지도 ----------
os.makedirs("figures", exist_ok=True)
gu = g.dissolve("자치구").reset_index()

def quantile_classes(s, k=5):
    q = np.nanquantile(s, np.linspace(0, 1, k + 1))
    idx = np.clip(np.searchsorted(q[1:-1], s, side="right"), 0, k - 1)
    labels = [f"{q[i]:,.0f} ~ {q[i + 1]:,.0f}" for i in range(k)]
    return idx, labels

def titles(ax, title, sub=None):
    ax.set_title(title, fontsize=13, color=INK, loc="left", pad=24 if sub else 8)
    if sub:
        ax.text(0.0, 1.012, sub, transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom")

def legend_right(ax, handles, title):
    ax.legend(handles=handles, title=title, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False,
              fontsize=8, title_fontsize=8.5, labelcolor=INK2, alignment="left")

def draw_seq(ax, col, title, unit, sub=None):
    s = g[col].values.astype(float)
    idx, labels = quantile_classes(s)
    colors = np.array(SEQ5)[idx]
    colors[np.isnan(s)] = "#e1e0d9"
    g.plot(ax=ax, color=colors, edgecolor=EDGE, linewidth=0.3)
    gu.boundary.plot(ax=ax, color=INK2, linewidth=0.6)
    titles(ax, title, sub)
    h = [Patch(facecolor=c, edgecolor="none", label=l) for c, l in zip(SEQ5, labels)][::-1]
    if np.isnan(s).any():
        h.append(Patch(facecolor="#e1e0d9", edgecolor="none", label="견인 없음"))
    legend_right(ax, h, f"{unit} (5분위)")
    ax.set_axis_off()

def number_top(ax, top, list_title):
    """상위 동에 번호 표시 + 지도 오른쪽 아래에 번호·이름 목록 (이름 겹침 방지)."""
    lines = []
    for i, (_, r) in enumerate(top.iterrows(), 1):
        p = r.geometry.representative_point()
        ax.scatter(p.x, p.y, s=150, color=SURFACE, edgecolor=INK, linewidth=1.0, zorder=5)
        ax.text(p.x, p.y, str(i), ha="center", va="center", fontsize=7, fontweight="bold", color=INK, zorder=6)
        lines.append(f"{i:>2}  {r['자치구']} {r['행정동']}")
    ax.text(1.0, 0.0, list_title + "\n" + "\n".join(lines), transform=ax.transAxes, fontsize=8, color=INK2,
            va="bottom", ha="left", linespacing=1.5)

def fig_base(ncols=1, w=10):
    fig, axes = plt.subplots(1, ncols, figsize=(w, 7.2), facecolor=SURFACE)
    return fig, np.atleast_1d(axes)

# 1) 건수 vs 보정
fig, (a1, a2) = fig_base(2, 19)
fig.subplots_adjust(wspace=0.45)
draw_seq(a1, "견인건수", "견인 건수", "건", "2021.7~2025.12 누적 · 번호는 상위 5개 동")
draw_seq(a2, "견인_1만명당", "생활인구 1만 명당 견인 건수", "건/1만 명", "생활인구로 보정 · 번호는 상위 5개 동")
number_top(a1, g.nlargest(5, "견인건수"), "상위 5")
number_top(a2, g.nlargest(5, "견인_1만명당"), "상위 5")
fig.text(0.13, 0.04, "생활인구: 서울 열린데이터광장 OA-23016 [내국인] 2026년 10월 평균 · 견인: 서울시 전동킥보드 견인 현황",
         fontsize=8, color=MUTED)
fig.savefig("figures/map_count_vs_rate.png", dpi=200, bbox_inches="tight", facecolor=SURFACE)
plt.close(fig)

# 2) Gi*
fig, (ax,) = fig_base()
g.plot(ax=ax, color=g["Gi_분류"].map(GI_COLORS), edgecolor=EDGE, linewidth=0.3)
gu.boundary.plot(ax=ax, color=INK2, linewidth=0.6)
cnt = g["Gi_분류"].value_counts()
legend_right(ax, [Patch(facecolor=c, edgecolor="#c3c2b7" if k == "유의하지 않음" else "none",
                        label=f"{k} ({cnt.get(k, 0)}개 동)") for k, c in GI_COLORS.items()],
             "Getis-Ord Gi*\n(순열 9,999회)")
I, p, z = moran_res["견인_1만명당"]
titles(ax, "생활인구 1만 명당 견인 — 핫스팟·콜드스팟",
       f"전역 Moran's I = {I:.3f} (p = {p:.4f}) · Queen 인접 · 신뢰수준은 유의확률 기준")
ax.set_axis_off()
fig.savefig("figures/map_hotspot_gi.png", dpi=200, bbox_inches="tight", facecolor=SURFACE)
plt.close(fig)

# 3) 위험 지수
fig, (ax,) = fig_base()
draw_seq(ax, "위험지수", "PM 방치 보행 위험 지수 (0~100)", "점",
         "노출(1만 명당 견인) 50% · 취약 위치 비율 25% · 주차구역 거리 25% — 백분위 가중 평균")
number_top(ax, g.nsmallest(10, "위험지수_순위"), "위험 지역 후보 상위 10")
fig.savefig("figures/map_risk_index.png", dpi=200, bbox_inches="tight", facecolor=SURFACE)
plt.close(fig)

print("\n[위험 지역 후보 상위 15]")
print(cand.head(15)[["위험지수_순위", "행정동명", "위험지수", "건수_순위", "보정_순위", "Gi_분류"]].to_string(index=False))
print("\n저장: risk_index.csv, risk_candidates.csv, figures/*.png")
