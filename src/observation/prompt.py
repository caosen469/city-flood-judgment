"""Stage 1 prompt for ``image -> Observation`` (ADR-0005 §5).

Single source of truth: the JSON Schema is rendered from
``Observation.model_json_schema()`` and the enum semantics from
``display_labels.DISPLAY_LABELS`` — no hand-maintained copy of the contract.
The prompt only adds *judgment discipline* (domain rules the schema cannot
express) and *output discipline* (JSON-only, code values, no inference).
"""

from __future__ import annotations

import json
from functools import lru_cache

from schemas.display_labels import DISPLAY_LABELS
from schemas.observation import Observation

# Enum groups the model must understand to emit correct code values, in the
# order they should be explained. Labels come from display_labels.py.
_ENUM_GROUPS: list[tuple[str, str]] = [
    ("waterlogging_status", "waterlogging.status"),
    ("waterlogging_level", "waterlogging.waterlogging_level / 每个水洼的 waterlogging_level"),
    ("surface_condition", "waterlogging.surface_condition"),
    ("reflection_type", "waterlogging.visual_cues.reflection_type"),
    ("patch_coverage", "每个水洼 water_patches[].coverage"),
    ("visual_impact_hint", "waterlogging.visual_impact_hint"),
    ("overall_confidence", "overall_confidence / depth_estimate.confidence"),
    ("likelihood", "各 reliability / likelihood 字段"),
]


@lru_cache(maxsize=1)
def observation_json_schema() -> str:
    """The Observation contract as pretty JSON, rendered once."""
    return json.dumps(Observation.model_json_schema(), ensure_ascii=False, indent=2)


def _enum_guide() -> str:
    lines: list[str] = []
    for group, path in _ENUM_GROUPS:
        labels = DISPLAY_LABELS.get(group, {})
        if not labels:
            continue
        items = " | ".join(f'{code}（{zh}）' for code, zh in labels.items())
        lines.append(f"- {path}：{items}")
    return "\n".join(lines)


