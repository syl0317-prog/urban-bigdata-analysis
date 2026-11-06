import geopandas as gpd

gdf = gpd.read_file("HangJeongDong_ver20261001.geojson")  
seoul = gdf[gdf["adm_cd"].str.startswith("11")].copy()

print(len(seoul), "개 행정동")
print(seoul[["adm_cd", "adm_nm"]].head())

seoul.to_file("seoul_hjd_boundary.geojson", driver="GeoJSON")