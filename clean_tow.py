"""견인 현황 정제: python clean_tow.py <원본csv> <출력폴더>"""
import sys, re, pandas as pd
src, out = sys.argv[1], sys.argv[2]
d = pd.read_csv(src, encoding='cp949', dtype=str)
n0 = len(d)

# 1) 구: 주소에서 추출 (구정보는 '중구 신'처럼 깨진 값이 많아 사용하지 않음)
d['주소'] = d['주소'].str.strip().str.replace(r'^서울시\s+', '서울특별시 ', regex=True)
d['주소'] = d['주소'].str.replace(r'\s+', ' ', regex=True)
d['자치구'] = d['주소'].str.extract(r'^서울특별시 (\S+구) ')[0]
d['자치구'] = d['자치구'].fillna(d['구정보'].str.split().str[0])

# 2) 날짜
d['신고일'] = pd.to_datetime(d['신고일시'], errors='coerce')
d['조치일'] = pd.to_datetime(d['조치일'], errors='coerce')
d['연도'] = d['신고일'].dt.year; d['월'] = d['신고일'].dt.month; d['요일'] = d['신고일'].dt.dayofweek

# 3) 유형 → 범주 (위에서부터 먼저 맞는 것)
rules = [
 ('오신고', r'오신고|허위'),
 ('보호구역', r'보호구역|어린이|노인|장애인|스쿨존'),
 ('횡단보도', r'횡단보도|건널목'),
 ('버스정류장·택시승강장', r'버스|택시|승강장|정류'),
 ('점자블록·교통약자시설', r'점자|엘리베이터|교통약자|휠체어|경사로|턱을 낮춘'),
 ('지하철역 출입구', r'지하철|역 ?(전면|진출입|출입)'),
 ('소방시설', r'소방|소화전'),
 ('건물·상가 출입', r'건물|상가|진출입'),
 ('교통섬', r'교통섬'),
 ('자전거도로', r'자전거'),
 ('차도', r'차도|주차'),
 ('보도', r'보도|산책로|인도'),
 ('통행불편(일반)', r'통행|불편|방해|제한|장애|위험|사고|수거|이동|치워|신고'),
]
def cat(x):
    if pd.isna(x) or not str(x).strip(): return '유형없음'
    for c, p in rules:
        if re.search(p, x): return c
    return '기타·분류불가'
d['유형'] = d['유형'].fillna('')
d['위치유형'] = d['유형'].map(cat)

# 4) 지번주소 → 법정동 + 지번 (지오코딩 입력용)
d['지오코딩주소'] = d['주소']
d['중복제거키'] = d['주소']

# 5) 품질 플래그
d['플래그_오신고'] = d['위치유형'].eq('오신고')
d['플래그_조치일이전'] = d['조치일'].notna() & (d['조치일'] < d['신고일'])
d['플래그_조치일없음'] = d['조치일'].isna()

keep = ['번호','신고일','조치일','연도','월','요일','자치구','주소','유형','위치유형','플래그_오신고','플래그_조치일이전','플래그_조치일없음']
d[keep].to_csv(f'{out}/tow_clean.csv', index=False, encoding='utf-8-sig')
u = d[['주소','자치구']].drop_duplicates('주소'); u.to_csv(f'{out}/tow_unique_addresses.csv', index=False, encoding='utf-8-sig')
m = d.groupby(['위치유형','유형']).size().reset_index(name='건수').sort_values(['위치유형','건수'], ascending=[True,False])
m.to_csv(f'{out}/type_mapping.csv', index=False, encoding='utf-8-sig')

print('원본', n0, '정제', len(d)); print('자치구', d['자치구'].nunique(), d['자치구'].isna().sum(), '결측')
print(d['위치유형'].value_counts().to_string())
print('고유주소', len(u)); print(d[['플래그_오신고','플래그_조치일이전','플래그_조치일없음']].sum().to_string())
