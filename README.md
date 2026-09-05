# VLM-Planning-Test

**中文名称：视觉语言模型任务规划测试**

项目开发、真实实验中发现的问题及修复历史见 [`问题与改进记录.md`](问题与改进记录.md)。
Benchmark 2.1 的完整中文实验报告见 [`实验报告_20260904.md`](实验报告_20260904.md)。

## 项目概述

VLM-Planning-Test 是一个可在普通 Windows 电脑上运行的小型科研项目。系统输入一张桌面场景照片和一条中文任务指令，让视觉语言模型（VLM）输出机器人动作计划。本项目只研究“视觉 + 语言 → 动作规划”，不控制真实机器人，也不涉及模型训练。

研究问题是：**结构化动作提示能否提高视觉语言模型在简单具身任务规划中的可靠性？**

当前 benchmark 与评测规则版本为 **2.1-visual-grounded**。10 张真实照片均已登记并通过哈希核对。Benchmark 2.1 正式实验已完成，80 次 API 调用全部成功，总体自动 Planning Accuracy 为 **88.75%**；完整结果、失败分析和适用范围见 [`实验报告_20260904.md`](实验报告_20260904.md)。旧真实结果只作历史留档，不能与 2.1 数字直接比较。

## 系统流程

```text
桌面照片 + 中文指令 → 同一个 VLM + 两种提示方法之一 → 模型原始输出
→ 透明的规则解析器 → 动作合法性与目标状态模拟 → 逐任务结果、指标、失败案例和图表
```

真实模型只能看到图片和指令。物体清单、任务类别、标准答案和目标状态仅供评测，不会发给模型。

## 动作空间

结构化模式只允许：

| 动作 | 含义 |
|---|---|
| `PICK(object)` | 抓取场景中存在的物体；夹爪必须为空 |
| `PLACE_IN(object, container)` | 预留的放入容器动作；当前 10 个场景没有容器，因此使用它会被判无效 |
| `PLACE_LEFT(object, target)` | 把手中物体放到目标物体左边 |
| `PLACE_RIGHT(object, target)` | 把手中物体放到目标物体右边 |
| `INVALID_TASK` | 拒绝无法执行的任务，必须单独出现 |

动作名和物体标识保留英文，以便稳定解析；用户指令、提示词和说明使用中文。左右方向以观看照片的人的视角为准。

## Benchmark 数据集

数据集包含 **10 个场景 × 每场景 4 个任务 = 40 个任务**：单步、空间、多步、不可执行四类各 10 条。不可执行任务至少引用一个照片中不存在的物体，正确答案为 `INVALID_TASK`。同一张照片对应四条指令，不需要拍摄 40 张照片。

新版故意让多个场景共享同一句视觉指代指令，但标准答案随照片内容改变。例如“把最右边的物体放到最左边物体的左边”，模型必须先看图，不能把指令直接翻译成固定答案。单步和不可执行任务使用“如果照片中有某物体就拿起，否则拒绝”，同一物体在不同照片中会形成存在/不存在对照。程序会检查：

- 可执行任务引用的物体都存在于对应场景；
- 不可执行任务至少引用一个不存在的物体；
- 指令、标准动作和目标状态一致；
- 每个场景恰好包含四类任务各一条，四类任务各 10 条；
- 标准动作能够通过动作模拟器执行。
- 视觉指代任务存在“相同指令、不同标准答案”的跨场景对照。

`data/scenes.json` 保存场景物体、容器、初始关系、拍摄顺序和照片校验状态。`data/tasks.json` 保存任务/场景 ID、图片路径、中文指令、类别、标准动作和目标状态。

## 照片拍摄清单

照片放入 `data/images/`，按观看者视角从左到右摆放：

| 文件名 | 从左到右应包含的物体 |
|---|---|
| `scene_01.jpg` | 纸巾、鼠标、笔、橡皮 |
| `scene_02.jpg` | 眼镜、饮料瓶、雨伞、计算器 |
| `scene_03.jpg` | 鼠标、橡皮、眼镜、饮料瓶 |
| `scene_04.jpg` | 笔、计算器、纸巾、雨伞 |
| `scene_05.jpg` | 饮料瓶、纸巾、鼠标、眼镜 |
| `scene_06.jpg` | 雨伞、笔、橡皮、计算器 |
| `scene_07.jpg` | 计算器、眼镜、饮料瓶、笔 |
| `scene_08.jpg` | 橡皮、雨伞、纸巾、鼠标 |
| `scene_09.jpg` | 纸巾、眼镜、计算器、橡皮 |
| `scene_10.jpg` | 鼠标、饮料瓶、笔、雨伞 |

拍摄要求：每种物体只放一个；不要拍入清单外物体或手；物体相互分开、无遮挡；略微俯拍，确保左右关系清楚。雨伞可以折叠，饮料瓶应盖紧并竖直放稳，眼镜展开摆放，纸巾使用同一种纸巾包或纸巾盒即可。只拍初始场景，不需要拍完成状态。

照片放好后运行：

