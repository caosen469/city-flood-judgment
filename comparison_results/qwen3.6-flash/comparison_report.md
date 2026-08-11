# 新旧 prompt 实测对比（qwen3.6-flash，thinking auto）

- 图片：road_water1.jpg、road_water2.jpg、road_water3.jpg、road_water4.jpg、road_water5.jpg、road_water6.jpg
- 模型：`qwen3.6-flash`
- 输出：`comparison_results/`

## 每图结果

| 图 | 旧 prompt（#18 前） | 新 prompt（#18 后） |
|---|---|---|
| road_water1 | uncertain · LX · cm=null · conf=medium | present · L2 · cm=有 · conf=medium |
| road_water2 | present · L3 · cm=有 · conf=medium | present · L2 · cm=有 · conf=low |
| road_water3 | present · L4 · cm=有 · conf=high | present · L4 · cm=有 · conf=low |
| road_water4 | present · LX · cm=null · conf=medium | ✗ 两步修复后仍无法解析/校验 Observation。
首段错误：Observat |
| road_water5 | present · L2 · cm=有 · conf=medium | present · L2 · cm=有 · conf=low |
| road_water6 | present · LX · cm=null · conf=low | present · L3 · cm=有 · conf=medium |

## 汇总

| 指标 | 旧 prompt（#18 前） | 新 prompt（#18 后） |
|---|---|---|
| 成功 | 6/6 | 5/6 |
| LX 率 | 3/6（50%） | 0/5（0%） |
| cm 填充率 | 3/6（50%） | 5/5（100%） |
| 等级分布 | L0:0、L1:0、L2:1、L3:1、L4:1、L5:0、LX:3 | L0:0、L1:0、L2:3、L3:1、L4:1、L5:0、LX:0 |
| confidence 分布 | high:1、medium:4、low:1 | high:0、medium:2、low:3 |

## 失败明细

- [new] road_water4: 两步修复后仍无法解析/校验 Observation。
首段错误：Observation 校验失败：2 validation errors for Observation
waterlogging.depth_estimate.depth_cm
  Input should be a valid dictionary or instance of DepthCm [type=model_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.10/v/model_type
waterlogging.water_patches.0.depth_cm
  Input should be a valid dictionary or instance of DepthCm [type=model_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.10/v/model_type
修复后错误：Observation 校验失败：2 validation errors for Observation
waterlogging.depth_estimate.depth_cm
  Input should be a valid dictionary or instance of DepthCm [type=model_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.10/v/model_type
waterlogging.water_patches.0.depth_cm
  Input should be a valid dictionary or instance of DepthCm [type=model_type, input_value=None, input_type=NoneType]
    For further information visit https://errors.pydantic.dev/2.10/v/model_type
