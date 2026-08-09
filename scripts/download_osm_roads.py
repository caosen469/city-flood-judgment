#!/usr/bin/env python3
"""南沙区道路网络下载与本地缓存.

实现 research/osm_roads_nansha.md（#2）的数据获取方案：用 OSMnx 按
南沙区行政边界（OSM relation R3287345）下载机动车路网，缓存为 GeoPackage。

产出
----
- ``data/urban/nansha_roads.gpkg``
    - ``edges`` 层 —— 每条路段一行，供 Stage 2 Grounding（#5）的
      ``ox.nearest_edges`` 匹配基（查询时用 ``ox.graph_from_gdfs`` 重建图）。
    - ``nodes`` 层 —— 路口节点，重建图所必需。

边界获取走 4 级回退（relation ID → 结构化地名 → 字符串地名 → 手动 bbox），
全失败则报错退出。路网 ``network_type="drive"``，并扩展 ``useful_tags_way``
以带上路面/照明等积水研判相关属性。

用法
----
    python scripts/download_osm_roads.py
    python scripts/download_osm_roads.py --network-type all --output data/urban/nansha_roads.gpkg

设计依据见 research/osm_roads_nansha.md §8。Provenance（source/data_vintage
/retrieved_at）由 #6 provider 契约在查询时填充，本脚本只落盘。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import osmnx as ox

# 南沙区 OSM relation（广州南沙，区别于三沙市同名南沙区 relation 6753263）。
NANSHA_RELATION = "R3287345"

# 手动回退 bbox（WGS-84），覆盖南沙区大致范围，略大于实际边界。
NANSHA_FALLBACK_BBOX = (113.32, 22.43, 113.78, 22.95)  # (west, south, east, north)

# 积水研判相关的额外 way 属性（在 OSMnx 默认 useful_tags_way 基础上扩展）。
EXTRA_WAY_TAGS = ["surface", "smoothness", "lit", "sidewalk", "name:zh"]

DEFAULT_OUTPUT = Path("data/urban/nansha_roads.gpkg")
DEFAULT_NETWORK_TYPE = "drive"


def get_nansha_boundary() -> gpd.GeoDataFrame:
    """获取南沙区行政边界，按可靠性依次尝试 4 种方式。

    Returns
    -------
    gpd.GeoDataFrame
        含南沙区边界 Polygon 的 GeoDataFrame（CRS = EPSG:4326）。

    Raises
    ------
    RuntimeError
        全部 4 种方式均失败。
    """
    # 方式 1：直接按 OSM relation ID（最精确，不依赖 Nominatim 模糊匹配）。
    try:
        print(f"[boundary] 尝试 by_osmid '{NANSHA_RELATION}' ...")
        gdf = ox.geocode_to_gdf(NANSHA_RELATION, by_osmid=True)
        print(f"[boundary] 成功（relation {NANSHA_RELATION}）")
        return gdf
    except Exception as e:  # noqa: BLE001
        print(f"[boundary] 失败：{e}")

    # 方式 2：结构化中文地名查询。
    try:
        print("[boundary] 尝试结构化查询（南沙区, 广州市, 广东省, 中国）...")
        gdf = ox.geocode_to_gdf(
            {"district": "南沙区", "city": "广州市", "state": "广东省", "country": "中国"}
        )
        print("[boundary] 成功（结构化地名）")
        return gdf
    except Exception as e:  # noqa: BLE001
        print(f"[boundary] 失败：{e}")

    # 方式 3：英文字符串地名 + which_result。
    try:
        print("[boundary] 尝试 'Nansha District, Guangzhou, Guangdong, China' ...")
        gdf = ox.geocode_to_gdf(
            "Nansha District, Guangzhou, Guangdong, China", which_result=1
        )
        print("[boundary] 成功（英文字符串）")
        return gdf
    except Exception as e:  # noqa: BLE001
        print(f"[boundary] 失败：{e}")

    # 方式 4：手动矩形 bbox（最终回退）。
    print("[boundary] 使用手动矩形 bbox 回退 ...")
    west, south, east, north = NANSHA_FALLBACK_BBOX
    from shapely.geometry import box

    gdf = gpd.GeoDataFrame(geometry=[box(west, south, east, north)], crs="EPSG:4326")
    print(f"[boundary] 使用近似矩形边界 ({west},{south})-({east},{north})")
    return gdf


def download_roads(
    boundary_gdf: gpd.GeoDataFrame,
    network_type: str,
    output_path: Path,
) -> gpd.GeoDataFrame:
    """下载南沙区道路网络并缓存为 GeoPackage（edges + nodes 两层）。

    Parameters
    ----------
    boundary_gdf : gpd.GeoDataFrame
        含南沙区边界的 GeoDataFrame。
    network_type : str
        OSMnx network_type（"drive" / "all" / "walk" / "bike"）。
    output_path : Path
        GeoPackage 输出路径。
    """
    polygon = boundary_gdf.union_all()
    print(f"[roads] 边界面积：{polygon.area / 1e6:.1f} deg²（WGS-84 度平方）")

    # 方式 1：按 polygon 下载；polygon 过大被拆分仍失败时回退到 bbox。
    try:
        print(f"[roads] 下载路网（graph_from_polygon, network_type={network_type}）...")
        G = ox.graph_from_polygon(
            polygon,
            network_type=network_type,
            simplify=True,
            truncate_by_edge=True,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[roads] graph_from_polygon 失败（{e}），回退到 bbox ...")
        minx, miny, maxx, maxy = polygon.bounds
        G = ox.graph_from_bbox(
            north=maxy, south=miny, east=maxx, west=minx,
            network_type=network_type, simplify=True,
        )

    gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)
    print(f"[roads] 获取到 {len(gdf_edges)} 条路段 / {len(gdf_nodes)} 个节点")

    # 缓存：edges 层（Grounding 匹配基）+ nodes 层（重建图所需）。
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()  # 全量重写，避免残留旧层
    gdf_edges.to_file(output_path, layer="edges", driver="GPKG")
    gdf_nodes.to_file(output_path, layer="nodes", driver="GPKG")
    print(f"[roads] 已缓存：{output_path.resolve()}")

    _print_summary(gdf_edges)
    return gdf_edges


def _print_summary(edges: gpd.GeoDataFrame) -> None:
    """打印路网概览（等级分布、命名覆盖率）。"""
    print("\n===== 南沙区道路网络概览 =====")
    print(f"总路段数：{len(edges)}")
    if "highway" in edges:
        # highway 列可能是 list（多条等级共一段），展开统计。
        flat = edges["highway"].explode()
        print("道路等级分布：")
        print(flat.value_counts().to_string())
    if "name" in edges:
        named = edges["name"].notna().sum()
        print(f"有名称路段：{named} / {len(edges)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--network-type", default=DEFAULT_NETWORK_TYPE,
        choices=["drive", "all", "walk", "bike"],
        help="OSMnx 路网类型（默认 drive）。",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="GeoPackage 输出路径。")
    args = parser.parse_args()

    # OSMnx 配置：启用 HTTP 缓存、扩展 way 属性。
    ox.settings.use_cache = True
    ox.settings.log_console = False
    ox.settings.cache_folder = str(Path("data/osmnx_cache"))
    for tag in EXTRA_WAY_TAGS:
        if tag not in ox.settings.useful_tags_way:
            ox.settings.useful_tags_way.append(tag)

    boundary = get_nansha_boundary()
    download_roads(boundary, args.network_type, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
