#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新旧 prompt 实测对比脚本（wayfinder ticket #19）。

对 ``data/images/road_water*.jpg`` 六张图，分别用：
  - 旧 prompt（tests/fixtures/old_waterlogging_prompt.py 中的 OLD_PROMPT_TEMPLATE，
    字节级快照自 ``南沙开发/src/waterlogging.py``，#18 改写前基线）；
  - 新 prompt（``src/observation/prompt.py`` 的 build_observation_prompt()，#18 改后）
跑默认模型 ``qwen3-vl-plus``（thinking auto），产出可对齐的对比指标：

  - LX 率（改后应显著低于旧版）；
  - 等级分布（L0–L5/LX 占比）；
  - cm 填充率（depth_cm 非 null 的比例——预期两版都低，因多数图无可靠参照）；
  - depth_estimate.confidence 分布。

输出：
  - 每个 (prompt, image) 的完整结果 JSON 到 ``comparison_results/``；
  - 汇总表 JSON + Markdown 到同目录。

实现说明：
  - 新 prompt 走 ``src/observation/generate.py::generate_observation``
    （新版 waterlogging.py 已薄化，analyze_image 不再存在）。
  - 旧 prompt 走与 ``scripts/batch_test.py`` 相同的流式 ``json_object`` 调用，
    但解析旧格式（顶层 waterlogging_level / estimated_depth_cm / confidence），
    并映射到 Observation 对齐指标（waterlogging_level / depth_cm / confidence）。
  - 旧 prompt 产物不套 Observation schema（历史格式），仅做字段映射对齐指标。
  - 映射规则：
      old waterlogging_status -> status（存在=present / 不存在=absent / 不确定=uncertain）
      old waterlogging_level -> waterlogging_level（相同 code）
      old estimated_depth_cm -> depth_cm（min/max/most_likely）
      old confidence（高/中/低）-> overall confidence（high/medium/low）
  - 旧 prompt 判断纪律是"缺可靠参照 -> 一律 LX + depth null"，与 #18 决策对旧版行为的
    预期一致；对比聚焦 LX 率 / 等级分布 / cm 填充率是否按预期变化。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 将 src/ 加入模块搜索路径。
_SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(_SRC))

from vlm.client import build_extra_body, make_client, resolve_thinking_choice
from vlm.reasoning import get_reasoning_content
from observation.generate import (
    DEFAULT_MODEL,
    ObservationGenerationError,
    generate_observation,
    prepare_image_input,
)
from observation.prompt import build_observation_prompt

# 旧 prompt fixture 放在 tests/fixtures/（与 pytest fixtures 同处，作为测试资产）。
_TESTS = Path(__file__).resolve().parent.parent / "tests"
sys.path.insert(0, str(_TESTS))
from fixtures.old_waterlogging_prompt import OLD_PROMPT_TEMPLATE

# =============================================================================
# 配置区
# =============================================================================

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = _PROJECT_ROOT / "data" / "images"
# Each model's outputs land in its own subdir so multiple model runs (prompt
# variable vs model variable cross-check) coexist without overwriting.
OUTPUT_ROOT = _PROJECT_ROOT / "comparison_results"

# 本票验收固定默认模型（map #17 Notes）。
MODEL = "qwen3-vl-plus"
THINKING = "auto"

_LEVEL_ORDER = ["L0", "L1", "L2", "L3", "L4", "L5", "LX"]
_CONFIDENCE_ORDER = ["high", "medium", "low"]

_STATUS_MAP = {"存在": "present", "不存在": "absent", "不确定": "uncertain"}
_CONF_MAP = {"高": "high", "中": "medium", "低": "low"}


# =============================================================================
# 旧 prompt 调用 + 解析（对齐 scripts/batch_test.py 的方式）
# =============================================================================

def _extract_json_text(raw: str) -> str:
    import re

    text = raw.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    if text.startswith("{"):
        return text
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _stream_completion(client, *, model: str, messages: list[dict], extra_body: dict) -> str:
    parts: list[str] = []
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        response_format={"type": "json_object"},
        extra_body=extra_body,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if isinstance(content, str) and content:
            parts.append(content)
    return "".join(parts).strip()


def _normalize_old_result(raw_result: dict[str, Any]) -> dict[str, Any]:
    """把旧格式 JSON 映射为对齐指标的结构。"""
    level = raw_result.get("waterlogging_level")
    if level not in _LEVEL_ORDER:
        level = "LX"
    depth = raw_result.get("estimated_depth_cm") or {}
    depth_cm = {
        "min": depth.get("min"),
        "max": depth.get("max"),
        "most_likely": depth.get("most_likely"),
    }
    conf_zh = raw_result.get("confidence")
    confidence = _CONF_MAP.get(str(conf_zh).strip(), "low") if conf_zh else "low"
    return {
        "status": _STATUS_MAP.get(str(raw_result.get("waterlogging_status")).strip(), "uncertain"),
        "waterlogging_level": level,
        "depth_cm": depth_cm,
        "confidence": confidence,
        "raw": raw_result,
    }


