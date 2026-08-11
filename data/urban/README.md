# `data/urban/` — 南沙城市数据缓存

本目录由下载脚本本地生成，**大体积二进制不入库**（见根 `.gitignore`）。

## 数据产出

| 文件 | 来源 | 用途 |
|---|---|---|
| `nansha_roads.gpkg` | OSM（relation R3287345，OSMnx） | Stage 2 Grounding（#5）：`edges` 层供 `ox.nearest_edges` 匹配；`nodes` 层供 `ox.graph_from_gdfs` 重建图 |
| `nansha_srtm30m.tif` | NASA SRTMGL1 30m（AWS Skadi 镜像） | Stage 2 Elevation/Terrain Context（#6）：ElevationProvider / TerrainProvider 查询 |

## 重新生成

```bash
pip install -r requirements.txt
python scripts/download_osm_roads.py
python scripts/download_srtm.py
```

- **OSM 路网**：走 4 级边界回退（relation ID → 结构化地名 → 字符串地名 → 手动 bbox），`network_type=drive`。OSMnx HTTP 缓存存于 `data/osmnx_cache/`。
- **SRTM DEM**：优先 `elevation` 包（需系统 GDAL）；否则从 AWS Skadi 公开镜像（无需鉴权）下载 `.hgt.gz` 瓦片，rasterio 裁剪（**不依赖系统 GDAL**）。原始瓦片缓存于 `data/srtm_tiles/`。

Provenance（`source=srtm_local/osm`、`data_vintage`、`retrieved_at`）由 #6 provider 契约在查询时填充，下载脚本只落盘。

方案依据见 `research/osm_roads_nansha.md`（#2）与 `research/srtm_dem_nansha.md`（#3）。
