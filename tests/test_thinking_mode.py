# -*- coding: utf-8 -*-

"""
resolve_thinking_choice 与 classify_model 的单元测试。

覆盖三档模型分类（ALWAYS / HYBRID / NON）与 `--thinking {auto,on,off}`
的完整交叉语义。无网络依赖，可通过 `python -m unittest tests.test_thinking_mode -v` 运行。

被测函数原住 `src/waterlogging.py`，ADR-0005 §7 重构后抽至 `src/vlm/client.py`
（Stage 1 / observation 生成与后续 LLM 阶段共用）。本测试继续守护该交叉表。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 将 src/ 加入模块搜索路径，以便导入主程序。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vlm.client import (
    ALWAYS_THINKING_MODELS,
    HYBRID_THINKING_MODELS,
    classify_model,
    resolve_thinking_choice,
)


# =============================================================================
# classify_model：三档分类规则
# =============================================================================

class ClassifyModelTests(unittest.TestCase):
    """覆盖 classify_model 的三条判定分支及默认策略。"""

    def test_hybrid_whitelist(self) -> None:
        # 名单中的每一个模型都应判为 hybrid。
        for model in HYBRID_THINKING_MODELS:
            with self.subTest(model=model):
                self.assertEqual(classify_model(model), "hybrid")

    def test_thinking_keyword_is_always(self) -> None:
        # 名字含 thinking（大小写不敏感）即判为 always，无需在名单中。
        for model in (
            "qwen3-vl-8b-thinking",
            "Qwen3-VL-8B-Thinking",
            "qwen3-vl-4b-thinking",
            "qwen3-vl-2b-thinking",
            "some-future-thinking-variant",
        ):
            with self.subTest(model=model):
                self.assertEqual(classify_model(model), "always")
        # 显式名单中的 ALWAYS 模型同样判为 always。
        for model in ALWAYS_THINKING_MODELS:
            with self.subTest(model=model):
                self.assertEqual(classify_model(model), "always")

    def test_unknown_defaults_to_non(self) -> None:
        # 不在名单、名字不含 thinking 的模型默认归为 non（保守策略）。
        for model in (
            "qwen2.5-vl-7b-instruct",
            "qwen2.5-vl-3b-instruct",
            "qwen-vl-plus",
            "a-brand-new-model",
        ):
            with self.subTest(model=model):
                self.assertEqual(classify_model(model), "non")


# =============================================================================
# resolve_thinking_choice：交叉语义表
# =============================================================================

class ResolveThinkingChoiceTests(unittest.TestCase):
    """按「模型档位 × thinking 参数」交叉表逐格验证。"""

    # --- ALWAYS 档 ---
    def test_always_auto_does_not_send(self) -> None:
        should_send, value, notice = resolve_thinking_choice(
            "qwen3-vl-8b-thinking", "auto"
        )
        self.assertFalse(should_send)
        self.assertIsNone(value)
        self.assertIsNone(notice)

    def test_always_on_does_not_send(self) -> None:
        should_send, value, notice = resolve_thinking_choice(
            "qwen3-vl-8b-thinking", "on"
        )
        self.assertFalse(should_send)
        self.assertIsNone(value)
        self.assertIsNone(notice)

    def test_always_off_emits_notice(self) -> None:
        # off 对仅思考型无效，不发参但需打印一行提示。
        should_send, value, notice = resolve_thinking_choice(
            "qwen3-vl-8b-thinking", "off"
        )
        self.assertFalse(should_send)
        self.assertIsNone(value)
        self.assertIsNotNone(notice)
        assert notice is not None  # 为类型检查器收窄
        self.assertGreater(len(notice), 0)

    # --- HYBRID 档 ---
    def test_hybrid_auto_sends_true(self) -> None:
        should_send, value, notice = resolve_thinking_choice(
            "qwen3-vl-plus", "auto"
        )
        self.assertTrue(should_send)
        self.assertTrue(value)
        self.assertIsNone(notice)

    def test_hybrid_on_sends_true(self) -> None:
        should_send, value, notice = resolve_thinking_choice(
            "qwen3-vl-plus", "on"
        )
        self.assertTrue(should_send)
        self.assertTrue(value)
        self.assertIsNone(notice)

    def test_hybrid_off_sends_false(self) -> None:
        should_send, value, notice = resolve_thinking_choice(
            "qwen3-vl-plus", "off"
        )
        self.assertTrue(should_send)
        self.assertFalse(value)
        self.assertIsNone(notice)

    # --- NON 档 ---
    def test_non_auto_does_not_send(self) -> None:
        should_send, value, notice = resolve_thinking_choice(
            "qwen2.5-vl-7b-instruct", "auto"
        )
        self.assertFalse(should_send)
        self.assertIsNone(value)
        self.assertIsNone(notice)

    def test_non_off_does_not_send(self) -> None:
        should_send, value, notice = resolve_thinking_choice(
            "qwen2.5-vl-7b-instruct", "off"
        )
        self.assertFalse(should_send)
        self.assertIsNone(value)
        self.assertIsNone(notice)

    def test_non_on_degrades_with_notice(self) -> None:
        # 对非思考型传 on：降级为不发参，并打印一行提示。
        should_send, value, notice = resolve_thinking_choice(
            "qwen2.5-vl-7b-instruct", "on"
        )
        self.assertFalse(should_send)
        self.assertIsNone(value)
        self.assertIsNotNone(notice)
        assert notice is not None  # 为类型检查器收窄
        self.assertGreater(len(notice), 0)


if __name__ == "__main__":
    unittest.main()
