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

## 结论与发现

### 1. #18 目标达成：LX 率降为 0%，且跨模型成立

- `qwen3-vl-plus`（默认 Stage-1 模型）：LX 率 33% → 0%；`qwen3.6-flash`：50% → 0%（new 5/6 成功，1 失败见 §4）。
- 新 prompt「按证据强度分级保守估计、LX 仅留给积水存在性本身存疑」在两个模型上一致生效 → LX 下降是 **prompt 变量**效应，非某模型偶然。
- 旧 prompt 在两模型上 LX 都偏高（33%/50%），印证 map #17 Notes「LX 偏多」真实存在；新 prompt 直接对症。**#18 决策成立，无需回退。**

### 2. 模型变量（同 prompt、跨模型）

- **cm 填充纪律两极分化**：vl-plus-new **0/6** 填 cm（最严——连 road_water2/3 这类旧 prompt 与 flash 都填 cm 的图也留 null）；flash-new **5/5** 全填（最松）。#18 设计意图「cm 仅可靠参照时填」落在两者之间——提示 vl-plus 偏严、flash 偏松，是 prompt 措辞可微调的信号（见 §5）。
- **等级本身有 ±1 档抖动**：road_water3 old（vl-plus L3 vs flash L4）、road_water2 new（vl-plus L3 vs flash L2）。
- **可靠性**：flash 新 prompt 1/6 硬失败；vl-plus 0/6。默认选 vl-plus 稳健。

### 3. road_water4/5：absent → present 的翻转（歧义图，建议人工视觉复核）

这是新 prompt 最显著的行为变化，单独说明：

| 图 | vl-plus old | vl-plus new | flash old | flash new |
|---|---|---|---|---|
| 4 | **absent·L0·high** | present·L2·low | present·LX | FAIL（schema，§4） |
| 5 | **absent·L0·high** | present·L2·low | present·L2·cm | present·L2·cm |

- vl-plus **旧** prompt 对 4/5 给「absent·L0·high」（高置信无积水），而 flash **旧** prompt 对 4/5 已判 present —— 即 **4/5 本就是两模型存在分歧的歧义图**，vl-plus-old 的「absent·high」是离群判断。
- 新 prompt 下 vl-plus 翻转为 present·L2，与 flash（两 prompt 下都倾向 present）**收敛** → 该翻转更可能是**纠正了 vl-plus-old 的假阴性**，而非凭空造假阳性。
- ⚠️ **但**：本会话图片视觉读取不可用，无法直接确认真值。上述为**跨模型收敛推断、非视觉 ground truth**。建议把 4/5 列为人工抽查项，#20 文档措辞体现「视觉等级估算为保守估计、歧义图可能高估或低估」。

### 4. flash-new road_water4 硬失败：json_object 嵌套对象可靠性（非 #18 prompt 缺陷）

- `qwen3.6-flash` 在新 prompt 下对 road_water4 **2/2 次确定性失败**：模型把嵌套 `depth_cm` 对象输出成 `null`（首次 `depth_estimate.depth_cm`，重试 `water_patches[1].depth_cm`），schema 要求 `DepthCm` 对象、拒收 null；两步修复未能纠正。
- 这是 flash 模型在 `json_object` 模式下对**嵌套对象**的可靠性限制，正是 ADR-0005 §5「json_object 可能产出非标准 JSON」与已毕业 fog「Stage 1 实测 json_object 稳定性」所指。
- vl-plus 0/6 失败 → 默认选型稳健；**不应因 flash 的失败回退 #18 prompt**。

### 5. confidence 过度对齐（vl-plus-new 全 low，可迭代项）

- vl-plus-new 6/6 `confidence=low`（符合设计「保守 + low」），但把 high/medium 信号也抹平；flash-new 仍保留部分 medium（2/5）。
- 提示新 prompt 的 confidence 引导对 vl-plus 偏「一律 low」。可选迭代：对「明显无积水」或「明显积水且有清晰参照」保留更高置信——但属另一次决策，本票只产出实测依据。

### 对 map #17 / #20 的影响

- **#18 决策成立**（见 §1）；新 prompt 达成目标且跨模型验证，无需回退。
- **#20 文档同步**应据本实测微调措辞（对应 map Notes Q2-B）：PRD §4.13 / `observation_schema.md` §3.4 / `CONTEXT.md` 加入「视觉等级为保守估计、歧义图可能高估或低估、cm 填充依赖模型对『可靠参照』的判断」。LX 新语义（仅积水存在性存疑）被实测验证合理（6 图均至少能判定存在性，新 prompt 下 LX=0）。
- **毕业 map Not-yet-specified 的 fog**：
  - 「实测后 prompt 措辞迭代」→ 部分毕业为两个可针对性措辞点：**cm 填充纪律**（vl-plus 偏严 / flash 偏松）、**confidence 引导**（过度 low）。是否迭代是后续决策，非本票。
  - 「『估计合理』的量化」→ 本票给出硬指标 + 跨模型收敛 + 歧义图人工抽查清单（4/5）；「合理」的最终裁定仍需人工视觉，保留为人工事项。

### 局限

- 单次运行抽样（LLM 非确定）；6 张图为现有测试集，未扩。
- 本会话图片视觉读取不可用，无法对 4/5 等「翻转图」做人工 ground truth；翻转结论为跨模型收敛推断。
- `qwen3-vl-plus` 旧 prompt 的 6 个 individual raw 文件因中途清理丢失，但 **12/12 cells 指标完整保存在 `summary.json`**。

---

### 产出索引（map #17 Decisions-so-far 上下文指针）

- 数据：`comparison_results/qwen3-vl-plus/summary.json`、`comparison_results/qwen3.6-flash/summary.json`（各 12 cells；flash-new 含 1 schema 失败）。
- 逐模型 per-cell：`comparison_results/<model>/{old,new}__road_water*.json`。
- 脚本：`scripts/compare_prompts.py`（逐模型对比）、`scripts/compare_report.py`（本跨模型汇总）。
- 旧 prompt 基线 fixture：`tests/fixtures/old_waterlogging_prompt.py`（与 `南沙开发/src/waterlogging.py` 的 `PROMPT_TEMPLATE` 字节一致，已 AST 校验）。
- 本报告：`comparison_results/cross_model_report.md`。

