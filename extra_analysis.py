"""보조 분석: 반복 방치 지점, 로드뷰 확인 목록, 연도·월·요일별 집계
python extra_analysis.py     (aggregate_dong.py, hotspot_risk.py 실행 후)

입력: tow_with_dong.csv, tow_geocoded_final.csv, risk_index.csv
출력:
- repeat_hotspots.csv      상시 점검 대상 지점: 같은 주소에서 누적 100건 이상, 3개 연도 이상 반복 견인
- roadview_checklist.csv   위험 상위 10개 동의 최다 견인 지점 + 카카오맵 로드뷰 링크 (현장 확인용)
- time_year_dong.csv       행정동 × 연도 견인 건수
- time_weekday_dong.csv    행정동 × 요일 견인 건수
- time_month.csv           서울 전체 연-월 견인 건수
- figures/chart_monthly.png, figures/chart_weekday.png
주의: 정밀 좌표(상태 ok)만 지점 분석에 사용 (동 대표점 ok_dong은 같은 지점으로 묶이면 왜곡). 신고 시각이
없어 시간대 분석은 하지 않음. 2021년은 7월 15일부터 집계.
"""
import os
import warnings

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")
matplotlib.rcParams["font.family"] = "Malgun Gothic"
matplotlib.rcParams["axes.unicode_minus"] = False
SURFACE, INK, INK2, MUTED, GRID, AXIS, BLUE = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7", "#2a78d6"
REPEAT_MIN_N, REPEAT_MIN_YEARS = 100, 3
VUL_TYPES = ["횡단보도", "버스정류장·택시승강장", "보호구역", "점자블록·교통약자시설", "지하철역 출입구"]
WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]

w = pd.read_csv("tow_with_dong.csv", dtype={"행정동코드": str, "번호": str})
w["신고일"] = pd.to_datetime(w["신고일"])
w["연도"], w["월"], w["요일"] = w["신고일"].dt.year, w["신고일"].dt.month, w["신고일"].dt.dayofweek
risk = pd.read_csv("risk_index.csv", dtype={"행정동코드": str})
names = risk.set_index("행정동코드")[["자치구", "행정동", "위험지수", "위험지수_순위"]]
geo = pd.read_csv("tow_geocoded_final.csv", dtype=str)[["주소", "x경도", "y위도"]]

# ---------- 반복 방치 지점 ----------
ok = w[w["상태"] == "ok"].copy()
ok["취약"] = ok["위치유형"].isin(VUL_TYPES)
agg = ok.groupby("주소").agg(
    행정동코드=("행정동코드", "first"), 견인건수=("번호", "size"), 반복연도수=("연도", "nunique"),
    첫신고일=("신고일", "min"), 마지막신고일=("신고일", "max"), 취약위치비율=("취약", "mean"),
    주요위치유형=("위치유형", lambda s: s.value_counts().index[0]))
agg = agg.reset_index().merge(geo, on="주소", how="left").join(names, on="행정동코드")
rep = agg[(agg["견인건수"] >= REPEAT_MIN_N) & (agg["반복연도수"] >= REPEAT_MIN_YEARS)].sort_values("견인건수", ascending=False)
rep["취약위치비율"] = rep["취약위치비율"].round(3)
rep["첫신고일"], rep["마지막신고일"] = rep["첫신고일"].dt.date, rep["마지막신고일"].dt.date
rep.insert(0, "순위", range(1, len(rep) + 1))
cols = ["순위", "주소", "자치구", "행정동", "견인건수", "반복연도수", "첫신고일", "마지막신고일", "주요위치유형",
        "취약위치비율", "위험지수", "y위도", "x경도"]
rep[cols].to_csv("repeat_hotspots.csv", index=False, encoding="utf-8-sig")
print(f"[반복 방치 지점] 누적 {REPEAT_MIN_N}건 이상·{REPEAT_MIN_YEARS}개 연도 이상: {len(rep)}곳 "
      f"(정밀 좌표 주소 {len(agg):,}곳의 {len(rep) / len(agg):.1%}, 견인 {rep['견인건수'].sum() / len(ok):.1%})")
print("  위험 상위 30개 동 안에 있는 지점:", int((rep["위험지수_순위"] <= 30).sum()))
print(rep[cols[:9]].head(10).to_string(index=False))

# ---------- 로드뷰 확인 목록 ----------
top10 = names.sort_values("위험지수_순위").head(10).index
chk = (agg[agg["행정동코드"].isin(top10)].sort_values("견인건수", ascending=False)
       .groupby("행정동코드").head(2).sort_values(["위험지수_순위", "견인건수"], ascending=[True, False]))
