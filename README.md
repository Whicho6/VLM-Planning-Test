# VLM-Planning-Test

**轻量级评测视觉语言模型在桌面具身任务规划中的表现。**

本项目研究一个简单问题：**Structured Action Prompting 是否能提高 VLM 任务规划的可靠性？**

| 项目 | 设置 |
|---|---|
| Benchmark | 10 个真实桌面场景、40 条任务 |
| 对比方法 | Free-form Prompt vs Structured Action Prompt |
| 真实 VLM | 阿里云百炼 `qwen3-vl-plus` |
| 实验规模 | 40 个任务 × 2 种提示，共 80 次 API 调用 |
| 主要结果 | Free-form **80.0%**；Structured **97.5%**；Overall **88.75%** |

这是一个小规模探索性评测项目。它测试“桌面图片 + 中文指令 → 动作计划”，不训练新模型，也不控制真实机器人。

## Main Results

正式结果来自 [`results/run_20260904_161430`](results/run_20260904_161430)，80 次 API 调用全部成功。

| Prompt | Planning Accuracy | Action Validity | Format Compliance | Object Hallucination Rate ↓ |
|---|---:|---:|---:|---:|
| Free-form | **80.0%** | 80.0% | 82.5% | 1.75% |
| Structured | **97.5%** | 97.5% | 100.0% | 1.25% |
| Overall | **88.75%** | 88.75% | 91.25% | 1.46% |

在这次实验中，Structured Action Prompt 的规划成功率比 Free-form Prompt 高 **17.5 个百分点**。这个结果只适用于当前模型、场景和单次运行，不能据此作普遍结论。

![各任务类别的规划成功率](results/run_20260904_161430/figures/planning_success.png)

完整逐任务输出、汇总和失败案例分别见：

- [`raw_results.json`](results/run_20260904_161430/raw_results.json)
- [`summary.json`](results/run_20260904_161430/summary.json)
- [`failure_cases.json`](results/run_20260904_161430/failure_cases.json)
- [`实验报告_20260904.md`](实验报告_20260904.md)

## Benchmark

Benchmark 2.1 包含 **10 张真实照片 × 每张 4 条任务 = 40 条任务**。每个场景各有一条：

- Single-step：拿起一个物体；
- Spatial：根据图片中的左右关系移动物体；
- Multi-step：连续执行抓取和放置；
- Impossible：识别场景中不存在的目标并输出 `INVALID_TASK`。

任务使用纸巾、鼠标、笔、橡皮、眼镜、饮料瓶、雨伞和计算器等日常物体。同一张图片可以对应多条指令。部分场景共享相同的视觉指代指令，但正确动作随图片布局变化，用来减少仅靠照抄指令得到答案的可能。

| 场景 | 从左到右的物体 |
|---|---|
| `scene_01` | 纸巾、鼠标、笔、橡皮 |
| `scene_02` | 眼镜、饮料瓶、雨伞、计算器 |
| `scene_03` | 鼠标、橡皮、眼镜、饮料瓶 |
| `scene_04` | 笔、计算器、纸巾、雨伞 |
| `scene_05` | 饮料瓶、纸巾、鼠标、眼镜 |
| `scene_06` | 雨伞、笔、橡皮、计算器 |
| `scene_07` | 计算器、眼镜、饮料瓶、笔 |
| `scene_08` | 橡皮、雨伞、纸巾、鼠标 |
| `scene_09` | 纸巾、眼镜、计算器、橡皮 |
| `scene_10` | 鼠标、饮料瓶、笔、雨伞 |

[`data/scenes.json`](data/scenes.json) 记录场景物体和空间关系，[`data/tasks.json`](data/tasks.json) 记录指令、类别、标准动作与目标状态。照片已经人工核对并登记 SHA-256；图片发生变化时，真实实验会要求重新核对。

## Method

```text
桌面图片 + 中文指令
        ↓
同一个 VLM，分别使用 Free-form / Structured Prompt
        ↓
模型原始输出
        ↓
规则解析 + 动作前提检查 + 目标状态模拟
        ↓
逐任务结果、汇总指标与失败案例
```

模型只能看到图片和指令。场景物体清单、任务类别、标准答案和目标状态只用于评测，不会发给模型。

Free-form 模式允许模型用限定的中文句式给出最终计划。Structured 模式要求模型只输出以下动作：