```powershell
.\.venv\Scripts\python.exe validate_benchmark.py --require-images
.\.venv\Scripts\python.exe verify_scene.py --scene all --confirm-objects-and-layout
.\.venv\Scripts\python.exe validate_benchmark.py --require-verified
```

第二条命令记录你已人工核对照片，并保存照片 SHA-256；它不是自动物体识别。如果照片被替换或修改，真实实验会被阻止，必须重新核对。

## 两种实验方法

### 方法 A：自由文本提示

模型可以先简要分析图片，但最后必须提供以 `【最终操作计划】` 开头的独立区块。该区块使用公开的有限句式，例如：`拿起纸巾。`、`把橡皮放到鼠标的右边。`。解析器支持编号、Markdown、中文物体名和小写英文标识；区块外的图片分析不作为机器人动作执行。

### 方法 B：结构化动作提示

模型只能输出动作格式，例如：

```text
PICK(eraser)
PLACE_RIGHT(eraser, mouse)
```

两种方法使用同一模型、图片、指令、温度 0 和 512 token 上限。每个“任务 × 方法”请求一次，共 80 次；顺序用固定随机种子 42 打乱。

运行器还支持三种独立的图片条件：`correct` 给正确照片，`text_only` 完全不给照片，`shuffled` 给下一场景的错误照片。主实验使用 `correct`。另外两种是对照实验：如果模型真的利用图片，正确图片的表现应当优于无图片和错配图片。每个条件单独保存、单独续跑，避免混在一份结果中。

## 评测指标

项目不使用黑盒评分器，也不把字符串完全相等作为唯一正确性标准。解析后的动作会经过前提检查和目标状态模拟。

| 指标 | 透明、可复现的定义 |
|---|---|
| **任务规划成功率 ↑** | 动作合法、达到全部目标并按指令顺序完成。单步“拿起”任务结束时应持有所需物体；放置任务结束时夹爪应为空。不可执行任务必须只输出 `INVALID_TASK`。允许不破坏目标的额外合法动作。 |
| **动作有效率 ↑** | 输出可完整解析；动作、参数数量、物体、夹爪状态和容器前提均合法。 |
| **物体幻觉率 ↓** | 引用不存在物体的次数 ÷ 全部已解析物体参数引用次数。分母为零时记录 `null`。 |
| **格式合规率 ↑** | 两种方法都必须能被各自公开的规则解析器完整解析，不能留下未识别片段。结构化模式使用严格动作语法；自由文本模式使用 README 公布的中文句式解析器。另行保存 `response_nonempty`，避免把“有文字但无法评测”误记为格式合规。 |

同时报告出现幻觉的任务比例、自由文本解析覆盖率、物体引用分母、API 错误数和失败原因数量。API 错误在三个任务级指标中计为失败，从幻觉率和解析覆盖率分母中排除并单独报告。

## 安装与快速开始

需要 Python 3.10+（本地使用 Python 3.12 验证）：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe validate_benchmark.py
.\.venv\Scripts\python.exe demo.py --backend mock --task-id task_001
.\.venv\Scripts\python.exe demo.py --backend mock --task-id task_003 --mode free_form
.\.venv\Scripts\python.exe run_evaluation.py --backend mock
```

MockVLM 是读取标准答案的理想测试夹具，不看图片，也不代表真实模型能力。

## 运行真实实验

项目当前默认使用**阿里云百炼的通义千问视觉模型**。完成并核对照片后，在阿里云百炼控制台创建 API Key，再填写 `.env`：

```dotenv
VLM_API_KEY=你的阿里云百炼API Key
VLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
VLM_MODEL=qwen3-vl-plus
```

然后运行：

```powershell
# 不调用 API，只检查数据、照片、模型配置和预计任务数
.\.venv\Scripts\python.exe run_evaluation.py --backend real --dry-run

# 可选：单条真实调用；加 --save 可保存到 results/demo_时间戳/
.\.venv\Scripts\python.exe demo.py --backend real --task-id task_001