chk["로드뷰"] = "https://map.kakao.com/link/roadview/" + chk["y위도"] + "," + chk["x경도"]
chk["지도"] = "https://map.kakao.com/link/map/" + chk["주소"].str.replace(",", " ") + "," + chk["y위도"] + "," + chk["x경도"]
chk["확인 결과(직접 기입)"] = ""
chk[["위험지수_순위", "자치구", "행정동", "주소", "견인건수", "주요위치유형", "로드뷰", "지도", "확인 결과(직접 기입)"]] \
    .to_csv("roadview_checklist.csv", index=False, encoding="utf-8-sig")
print(f"\n[로드뷰 확인 목록] 위험 상위 10개 동 × 최다 견인 지점 2곳 = {len(chk)}곳")

# ---------- 연도·월·요일 집계 ----------
yd = w.pivot_table(index="행정동코드", columns="연도", values="번호", aggfunc="size", fill_value=0)
yd.columns = [f"{c}년" for c in yd.columns]
names.join(yd, how="right").reset_index().sort_values("위험지수_순위") \
    .to_csv("time_year_dong.csv", index=False, encoding="utf-8-sig")
wd = w.pivot_table(index="행정동코드", columns="요일", values="번호", aggfunc="size", fill_value=0)
wd.columns = WEEKDAY
names.join(wd, how="right").reset_index().sort_values("위험지수_순위") \
    .to_csv("time_weekday_dong.csv", index=False, encoding="utf-8-sig")
mon = w.groupby(w["신고일"].dt.to_period("M")).size().rename("견인건수")
mon.index = mon.index.astype(str)
mon.to_frame().to_csv("time_month.csv", index_label="연월", encoding="utf-8-sig")

# 요일별 하루 평균 (요일마다 날짜 수가 달라 날짜 수로 나눔)
days = pd.Series(pd.date_range(w["신고일"].min(), w["신고일"].max())).dt.dayofweek.value_counts().sort_index()
wk = (w.groupby("요일").size() / days).round(1)
yr = w.groupby("연도").size()
print("\n[연도별]", yr.to_dict(), "(2021년은 7.15~)")
print("[요일별 하루 평균]", dict(zip(WEEKDAY, wk.values)))
print(f"[월별] 최다 {mon.idxmax()} {mon.max():,}건 · 최소 {mon.idxmin()} {mon.min():,}건")

# ---------- 그래프 ----------
os.makedirs("figures", exist_ok=True)

def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)

# 월별 추이 (선 하나 → 범례 없음, 제목이 이름)
fig, ax = plt.subplots(figsize=(11, 4.2), facecolor=SURFACE)
style(ax)
x = np.arange(len(mon))
ax.plot(x, mon.values, color=BLUE, linewidth=2, solid_capstyle="round")
ticks = [i for i, m in enumerate(mon.index) if m.endswith("-01") or i == 0]
ax.set_xticks(ticks, [mon.index[i][:4] + "년" if mon.index[i].endswith("-01") else mon.index[i] for i in ticks])
ax.set_ylim(0, mon.max() * 1.15)
ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
i_max = int(np.argmax(mon.values))
ax.scatter([i_max], [mon.values[i_max]], s=40, color=BLUE, edgecolor=SURFACE, linewidth=2, zorder=3)
ax.annotate(f"최다 {mon.index[i_max]} · {mon.values[i_max]:,}건", (i_max, mon.values[i_max]), xytext=(8, 4),
            textcoords="offset points", fontsize=8.5, color=INK)
ax.set_title("서울 전동킥보드 월별 견인 건수", loc="left", fontsize=13, color=INK, pad=22)
ax.text(0, 1.03, "2021.7.15~2025.12.31 · 오신고 제외 · 행정동 배정 건 기준", transform=ax.transAxes, fontsize=8.5, color=INK2)
fig.savefig("figures/chart_monthly.png", dpi=200, bbox_inches="tight", facecolor=SURFACE)
plt.close(fig)

# 요일별 하루 평균
fig, ax = plt.subplots(figsize=(7, 4.2), facecolor=SURFACE)
style(ax)
bars = ax.bar(WEEKDAY, wk.values, color=BLUE, width=0.6)
for b, v in zip(bars, wk.values):
    ax.text(b.get_x() + b.get_width() / 2, v, f"{v:,.0f}", ha="center", va="bottom", fontsize=8.5, color=INK2)
ax.set_ylim(0, wk.max() * 1.18)
ax.set_title("요일별 하루 평균 견인 건수", loc="left", fontsize=13, color=INK, pad=22)
ax.text(0, 1.03, "요일마다 날짜 수가 달라 해당 요일 일수로 나눈 값 · 신고일 기준", transform=ax.transAxes, fontsize=8.5, color=INK2)
fig.savefig("figures/chart_weekday.png", dpi=200, bbox_inches="tight", facecolor=SURFACE)
plt.close(fig)
print("\n저장: repeat_hotspots.csv, roadview_checklist.csv, time_*.csv, figures/chart_*.png")
