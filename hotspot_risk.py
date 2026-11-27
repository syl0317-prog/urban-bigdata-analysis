"""6단계: 공간 자기상관(Moran's I), 핫스팟(Getis-Ord Gi*), 위험 지수, 정책 대상지, 지도
python hotspot_risk.py

입력: dong_stats.csv, tow_with_dong.csv(aggregate_dong.py가 생성), seoul_hjd_boundary.geojson
출력:
- risk_index.csv        행정동 427개: 지표·위험 지수(기본안·비교안)·순위·Gi*·정책 유형
- risk_candidates.csv   위험 지역 후보 상위 30개 동
- policy_targets.csv    정책별 대상지 (주차구역 증설 / 집중 수거·순찰 / 보호구역·교통약자시설 점검)
- validation.csv        타당성 점검: 위험 지수와 보행 밀집 시설(보호구역·지하철역·버스정류소) 밀도의 관계
- figures/map_count_vs_rate.png, map_hotspot_gi.png, map_risk_index.png, map_policy.png

[위험 지수 설계와 근거]
- 위험의 정의: 위험 = 위해(hazard) × 취약성(vulnerability)
  (UNDRR 2017 용어 정의; Wisner et al. 2004 『At Risk』의 압력-완화(PAR) 모형)
  · 위해 = 생활인구 1만 명당 PM 방치(견인) 건수
  · 취약성 = 방치가 보행약자에게 피해를 주기 쉬운 위치(횡단보도·버스정류장·보호구역·점자블록·
    지하철 출입구)에서 일어난 비율. 건수가 적은 동의 비율이 튀지 않도록 서울 평균 쪽으로 축소
    (경험적 베이즈식 축소, (취약+k·p0)/(n+k), k=50)
  · 위해×취약성 = '취약 위치 견인 1만 명당 건수' → 서울 427개 동 중 백분위 × 100 = 위험 지수(0~100)
- 대체 주차공간 접근성(견인 지점~최근접 주차구역 평균 거리)은 INFORM 위험 지수(EU JRC)의
  '대응역량 부족(lack of coping capacity)'에 해당한다. 그러나 이 데이터에서는 견인이 많은 곳에
  주차구역이 이미 설치돼 있어(노출과 순위 상관 -0.23) 지수에 합치면 방치 정도가 거의 반영되지 않는다
  (INFORM식 3차원 기하평균 시 노출과의 순위 상관 0.17). OECD·JRC 복합지표 핸드북(2008)이 권하는 대로
  지표 간 상관 구조를 확인한 결과이며, 거리는 지수에서 분리해 정책 처방 축으로 쓴다
  (Hemphill & McNeil 2022: 전용 주차공간이 있는 블록에서 주차 준수율이 유의하게 높음).
  · 위험 상위 + 주차구역 400m 이상(보행 5분권 밖) → 주차구역 증설 후보
  · 위험 상위 + 주차구역 400m 미만(있는데도 방치) → 집중 수거·순찰·단속 대상
- 비교안(민감도): ① INFORM식 3차원(로그 변환·0~10 최소-최대 정규화, 동일 가중 기하평균)
                  ② 백분위 가중 평균(노출 0.5, 취약 0.25, 주차 0.25)
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
WALK_M = 400      # 보행 5분권 (도보 약 80m/분)
TOP_N = 30
VUL = ["견인_횡단보도", "견인_버스정류장·택시승강장", "견인_보호구역", "견인_점자블록·교통약자시설", "견인_지하철역 출입구"]

# 색 (dataviz 기본 팔레트: 순차=파랑 한 색조, 발산=빨강↔파랑 + 회색 중립, 범주=고정 순서)
SURFACE, INK, INK2, MUTED, EDGE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#fcfcfb"
SEQ5 = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
GI_COLORS = {"핫스팟 99%": "#b42a2a", "핫스팟 95%": "#e34948", "핫스팟 90%": "#f2a3a2",
             "유의하지 않음": "#f0efec",
             "콜드스팟 90%": "#9ec5f4", "콜드스팟 95%": "#3987e5", "콜드스팟 99%": "#184f95"}
POLICY_COLORS = {"주차구역 증설 후보": "#2a78d6", "집중 수거·순찰 대상": "#eb6834", "해당 없음": "#f0efec"}

# ---------- 데이터 ----------
dong = gpd.read_file("seoul_hjd_boundary.geojson")
dong["행정동코드"] = dong["adm_cd2"].str[:8]
st = pd.read_csv("dong_stats.csv", dtype={"행정동코드": str})
g = dong[["행정동코드", "geometry"]].merge(st, on="행정동코드", how="inner").to_crs(5186)
g = g.sort_values("행정동코드").reset_index(drop=True)
assert len(g) == 427, len(g)
g["면적km2"] = g.geometry.area / 1e6

tw = pd.read_csv("tow_with_dong.csv", dtype={"행정동코드": str}, usecols=["행정동코드", "상태", "주차구역거리m"])
dist_ok = tw[tw["상태"] == "ok"].groupby("행정동코드")["주차구역거리m"].mean()
g["주차구역거리m_정밀"] = g["행정동코드"].map(dist_ok)
has = g["견인건수"] > 0

# ---------- 위험 지수 (기본안: 위해 × 취약성) ----------
n = g["견인건수"].astype(float)
vul = g[VUL].sum(axis=1).astype(float)
p0 = vul.sum() / n.sum()
g["취약위치비율_보정"] = (vul + K_SHRINK * p0) / (n + K_SHRINK)
g["취약위치견인_1만명당"] = (g["견인_1만명당"] * g["취약위치비율_보정"]).round(2)
g["위험지수"] = np.where(has, g["취약위치견인_1만명당"].rank(pct=True) * 100, np.nan).round(1)
g["위험지수_순위"] = g["위험지수"].rank(ascending=False, method="min")
g["건수_순위"] = g["견인건수"].rank(ascending=False, method="min")
g["보정_순위"] = g["견인_1만명당"].rank(ascending=False, method="min")

# ---------- 비교안 ----------
def mm10(x):
    return (x - x.min()) / (x.max() - x.min()) * 10

e_i = mm10(np.log1p(g["견인_1만명당"]))
v_i = mm10(g["취약위치비율_보정"])
d_i = mm10(np.log1p(g["주차구역거리m_정밀"].fillna(g["주차구역거리m_정밀"].median())))
g["비교_INFORM3"] = np.where(has, (np.exp((np.log1p(e_i) + np.log1p(v_i) + np.log1p(d_i)) / 3) - 1) * 10, np.nan).round(1)
pct = {k: g[c].rank(pct=True) for k, c in
       {"노출": "견인_1만명당", "취약": "취약위치비율_보정", "주차": "주차구역거리m_정밀"}.items()}
g["비교_가중3"] = np.where(has, (0.5 * pct["노출"] + 0.25 * pct["취약"] + 0.25 * pct["주차"]) * 100, np.nan).round(1)

top = set(g.nsmallest(TOP_N, "위험지수_순위")["행정동코드"])
print("[지표 간 순위 상관] 노출-주차거리 %.2f · 노출-취약 %.2f · 취약-주차거리 %.2f"
      % (pct["노출"].corr(pct["주차"]), pct["노출"].corr(pct["취약"]), pct["취약"].corr(pct["주차"])))
print(f"\n[위험 지수 민감도] 기본안(위해×취약성) 대비")
sens = []
for name, col in [("INFORM식 3차원 기하평균", "비교_INFORM3"), ("백분위 가중 평균 .5/.25/.25", "비교_가중3")]:
    t = set(g.loc[g[col].rank(ascending=False) <= TOP_N, "행정동코드"])
    rho = g.loc[has, "위험지수"].rank().corr(g.loc[has, col].rank())
    sens.append((name, rho, len(top & t)))
    print(f"  {name:26s} 순위 상관 {rho:.3f} · 상위{TOP_N} 겹침 {len(top & t)}/{TOP_N}")
for name, col in [("기본안", "위험지수"), ("INFORM식 3차원", "비교_INFORM3"), ("가중 평균", "비교_가중3")]:
    t = g[g[col].rank(ascending=False) <= TOP_N]
    print(f"  {name:14s} 상위{TOP_N}의 1만 명당 견인 순위 중앙값 {t['보정_순위'].median():.0f}위 · 노출과 순위 상관 "
          f"{g.loc[has, col].rank().corr(g.loc[has, '견인_1만명당'].rank()):.2f}")

# ---------- 공간 가중치 · Moran's I ----------
w = Queen.from_dataframe(g, use_index=False, silence_warnings=True)
print(f"\n공간가중치(Queen): 동 {w.n}개, 평균 이웃 {w.mean_neighbors:.1f}, 고립 동 {len(w.islands)}")
w.transform = "r"
moran_res = {}
print("[Moran's I] (순열 %d회)" % PERM)
for col in ["견인건수", "견인_1만명당", "위험지수"]:
    m = Moran(g[col].fillna(g[col].median()).values, w, permutations=PERM)
    moran_res[col] = (m.I, m.p_sim, m.z_sim)
    print(f"  {col:10s} I={m.I:.3f}  z={m.z_sim:.2f}  p={m.p_sim:.4f}")

# ---------- Getis-Ord Gi* (견인_1만명당) ----------
wb = Queen.from_dataframe(g, use_index=False, silence_warnings=True)
gi = G_Local(g["견인_1만명당"].values, wb, transform="B", star=True, permutations=PERM, seed=42)
g["Gi_z"], g["Gi_p"] = gi.Zs, gi.p_sim

def gi_class(z, p):
    for conf, a in ((99, 0.01), (95, 0.05), (90, 0.10)):
        if p <= a:
            return f"{'핫스팟' if z > 0 else '콜드스팟'} {conf}%"
    return "유의하지 않음"

g["Gi_분류"] = [gi_class(z, p) for z, p in zip(g["Gi_z"], g["Gi_p"])]
pv = np.sort(g["Gi_p"].values)
passed = pv <= 0.05 * np.arange(1, len(pv) + 1) / len(pv)        # Benjamini-Hochberg FDR 5%
fdr_cut = pv[passed].max() if passed.any() else 0.0
g["Gi_FDR유의"] = g["Gi_p"] <= fdr_cut
print("\n[Gi* — 견인_1만명당]")
print(g["Gi_분류"].value_counts().reindex(GI_COLORS.keys()).fillna(0).astype(int).to_string())
print(f"  FDR 5% (유의확률 ≤ {fdr_cut:.4f}): 핫스팟 {int((g['Gi_FDR유의'] & (g['Gi_z'] > 0)).sum())}개, "
      f"콜드스팟 {int((g['Gi_FDR유의'] & (g['Gi_z'] < 0)).sum())}개 동")

# ---------- 정책 대상지 ----------
cand = g[g["행정동코드"].isin(top)]
far = cand["주차구역거리m_정밀"] >= WALK_M
g["정책유형"] = "해당 없음"
g.loc[cand.index[far], "정책유형"] = "주차구역 증설 후보"
g.loc[cand.index[~far], "정책유형"] = "집중 수거·순찰 대상"
hot_fdr = g["Gi_FDR유의"] & (g["Gi_z"] > 0)
g.loc[hot_fdr & (g["정책유형"] == "해당 없음"), "정책유형"] = "집중 수거·순찰 대상"
g["보호·교통약자시설_견인"] = g["견인_보호구역"] + g["견인_점자블록·교통약자시설"]

rows = []
for _, r in g[g["정책유형"] == "주차구역 증설 후보"].sort_values("위험지수_순위").iterrows():
    rows.append(("주차구역 증설 후보", r, f"위험 {int(r['위험지수_순위'])}위, 주차구역까지 평균 {r['주차구역거리m_정밀']:,.0f}m"))
for _, r in g[g["정책유형"] == "집중 수거·순찰 대상"].sort_values(["위험지수_순위"]).iterrows():
    why = []
    if r["행정동코드"] in top:
        why.append(f"위험 {int(r['위험지수_순위'])}위, 주차구역 {r['주차구역거리m_정밀']:,.0f}m 이내에도 방치")
    if hot_fdr[_]:
        why.append(f"Gi* 핫스팟(FDR 5% 유의, z={r['Gi_z']:.1f})")
    rows.append(("집중 수거·순찰 대상", r, " / ".join(why)))
for _, r in g.nlargest(20, "보호·교통약자시설_견인").iterrows():
    rows.append(("보호구역·교통약자시설 점검 대상", r,
                 f"보호구역 {int(r['견인_보호구역'])}건, 점자블록·교통약자시설 {int(r['견인_점자블록·교통약자시설'])}건"))
policy = pd.DataFrame([{"정책": p, "행정동코드": r["행정동코드"], "자치구": r["자치구"], "행정동": r["행정동"],
                        "위험지수": r["위험지수"], "위험지수_순위": r["위험지수_순위"], "견인건수": r["견인건수"],
                        "근거": why} for p, r, why in rows])
policy.to_csv("policy_targets.csv", index=False, encoding="utf-8-sig")
print("\n[정책 대상지]", policy["정책"].value_counts().to_dict())

# ---------- 타당성 점검 ----------
val = []
for col, label in [("보호구역수", "보호구역"), ("지하철역수", "지하철역"), ("버스정류소수", "버스정류소")]:
    dens = g[col] / g["면적km2"]
    in_top = g["행정동코드"].isin(top)
    val.append({"시설": label, "단위": "개/km²",
                "위험지수와_순위상관": round(g.loc[has, "위험지수"].rank().corr(dens[has].rank()), 3),
                "견인건수와_순위상관": round(g["견인건수"].rank().corr(dens.rank()), 3),
                f"위험상위{TOP_N}_밀도중앙값": round(dens[in_top].median(), 2),
                "나머지_밀도중앙값": round(dens[~in_top & has].median(), 2)})
val = pd.DataFrame(val)
val.to_csv("validation.csv", index=False, encoding="utf-8-sig")
print("\n[타당성 점검 — 보행 밀집 시설 밀도]"); print(val.to_string(index=False))

# ---------- 저장 ----------
out_cols = ["행정동코드", "행정동명", "자치구", "행정동", "견인건수", "생활인구_평균", "견인_1만명당",
            "취약위치비율_보정", "취약위치견인_1만명당", "주차구역거리m_정밀", "주차구역수", "보호구역수",
            "위험지수", "위험지수_순위", "건수_순위", "보정_순위", "비교_INFORM3", "비교_가중3",
            "Gi_z", "Gi_p", "Gi_분류", "Gi_FDR유의", "정책유형"]
res = g[out_cols].copy()
for c in ["취약위치비율_보정", "Gi_z", "Gi_p"]:
    res[c] = res[c].round(4)
res["주차구역거리m_정밀"] = res["주차구역거리m_정밀"].round(0)
res.sort_values("위험지수_순위").to_csv("risk_index.csv", index=False, encoding="utf-8-sig")
res.sort_values("위험지수_순위").head(TOP_N)[
    ["위험지수_순위", "행정동명", "위험지수", "취약위치견인_1만명당", "견인건수", "건수_순위", "견인_1만명당", "보정_순위",
     "취약위치비율_보정", "주차구역거리m_정밀", "Gi_분류", "Gi_FDR유의", "정책유형"]
].to_csv("risk_candidates.csv", index=False, encoding="utf-8-sig")

# ---------- 지도 ----------
os.makedirs("figures", exist_ok=True)
gu = g.dissolve("자치구").reset_index()

def quantile_classes(s, k=5):
    q = np.nanquantile(s, np.linspace(0, 1, k + 1))
    idx = np.clip(np.searchsorted(q[1:-1], s, side="right"), 0, k - 1)
    return idx, [f"{q[i]:,.0f} ~ {q[i + 1]:,.0f}" for i in range(k)]

def titles(ax, title, sub=None):
    ax.set_title(title, fontsize=13, color=INK, loc="left", pad=24 if sub else 8)
    if sub:
        ax.text(0.0, 1.012, sub, transform=ax.transAxes, fontsize=8.5, color=INK2, va="bottom")

def legend_right(ax, handles, title):
    ax.legend(handles=handles, title=title, loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False,
              fontsize=8, title_fontsize=8.5, labelcolor=INK2, alignment="left")

def base_map(ax, colors):
    g.plot(ax=ax, color=colors, edgecolor=EDGE, linewidth=0.3)
    gu.boundary.plot(ax=ax, color=INK2, linewidth=0.6)
    ax.set_axis_off()

def draw_seq(ax, col, title, unit, sub=None):
    s = g[col].values.astype(float)
    idx, labels = quantile_classes(s)
    colors = np.array(SEQ5)[idx]
    colors[np.isnan(s)] = "#e1e0d9"
    base_map(ax, colors)
    titles(ax, title, sub)
    h = [Patch(facecolor=c, edgecolor="none", label=l) for c, l in zip(SEQ5, labels)][::-1]
    if np.isnan(s).any():
        h.append(Patch(facecolor="#e1e0d9", edgecolor="none", label="견인 없음"))
    legend_right(ax, h, f"{unit} (5분위)")

def number_top(ax, top_df, list_title, extra=None):
    lines = []
    for i, (_, r) in enumerate(top_df.iterrows(), 1):
        p = r.geometry.representative_point()
        ax.scatter(p.x, p.y, s=150, color=SURFACE, edgecolor=INK, linewidth=1.0, zorder=5)
        ax.text(p.x, p.y, str(i), ha="center", va="center", fontsize=7, fontweight="bold", color=INK, zorder=6)
        lines.append(f"{i:>2}  {r['자치구']} {r['행정동']}" + (f"  {extra(r)}" if extra else ""))
    ax.text(1.0, 0.0, list_title + "\n" + "\n".join(lines), transform=ax.transAxes, fontsize=8, color=INK2,
            va="bottom", ha="left", linespacing=1.5)

def save(fig, name):
    fig.savefig(f"figures/{name}", dpi=200, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)

# 1) 건수 vs 보정
fig, (a1, a2) = plt.subplots(1, 2, figsize=(19, 7.2), facecolor=SURFACE)
fig.subplots_adjust(wspace=0.45)
draw_seq(a1, "견인건수", "견인 건수", "건", "2021.7~2025.12 누적 · 번호는 상위 5개 동")
draw_seq(a2, "견인_1만명당", "생활인구 1만 명당 견인 건수", "건/1만 명", "생활인구로 보정 · 번호는 상위 5개 동")
number_top(a1, g.nlargest(5, "견인건수"), "상위 5")
number_top(a2, g.nlargest(5, "견인_1만명당"), "상위 5")
fig.text(0.13, 0.04, "생활인구: 서울 열린데이터광장 OA-23016 [내국인] 2026년 10월 평균 · 견인: 서울시 전동킥보드 견인 현황",
         fontsize=8, color=MUTED)
save(fig, "map_count_vs_rate.png")

# 2) Gi*
fig, ax = plt.subplots(figsize=(10, 7.2), facecolor=SURFACE)
base_map(ax, g["Gi_분류"].map(GI_COLORS))
cnt = g["Gi_분류"].value_counts()
legend_right(ax, [Patch(facecolor=c, edgecolor="#c3c2b7" if k == "유의하지 않음" else "none",
                        label=f"{k} ({cnt.get(k, 0)}개 동)") for k, c in GI_COLORS.items()],
             "Getis-Ord Gi*\n(순열 9,999회)")
hf = g[hot_fdr]
ax.scatter(hf.geometry.representative_point().x, hf.geometry.representative_point().y, marker="o", s=22,
           facecolor=INK, edgecolor=SURFACE, linewidth=0.8, zorder=5)
ax.text(1.0, 0.0, f"●  FDR 5% 보정 후에도 유의한\n    핫스팟 ({len(hf)}개 동)", transform=ax.transAxes, fontsize=8,
        color=INK2, va="bottom")
I, p, z = moran_res["견인_1만명당"]
titles(ax, "생활인구 1만 명당 견인 — 핫스팟·콜드스팟",
       f"전역 Moran's I = {I:.3f} (p = {p:.4f}) · Queen 인접 · 신뢰수준은 유의확률 기준")
save(fig, "map_hotspot_gi.png")

# 3) 위험 지수
fig, ax = plt.subplots(figsize=(10, 7.2), facecolor=SURFACE)
draw_seq(ax, "위험지수", "PM 방치 보행 위험 지수 (0~100)",
         "점", "위험 = 위해(1만 명당 견인) × 취약성(취약 위치 비율) · 서울 427개 동 중 백분위")
number_top(ax, g.nsmallest(10, "위험지수_순위"), "위험 지역 후보 상위 10")
save(fig, "map_risk_index.png")

# 4) 정책 대상지
fig, ax = plt.subplots(figsize=(10, 7.2), facecolor=SURFACE)
base_map(ax, g["정책유형"].map(POLICY_COLORS))
pc = g["정책유형"].value_counts()
legend_right(ax, [Patch(facecolor=c, edgecolor="#c3c2b7" if k == "해당 없음" else "none",
                        label=f"{k} ({pc.get(k, 0)}개 동)") for k, c in POLICY_COLORS.items()], "정책 유형")
insp = g.nlargest(20, "보호·교통약자시설_견인")
ax.scatter(insp.geometry.representative_point().x, insp.geometry.representative_point().y, marker="^", s=40,
           facecolor=INK, edgecolor=SURFACE, linewidth=0.8, zorder=5)
ax.text(1.0, 0.0, "▲  보호구역·교통약자시설 점검 대상\n    (해당 위치 견인 상위 20개 동)", transform=ax.transAxes,
        fontsize=8, color=INK2, va="bottom")
titles(ax, "정책별 대상지",
       f"위험 상위 {TOP_N}개 동: 주차구역 {WALK_M}m 이상 → 증설 / {WALK_M}m 미만 → 수거·순찰 · FDR 유의 핫스팟은 수거·순찰")
save(fig, "map_policy.png")

print("\n[위험 지역 후보 상위 15]")
print(res.sort_values("위험지수_순위").head(15)[["위험지수_순위", "행정동명", "위험지수", "건수_순위", "보정_순위",
                                               "주차구역거리m_정밀", "정책유형"]].to_string(index=False))
print("\n저장: risk_index.csv, risk_candidates.csv, policy_targets.csv, validation.csv, figures/*.png")