# 完整实验：40 个任务 × 2 种提示模式 = 80 对任务/模式
.\.venv\Scripts\python.exe run_evaluation.py --backend real
```

可选的视觉依赖对照实验各需另外调用 80 次 API：

```powershell
.\.venv\Scripts\python.exe run_evaluation.py --backend real --image-condition text_only
.\.venv\Scripts\python.exe run_evaluation.py --backend real --image-condition shuffled
```

完整做三种条件共需 240 次调用。建议先完成 80 次 `correct` 主实验并检查结果，再决定是否付费运行两个对照。

适配器使用百炼的 OpenAI 兼容 Chat Completions 接口、base64 JPEG 和中文指令。百炼 API Key 与服务地域必须匹配；这里使用中国大陆兼容地址。`.env` 已被 Git 忽略，密钥不会写入结果。缺图、图片损坏、未人工核对或照片被替换时，会在创建 API 客户端前停止。

每次完整运行会创建 `results/run_YYYYMMDD_HHMMSS/`，不会覆盖旧结果：

- `run_metadata.json`：模型、参数、中文提示词、时间及数据/代码/照片哈希；
- `raw_results.json`：80 条逐调用记录，包括任务、图片、提示模式、标准答案、原始/解析输出、四项指标、幻觉引用、失败原因、模拟结果、耗时、重试次数、请求 ID 和服务商返回的 token usage；
- `summary.json`：总体、四类任务、自由文本和结构化模式的统计；
- `summary.csv`：与 JSON 相同指标的扁平汇总表；
- `failure_cases.json`：自动筛选的失败任务；
- `figures/planning_success.png`：按类别比较的成功率图。

每次调用结束后都会原子写入 checkpoint。429、网络错误和常见 5xx 最多尝试 3 次，其他错误不盲目重试；真实接口失败时不会偷偷切换为 mock。运行元数据会保存实际 API 调用数、成功/失败调用数、完成任务对数、总耗时和累计 token usage（服务商返回时）。

如果实验中断，使用输出中显示的原结果目录续跑：

```powershell
.\.venv\Scripts\python.exe run_evaluation.py --backend real --resume results\run_YYYYMMDD_HHMMSS
```

续跑前会核对 backend、模型、数据和所有图片哈希；已有成功记录不会再次调用。失败记录会重试。若调用恰好在进程被强制结束时已到达服务商但尚未写入 checkpoint，该单次调用是否计费无法由本地可靠判断。

查看最新完整 `run_*` 结果，或指定某次目录：

```powershell
.\.venv\Scripts\python.exe show_results.py
.\.venv\Scripts\python.exe show_results.py results\run_YYYYMMDD_HHMMSS
```

## 当前结果与失败案例

Benchmark 2.1 正式真实结果保存在 `results/run_20260904_161430/`。80 次 API 调用全部成功，总体自动 Planning Accuracy 为 88.75%，自由文本为 80%，结构化动作为 97.5%。9 个自动失败中，5 个来自自由文本解析器未收录正常中文同义词，4 个与模型视觉识别有关；详细区分见实验报告。

`results/run_20260904_152757/` 和 `results/run_20260904_155231/` 保留原始记录且不重算，用于记录旧任务设计、scene 04 元数据错误、自由文本解析覆盖不足和结构化多步动作遗漏等问题。`results/local_dry_run_v2_1_20260904/` 是 mock 流程检查；MockVLM 读取标准答案，不看图片，只验证程序管线，不能证明模型能力。

公开仓库中的真实结果不包含 API Key。`.env` 只保存在本地并由 Git 忽略；其他使用者应复制 `.env.example` 并填写自己的配置。

`examples/synthetic_failures.json` 是明确标记的人工测试案例，覆盖物体幻觉、非法动作、格式错误、空间关系错误、顺序错误和未拒绝不可执行任务；它们不是模型真实失败。

## 局限性

- 40 条任务共享 10 张照片，不能视为 40 个独立视觉场景，也不足以声称统计显著性。
- 同一句视觉指令跨场景复用是有意设计的对照，不是重复数据；这些任务仍共享有限的物体和句式。
- 无图片和错配图片对照能检测模型是否依赖视觉，但不能单独证明模型正确识别了每一个物体；仍需检查逐条原始输出。
- 拍照前，`scenes.json` 只是预期清单。解码和哈希不能证明画面内容，仍需人工核对。
- 中文自由文本解析器只执行 `【最终操作计划】` 区块中的公开句式。区块外可以解释，但区块内的代词、复杂句或未公开同义词仍可能解析失败。
- 为避免把常见同义标识误算成幻觉，评测前公开归一化：`tissues`、`tissue_box`、`tissue_pack` → `tissue`，`drink_bottle`、`beverage_bottle` → `bottle`，`rubber` → `eraser`；逐条结果会保存归一化记录。其他未知名称仍按幻觉处理。
- 结构化方法天然更容易解析；比较时必须同时报告解析覆盖率并检查原始输出。
- 未解析自由文本中的幻觉无法可靠计数。解析覆盖率低时，低幻觉率没有说服力。
- 符号模拟器不模拟碰撞、可达性、物理尺寸、关系传递或真实轨迹。
- 评测允许不破坏目标的额外合法动作，没有衡量计划最短性。
- 温度为 0 也不保证服务商完全确定；每个任务只运行一次，不能衡量随机波动。

## 后续工作

按清单拍摄并核对 10 张照片，配置支持图片的真实 VLM，运行双方法对照，人工审查自由文本解析失败，并逐步增加独立场景和重复实验次数。

## 代码结构

- `src/benchmark.py`：生成和校验数据；
- `src/prompts.py`：中文提示词；
- `src/vlm.py`：Mock 和真实接口；
- `src/parser.py`：结构化及中文自由文本解析；
- `src/evaluator.py`：动作模拟和指标；
- `demo.py`：单条演示；
- `run_evaluation.py`：双方法批量实验；
- `show_results.py`：终端展示总体、分类和提示模式结果；
- `tests/`：数据、解析、评测、图片门禁和接口测试。
