#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨模型汇总报告生成器（wayfinder ticket #19）。

读取 ``comparison_results/<model>/summary.json``（由 ``compare_prompts.py``
逐模型产出），合成一份跨模型对比报告，重点分离 **prompt 变量**（同模型下
新旧 prompt 的差）与 **模型变量**（同 prompt 下不同模型的差）——对应 map #17
Notes 的「模型因素警示」。

用法：
    python scripts/compare_report.py
（自动发现 comparison_results/ 下所有 ``<model>/summary.json``。）
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "comparison_results"
OUT = RESULTS / "cross_model_report.md"

LEVEL_ORDER = ["L0", "L1", "L2", "L3", "L4", "L5", "LX"]
CONF_ORDER = ["high", "medium", "low"]


def load_models() -> list[tuple[str, dict]]:
    found = []
    for sub in sorted(RESULTS.glob("*/summary.json")):
        model = sub.parent.name
        found.append((model, json.loads(sub.read_text(encoding="utf-8"))))
    return found


def fmt_cell(s: dict) -> str:
    if not s.get("success"):
        return "✗ " + str(s.get("error", "失败"))[:30]
    cm = "有" if s.get("depth_cm_filled") else "null"
    return f'{s["status"]}·{s["level"]}·cm={cm}·{s["confidence"]}'


def lx(a: dict) -> str:
    return f'{a["lx_count"]}/{a["success"]}（{a["lx_rate"]:.0%}）' if a["success"] else "—"


def cm(a: dict) -> str:
    return f'{a["cm_fill_count"]}/{a["success"]}（{a["cm_fill_rate"]:.0%}）' if a["success"] else "—"


def dist(a: dict) -> str:
    return "、".join(f"{l}:{a['level_distribution'][l]}" for l in LEVEL_ORDER)


def cdist(a: dict) -> str:
    return "、".join(f"{c}:{a['confidence_distribution'][c]}" for c in CONF_ORDER)


def main() -> int:
    models = load_models()
    if not models:
        print("未发现 comparison_results/<model>/summary.json")
        return 2

    images = models[0][1]["images"]

    md: list[str] = []
    md.append("# 新旧 Stage-1 prompt 实测对比 — 跨模型汇总（#19）")
    md.append("")
    md.append(f"- 图片（{len(images)}）：{'、'.join(images)}")
    md.append(f"- 模型：{', '.join(f'`{m}`' for m, _ in models)}")
    md.append("- thinking：auto（hybrid 模型 enable_thinking=True）")
    md.append("- 每个 (模型, prompt, 图) 为单次运行；LLM 非确定，结果为一次抽样。")
    md.append("")

    # ---- per-model per-image table ----
    md.append("## 每图结果（按模型）")
    md.append("")
    for model, s in models:
        md.append(f"### `{model}`")
        md.append("")
        md.append("| 图 | 旧 prompt（#18 前） | 新 prompt（#18 后） | 变化 |")
        md.append("|---|---|---|---|")
        for img_stem in (Path(n).stem for n in images):
            o = s["per_image"]["old"].get(img_stem, {})
            n = s["per_image"]["new"].get(img_stem, {})
            change = ""
            if o.get("success") and n.get("success"):
                if o["level"] != n["level"]:
                    change = f'{o["level"]}→{n["level"]}'
                if o.get("depth_cm_filled") != n.get("depth_cm_filled"):
                    change += ("；" if change else "") + "cm 翻转"
            md.append(f"| {img_stem} | {fmt_cell(o)} | {fmt_cell(n)} | {change} |")
        md.append("")

    # ---- per-model aggregate ----
    md.append("## 汇总指标（按模型）")
    md.append("")
    for model, s in models:
        md.append(f"### `{model}`")
        md.append("")
        ao, an = s["aggregate"]["old"], s["aggregate"]["new"]
        md.append("| 指标 | 旧 prompt | 新 prompt | Δ（新−旧） |")
        md.append("|---|---|---|---|")
        md.append(f"| 成功 | {ao['success']}/{ao['total']} | {an['success']}/{an['total']} | — |")
        d_lx = (an["lx_rate"] - ao["lx_rate"])
        md.append(f"| **LX 率** | {lx(ao)} | {lx(an)} | {d_lx:+.0%} |")
        d_cm = (an["cm_fill_rate"] - ao["cm_fill_rate"])
        md.append(f"| cm 填充率 | {cm(ao)} | {cm(an)} | {d_cm:+.0%} |")
        md.append(f"| 等级分布 | {dist(ao)} | {dist(an)} | — |")
        md.append(f"| confidence 分布 | {cdist(ao)} | {cdist(an)} | — |")
        md.append("")

    # ---- cross-model prompt-vs-model matrix ----
    md.append("## prompt 变量 vs 模型变量")
    md.append("")
    md.append("LX 率按 (模型, prompt) 矩阵：行=模型，列=prompt。")
    md.append("")
    md.append("| 模型 | 旧 prompt LX 率 | 新 prompt LX 率 | 同模型 Δ（prompt 效应） |")
    md.append("|---|---|---|---|")
    row_for = {}
    for model, s in models:
        ao, an = s["aggregate"]["old"], s["aggregate"]["new"]
        d = an["lx_rate"] - ao["lx_rate"]
        md.append(f"| `{model}` | {lx(ao)} | {lx(an)} | {d:+.0%} |")
        row_for[model] = (ao["lx_rate"], an["lx_rate"])
    md.append("")

    OUT.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"写入 {OUT.relative_to(ROOT)}")
    print("\n--- LX 率矩阵 ---")
    for model, (o, n) in row_for.items():
        print(f"  {model}: old {o:.0%} -> new {n:.0%} (Δ {n-o:+.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
