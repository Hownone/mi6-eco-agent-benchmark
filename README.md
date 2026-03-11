# mi6-eco-agent-benchmark

mi6-eco-agents 的 Benchmark Case 自动构建工具。从开源 RTL 代码出发，利用 LLM 自动生成 Conformal ECO 流程所需的全部配置文件，并支持自动生成符合 ECO 场景的 RTL 变体（r1），用于评估 eco-agent 的端到端能力。

## 项目背景

[mi6-eco-agents](https://github.com/user/mi6-eco-agents) 是一套自动化 Conformal ECO → Signoff Clean 的 Agent 系统。它需要标准化的输入 case 来驱动：

- **r0（基线版本）**：原始 RTL + P&R 后的 netlist/DEF/SDC
- **r1（修改版本）**：经过 ECO 修改的 RTL

收集开源 RTL 代码很容易，但大多数开源项目不提供 `func.sdc`、`load.tcl` 等 EDA 配套文件。本项目解决这个问题——用 LLM 分析 RTL 端口和层次结构，自动生成合理的约束文件，并自动构造符合 ECO 场景的 r1 变体。

## 架构概览

```
┌──────────────────────────────────────────────────────────┐
│                      CLI (cli.py)                        │
│   build-case │ gen-variant │ validate │ batch-build      │
└──────┬───────┴──────┬──────┴─────┬────┴──────────────────┘
       │              │            │
       ▼              ▼              ▼
┌─────────────┐ ┌───────────┐ ┌───────────┐
│ case_builder│ │variant_gen│ │ validator │
│   (编排层)   │ │ (r1 生成)  │ │ (校验)    │
└──────┬──────┘ └─────┬─────┘ └───────────┘
       │              │
       ▼              ▼
┌─────────────────────────────┐   ┌───────────┐
│       rtl_analyzer/         │   │  llm.py   │
│  verilog_parser.py  静态解析 │◄──┤ LLM 调用层 │
│  hierarchy.py     层次分析   │   │ (fallback)│
└──────┬──────────────────────┘   └───────────┘
       │
       ▼
┌─────────────────────────────┐
│        generators/          │
│  sdc_gen.py     LLM+模板    │
│  load_tcl_gen.py  确定性     │
│  flist_gen.py     确定性     │
│  design_json_gen.py 确定性   │
└─────────────────────────────┘
```

核心设计原则：

- **LLM 只做语义决策**（时钟频率估算、多时钟域关系判断），不直接生成 Tcl 语法
- **Jinja2 模板渲染**保证输出格式 100% 正确
- **确定性逻辑与 LLM 逻辑严格分离**：`load.tcl`、`mi6.flist`、`design.json` 完全不依赖 LLM

## 生成的 Case 结构

```
<case_name>-r0/
├── rtl/                    # RTL 源码
│   ├── top.v
│   └── ...
├── func.sdc                # 功能约束（LLM + 模板生成）
├── load.tcl                # Genus 加载脚本（确定性生成）
├── mi6.flist               # 文件列表（确定性生成）
└── design/
    ├── design.json          # 设计元数据（确定性生成）
    └── data/                # P&R 产出（阶段 2 填充）
        ├── signoff.v
        ├── signoff.def
        └── signoff.sdc

<case_name>-r1/
├── rtl/                    # 修改后的 RTL
├── func.sdc                # 从 r0 复制
├── load.tcl
├── mi6.flist
├── CHANGELOG.md            # 自动生成的变更说明
└── design/
    └── design.json
```

## 安装

```bash
cd mi6-eco-agent-benchmark
uv venv .venv
source .venv/bin/activate
.venv/bin/python -m ensurepip
.venv/bin/python -m pip install -e .
```

## 环境变量

至少配置一个 LLM API Key，优先级从高到低：

| 环境变量 | Provider | 用途 |
|---------|----------|------|
| `MI6_PROVIDERS__OPENROUTER__API_KEY` | OpenRouter | 主力（默认 claude-sonnet-4.6） |
| `MI6_PROVIDERS__DEEPSEEK__API_KEY` | DeepSeek | Fallback（deepseek-reasoner） |
| `MI6_PROVIDERS__BIGMODEL__API_KEY` | 智谱 | Fallback（glm-5） |

当主力 Provider 调用失败时，自动按顺序尝试 fallback。

## 使用方法

### 1. 从 RTL 构建 r0 Case

```bash
benchmark build-case \
  --rtl-dir /path/to/verilog/files \
  --output-dir /path/to/cases/my_design-r0
```

可选参数：

| 参数 | 说明 |
|------|------|
| `--top-module NAME` | 手动指定 top module（最高优先级） |
| `--top-config PATH` | 指定含 `design_top` 的 config.py |
| `--clock-period NS` | 覆盖时钟周期（不指定则由 LLM 估算） |
| `--model MODEL` | 覆盖 LLM 模型（如 `openrouter/anthropic/claude-opus-4.6`） |
| `--no-copy-rtl` | 不复制 RTL 文件 |

**Top Module 解析优先级**：`--top-module` > `--top-config` 中的 `design_top` > case 目录下 `config.py` 中的 `design_top` > 自动推断

### 2. 生成 r1 变体（ECO 修改版）

```bash
benchmark gen-variant \
  --r0-dir /path/to/cases/my_design-r0 \
  --output-dir /path/to/cases/my_design-r1
```

可选参数：

| 参数 | 说明 |
|------|------|
| `--mutation-type TYPE` | 指定 ECO 变体类型（见下表），不指定则自动选择 |
| `--top-module NAME` | 手动指定 top module |
| `--top-config PATH` | 指定含 `design_top` 的 config.py |

支持的 10 种 ECO 变体类型：

| 类型 | 场景 |
|------|------|
| `bug_fix` | 修复功能 bug（计数器越界、状态跳转错误、缺失复位） |
| `new_feature` | 新增小功能（状态寄存器、旁路 mux、调试端口） |
| `timing_opt` | 关键路径插入流水级 |
| `area_opt` | 资源共享 / 时分复用减面积 |
| `power_opt` | 添加时钟门控 / 操作数隔离 |
| `fsm_refactor` | FSM 重构（补缺失状态、拆分复杂状态） |
| `pipeline_insert` | 数据通路插入流水级 |
| `interface_change` | 修改模块接口（加宽总线、添加握手信号） |
| `clock_domain_fix` | 跨时钟域修复（添加同步器 / FIFO） |
| `reset_logic_fix` | 复位逻辑修复（异步转同步、补缺失复位） |

生成完成后会自动产出 `CHANGELOG.md`，记录变更类型、修改摘要、涉及文件。

### 3. 校验 Case 完整性

```bash
benchmark validate --case-dir /path/to/cases/my_design-r0

# 要求 signoff 数据也必须存在
benchmark validate --case-dir /path/to/cases/my_design-r0 --require-signoff
```

### 4. 批量构建

```bash
benchmark batch-build \
  --source-dir /path/to/multiple/rtl/projects \
  --output-dir /path/to/cases/
```

扫描 `source-dir` 下所有含 HDL 文件的子目录，逐个生成 `<name>-r0` case。

## SDC 生成策略

func.sdc 的生成采用 **LLM 决策 + 模板渲染** 的混合方案：

1. **RTL 静态分析**（正则解析器）提取模块端口、实例化关系、层次结构
2. **启发式规则**识别时钟 / 复位候选端口（匹配 `clk*`、`rst*` 等命名模式）
3. **LLM 返回结构化 JSON**：时钟端口、周期、多时钟域关系、复位端口
4. **Jinja2 模板**将 JSON 渲染为语法正确的 SDC

LLM 不直接写 Tcl 代码，避免语法错误。模板保证输出格式与 Genus/Innovus 兼容。

## 项目结构

```
src/benchmark/
├── cli.py               # CLI 入口：build-case / gen-variant / validate / batch-build
├── config.py            # LLM Provider 配置（OpenRouter / DeepSeek / 智谱，自动 fallback）
├── models.py            # 数据模型：端口、模块、时钟、SDC 参数、10 种 ECO 变体类型
├── llm.py               # LLM 调用层（自动清理 SOCKS 代理、Provider fallback）
├── top_resolver.py      # Top Module 解析：CLI 参数 > config.py design_top > 自动推断
├── case_builder.py      # 阶段 1 编排：RTL 分析 → 配置文件生成 → 输出 case
├── variant_gen.py       # r1 变体生成：LLM 驱动 ECO 修改 + CHANGELOG 输出
├── validator.py         # Case 完整性校验
├── rtl_analyzer/
│   ├── verilog_parser.py  # Verilog / SystemVerilog / VHDL 解析器
│   └── hierarchy.py       # 模块层次分析、Top Module 自动检测、拓扑排序
├── generators/
│   ├── sdc_gen.py         # func.sdc 生成（LLM + Jinja2）
│   ├── load_tcl_gen.py    # load.tcl 生成（确定性）
│   ├── flist_gen.py       # mi6.flist 生成（确定性）
│   └── design_json_gen.py # design.json 生成（确定性）
└── templates/
    └── func_sdc.j2        # SDC Jinja2 模板
```

## 支持的 HDL 格式

- Verilog (`.v`)
- SystemVerilog (`.sv`)
- VHDL (`.vhd`, `.vhdl`)

## 后续规划

- **阶段 2**：P&R 自动化（Genus + Innovus），生成 `signoff.v` / `signoff.def` / `signoff.sdc`
- **阶段 3**：批量 GitHub 开源 RTL 拉取 + 自动构建 case 库
