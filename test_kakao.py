"""카카오 주소 검색 API 연결 테스트: python test_kakao.py [검색할 주소]

사전 준비: 프로젝트 폴더에 .env 파일을 만들고 아래 한 줄을 넣는다 (.env.example 참고).
    KAKAO_REST_API_KEY=발급받은_REST_API_키
"""
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "").strip()
if not REST_API_KEY:
    sys.exit("KAKAO_REST_API_KEY가 없습니다. .env 파일에 KAKAO_REST_API_KEY=키 를 넣어주세요.")

url = "https://dapi.kakao.com/v2/local/search/address.json"
headers = {"Authorization": f"KakaoAK {REST_API_KEY}"}
query = " ".join(sys.argv[1:]) or "서울특별시 종로구 사직동"

res = requests.get(url, headers=headers, params={"query": query}, timeout=10)
print("상태코드:", res.status_code)
if res.status_code != 200:
    sys.exit(f"요청 실패: {res.text}")

docs = res.json().get("documents", [])
print(f"'{query}' 검색 결과 {len(docs)}건")
for d in docs[:5]:
    print(f"- {d['address_name']}  (경도 x={d['x']}, 위도 y={d['y']})")
