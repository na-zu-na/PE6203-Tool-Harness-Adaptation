# 成员 1 阶段一运行说明

阶段二已经完成，新的自动三版本入口、固定任务清单和 9 次真实验证见 [阶段二交付说明](../docs/stage2-fixed-tasks-and-running.md)。本页保留阶段一的单任务运行方式与历史结果说明。

阶段一已在 Windows 上完成一次真实模型试运行：方舟 `deepseek-v4-flash-ga-260731` 调用 MCP 时间服务和计算器，完成 MCPEvol-Bench 原始任务 156，保存最终回答及调用日志。

## 1. 代码和环境来源

| 项目 | 本次使用内容 |
| --- | --- |
| 基准仓库 | https://github.com/Octobrist/MCPEvol-Bench |
| 上游 commit | `888c779a0fe735f612ca62bdd1fdd7c9e6bf8701` |
| 本地分支 | `member1-stage1` |
| 系统 | Windows 11，PowerShell |
| Python | 3.12.14，项目独立 `.venv` |
| Node.js / npm | 24.0.2 / 11.3.0 |
| 模型 | 火山方舟 `deepseek-v4-flash-ga-260731` |
| 接口 | `https://ark.cn-beijing.volces.com/api/v3` |
| 模型参数 | temperature 0.2，max_completion_tokens 4096 |
| 工具聚合器 | `@1mcp/agent` 0.39.6 |
| 时间服务 | `@guanxiong/mcp-server-time` 1.0.0 |
| 计算器 | `mcp-server-calculator` 0.2.1 |

本次是 Early / original 配置中的两个服务，未下载或启动演化服务包。上游 npm 命令未固定工具版本，本次通过 `package-lock.json` 和 `member1/requirements-lock.txt` 记录解析后的版本；阶段二需要继续确认 Middle、Late 的版本映射。

上游 README 测试环境为 Python 3.12、Node 24.13.0、npm 11.6.2；表中是本机实际通过运行的版本。阶段一使用远程模型 API，安装最小执行依赖，没有安装上游完整 requirements 中的 GPU、训练和 FastChat 依赖。原始 `requirements.txt` 和任务数据未修改。

## 2. 安装依赖

下面命令在 `MCPEvol-Bench` 根目录的 PowerShell 中执行。本机已安装，可直接进入第 3 节。

```powershell
# 首次安装：使用已安装的 Python 3.12 创建虚拟环境。
py -3.12 -m venv .venv

# 精确恢复本次 Python 环境。
.venv\Scripts\python.exe -m pip install -r member1/requirements-lock.txt

# 安装已锁定的本地 Node 依赖，不需要全局安装 1mcp。
npm.cmd ci --registry=https://registry.npmjs.org --cache=.npm-cache --no-audit --no-fund
```

本机 Python 3.12 来自 Codex 运行时，创建虚拟环境的实际命令是：

```powershell
& 'C:\Users\25537\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m venv .venv
```

`py -3.12` 适用于已注册该版本的其他电脑；安装依赖与后续运行命令已经在本机实际验证。

## 3. 配置模型

首次使用时复制 `.env.example` 为 `.env`，已有 `.env` 时直接编辑，保留已有凭证。配置项为：

```dotenv
ARK_API_KEY=在本地填写自己的方舟密钥
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
ARK_MODEL=deepseek-v4-flash-ga-260731
```

脚本从指定 `.env` 读取这些值；若进程已有同名环境变量，以进程环境变量为准。`.env` 已被 Git 忽略，示例文件没有密钥。

