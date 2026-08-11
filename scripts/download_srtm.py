#!/usr/bin/env python3
"""南沙区 SRTM 30m DEM 下载与本地缓存.

实现 research/srtm_dem_nansha.md（#3）的数据获取方案：下载覆盖南沙区的
NASA SRTMGL1 v003 30m DEM，裁剪到南沙范围，缓存为单个 GeoTIFF。

产出
----
- ``data/urban/nansha_srtm30m.tif`` —— 南沙覆盖范围 SRTM 30m GeoTIFF，
  供 ElevationProvider / TerrainProvider（#6）查询高程与地形。

下载策略
--------
1. **首选**：若 ``elevation``（bopen/elevation）包可用，用它从 NASA 源裁剪
   （research §1 推荐；但需要系统 GDAL 的 ``gdal_translate``）。
2. **回退**：直接从 AWS Mapzen/Skadi 公开镜像（无需鉴权）下载覆盖 bbox 的
   ``.hgt.gz`` 瓦片，gunzip 后用 rasterio（自带 GDAL）读取并按 bbox 窗口裁剪，
   写出 GeoTIFF。**不依赖系统 GDAL** —— rasterio 内置的 GDAL 原生支持 HGT 读取
   与 GeoTIFF 写出。

覆盖南沙的 SRTM 瓦片：主瓦片 ``N22E113.hgt``（22–23°N, 113–114°E），
完整覆盖南沙 bbox（113.28–113.72°E, 22.48–23.02°N）。脚本按 bbox 自动
计算所需瓦片，跨瓦片边界时下载并拼接全部所需瓦片。

用法
----
    python scripts/download_srtm.py
    python scripts/download_srtm.py --margin 0.05

设计依据见 research/srtm_dem_nansha.md §1/§2。Provenance（source=srtm_local
/data_vintage/retrieved_at）由 #6 provider 契约在查询时填充，本脚本只落盘。
"""
from __future__ import annotations

import argparse
import gzip
import io
import shutil
import sys
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.transform import from_bounds
from rasterio.windows import from_bounds as window_from_bounds

# 南沙覆盖 bbox（WGS-84），取南沙大致范围并加边距。
NANSHA_BBOX = (113.3, 22.5, 113.7, 23.0)  # (west, south, east, north)，依 research §1
DEFAULT_MARGIN = 0.02  # 度，约 2km 边距，覆盖边界查询（research §1 建议 0.02）

DEFAULT_OUTPUT = Path("data/urban/nansha_srtm30m.tif")
SRTM_CACHE_DIR = Path("data/srtm_tiles")  # 原始 .hgt 瓦片缓存（避免重复下载）

# AWS Mapzen/Skadi 公开镜像（无需鉴权）。瓦片按西南角整数经纬度命名，gzip 压缩。
SKADI_BASE = "https://elevation-tiles-prod.s3.amazonaws.com/skadi"
SRTM_NODATA = -32768


# --------------------------------------------------------------------------- #
# 方式 1：bopen/elevation（首选，需要系统 GDAL）
# --------------------------------------------------------------------------- #
def download_via_elevation_pkg(bbox: tuple[float, float, float, float], output: Path) -> bool:
    """尝试用 bopen/elevation 包下载；成功返回 True。

    elevation 包内部调用系统 ``gdal_translate``，需系统安装 GDAL。
    本机若无系统 GDAL，会抛异常，调用方应回退到直接下载路径。
    """
    try:
        import elevation  # noqa: PLC0415
    except ImportError:
        print("[srtm] elevation 包未安装，跳过该路径。")
        return False

    print("[srtm] 使用 bopen/elevation 包下载（需要系统 GDAL）...")
    output.parent.mkdir(parents=True, exist_ok=True)
    elevation.clip(bounds=bbox, output=str(output))
    print(f"[srtm] 已缓存：{output.resolve()}")
    return True


# --------------------------------------------------------------------------- #
# 方式 2：直接 .hgt.gz 下载 + rasterio 裁剪（回退，无需系统 GDAL）
# --------------------------------------------------------------------------- #
def _tile_name(lat_floor: int, lon_floor: int) -> str:
    """生成 SRTM 瓦片名，如 (22,113) -> 'N22E113'。"""
    ns = "N" if lat_floor >= 0 else "S"
    ew = "E" if lon_floor >= 0 else "W"
    return f"{ns}{abs(lat_floor):02d}{ew}{abs(lon_floor):03d}"


def _needed_tiles(bbox: tuple[float, float, float, float]) -> list[tuple[int, int]]:
    """计算覆盖 bbox 所需的（lat_floor, lon_floor）瓦片集合。

    bbox = (west, south, east, north)。瓦片覆盖 [floor, floor+1] 区间。
    """
    west, south, east, north = bbox
    tiles: set[tuple[int, int]] = set()
    lon = int(np.floor(west))
    while lon <= int(np.floor(east)):
        lat = int(np.floor(south))
        while lat <= int(np.floor(north)):
            tiles.add((lat, lon))
            lat += 1
        lon += 1
    return sorted(tiles)


