import requests

REST_API_KEY = "https://developers.kakao.com/docs/ko/app-setting/app#rest-api-key"
url = "https://dapi.kakao.com/v2/local/search/address.json"
headers = {"Authorization": f"KakaoAK {REST_API_KEY}"}
params = {"query": "서울특별시 종로구 사직동"}

res = requests.get(url, headers=headers, params=params)
print(res.status_code)
print(res.json())