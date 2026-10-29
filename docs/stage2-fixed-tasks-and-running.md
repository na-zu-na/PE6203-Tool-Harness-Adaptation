# 阶段二交付说明与固定任务清单

更新日期：2026-10-30。适用范围：成员 1 的“支持三个环境版本和固定任务清单”阶段。

阶段二已经实现真实服务快照切换、固定任务执行、独立工作目录和原始日志保存。已使用同一个方舟模型，在三个版本上分别运行清单中的三个任务，完成 9 次真实验证。

## 1. 固定任务清单

机器可读清单：[tasks_manifest.json](../member1/tasks_manifest.json)。任务来自上游 `chosen_idx.json` 的 201 项正式选择，保留原问题与标签。

清单在阶段二模型验证前确定，选择依据为服务依赖少、无需额外商业服务凭证、可在本地执行，并覆盖文件状态和三类环境变化。后续三种策略统一使用这三项任务及三个版本。

| 任务 ID | 任务内容 | 所需服务 | 变化类型及证据范围 |
| --- | --- | --- | --- |
| **28** | 比较 `txt/log_yesterday.txt` 与 `txt/log_today.txt`，将未解决事项写入 `tasks.md` | `mcp-filesystem-server`、`mcp-tasks` | **Parameter、Description**。Late 的 `read_multiple_files` 有新增可选参数和描述变化，`tasks_setup` 的描述也发生变化。Middle 的 `list_directory` 排序参数属于服务级变化，该工具未暴露给本任务，不把它计作任务实际使用的变化。 |
| **144** | 查询东京当前时间并换算为纽约时间 | `time-mcp`、`time`（Python `mcp-server-time`） | **Description**。`time-mcp` 的 `convert_time`、`current_time` 描述在元数据中演化；另一时间服务保持不变。两者同名的 `convert_time` 已分别路由。 |
| **156** | 计算东京当天已过去的秒数 | `@guanxiong/mcp-server-time`、`calculator`（Python `mcp-server-calculator`） | **Parameter、Tool**。Middle 的 `get_time_info` 增加可选参数；Late 新增 `convert_timezone` 及其后续可选参数。新增工具确实存在并可调用，但该问题不强制使用它，不能将此任务描述成强制工具迁移测试。 |

这个三任务子集是课程项目的较小实验范围。接口新增多为向后兼容变化，因此结果不保证体现修补策略优势；也不足以推断对大规模、破坏性工具迁移的普遍效果。

## 2. 三个版本如何对应真实环境

| 运行参数 | 官方服务包 | 描述元数据层 | 默认端口 |
| --- | --- | --- | --- |
| `Early` | `original_servers.zip` | 不应用演化描述 | 3051 |
| `Middle` | `iter3_servers.zip` | 第 1 层 `HYBRID/evolution.json` | 3053 |
| `Late` | `iter5_servers.zip` | 第 1–4 层，按先后顺序累计 | 3055 |

**映射以真实服务源码和工具列表为准。** 当前发布的 `iter3` 包只包含第 1 层对应的时间参数扩展，尚无 `convert_timezone`，文件服务也尚无 `read_multiple_files` 的元数据参数。`iter5` 包则包含第 4 层的时区参数与文件读取扩展。不能按包名中的数字直接推算 `HYBRID` 层数，也不能将尚不存在的工具提前提供给模型。