def build_observation_prompt() -> str:
    """The full Stage 1 user prompt (image is attached separately by the caller)."""
    return f"""
你是一名城市道路积水视觉研判专家。请仅根据这张图片中**实际可见**的内容，产出一个结构化 Observation（道路积水现象）。

# 你的输出契约（JSON Schema）

你必须、且只能输出一个符合下列 JSON Schema 的 JSON 对象。schema 是单一真值来源——字段名、类型、嵌套结构、枚举 code 值都以它为准：

```json
{observation_json_schema()}
```

# 枚举 code 含义（值为语言中性 code，不是中文）

{_enum_guide()}

积水深度等级的物理含义（仅视觉估算，非实测）：
- L0：无积水，或仅轻微潮湿；
- L1：约 0–3 cm，浅层积水；
- L2：约 3–10 cm，可能覆盖鞋底；
- L3：约 10–20 cm，对行人/小型车辆/非机动车明显影响；
- L4：约 20–30 cm，可能接近普通小汽车轮毂下沿；
- L5：大于 30 cm，可能造成车辆熄火/失控/人员涉水危险；
- LX：**无法可靠判断是否存在真实积水**（如极端模糊、夜间无光、镜头污渍遮挡、信号相互矛盾）时使用——不是"有积水但没参照"的兜底。

# 输出纪律（严格遵守）

1. **只输出 JSON**：不要输出 JSON 以外的任何文字，不要使用 ```json 代码围栏，不要解释。
2. **不要产出 `meta`**：`observation_id / source_image / observed_at / source_location` 由系统盖戳，你不需要、也不得编造。
3. **code 值**：所有枚举字段使用上面的 code（如 `present` / `L2` / `clear_water`），不要写中文枚举值。
4. **unknown 由值表达，绝不靠缺键**：枚举用哨兵（status→uncertain、level→LX、surface_condition→unknown、visual_impact_hint→unclear），数值（depth_cm 的 min/max/most_likely）用 null，列表（water_patches / reference_objects / visual_evidence / alternative_explanations / uncertainty_reasons）无内容用空数组 []。`overall_confidence` 无 unknown，至少 low。
5. **守住 Observation/Inference 边界**：本对象只描述画面**可见**内容。**不要**输出交通风险、事件定性、因果推论（那些属于后续推理层）。`visual_impact_hint` 仅是基于画面可见证据的描述性提示（如「覆盖道路标线」「接近车辆底盘」），不是交通影响判断。`observed_summary` 仅概括可见内容，禁止风险/事件/因果措辞。
6. **`visible_location_text`**：若画面中有 OSD/水印/路牌/招牌等可见地名文字，原样抄录（如「进港大道」「明珠湾」）；看不到则填 null。不要根据画面猜测地名、不要使用你的世界知识。

# 判断纪律（domain rules，schema 无法表达）

1. 不得仅凭反光判断积水深度；倒影不等于深水。
2. 不得把潮湿路面、阴影、灯光反射、路面材质镜面反光、镜头污渍直接判断为积水。
3. **深度等级按证据强度分级估计；只要存在任何已知尺寸参照与水面关系，就应估计 depth_cm（宽区间）；仅在完全看不到参照时 depth_cm 才留 null**：
   - 有清晰参照（水位线、已知尺寸物体与水面明确交线、**已知尺寸物体的部分浸没**如半淹车胎/轮毂、被水没过的路缘石/台阶、浸没到某高度的车辆底盘/裙板）→ 给 depth_cm **宽区间**（min/max 跨参照可推出的合理范围，most_likely 取最佳估计），`depth_estimate.confidence` 与证据强度匹配，至少 medium；
   - 有中等参照（路面标线被覆盖范围、水波、反光模式等间接线索）→ 给 depth_cm 宽区间（区间更宽、反映线索不确定性），`depth_estimate.confidence` 用 low——有参照就填 cm，宁可区间宽不宁可全 null；
   - 积水明显但**画面中完全没有任何已知尺寸参照与水面的关系** → **保守单值等级估计**（按可见视觉强度取保守档，如 L2/L3），`depth_estimate.confidence=low`，`depth_cm` 保持 null——cm 承载测量，无参照不编造厘米数；
   - 仅当**积水存在与否本身存疑**（极端模糊 / 夜间无光 / 镜头污渍遮挡 / 信号互相矛盾）→ 才用 LX。
4. **只要画面中存在任何一种已知尺寸参照与水面关系，就应填写 depth_cm**：有效参照包括但不限于——清晰水位线、半淹的车胎/轮毂、被水没过的路缘石/台阶、浸没到已知高度的车辆底盘/裙板、其他可见的已知尺寸物体与水面交界。**优先给区间而非伪精确单值**——同时填写 min 和 max 给出范围，并给出 most_likely 最佳估计；不要仅填 most_likely 而 min/max 全 null（等同于伪精确单值）。**仅当画面中完全不存在任何已知尺寸参照与水面的关系时**，depth_cm 才全填 null。
5. **一个清晰、无歧义的已知尺寸参照**（如一个明确半淹、淹没线可见的车胎）即足以支撑 `depth_estimate.confidence=medium`；多个强且一致的参照且区间较窄 → `high`（罕见）；仅有间接/弱的视觉线索（如仅凭水波、反光推断）→ `low`。证据矛盾时扩大 depth_cm 区间并降低置信度。
6. 「没看到水位线」不等于「没有积水」；「有明显反光」不等于「积水较深」。
7. 一切结论必须基于图中实际可见内容，不得补充图中不存在的车辆、行人、路缘石等参照物。
8. 无法确认是否存在真实积水时，status 用 uncertain，不要强行二选一。
9. status==absent 时，waterlogging_level 必须为 L0。
10. 每个独立积水区域作为一个 water_patches 元素；可同时存在浅水洼与较深路面水。
""".strip()
