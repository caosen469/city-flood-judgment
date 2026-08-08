# 道路积水视觉研判（南沙积水研判）

基于阿里云百炼 Qwen3-VL 系列视觉模型的命令行工具，对输入的道路图片进行积水智能研判，输出结构化 JSON 结果。

> 本项目从 `waterlogging-cli/waterlogging-core` 迁移核心代码而来，作为后续开发的基础。详细的字段语义、模型三档分类、退出码等说明见原项目 [README](../../waterlogging-cli/waterlogging-core/README.md)。

## 目录结构

```
南沙积水研判/
├── src/
│   └── waterlogging.py          # 主程序（CLI 入口）
├── scripts/
│   └── batch_test.py            # 批量多模型测试脚本
├── tests/
│   └── test_thinking_mode.py    # 单元测试
├── requirements.txt             # 依赖：openai>=1.52.0,<3.0.0
└── .gitignore
```

## 环境要求

- Python 3.10 及以上
- 可访问公网的运行环境（调用阿里云百炼 API）
- 一个阿里云百炼（DashScope）的 API Key

## 安装

```bash
pip install -r requirements.txt
```

## 配置 API Key

推荐用环境变量配置（避免把密钥提交到 git）：

```bash
export DASHSCOPE_API_KEY="你的阿里云百炼 API Key"
```

也可以打开 `src/waterlogging.py` 配置区的 `API_KEY` 占位符，直接填入你的阿里云百炼 API Key（在[阿里云百炼控制台](https://bailian.console.aliyun.com/)「API-KEY 管理」创建）。

> 安全提示：请勿将填有真实 API Key 的代码提交到公开仓库或分享给他人。

## 快速开始

最简运行（默认模型 `qwen3-vl-8b-thinking`，自动启用思考）：

```bash
python src/waterlogging.py "https://example.com/road.jpg"
```

本地图片路径同样支持：

```bash
python src/waterlogging.py /path/to/local/road.jpg
```

## 命令行参数

```
usage: waterlogging.py [-h] [--model MODEL] [--thinking {auto,on,off}] image_url
```

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `image_url` | 是 | — | 公网可访问的图片 URL，或本地图片文件路径 |
| `--model` | 否 | `qwen3-vl-8b-thinking` | 被测模型名 |
| `--thinking` | 否 | `auto` | 思考模式开关，可选 `auto` / `on` / `off` |
| `-h` / `--help` | 否 | — | 查看帮助并退出 |

## 模型与思考模式

程序内置三档模型分类，自动决定是否向 API 发送 `enable_thinking` 参数：

| 档位 | 行为 | 识别方式 | 示例模型 |
|---|---|---|---|
| **ALWAYS**（仅思考型） | 始终思考，不发参 | 模型名含 `thinking` 或名单内 | `qwen3-vl-8b-thinking` 等 |
| **HYBRID**（混合思考型） | 接受 `enable_thinking` 开关 | 名单内 | `qwen3-vl-plus`、`qwen3-vl-8b` |
| **NON**（非思考型） | 不支持思考参数，发送会报错 | 其余所有模型 | `qwen2.5-vl-7b-instruct` 等 |

## 使用示例

```bash
# 默认行为
python src/waterlogging.py "https://example.com/road.jpg"

# 切换到混合思考型模型，显式开启思考
python src/waterlogging.py "https://example.com/road.jpg" --model qwen3-vl-plus --thinking on

# 切换到非思考型老模型作为 baseline
python src/waterlogging.py "https://example.com/road.jpg" --model qwen2.5-vl-7b-instruct
```

## 批量测试

`scripts/batch_test.py` 对指定图片目录下的所有 JPG 图片，使用全部混合思考型模型进行批量交叉测试，结果保存到 `batch_results/`。配置（图片目录、模型列表、并发数等）硬编码于脚本顶部配置区。

```bash
python scripts/batch_test.py
```

## 运行测试

```bash
python -m unittest tests.test_thinking_mode -v
```

预期 12 项全部 ok（覆盖 `resolve_thinking_choice` 与 `classify_model` 的全部交叉语义，无网络依赖）。

## 后续开发方向（背景）

项目远景（见原项目 `motivation.md`）：面向广州南沙智慧城市运维，用监控视频/图片数据识别道路内涝点位。当前基于反光率的算法无法区分小水坑与严重积水，本方案通过大模型（视觉 Qwen 系列）+ 精心设计的 prompt 做研判；后续可基于多源数据融合（摄像头地点数据 → 政务内涝台账 / 水位数据，经 API 或 MCP 接入），将额外上下文拼入 prompt，提升研判准确率。

原项目 `.scratch/web-service/` 中还规划了把研判能力做成网页端服务（FastAPI + 前端 Demo）的方案，含 05 API Key 管理、06 前端原型、07 本地运行等待办事项，可作为后续开发参考。