方舟接口配置依据：[兼容 OpenAI SDK](https://console.volcengine.com/ark/region%3Acn-beijing/docs/compatible-with-openai-sdk)。模型 ID 使用本组指定的值，并已通过真实调用验证。

## 4. 启动工具服务

在第一个 PowerShell 窗口执行，并保持运行：

```powershell
& .\member1\start_mcp.ps1
```

脚本生成本机路径配置 `member1/mcp.stage1.local.json`，然后将两个服务通过 1mcp 暴露到 `http://127.0.0.1:3050/mcp`。停止时在该窗口按 `Ctrl+C`。

1mcp 在配置旁自动生成的 capability、admin、runtime.owner、PID 等运行时文件已排除在 Git 提交之外；它们是本机临时状态，交接代码时使用干净的仓库文件及 `evidence` 即可。

当前 1mcp 会规范化并哈希较长的带作用域服务名，因此将时间服务在本机配置中的名称设为 `clock`，调用时使用 `clock_1mcp_get_time_info` 等路由；基准任务中的原服务名仍为 `@guanxiong/mcp-server-time`。这是运行路由映射，任务问题、工具参数和参考标签均保留原样。

## 5. 运行阶段一任务

在第二个 PowerShell 窗口进入同一仓库目录，先检查工具：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_task.py --check-tools
```

预期输出 `Status: tools_ready`。该命令实际发现三个所需工具，并人工调用时间服务和计算器验证连通性，不调用模型；日志标记为 `manual_tool_probe`。

然后运行真实模型任务：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_task.py
```

默认任务为 156，原问题为：

> What is the total number of seconds that have passed since the start of the day in Tokyo right now?

脚本从原始 `test_cases.json` 读取该任务，并校验其属于 `chosen_idx.json` 的 201 项正式选择。原始文件含 393 条候选记录，不能把候选数量当作正式基准任务数。模型只接收任务问题、系统提示和工具定义，不接收数据文件里已有的答案和轨迹。

本次运行经过 `get_time_info`、`get_current_time`、`calculate` 三次工具调用，时间字段为东京 2026-10-30 06:29:03，计算器返回 `23343`，模型给出了同样的最终结果。脚本输出 `Status: completed`，退出码 0。

每次运行保存到独立的 `outputs/stage1-<UTC时间>-<随机后缀>/`，不会覆盖已有运行。手动指定 `--output-dir` 时要求目录尚不存在。

## 6. 保存了哪些结果

| 文件 | 内容 |
| --- | --- |
| `summary.json` | 模型、任务、版本、代码版本、运行状态、工具调用计数、时间等 |
| `task.json` | 从基准中选出的任务字段 |
| `tools.json` | 实际加载的工具描述和参数定义 |
| `events.jsonl` | 逐条保存模型输出、完整工具返回值、错误信息 |
| `ANSWER/156.json` | 与上游评分输入相同的主要字段：question、servers、answer、trajectory_messages、stop、exceeded、involved_tools 等 |

成功运行的原始结果已另存到 [evidence/success/](evidence/success/)，便于随代码提交。排障时的工具名不匹配日志和达到轮次上限的首次模型运行保留在 `outputs/`。

`completed` 表示运行正常结束并有工具调用，不代表 TF / PE 已获高分；评分仍由成员 3 完成。

运行失败会保存 `summary.json` 和已产生的事件：缺少配置为 `configuration_error`，MCP 连接或工具发现失败为 `mcp_connection_error`，模型请求失败为 `model_error`，工具执行异常为 `tool_error`，达到轮次限制为 `round_limit`。

## 7. 对上游 Agent 的必要调整

复用 `src/custom/agents/SimpleOpenAIAgent.py` 的工具调用循环，做了以下调整：

1. FastChat 改为仅在选择 FastChat 分支时导入，远程 API 调用无需 GPU 推理依赖。
2. 增加事件回调，保存完整工具结果及模型/工具错误；原 Agent 给模型的工具返回值仍沿用截断规则，完整原文另存于 `events.jsonl`。
3. 显式设置请求超时为 60 秒、SDK 自动重试为 0；保留原 Agent 的外层退避重试。
4. 增加可选 `stop_on_final_answer`。阶段一入口启用它：有工具返回后，模型给出不含新工具调用的正文回答即可结束。默认值为 False，其他直接使用 Agent 的脚本仍保留原停止规则。

首次真实运行中，原停止规则不断在正确回答之后追加“继续调用工具”的提示，导致达到轮次上限。因此启用上述停止选项，并在 `summary.json` 的 `stop_policy` 中记录。正式对比时三种策略必须使用同一停止规则与推理配置。

观察到时间服务的 `get_current_time` ISO 输出存在时区偏移现象；本次秒数计算依据 `get_time_info` 返回的东京时、分、秒，计算结果一致。工具服务源码未修改；后续涉及 ISO 时间判断的任务需要单独核查。

## 8. 验证与交接

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -q
.venv\Scripts\python.exe -m pip check
git diff --check
```

测试覆盖：任务读取不泄漏已有答案、缺少凭证时记录失败、无需 FastChat 即可加载 Agent、模型错误日志、完整工具结果日志、最终回答后的停止行为。`pytest.ini` 将测试范围设为本组新增的执行部分；仓库中另附的 FastChat 测试依赖本地 GPU/服务，不属于本次远程 API 环境的验证范围。

成员 2 可以先查看 `ChatModel` 的 `tools` 参数和 `run_task.py` 的加载位置；正式知识更新接口在阶段三联调。成员 3 可以先使用 `ANSWER/156.json` 对接评分流程，注意上游评分脚本仍有自己的环境和 judge 配置需求。

**阶段一交付：** 单任务运行命令、两个真实工具服务、真实模型调用及最终答案、原始轨迹、依赖锁定和本说明。
