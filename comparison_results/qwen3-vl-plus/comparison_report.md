# 新旧 prompt 实测对比（qwen3-vl-plus，thinking auto）

- 图片：road_water1.jpg、road_water2.jpg、road_water3.jpg、road_water4.jpg、road_water5.jpg、road_water6.jpg
- 模型：`qwen3-vl-plus`
- 输出：`comparison_results/`

## 每图结果

| 图 | 旧 prompt（#18 前） | 新 prompt（#18 后） |
|---|---|---|
| road_water1 | uncertain · LX · cm=null · conf=low | present · L2 · cm=null · conf=low |
| road_water2 | present · L3 · cm=有 · conf=medium | present · L3 · cm=null · conf=low |
| road_water3 | present · L3 · cm=有 · conf=medium | present · L3 · cm=null · conf=low |
| road_water4 | absent · L0 · cm=null · conf=high | present · L2 · cm=null · conf=low |
| road_water5 | absent · L0 · cm=null · conf=high | present · L2 · cm=null · conf=low |
| road_water6 | present · LX · cm=null · conf=medium | present · L3 · cm=null · conf=low |

## 汇总

| 指标 | 旧 prompt（#18 前） | 新 prompt（#18 后） |
|---|---|---|
| 成功 | 6/6 | 6/6 |
| LX 率 | 2/6（33%） | 0/6（0%） |
| cm 填充率 | 2/6（33%） | 0/6（0%） |
| 等级分布 | L0:2、L1:0、L2:0、L3:2、L4:0、L5:0、LX:2 | L0:0、L1:0、L2:3、L3:3、L4:0、L5:0、LX:0 |
| confidence 分布 | high:2、medium:3、low:1 | high:0、medium:0、low:6 |