def run_old_prompt(client, image_source: str, model: str, thinking: str) -> dict[str, Any]:
    """旧 prompt：流式 json_object 调用 + 旧格式解析映射。"""
    thinking_decision = resolve_thinking_choice(model, thinking)
    extra_body = build_extra_body(thinking_decision)
    prompt = OLD_PROMPT_TEMPLATE.replace("__IMAGE_URL__", "(local image attached)")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": image_source}},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    raw = _stream_completion(client, model=model, messages=messages, extra_body=extra_body)
    if not raw:
        return {"success": False, "error": "模型没有返回任何 content"}
    try:
        payload = json.loads(_extract_json_text(raw))
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"JSON 解析失败：{exc}", "raw": raw}
    if not isinstance(payload, dict):
        return {"success": False, "error": "JSON 顶层不是对象", "raw": raw}
    return {"success": True, **{k: v for k, v in _normalize_old_result(payload).items() if k != "raw"}, "raw": payload}


# =============================================================================
# 指标提取
# =============================================================================

def _depth_filled(depth_cm: dict[str, Any]) -> bool:
    return any(v is not None for v in (depth_cm.get("min"), depth_cm.get("max"), depth_cm.get("most_likely")))


def summarize_cell(cell: dict[str, Any]) -> dict[str, Any]:
    """把单个 (prompt, image) 结果压成对比指标。"""
    base: dict[str, Any] = {"success": cell.get("success", False)}
    if not cell.get("success"):
        base["error"] = cell.get("error", "unknown")
        return base
    depth_cm = cell["depth_cm"]
    base.update(
        {
            "status": cell["status"],
            "level": cell["waterlogging_level"],
            "depth_cm_filled": _depth_filled(depth_cm),
            "depth_cm": depth_cm,
            "confidence": cell["confidence"],
        }
    )
    return base


