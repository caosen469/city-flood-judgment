# OSM 道路网络数据获取调研：广州市南沙区

> 调研日期：2026-08-08
> 目的：为南沙积水研判项目确定获取广州市南沙区道路网络数据的最佳方案

---

## 1. 数据获取工具/API 对比

### 1.1 OSMnx（推荐首选）

**原理**：OSMnx 本质上是 Overpass API 的 Python 封装，内部调用 Nominatim 做地理编码、调用 Overpass API 下载数据。
[OSMnx 用户手册](https://osmnx.readthedocs.io/en/stable/user-reference.html)

**核心函数**：

| 函数 | 用途 |
|---|---|
| `ox.graph_from_place()` | 按地名下载道路网络 |
| `ox.graph_from_bbox()` | 按经纬度矩形框下载 |
| `ox.graph_from_polygon()` | 按自定义 Polygon/MultiPolygon 下载 |
| `ox.graph_from_point()` | 按某点周围距离下载 |
| `ox.features_from_place()` | 下载指定地名的任意 OSM 要素（含行政边界） |
| `ox.geocode_to_gdf()` | 将地名地理编码为边界 Polygon |

**优点**：
- Pythonic 接口，一行代码即可完成下载
- 自动处理大区域分片（`max_query_area_size` 默认 50km x 50km，超出自动拆分为多次请求）
- 默认启用 HTTP 缓存（`use_cache=True`），避免重复下载
- `custom_filter` 参数支持自定义 Overpass QL 过滤器
- 默认缓存目录为 `./cache`

**缺点**：
- 依赖 Nominatim 地理编码，对中国地名的支持不够可靠
- 本质依赖 Overpass API，受其速率限制

### 1.2 Overpass API

**原理**：只读 API，客户端发送 QL 查询语句，服务端返回匹配数据。
[Overpass API 文档](https://wiki.openstreetmap.org/wiki/Overpass_API)

**优点**：
- 灵活的 QL 查询语法，可按标签、空间、递归关系精确查询
- 支持 area-based 查询（`area[name="南沙区"]`）
- 输出格式：XML、JSON、CSV、GeoJSON
- 公共端点 `https://overpass-api.de/api/interpreter` 免费使用（fair-use 上限约 10,000 次/天、1 GB/天）

**缺点**：
- 需要学习 Overpass QL 查询语法
- 不适合国家规模的批量下载（官方建议用 planet.osm 镜像）
- 大查询无 ETA 提示
- 数据更新有分钟级延迟

**Overpass QL 按区查询道路的示例**：
```sql
[out:json][timeout:300];
area[name="南沙区"][admin_level=6][boundary=administrative]->.nansha;
way(area.nansha)[highway];
(._;>;);
out body;
```

### 1.3 Geofabrik 下载

**原理**：定期从 OSM 主数据库提取区域快照，提供静态文件下载。
[Geofabrik 中国页面](https://download.geofabrik.de/asia/china.html)
[Geofabrik 广东页面](https://download.geofabrik.de/asia/china/guangdong.html)

**关键信息**：

| 层级 | 文件 | 大小 |
|---|---|---|
| 全国 | `china-latest.osm.pbf` | 1.5 GB |
| 广东省（含港澳） | `guangdong-latest.osm.pbf` | 162 MB |
| 广东省（含港澳） | `guangdong-latest-free.gpkg.zip` | 318 MB |
| 广州市/南沙区 | **无单独提取** | — |

**优点**：
- 下载稳定，不依赖 API 可用性
- 有 `.pbf`、`.shp.zip`、`.gpkg.zip` 多种格式
- 提供每日更新文件（`.osc.gz`）

**缺点**：
- 广东省是最小子区域，无广州市或南沙区的独立提取
- 中国道路数据覆盖率受本地政策限制（见下文 1.4）
- 需要自行按边界裁剪（用 OSMnx 或 geopandas 裁剪 162 MB 的广东 PBF）

### 1.4 中国 OSM 数据质量说明

根据 [OSM Wiki - WikiProject China](https://wiki.openstreetmap.org/wiki/WikiProject_China) 和 [OSM China 页面](https://wiki.openstreetmap.org/wiki/China)：

- 中国的《测绘法》限制了未经授权的私人测绘活动，外国人在中国操作 GPS 测绘制图在法律上有困难。
- 中国在线地图服务使用 GCJ-02 偏移坐标系，OSM 使用 WGS-84 — 不能混用。
- 道路分类标准被认为"不够精确"，社区有专门的[中国标注指南](https://wiki.openstreetmap.org/wiki/Chinese_tagging_guidelines)。
- 在实际使用中，中国主要城市的 OSM 道路数据覆盖相对完整，但偏远地区可能存在缺失。对于 Demo/PoC 而言，主要道路（motorway/trunk/primary/secondary）的数据通常足够使用。

**特别提醒**：OSM 内 Nansha 相关 relation 中有一个是 三沙市的南沙区 (relation 6753263)，不是广州南沙。正确的关系是 **relation 3287345**（`name=南沙区`, `admin_level=6`, 属于 `广州市 relation 3287346`）。

---

## 2. 南沙区边界定义方案

### 2.1 方案 A：OSMnx geocode_to_gdf()（可尝试，但需备选）

`ox.geocode_to_gdf()` 内部调用 Nominatim API 进行地理编码，返回包含边界 Polygon 的 GeoDataFrame。
[OSMnx geocode_to_gdf 参考](https://deepwiki.com/gboeing/osmnx-examples/3.2-geographic-queries-and-place-based-analysis)

```python
# 尝试方式1：全名查询
gdf = ox.geocode_to_gdf("南沙区, 广州市, 广东省, China")

# 尝试方式2：结构化字典（更精确）
gdf = ox.geocode_to_gdf({"district": "南沙区", "city": "广州市", "state": "广东省", "country": "China"})

# 尝试方式3：直接按 OSM relation ID（最精确）
gdf = ox.geocode_to_gdf("R3287345", by_osmid=True)
```

**可靠性评估**：

- OSMnx 官方文档不涉及中国地名支持的特殊说明，只提供了通用的 `which_result` 等回退机制。
  [OSMnx 配置文档](https://deepwiki.com/gboeing/osmnx/2.2-configuration-and-settings)
- Nominatim 对中国行政区划的边界数据依赖于 OSM 社区的维护程度。
- 广州南沙区 relation 3287345 在 OSM 中存在（36 members, admin_level=6），边界数据基本可用。
  [南沙区 Relation 3287345](https://www.openstreetmap.org/relation/3287345)
- **推荐**：优先尝试 `by_osmid=True` 方式，因为直接使用 OSM relation ID 最精确，不需要 Nominatim 的模糊匹配。

### 2.2 方案 B：手动 GeoJSON 边界（推荐作为回退方案）

如果 Nominatim 地理编码失败或不准确，可以使用手动定义的边界多边形：

```python
from shapely.geometry import Polygon

# 南沙区大致边界（WGS-84，以下为近似值，需根据实际范围调整）
nansha_bbox = Polygon([
    (113.35, 22.45),  # 左下
    (113.75, 22.45),  # 右下
    (113.75, 22.95),  # 右上
    (113.35, 22.95),  # 左上
])
```

更精确的做法是从 OSM 手动导出 relation 3287345 的 GeoJSON（通过 `https://polygons.openstreetmap.fr/?id=3287345` 或 Overpass Turbo），保存为本地文件备用。

---

## 3. 道路属性

### 3.1 OSM highway 标签值

[OSM Key:highway 文档](https://wiki.openstreetmap.org/wiki/Key:highway)

OSM 按**功能和重要性**（而非物理特性）对道路分级：

| highway 值 | 说明 | 中国道路对应 |
|---|---|---|
| `motorway` | 全封闭高速公路 | 高速 (G级) |
| `trunk` | 最重要的非高速干线 | 国道 (G级非高速段) |
| `primary` | 重要干线 | 省道/城市主干道 |
| `secondary` | 次要干线 | 县道/城市次干道 |
| `tertiary` | 一般连接道路 | 乡道/城市支路 |
| `unclassified` | 次要通道（非"未分类"） | 村级道路 |
| `residential` | 住宅区道路 | 小区道路 |
| `service` | 服务性通道 | 厂区/停车场内部路 |
| `living_street` | 生活性街道 | 步行优先街道 |
| `pedestrian` | 步行街 | 步行街 |
| `track` | 农林道路 | 机耕路 |
| 其他 | `path`, `footway`, `steps`, `cycleway` 等 | |

**链接道路**：`motorway_link`, `trunk_link`, `primary_link`, `secondary_link`, `tertiary_link`

**生命周期状态**：`construction` + `construction=*`, `proposed` + `proposed=*`

### 3.2 OSMnx 默认暴露的属性

OSMnx 的 `settings.useful_tags_way` 定义了哪些 OSM way 标签会被转换为图的边属性：
[OSMnx settings.py 源码](https://github.com/gboeing/osmnx/blob/main/osmnx/settings.py)

```python
useful_tags_way = [
    "access", "area", "bridge", "est_width", "highway",
    "junction", "landuse", "lanes", "maxspeed", "name",
    "oneway", "ref", "service", "tunnel", "width"
]
```

需要额外属性时，可在下载前修改此列表：
```python
ox.settings.useful_tags_way += ["surface", "smoothness", "lit"]
```

### 3.3 本项目至少需要的属性

| 属性 | OSM 标签 | 说明 |
|---|---|---|
| 道路几何 | `geometry` (way nodes) | 线或多边形 |
| 道路名称 | `name` / `name:zh` | 中文路名 |
| 道路等级 | `highway` | 如 motorway/primary/secondary |
| 车道数 | `lanes` | 用于交通风险评估 |
| 是否单向 | `oneway` | 影响路径分析 |
| 桥梁/隧道 | `bridge` / `tunnel` | 积水风险关键因素 |
| 最高时速 | `maxspeed` | 辅助交通评估 |

---

## 4. 本地缓存格式对比

[GeoParquet vs GeoPackage vs Shapefile — 2026 GIS 堆栈决策树](https://cadshift.com/blog/geoparquet-vs-geopackage-vs-shapefile-decision-tree-2026/)
[geopandas IO 文档](https://geopandas.org/en/stable/docs/user_guide/io.html)

基于 120 万条 OSM 建筑物数据基准测试（英格兰地区）：

| 指标 | Shapefile | GeoPackage | GeoParquet (zstd) |
|---|---|---|---|
| **文件大小** | 2.1 GB | 1.4 GB | **380 MB** |
| **顺序读取（热缓存）** | 6.4s | 5.1s | **1.8s** |
| **BBOX 空间查询（1%数据）** | 0.4s | 0.2s | **0.05s** |
| **单列扫描** | 4.2s | 2.8s | **0.18s** |

### 推荐方案

**对于本项目（Demo/PoC 阶段）**：

1. **推荐 GeoPackage** — 单个文件、支持多层、GIS 工具兼容性好、geopandas 原生读写。广东省道路数据只需几十到几百 MB，GeoPackage 的读取速度完全够用。
   ```python
   gdf.to_file("nansha_roads.gpkg", layer="roads", driver="GPKG")
   ```

2. **备选 GeoParquet** — 如果需要反复分析大数据的场景，文件更小、列式读取更快。
   ```python
   gdf.to_parquet("nansha_roads.parquet")
   ```

当前项目数据量（一个区的道路网络通常在 1k-10k 条路段级别），GeoPackage 性能和便利性完全足够，不需要引入 Parquet 的额外依赖。

---

## 5. 数据更新策略

**结论：一次性静态下载即可满足 Demo/PoC 需求。**

理由：
- 道路网络属于缓慢变化的基础设施数据，月度乃至季度更新频率足够。
- Geofabrik 提供每日更新的 `.osc.gz` 增量文件，但 Demo 阶段不需要。
- OSMnx 默认启用 HTTP 缓存（`use_cache=True`），重复运行不会重复请求 API。

如果需要后续更新，重新运行下载脚本即可 -- 缓存会在过期后自动刷新。

---

## 6. Python 依赖

| 库 | 最新版本 | 用途 |
|---|---|---|
| `osmnx` | **2.1.1** | 下载 OSM 道路网络，路网分析 |
| `geopandas` | **1.1.4**（已安装 1.1.2） | 地理数据处理 |
| `shapely` | **2.1.2**（已安装 2.1.2） | 几何操作（osmnx 依赖） |
| `networkx` | （osmnx 自动安装） | 路网图结构 |
| `pyarrow` | （如需 GeoParquet） | Parquet 读写引擎 |

osmnx 的 `pip install osmnx` 会自动安装 geopandas、shapely、networkx 等依赖。
[OSMnx GitHub](https://github.com/gboeing/osmnx)

建议在 `requirements.txt` 中新增：
```
osmnx>=2.1.1
geopandas>=1.0.0
```

shapely 已经作为 geopandas 的依赖自动安装，无需单独声明。

---

## 7. 现有代码库分析

检查了现有代码（`src/waterlogging.py`、`scripts/batch_test.py`）：

- **当前无任何空间数据获取逻辑**。项目目前只包含视觉 LLM 积水研判功能。
- `requirements.txt` 仅依赖 `openai>=1.52.0,<3.0.0`。
- README 提到后续方向包括"多源数据融合（摄像头地点数据 -> 政务内涝台账 / 水位数据）"，明确需要空间数据能力。
- 道路数据将成为独立的获取与缓存模块，不与现有视觉研判逻辑耦合。

---

## 8. 推荐实现方案与代码示例

### 推荐策略（优先级从高到低）

1. **首选**：OSMnx + OSM relation ID (R3287345) 查询南沙区边界 + 按边界下载道路
2. **回退 A**：OSMnx + 中英文混合地名查询 + `which_result` 选择正确结果
3. **回退 B**：手动 GeoJSON 边界 + OSMnx `graph_from_polygon()`
4. **备选**：下载 Geofabrik 广东 PBF + `graph_from_xml()` + 按边界裁剪

### 完整代码示例

```python
#!/usr/bin/env python3
"""南沙区道路网络下载与缓存脚本."""
import geopandas as gpd
import osmnx as ox
from pathlib import Path


def get_nansha_boundary() -> gpd.GeoDataFrame:
    """获取南沙区行政边界，依次尝试多种方式.

    Returns
    -------
    gpd.GeoDataFrame
        包含南沙区边界 Polygon 的 GeoDataFrame.
    """
    # 方式1：直接使用 OSM relation ID（最精确）
    try:
        print("尝试方式1：by_osmid 'R3287345' ...")
        gdf = ox.geocode_to_gdf("R3287345", by_osmid=True)
        print("  成功！")
        return gdf
    except Exception as e:
        print(f"  失败：{e}")

    # 方式2：结构化中文地址查询
    try:
        print("尝试方式2：结构化查询（南沙区, 广州市, 广东省, 中国） ...")
        gdf = ox.geocode_to_gdf({
            "district": "南沙区",
            "city": "广州市",
            "state": "广东省",
            "country": "中国",
        })
        print("  成功！")
        return gdf
    except Exception as e:
        print(f"  失败：{e}")

    # 方式3：简单字符串查询 + 指定结果序号
    try:
        print("尝试方式3：'Nansha District, Guangzhou, China' + which_result ...")
        gdf = ox.geocode_to_gdf(
            "Nansha District, Guangzhou, Guangdong, China",
            which_result=1,
        )
        print("  成功！")
        return gdf
    except Exception as e:
        print(f"  失败：{e}")

    # 方式4：手动 GeoJSON 边界（最终回退）
    print("使用手动定义边界 ...")
    from shapely.geometry import Polygon
    gdf = gpd.GeoDataFrame(
        geometry=[Polygon([
            (113.32, 22.43),
            (113.78, 22.43),
            (113.78, 22.95),
            (113.32, 22.95),
        ])],
        crs="EPSG:4326",
    )
    print("  使用近似矩形边界（113.32-113.78°E, 22.43-22.95°N）")
    return gdf


def download_roads(
    boundary_gdf: gpd.GeoDataFrame,
    network_type: str = "drive",
    output_dir: str = "./data/roads",
) -> gpd.GeoDataFrame:
    """下载南沙区道路网络并转为 GeoDataFrame.

    Parameters
    ----------
    boundary_gdf : gpd.GeoDataFrame
        包含南沙区边界 Polygon 的 GeoDataFrame.
    network_type : str
        道路类型，可选 "drive", "all", "walk", "bike".
        默认 "drive" 涵盖 motorway~residential 等可通行机动车道路.
    output_dir : str
        GeoPackage 输出目录.

    Returns
    -------
    gpd.GeoDataFrame
        包含道路几何与属性的 GeoDataFrame.
    """
    polygon = boundary_gdf.union_all()
    print(f"边界面积：{polygon.area / 1e6:.1f} km²")

    # 方式1：直接按 polygon 下载
    try:
        print("下载道路网络（graph_from_polygon）...")
        G = ox.graph_from_polygon(
            polygon,
            network_type=network_type,
            simplify=True,       # 简化拓扑
            truncate_by_edge=True,
        )
    except Exception:
        # 如果 polygon 太大被拆分后仍失败，尝试更小的区域
        print("全量下载失败，尝试按 bbox ...")
        bbox = polygon.bounds  # (minx, miny, maxx, maxy)
        G = ox.graph_from_bbox(
            north=bbox[3],
            south=bbox[1],
            east=bbox[2],
            west=bbox[0],
            network_type=network_type,
            simplify=True,
        )

    # graph -> GeoDataFrame (每条边一行)
    gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)
    print(f"获取到 {len(gdf_edges)} 条路段")
    print(f"道路等级分布：\n{gdf_edges['highway'].value_counts()}")

    # 缓存为 GeoPackage
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    gpkg_path = Path(output_dir) / "nansha_roads.gpkg"

    # 同时保存边和节点
    gdf_edges.to_file(gpkg_path, layer="edges", driver="GPKG")
    gdf_nodes.to_file(gpkg_path, layer="nodes", driver="GPKG")
    print(f"已缓存至：{gpkg_path.resolve()}")

    return gdf_edges


def load_cached_roads(cache_path: str = "./data/roads/nansha_roads.gpkg") -> gpd.GeoDataFrame | None:
    """从本地缓存加载道路数据."""
    path = Path(cache_path)
    if path.exists():
        return gpd.read_file(path, layer="edges")
    return None


def main():
    # 配置
    ox.settings.use_cache = True
    ox.settings.log_console = True
    ox.settings.cache_folder = "./data/osmnx_cache"

    # 获取边界
    boundary = get_nansha_boundary()

    # 下载道路
    edges = download_roads(boundary, network_type="drive")

    # 统计
    print("\n===== 南沙区道路网络概览 =====")
    print(f"总路段数：{len(edges)}")
    print(f"道路等级分布：\n{edges['highway'].value_counts().to_string()}")
    print(f"有名称路段：{edges['name'].notna().sum()} / {len(edges)}")


if __name__ == "__main__":
    main()
```

### 如需获取更多道路属性

```python
# 在下载前扩展 useful_tags_way，添加积水研判相关的属性
ox.settings.useful_tags_way += [
    "surface",         # 路面材质
    "smoothness",      # 路面平整度
    "lit",             # 是否有路灯
    "sidewalk",        # 是否有人行道
    "name:zh",         # 中文路名（有时 name 为拼音）
]
```

### 仅下载特定等级的机动车道路（排除步行道等）

```python
# 使用 custom_filter 精确控制 high 标签
G = ox.graph_from_polygon(
    polygon,
    custom_filter='["highway"~"motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"]',
    simplify=True,
)
```

---

## 参考文献

1. [OSMnx 用户手册 — 下载道路网络](https://osmnx.readthedocs.io/en/stable/user-reference.html)
2. [OSMnx settings.py 源码](https://github.com/gboeing/osmnx/blob/main/osmnx/settings.py)
3. [OSMnx 配置文档 (DeepWiki)](https://deepwiki.com/gboeing/osmnx/2.2-configuration-and-settings)
4. [OSMnx 地理查询文档 (DeepWiki)](https://deepwiki.com/gboeing/osmnx-examples/3.2-geographic-queries-and-place-based-analysis)
5. [Overpass API 文档](https://wiki.openstreetmap.org/wiki/Overpass_API)
6. [Overpass QL 语言参考](https://wiki.openstreetmap.org/wiki/Overpass_API/Overpass_QL)
7. [Geofabrik 中国下载页](https://download.geofabrik.de/asia/china.html)
8. [Geofabrik 广东下载页](https://download.geofabrik.de/asia/china/guangdong.html)
9. [OSM Key:highway 道路分类](https://wiki.openstreetmap.org/wiki/Key:highway)
10. [OSM WikiProject China](https://wiki.openstreetmap.org/wiki/WikiProject_China)
11. [OSM China 页面](https://wiki.openstreetmap.org/wiki/China)
12. [南沙区 (广州) Relation 3287345](https://www.openstreetmap.org/relation/3287345)
13. [GeoParquet vs GeoPackage — 2026 GIS 堆栈决策树](https://cadshift.com/blog/geoparquet-vs-geopackage-vs-shapefile-decision-tree-2026/)
14. [geopandas IO 文档](https://geopandas.org/en/stable/docs/user_guide/io.html)
15. [OSMnx GitHub](https://github.com/gboeing/osmnx)
