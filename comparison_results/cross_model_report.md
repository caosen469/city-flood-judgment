# 新旧 Stage-1 prompt 实测对比 — 跨模型汇总（#19）

- 图片（6）：road_water1.jpg、road_water2.jpg、road_water3.jpg、road_water4.jpg、road_water5.jpg、road_water6.jpg
- 模型：`qwen3-vl-plus`, `qwen3.6-flash`
- thinking：auto（hybrid 模型 enable_thinking=True）
- 每个 (模型, prompt, 图) 为单次运行；LLM 非确定，结果为一次抽样。

## 每图结果（按模型）

### `qwen3-vl-plus`

| 图 | 旧 prompt（#18 前） | 新 prompt（#18 后） | 变化 |
|---|---|---|---|
| road_water1 | uncertain·LX·cm=null·low | present·L2·cm=null·low | LX→L2 |
| road_water2 | present·L3·cm=有·medium | present·L3·cm=null·low | cm 翻转 |
| road_water3 | present·L3·cm=有·medium | present·L3·cm=null·low | cm 翻转 |
| road_water4 | absent·L0·cm=null·high | present·L2·cm=null·low | L0→L2 |
| road_water5 | absent·L0·cm=null·high | present·L2·cm=null·low | L0→L2 |
| road_water6 | present·LX·cm=null·medium | present·L3·cm=null·low | LX→L3 |

### `qwen3.6-flash`

| 图 | 旧 prompt（#18 前） | 新 prompt（#18 后） | 变化 |
|---|---|---|---|
| road_water1 | uncertain·LX·cm=null·medium | present·L2·cm=有·medium | LX→L2；cm 翻转 |
| road_water2 | present·L3·cm=有·medium | present·L2·cm=有·low | L3→L2 |
| road_water3 | present·L4·cm=有·high | present·L4·cm=有·low |  |
| road_water4 | present·LX·cm=null·medium | ✗ 两步修复后仍无法解析/校验 Observation。
首段错 |  |
| road_water5 | present·L2·cm=有·medium | present·L2·cm=有·low |  |
| road_water6 | present·LX·cm=null·low | present·L3·cm=有·medium | LX→L3；cm 翻转 |

## 汇总指标（按模型）

### `qwen3-vl-plus`

| 指标 | 旧 prompt | 新 prompt | Δ（新−旧） |
|---|---|---|---|
| 成功 | 6/6 | 6/6 | — |
| **LX 率** | 2/6（33%） | 0/6（0%） | -33% |
| cm 填充率 | 2/6（33%） | 0/6（0%） | -33% |
| 等级分布 | L0:2、L1:0、L2:0、L3:2、L4:0、L5:0、LX:2 | L0:0、L1:0、L2:3、L3:3、L4:0、L5:0、LX:0 | — |
| confidence 分布 | high:2、medium:3、low:1 | high:0、medium:0、low:6 | — |

### `qwen3.6-flash`

| 指标 | 旧 prompt | 新 prompt | Δ（新−旧） |
|---|---|---|---|
| 成功 | 6/6 | 5/6 | — |
| **LX 率** | 3/6（50%） | 0/5（0%） | -50% |
| cm 填充率 | 3/6（50%） | 5/5（100%） | +50% |
| 等级分布 | L0:0、L1:0、L2:1、L3:1、L4:1、L5:0、LX:3 | L0:0、L1:0、L2:3、L3:1、L4:1、L5:0、LX:0 | — |
| confidence 分布 | high:1、medium:4、low:1 | high:0、medium:2、low:3 | — |

## prompt 变量 vs 模型变量

LX 率按 (模型, prompt) 矩阵：行=模型，列=prompt。

| 模型 | 旧 prompt LX 率 | 新 prompt LX 率 | 同模型 Δ（prompt 效应） |
|---|---|---|---|
| `qwen3-vl-plus` | 2/6（33%） | 0/6（0%） | -33% |
| `qwen3.6-flash` | 3/6（50%） | 0/5（0%） | -50% |