# =============================================================================
# 主流程
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="新旧 prompt 实测对比（#19）")
    parser.add_argument("--model", default=MODEL, help=f"被测模型。默认：%(default)s")
    parser.add_argument("--images", nargs="*", default=None, help="图片文件名列表（默认 data/images/road_water*.jpg）")
    args = parser.parse_args()

    images = sorted(Path(IMAGE_DIR).glob("road_water*.jpg"))
    if args.images:
        images = [Path(IMAGE_DIR) / name for name in args.images]
    if not images:
        print(f"错误：未找到图片：{IMAGE_DIR}")
        return 2

    OUTPUT_DIR = OUTPUT_ROOT / args.model
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = make_client(timeout=180)

    print(f"对比测试：2 prompts × {len(images)} 张图，模型 {args.model}（thinking {THINKING}）")
    print(f"输出目录：{OUTPUT_DIR.resolve()}")

    cells: dict[str, dict[str, Any]] = {}
    prompts = {"old": "旧 prompt（#18 前）", "new": "新 prompt（#18 后）"}

    for prompt_key, label in prompts.items():
        for img in images:
            image_source, _label = prepare_image_input(str(img))
            if prompt_key == "new":
                try:
                    result = generate_observation(
                        image_source,
                        model=args.model,
                        thinking=THINKING,
                        repair_model=args.model,
                    )
                    obs = result.observation
                    cell = {
                        "success": True,
                        "status": obs.waterlogging.status.value,
                        "waterlogging_level": obs.waterlogging.waterlogging_level.value,
                        "depth_cm": {
                            "min": obs.waterlogging.depth_estimate.depth_cm.min,
                            "max": obs.waterlogging.depth_estimate.depth_cm.max,
                            "most_likely": obs.waterlogging.depth_estimate.depth_cm.most_likely,
                        },
                        "confidence": obs.waterlogging.depth_estimate.confidence.value,
                        "raw": json.loads(result.raw_content) if result.repaired else None,
                    }
                    # repaired 时 raw_content 是修复后的 JSON；保留完整 observation 以便复核
                    cell["observation"] = obs.model_dump(exclude_none=True, exclude={"meta"})
                except ObservationGenerationError as exc:
                    cell = {"success": False, "error": str(exc)}
            else:
                cell = run_old_prompt(client, image_source, args.model, THINKING)

            key = f"{prompt_key}__{img.stem}"
            cells[key] = cell
            # 保存完整结果
            (OUTPUT_DIR / f"{key}.json").write_text(
                json.dumps(cell, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            status = "OK" if cell.get("success") else f"FAIL: {cell.get('error', '')}"
            print(f"  [{prompt_key}] {img.name}: {status}")

    # 汇总指标
    summary: dict[str, Any] = {
        "model": args.model,
        "thinking": THINKING,
        "images": [img.name for img in images],
        "prompts": prompts,
        "per_image": {},
        "aggregate": {},
    }
    for prompt_key in prompts:
        summary["per_image"][prompt_key] = {}
        for img in images:
            key = f"{prompt_key}__{img.stem}"
            summary["per_image"][prompt_key][img.stem] = summarize_cell(cells[key])

    for prompt_key in prompts:
        agg = summary["aggregate"][prompt_key] = {
            "total": len(images),
            "success": sum(1 for img in images if cells[f"{prompt_key}__{img.stem}"].get("success")),
            "failure": sum(1 for img in images if not cells[f"{prompt_key}__{img.stem}"].get("success")),
            "lx_count": 0,
            "lx_rate": 0.0,
            "level_distribution": {lvl: 0 for lvl in _LEVEL_ORDER},
            "cm_fill_count": 0,
            "cm_fill_rate": 0.0,
            "confidence_distribution": {c: 0 for c in _CONFIDENCE_ORDER},
            "failures": [],
        }
        for img in images:
            cell = cells[f"{prompt_key}__{img.stem}"]
            if not cell.get("success"):
                agg["failures"].append({"image": img.stem, "error": cell.get("error")})
                continue
            s = summary["per_image"][prompt_key][img.stem]
            if s["level"] == "LX":
                agg["lx_count"] += 1
            agg["level_distribution"][s["level"]] += 1
            if s["depth_cm_filled"]:
                agg["cm_fill_count"] += 1
            agg["confidence_distribution"][s["confidence"]] += 1
        if agg["success"]:
            agg["lx_rate"] = round(agg["lx_count"] / agg["success"], 3)
            agg["cm_fill_rate"] = round(agg["cm_fill_count"] / agg["success"], 3)

    (OUTPUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Markdown 汇总表（每图 + 汇总指标，新旧并列）
    md = [
        f"# 新旧 prompt 实测对比（{args.model}，thinking auto）",
        "",
        f"- 图片：{'、'.join(img.name for img in images)}",
        f"- 模型：`{args.model}`",
        f"- 输出：`comparison_results/`",
        "",
        "## 每图结果",
        "",
        "| 图 | 旧 prompt（#18 前） | 新 prompt（#18 后） |",
        "|---|---|---|",
    ]
    for img in images:
        s_old = summary["per_image"]["old"][img.stem]
        s_new = summary["per_image"]["new"][img.stem]

        def fmt(s):
            if not s.get("success"):
                return "✗ " + s.get("error", "失败")[:40]
            cm = "有" if s["depth_cm_filled"] else "null"
            return f'{s["status"]} · {s["level"]} · cm={cm} · conf={s["confidence"]}'

        md.append(f"| {img.stem} | {fmt(s_old)} | {fmt(s_new)} |")

    old_agg = summary["aggregate"]["old"]
    new_agg = summary["aggregate"]["new"]

    def lx_str(a):
        return f"{a['lx_count']}/{a['success']}（{a['lx_rate']:.0%}）" if a["success"] else "—"

    def cm_str(a):
        return f"{a['cm_fill_count']}/{a['success']}（{a['cm_fill_rate']:.0%}）" if a["success"] else "—"

    def dist_str(a):
        return "、".join(f"{l}:{a['level_distribution'][l]}" for l in _LEVEL_ORDER)

    def conf_str(a):
        return "、".join(f"{c}:{a['confidence_distribution'][c]}" for c in _CONFIDENCE_ORDER)

    md += [
        "",
        "## 汇总",
        "",
        "| 指标 | 旧 prompt（#18 前） | 新 prompt（#18 后） |",
        "|---|---|---|",
        f"| 成功 | {old_agg['success']}/{old_agg['total']} | {new_agg['success']}/{new_agg['total']} |",
        f"| LX 率 | {lx_str(old_agg)} | {lx_str(new_agg)} |",
        f"| cm 填充率 | {cm_str(old_agg)} | {cm_str(new_agg)} |",
        f"| 等级分布 | {dist_str(old_agg)} | {dist_str(new_agg)} |",
        f"| confidence 分布 | {conf_str(old_agg)} | {conf_str(new_agg)} |",
    ]
    if old_agg["failures"] or new_agg["failures"]:
        md += ["", "## 失败明细", ""]
        for prompt_key, a in (("old", old_agg), ("new", new_agg)):
            for f in a["failures"]:
                md.append(f"- [{prompt_key}] {f['image']}: {f['error']}")

    (OUTPUT_DIR / "comparison_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n汇总表已写入 comparison_results/comparison_report.md")
    print(open(OUTPUT_DIR / "comparison_report.md", encoding="utf-8").read())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