def _download_tile(lat_floor: int, lon_floor: int) -> Path:
    """下载并解压单个 SRTM .hgt 瓦片到本地缓存，返回 .hgt 路径。"""
    name = _tile_name(lat_floor, lon_floor)
    gz_url = f"{SKADI_BASE}/{name[:3]}/{name}.hgt.gz"  # 子目录如 'N22'
    hgt_path = SRTM_CACHE_DIR / f"{name}.hgt"
    if hgt_path.exists():
        print(f"[srtm] 瓦片 {name} 已缓存：{hgt_path}")
        return hgt_path

    print(f"[srtm] 下载瓦片 {name} <- {gz_url} ...")
    SRTM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(gz_url, timeout=120) as resp:  # noqa: S310 — 公开镜像
        raw = resp.read()
    with gzip.open(io.BytesIO(raw)) as gz:
        with open(hgt_path, "wb") as f:
            shutil.copyfileobj(gz, f)
    print(f"[srtm] 瓦片 {name} 解压完成（{hgt_path.stat().st_size / 1e6:.1f} MB）")
    return hgt_path


def download_via_direct_clip(
    bbox: tuple[float, float, float, float], output: Path
) -> None:
    """直接下载 .hgt 瓦片并用 rasterio 裁剪到 bbox（无需系统 GDAL）。

    多瓦片时先拼接（merge），再按 bbox 窗口裁剪写出。
    """
    tiles = _needed_tiles(bbox)
    print(f"[srtm] 覆盖 bbox 需 {len(tiles)} 个瓦片：{[_tile_name(*t) for t in tiles]}")
    hgt_paths = [_download_tile(*t) for t in tiles]

    output.parent.mkdir(parents=True, exist_ok=True)

    if len(hgt_paths) == 1:
        _clip_single(hgt_paths[0], bbox, output)
    else:
        _merge_and_clip(hgt_paths, bbox, output)

    print(f"[srtm] 已缓存：{output.resolve()}")


def _clip_single(hgt_path: Path, bbox: tuple[float, float, float, float], output: Path) -> None:
    """单瓦片：按 bbox 窗口读取并写出 GeoTIFF。"""
    west, south, east, north = bbox
    with rasterio.open(hgt_path) as src:
        win = window_from_bounds(west, south, east, north, src.transform)
        win = win.round_lengths(op="ceil").round_offsets(op="floor")
        data = src.read(1, window=win, boundless=True, fill_value=SRTM_NODATA)
        # 窗口对应的仿射变换：以窗口左上像素对齐源栅格。
        win_transform = src.window_transform(win)
        profile = {
            "driver": "GTiff", "height": data.shape[0], "width": data.shape[1],
            "count": 1, "dtype": "int16", "crs": src.crs,
            "transform": win_transform, "nodata": SRTM_NODATA,
            "compress": "deflate",
        }
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(data, 1)

    _report_stats(output)


def _merge_and_clip(hgt_paths: list[Path], bbox: tuple[float, float, float, float], output: Path) -> None:
    """多瓦片：先 mosaic 再按 bbox 裁剪写出。"""
    west, south, east, north = bbox
    srcs = [rasterio.open(p) for p in hgt_paths]
    try:
        mosaic_arr, mosaic_transform = merge(srcs)
        mosaic_crs = srcs[0].crs
    finally:
        for s in srcs:
            s.close()

    band = mosaic_arr[0]
    mosaic_profile = {
        "driver": "GTiff", "height": band.shape[0], "width": band.shape[1],
        "count": 1, "dtype": "int16", "crs": mosaic_crs,
        "transform": mosaic_transform, "nodata": SRTM_NODATA, "compress": "deflate",
    }
    # 先落盘 mosaic，再用窗口裁剪（保持简单）。
    mosaic_tmp = SRTM_CACHE_DIR / "_mosaic.tif"
    with rasterio.open(mosaic_tmp, "w", **mosaic_profile) as dst:
        dst.write(band.astype("int16"), 1)

    with rasterio.open(mosaic_tmp) as src:
        win = window_from_bounds(west, south, east, north, src.transform)
        win = win.round_lengths(op="ceil").round_offsets(op="floor")
        data = src.read(1, window=win, boundless=True, fill_value=SRTM_NODATA)
        win_transform = src.window_transform(win)
        profile = {
            "driver": "GTiff", "height": data.shape[0], "width": data.shape[1],
            "count": 1, "dtype": "int16", "crs": src.crs,
            "transform": win_transform, "nodata": SRTM_NODATA, "compress": "deflate",
        }
        with rasterio.open(output, "w", **profile) as dst:
            dst.write(data, 1)
    mosaic_tmp.unlink(missing_ok=True)
    _report_stats(output)


def _report_stats(tif_path: Path) -> None:
    """打印裁剪后 DEM 的高程范围，供人工 sanity check。"""
    with rasterio.open(tif_path) as src:
        arr = src.read(1, masked=True)
        crs = src.crs
        bounds = src.bounds
    valid = arr.compressed()
    if valid.size:
        print(
            f"[srtm] 高程范围：min={valid.min()}m  max={valid.max()}m  "
            f"mean={valid.mean():.1f}m  有效像素={valid.size}  "
            f"shape={arr.shape}  crs={crs}"
        )
    print(
        f"[srtm] 地理范围：W={bounds.left}  S={bounds.bottom}  "
        f"E={bounds.right}  N={bounds.top}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--margin", type=float, default=DEFAULT_MARGIN,
                        help="bbox 四周外扩边距（度），默认 0.02（约 2km）。")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="GeoTIFF 输出路径。")
    args = parser.parse_args()

    west, south, east, north = NANSHA_BBOX
    bbox = (west - args.margin, south - args.margin, east + args.margin, north + args.margin)
    print(f"[srtm] 目标 bbox（含边距 {args.margin}°）：{bbox}")

    # 首选 elevation 包；失败/不可用则回退到直接下载 + rasterio 裁剪。
    if not download_via_elevation_pkg(bbox, args.output):
        download_via_direct_clip(bbox, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
