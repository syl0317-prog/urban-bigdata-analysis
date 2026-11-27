# 도시빅데이터분석

## 👥 팀원
- 신유림
- 한지민

## 📂 데이터셋 목록
본 저장소는 서울시 도시빅데이터 분석을 위한 공간 및 교통 관련 데이터셋을 포함하고 있습니다.

1. **서울시 전동킥보드 견인 현황.csv** (29.8 MB)
   - 서울시 내 전동킥보드 불법 주정차 및 견인 조치 현황 데이터
2. **서울시 전동킥보드 주차구역 현황.csv** (15.8 KB)
   - 서울시 공식 전동킥보드 전용 주차구역 위치 및 상세 정보
3. **노인. 장애인보호구역 지정현황(2026.6월말 기준).hwpx** (82.3 KB)
   - 서울시 노인 및 장애인 보호구역 지정 현황 문서
4. **어린이 보호구역 지정현황(2026.6월말 기준).xlsx** (223 KB)
   - 서울시 어린이 보호구역(스쿨존) 지정 위치 및 시설 정보
5. **서울시버스정류소위치정보(20260902).xlsx** (741 KB)
   - 서울시 시내버스 정류소별 고유번호, 정류소명, 좌표(WGS84) 정보
6. **전체_도시철도역사정보_20260630.xlsx** (313 KB)
   - 수도권 도시철도(지하철) 노선별 역사 명칭, 호선, 위치 정보
7. **생활인구 — `pop_full_202610/250_LOCAL_RESD_ADMDONG_YYYYMMDD.csv`** (31개 파일, 분석에 사용)
   - 서울 열린데이터광장 OA-23016 [내국인] 행정동별 서울 생활인구(250m), 2026년 10월 (서울에 머문 내국인 전체, 통근자 포함)
   - ⚠️ 저장소에서 제외. OA-23016에서 `250_LOCAL_RESD_ADMDONG_202610.zip`(35MB)을 받아 `pop_full_202610/` 폴더에 압축 해제
   - 참고: 예전 파일 `250_ORGN_CT_IN_SE_20261017.csv`(OA-22851, 서울 거주자만·하루치)는 `pop_full_*/`가 없을 때만 사용
8. **HangJeongDong_ver20261001.geojson** (34.7 MB) → **seoul_hjd_boundary.geojson** (0.9 MB)
   - 전국 행정동 경계에서 서울(코드 `11`로 시작)만 추출한 행정동 경계 (`boundary.py`)

## 🧹 가공 데이터 (`clean_tow.py` 생성)
- **tow_clean.csv** — 견인 현황 정제본 (자치구, 연·월·요일, 위치유형 범주, 품질 플래그)
- **tow_unique_addresses.csv** — 지오코딩 대상 고유 주소 목록
- **type_mapping.csv** — 원본 `유형` 문구 → 위치유형 범주 매핑과 건수

```
python clean_tow.py "서울시 전동킥보드 견인 현황.csv" .
```

## 📍 주차구역·보호구역 지오코딩 (`geocode_zones.py`, 카카오 로컬 API, WGS84)
- **parking_geocoded.csv** — 주차구역 329곳 + 위도/경도 (328곳 성공, 99.7%)
- **protect_zone_geocoded.csv** — 보호구역 1,855곳 (구역유형: 어린이 1,630 / 노인 196 / 장애인 29) + 위도/경도 (1,851곳 성공, 99.8%)
- **geocode_failures.csv** — 좌표를 찾지 못한 5건 (폐업·주소 변경 추정)
- 검색 순서: 주소검색 → 키워드(주소) → 주소 표기 정리 후 재검색 → 키워드(시설명/상세위치). 결과 자치구가 원본과 다르면 버림
- `지오코딩방법`, `매칭주소`, `매칭장소` 열로 각 좌표가 어떻게 잡혔는지 확인 가능

```
python geocode_zones.py
```

## ⚙️ 환경 설정
`venv/`는 저장소에 올리지 않습니다. 각자 가상환경을 만들어 사용하세요.
```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
API 키(카카오 등)는 코드에 직접 쓰지 말고 `.env` 파일에 보관합니다 (`.gitignore` 처리됨).
`.env.example`을 복사해 `.env`로 만든 뒤 `KAKAO_REST_API_KEY`에 본인 REST API 키를 넣고, `python test_kakao.py`로 연결을 확인하세요.

## 🔥 핫스팟·위험 지수·정책 대상지 (`hotspot_risk.py`)
`aggregate_dong.py`를 먼저 실행해 `dong_stats.csv`, `tow_with_dong.csv`를 만든 뒤 실행합니다.
```
python hotspot_risk.py
python extra_analysis.py
```
- **Moran's I** (Queen 인접, 순열 9,999회): 견인 건수, 1만 명당 견인, 위험 지수의 전역 공간 자기상관
- **Getis-Ord Gi\*** (1만 명당 견인): 핫스팟·콜드스팟 90/95/99% 분류 + Benjamini-Hochberg FDR 5% 보정
- **위험 지수 (0~100)** = 위해 × 취약성 (UNDRR 2017; Wisner et al. 2004) — 생활인구 1만 명당 견인 × 취약 위치 비율(횡단보도·버스정류장·보호구역·점자블록·지하철 출입구, 서울 평균 쪽으로 축소 보정)의 백분위
  - 주차구역 거리는 INFORM 위험 지수의 '대응역량 부족'에 해당하지만, 견인이 많은 곳에 주차구역이 이미 있어 지수에 합치면 방치 정도가 반영되지 않음 → 정책 처방 축으로 분리
  - 비교안: INFORM식 3차원 기하평균, 백분위 가중 평균(0.5/0.25/0.25) — `risk_index.csv`의 `비교_*` 열
- **정책 대상지**: 위험 상위 30개 동 중 주차구역 400m 이상 → 증설 후보, 400m 미만 → 집중 수거·순찰, FDR 유의 핫스팟 → 집중 수거·순찰, 보호구역·교통약자시설 견인 상위 20개 동 → 점검 대상
- 출력: `risk_index.csv`, `risk_candidates.csv`, `policy_targets.csv`, `validation.csv`, `figures/map_*.png`

## 🔁 보조 분석 (`extra_analysis.py`)
- `repeat_hotspots.csv` — 상시 점검 대상 지점: 같은 주소에서 누적 100건 이상·3개 연도 이상 반복 견인 (244곳, 전체 견인의 17%)
- `roadview_checklist.csv` — 위험 상위 10개 동의 최다 견인 지점 20곳 + 카카오맵 로드뷰 링크 (현장 확인 결과를 직접 기입)
- `time_year_dong.csv`, `time_weekday_dong.csv`, `time_month.csv` — 연도·요일·월별 집계, `figures/chart_monthly.png`, `figures/chart_weekday.png`
- 주의: 견인은 평일 하루 약 240건, 주말 약 10건 → 신고일은 실제 방치 시점보다 행정 처리 일정을 반영