```text
PICK(object)
PLACE_LEFT(object, target)
PLACE_RIGHT(object, target)
PLACE_IN(object, container)
INVALID_TASK
```

两种方法使用相同模型、图片、任务、温度（0）和 token 上限（512），请求顺序按固定随机种子 42 打乱。

## Evaluation Metrics

项目使用透明、可复现的规则，不使用黑盒评分器，也不把字符串完全相等作为唯一标准。

| 指标 | 定义 |
|---|---|
| **Task Planning Success** | 动作合法，并通过状态模拟达到任务目标；Impossible 任务必须只输出 `INVALID_TASK` |
| **Action Validity** | 动作能完整解析，且动作类型、参数、物体和夹爪状态都合法 |
| **Object Hallucination Rate** | 对不存在物体的引用数 ÷ 全部已解析物体引用数 |
| **Format Compliance** | 输出能被对应模式的公开规则完整解析，没有未识别内容 |

## Quick Start

需要 Python 3.10 或更高版本。本项目在 Python 3.12 下验证。

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe validate_benchmark.py --require-verified
.\.venv\Scripts\python.exe demo.py --backend mock --task-id task_001
.\.venv\Scripts\python.exe run_evaluation.py --backend mock
```

Mock backend 读取标准答案，只用于检查程序流程，不代表真实模型能力。

运行真实 VLM 前，将 `.env.example` 复制为 `.env`，填写自己的阿里云百炼 API Key：

```dotenv
VLM_API_KEY=
VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VLM_MODEL=qwen3-vl-plus
```

```powershell
# 只检查配置，不调用 API
.\.venv\Scripts\python.exe run_evaluation.py --backend real --dry-run

# 完整实验：40 个任务 × 2 种提示模式
.\.venv\Scripts\python.exe run_evaluation.py --backend real

# 查看保存的结果
.\.venv\Scripts\python.exe show_results.py
```

每次真实运行会创建独立的 `results/run_YYYYMMDD_HHMMSS/` 目录。程序逐条保存 checkpoint；中断后可使用 `--resume 结果目录` 继续，已经成功的任务不会再次请求 API。`.env` 已被 Git 忽略，API Key 不会写入结果文件。

## Project Structure

```text
data/                  场景照片、场景元数据和 40 条任务
results/               正式实验、历史实验和 mock 检查结果
src/benchmark.py       数据生成与一致性校验
src/prompts.py         两种提示方法
src/vlm.py             Mock 与真实 VLM 接口
src/parser.py          结构化动作和中文计划解析
src/evaluator.py       动作检查、状态模拟与指标计算
tests/                 无需真实 API 的自动化测试
demo.py                单条任务演示
run_evaluation.py      批量实验、重试、断点续跑与结果保存
show_results.py        在终端展示实验汇总
```

## Failure Analysis

正式实验共出现 9 个规划失败。自动记录的失败类型为：

- 7 个 `unsupported_prose`：Free-form 输出没有被限定句式完整解析；
- 2 个 `object_hallucination`：计划引用了场景中不存在的物体。

Structured 模式的唯一规划失败出现在 Multi-step 类别。Free-form 的主要弱点集中在 Spatial 和 Multi-step 任务及其输出解析。逐条原始回答均保存在正式结果目录，便于区分模型错误与规则解析限制。

旧结果目录 `run_20260904_152757` 和 `run_20260904_155231` 记录了任务设计及评测规则修正前的运行，不能与 Benchmark 2.1 的正式结果直接比较。[`问题与改进记录.md`](问题与改进记录.md) 说明了发现的问题和修复过程。

## Limitations

- 40 条任务只来自 10 个场景，规模较小，也不能视为 40 个独立视觉场景。
- 每个任务只运行一次，尚未测量模型输出的随机波动。
- Structured Prompt 天然更容易解析，因此结果同时报告格式合规率，并保留原始输出供人工检查。
- Free-form 解析器只支持公开的有限句式，正常但未收录的表达可能被判为格式错误。
- 符号模拟器不模拟碰撞、可达性、物理尺寸或真实机器人轨迹。
- 当前结果只来自 `qwen3-vl-plus`，不能代表其他 VLM。

## Future Work

- 扩展更多相互独立的场景和物体类别；
- 对同一设置进行多次重复实验，分析结果稳定性；
- 完成 `text_only` 和 `shuffled-image` 视觉依赖对照；
- 研究更长、更复杂的多步任务规划。