- 基准来源：`Octobrist/MCPEvol-Bench`，上游 commit 为 `888c779a0fe735f612ca62bdd1fdd7c9e6bf8701`。
- 服务包来源：[anonymous2233/evol-servers](https://huggingface.co/datasets/anonymous2233/evol-servers/tree/162e3ffbea1717ac8a20fe9b26465e29117229e4)，固定 revision 为 `162e3ffbea1717ac8a20fe9b26465e29117229e4`。
- 本仓库保存了所需 4 个 Node 服务在三套快照中的 `package.json` 与执行入口，共 24 份原始文件，约 200 KB，无需下载完整 3.4 GB 服务包。
- 每份原始文件的包内路径和 SHA-256 见 [快照来源记录](../member1/snapshots/provenance.json)。启动前核对哈希，运行记录再保存实际入口路径及哈希。
- 两个 Python 服务在三个版本中使用同样的锁定版本：`mcp-server-time==2026.7.10`、`mcp-server-calculator==0.2.1`。

Parameter、Tool 变化由真实服务器代码执行；Description 变化按上游演化元数据应用到模型看到的工具描述及参数说明，不自行改写参数类型或业务逻辑。原始 MCP 工具列表和模型实际看到的工具定义分别保存，便于复查。

## 3. 如何运行

在 `MCPEvol-Bench` 根目录的 PowerShell 执行。已有阶段一的 `.env` 可继续使用，模型固定为 `deepseek-v4-flash-ga-260731`。

首次安装或拉取更新后安装依赖：

```powershell
.venv\Scripts\python.exe -m pip install -r member1/requirements-lock.txt
npm.cmd ci --registry=https://registry.npmjs.org --cache=.npm-cache --ignore-scripts --no-audit --no-fund
```

运行全部固定任务、全部三个版本：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_versions.py --version all
```

只运行指定任务的三个版本：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_versions.py --version all --task-id 156
```

只运行某一版本下的固定清单：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_versions.py --version Middle
```

只检查服务和所需工具、不调用模型：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_versions.py --version all --check-tools
```

入口会自动生成配置、启动对应版本、执行任务并停止本次启动的服务，**不需要先手动运行阶段一的 `start_mcp.ps1`**。默认端口被占用时直接报错，不会把已有服务误记成所请求的版本。清单外任务会被拒绝。

## 4. 状态重置与一致性

- 每个“版本 × 任务”使用独立 MCP 进程、运行目录和工作目录；相同版本下的两个任务也不共用任务状态。
- 两份日志从原始 `anotation_path/txt/` 重新复制，任务 28 生成的 `tasks.md` 保留在本次目录。
- 待办工具的工作目录和 `SOURCES_PATH` 都指向本次运行，初始来源登记为空，不继承前一次的任务文件。
- 工具的模型侧名称包含服务别名，例如 `time_mcp__convert_time` 与 `time_py__convert_time`，各自映射到不同 MCP 路由。
- 所有验证使用相同模型、temperature 0.2、最大输出 4096 token，以及阶段一确定的最终回答停止规则。
- Windows 上的待办服务通过模块路径适配加载原始快照；适配仅处理绝对路径导入，归档文件字节保持不变。适配代码为 [windows_paths.mjs](../member1/windows_paths.mjs)。

## 5. 验证结果

以下为本次真实模型运行记录，**不是 TF / PE / ECS 评分**。`completed` 表示执行流程正常结束并产生工具返回及最终回答。

| 版本 | 任务 ID | 工具调用次数 | 成功工具返回 | 状态 |
| --- | --- | --- | --- | --- |
| Early | 28 | 5 | 5 | completed |
| Early | 144 | 4 | 4 | completed |
| Early | 156 | 2 | 2 | completed |
| Middle | 28 | 5 | 5 | completed |
| Middle | 144 | 4 | 4 | completed |
| Middle | 156 | 3 | 3 | completed |
| Late | 28 | 5 | 5 | completed |
| Late | 144 | 3 | 3 | completed |
| Late | 156 | 2 | 2 | completed |

9 次运行的结果与原始轨迹见 [阶段二验证材料](../member1/evidence/stage2/validation/)。任务 28 在三个版本下均生成了各自的 `tasks.md`，可在相应案例的 `generated/tasks.md` 中查看。

独立检查发现的进程清理异常处理已补充：清理失败时仍写入运行摘要，记录 `cleanup_error` 和原执行状态，整批任务继续留下可追溯记录。自动测试共 17 项通过。

## 6. 日志和下一步对接

新运行的目录结构：

```text
outputs/stage2-<时间>-<批次>/
├─ suite.json
└─ <版本>-task-<ID>/
   ├─ run_summary.json      # 案例状态、模型、版本、配置及哈希
   ├─ mcp.log              # 服务启动与错误日志
   ├─ runner.log
   ├─ workspace/           # 本次独立任务文件及待办状态
   ├─ runtime/             # 本机配置与临时凭证，不作为公开交付材料
   └─ result/
      ├─ summary.json
      ├─ runtime_context.json
      ├─ runtime_tools.json # 服务器真实返回的工具列表
      ├─ tools.json         # 本次提供给模型的工具定义
      ├─ events.jsonl       # 模型输出与完整工具返回值
      └─ ANSWER/<ID>.json   # 供后续评分使用的轨迹
```

本次验证使用的是实时工具定义加官方描述演化，用于确认三个环境可以运行，标记为 `environment_smoke`。它尚不代表“不更新”“全量重写”或“选择性修补”中的任何一种策略结果；成员 2 后续接入知识更新时需要保持三种策略的可见信息和配置约定一致。

成员 3 可直接读取固定任务清单和 `ANSWER` 文件，继续接入 judge 评分、重复运行和结果汇总。失败分析仍需依据正式策略实验的真实轨迹整理，不能从本次全部正常结束的连接验证中虚构更新失败案例。

**阶段二验收：** 实际三版本切换、固定任务与变化映射、9 次真实运行、独立状态、原始日志和运行说明均已提供。
