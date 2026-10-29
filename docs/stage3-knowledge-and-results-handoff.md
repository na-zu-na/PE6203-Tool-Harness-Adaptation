# 阶段三交付说明：工具知识传入与原始结果读取

更新日期：2026-10-30。适用范围：成员 1 的知识接入、日志保存，以及与成员 2、3 的数据交接。

**已确定的方式：成员 2 交付按任务组织的 JSON 知识包；运行器通过文件或目录加载；成员 3 使用统一脚本读取整批或单案例结果，导出 JSONL。**

## 1. 成员 2 要交付什么

每个任务一个文件，文件名为 `28.json`、`144.json` 或 `156.json`。知识包包含工具说明、参数 Schema、原工具身份，以及可选使用规则和更新成本。

下面是合法的格式示例。实际实验请保留所需的完整工具集合，或使用本项目提供的完整样例包：

```json
{
  "schema_version": 1,
  "task_id": 156,
  "strategy": "no_update",
  "source_version": "Early",
  "instructions": "按知识包中的工具说明和参数定义调用工具。",
  "update_cost": null,
  "tools": [
    {
      "name": "clock__get_time_info",
      "source_server": "@guanxiong/mcp-server-time",
      "source_name": "get_time_info",
      "description": "获取详细时间信息。",
      "inputSchema": {
        "type": "object",
        "properties": {
          "timezone": {"type": "string"}
        }
      }
    }
  ]
}
```

| 字段 | 约定 |
| --- | --- |
| `schema_version` | 固定为整数 `1` |
| `task_id` | 必须与本次任务相同，限固定清单 28、144、156 |
| `strategy` | `no_update`、`full_rewrite`、`selective_patch` 三者之一 |
| `source_version` | 知识捕获或生成时对应的版本，允许与执行环境不同，例如 Early 知识用于 Late |
| `instructions` | 可选字符串，用于工具使用规则和示例；追加到系统提示中 |
| `tools` | 非空列表，工具模型侧名称唯一；每项保留描述、参数定义及源服务/源工具名 |
| `update_cost` | 可省略或为 `null`；已测量时填 `tokens`、`seconds`、`usd` 中的一项或多项，均为非负数，token 为整数 |

`name` 是模型看到的函数名；`source_server`、`source_name` 决定实际 MCP 路由。工具说明和 Schema 不会从当前服务器补齐，也不会自动替换已经过时的原工具名。

格式错误、任务不匹配、名称重复、无效 Schema、负成本或清单外服务会在模型调用前被拒绝。**格式合法不代表工具在新环境中仍然可用**：旧路由失效时，错误应保留为真实执行记录。

## 2. 如何准备和传入知识包

完整 Early 样例位于 [knowledge_examples/no_update](../member1/knowledge_examples/no_update/)，由阶段二真实保存的 Early 工具定义导出。

成员 2 可用下列命令从已有 `tools.json` 创建新的知识包；输出文件已存在时会拒绝覆盖：

```powershell
.venv\Scripts\python.exe -X utf8 member1/knowledge.py --tools member1/evidence/stage2/validation/Early-task-156/result/tools.json --output outputs/handoff/no_update/156.json --task-id 156 --source-version Early --strategy no_update
```

在仓库根目录运行同一组 Early 知识包、三个环境版本：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_versions.py --version all --knowledge-dir member1/knowledge_examples/no_update
```

只接入一个文件时，需要同时指定任务 ID：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_versions.py --version Late --task-id 156 --knowledge-file member1/knowledge_examples/no_update/156.json
```

正式重写/修补实验，建议由成员 2 按“策略 / 目标版本 / 任务”组织文件，例如：

```text
outputs/handoff/
├─ full_rewrite/Late/28.json
├─ full_rewrite/Late/144.json
├─ full_rewrite/Late/156.json
└─ selective_patch/Late/...
```

在成员 2 实际生成相应文件之后，批量接入命令为：

```powershell
.venv\Scripts\python.exe -X utf8 member1/run_versions.py --version Late --knowledge-dir outputs/handoff/full_rewrite/Late
```

同一目录内的知识包必须使用同一策略标签。`--knowledge-dir` 指向的这一组文件会原样应用到所有选定版本；这适合验证“不更新”。重写/修补产生不同目标版本的知识时，应分别指定版本和对应目录。

**本阶段提供三种策略的共同输入接口，不代替成员 2 实现具体更新方法；仅修改 `strategy` 标签不算完成该策略。**

文件格式不限制成员 2 内部如何组织知识库。若使用统一知识库，可在完成更新后按任务导出文件，另行记录整体更新范围及成本。

## 3. 为什么“不更新”不会被悄悄刷新

1. 开始整批运行前，先校验并冻结输入文件字节，保存到该批次的 `knowledge_inputs/`。外部原文件随后被修改，不影响本批已冻结的输入。
2. 每个案例把实际输入另存为 `result/knowledge.json`，记录 SHA-256、来源版本和策略。
3. 传入文件时，直接使用包内的工具定义和规则，跳过实时工具选择及描述覆盖；实时 MCP 列表仅另存为 `runtime_tools.json` 供审计。
4. 实际提供给模型的定义保存在 `tools.json`，并记录其哈希。旧工具名按包内身份形成路由，不根据当前服务器名称进行修复。

本次验证中，同一任务在 Early、Middle、Late 使用的知识包字节与工具定义完全一致。Late 服务器已经新增的时区转换工具仍可在审计列表中看到，但不会因此进入 Early 知识包的模型工具集合。

未提供知识文件时，阶段二的实时工具模式仍然可用，并标记为 `environment_smoke`，不能将它冒充“不更新”实验。

## 4. 成员 3 如何读取原始结果

读取脚本：[read_results.py](../member1/read_results.py)。下面命令可直接读取本次提交的验证材料，输出 UTF-8 JSONL，每行对应一个案例：

```powershell
.venv\Scripts\python.exe -X utf8 member1/read_results.py member1/evidence/stage3/handoff_validation --output outputs/stage3-collected.jsonl
```

读取新运行的整批结果时，将输入路径替换为命令输出的 `outputs/stage3-...` 目录。也可以传入 `suite.json`、单案例目录、该案例的 `result/` 或 `result/summary.json`。输出文件已存在时不会覆盖，换一个文件名即可。

代码中可直接调用：

```python
from member1.read_results import read_results

for row in read_results("member1/evidence/stage3/handoff_validation"):
    print(row["version"], row["task_id"], row["strategy"], row["status"])
    if row["answer_record"] is not None:
        answer_for_judge = row["answer_record"]
        # 使用 answer_for_judge 中的 question、answer、trajectory_messages、
        # involved_tools 等字段接入后续评分。
```

| JSONL 字段 | 内容 |
| --- | --- |
| `schema_version` | 读取输出格式版本，目前为 1 |
| `task_id`、`version`、`strategy`、`status` | 案例标识和最终执行状态 |
| `knowledge` | 输入知识包的来源、版本、SHA-256 |
| `update_cost` | 成员 2 提供的知识更新成本；未上报时为 `null`，不会猜成 0 |
| `summary` | 完整运行摘要，包括模型参数、错误、工具调用计数和文件哈希 |
| `answer_record` | 原始 `ANSWER/<ID>.json`，未生成时为 `null` |
| `trajectory_messages` | 完整已保存对话；没有最终答案时尝试读取过程检查点 |
| `events` | 原始模型事件、完整工具返回、模型实际返回的 token 用量等 |
| `read_errors` | 截断 JSON、损坏 UTF-8 或其他读取问题，保留此前可解析内容 |
| `source_files` | 相对于归一化读取根目录的原始文件位置，不依赖历史机器绝对路径 |

读取托管案例时，以执行器写入的 `run_summary.json` 为最终状态。即便直接传入 `result/`，也不会把超时前遗留的 `running` 或清理前的 `completed` 当作最终状态。

模型工具名含服务别名。需要原工具身份时，使用 `answer_record.involved_tools` 中的 `source_server`、`source_name` 对照，不要把别名前缀误认为工具演化改名。

## 5. 保留哪些日志，怎样区分成本

```text
outputs/stage3-<批次>/
├─ suite.json
├─ knowledge_inputs/<ID>.json       # 批次开始时冻结的输入
└─ <版本>-task-<ID>/
   ├─ run_summary.json             # 包括超时、清理异常在内的最终状态
   ├─ mcp.log / runner.log
   └─ result/
      ├─ summary.json
      ├─ knowledge.json            # 此案例实际输入的原始知识包字节
      ├─ tools.json                # 模型实际获得的工具定义
      ├─ runtime_tools.json        # 服务器实时工具列表，仅供审计
      ├─ trajectory.json           # 随模型/工具事件保存的对话检查点
      ├─ events.jsonl              # 完整工具结果、模型事件、用量及错误
      └─ ANSWER/<ID>.json
```

模型异常、工具异常、执行器超时都保留已产生的记录。超时标记为 `runner_timeout`，不会误记为启动失败；清理异常标记为 `cleanup_error` 并保留原执行状态。日志末尾被截断时，读取器保留完整事件并报告读取错误。

更新成本来自知识包的 `update_cost`，是成员 2 对更新操作的测量或记录。`model_usage` 事件是任务推理的实际返回用量，两者分开保存。同一个已生成知识包的多次使用不意味着执行了多次更新，正式成本汇总应结合成员 2 的更新记录统计。

所有策略共用模型 `deepseek-v4-flash-ga-260731`、temperature 0.2、最大输出 4096 token，以及固定的 10 轮预算。预算不再随包内工具数量变化，并修正了边界多执行一轮或最后一轮成功被误记为超限的问题。

## 6. 本次验证结果

本次只使用提供的三个 Early `no_update` 知识包，在固定任务和三个真实环境上完成接口验证。**不包含全量重写/选择性修补的效果比较，也未计算 TF、PE、ECS。**

| 版本 | 任务 ID | 工具调用 / 成功返回 | 输入方式 | 状态 |
| --- | --- | --- | --- | --- |
| Early | 28 | 5 / 5 | provided_file | completed |
| Early | 144 | 4 / 4 | provided_file | completed |
| Early | 156 | 3 / 3 | provided_file | completed |
| Middle | 28 | 5 / 5 | provided_file | completed |
| Middle | 144 | 3 / 3 | provided_file | completed |
| Middle | 156 | 2 / 2 | provided_file | completed |
| Late | 28 | 6 / 6 | provided_file | completed |
| Late | 144 | 3 / 3 | provided_file | completed |
| Late | 156 | 3 / 3 | provided_file | completed |

实际材料见 [handoff_validation](../member1/evidence/stage3/handoff_validation/)。每个任务的三个版本均核对了输入包哈希、模型工具定义一致性、检查点和原始返回。自动测试共 37 项通过，另完成独立代码检查及异常状态读取回归修复。

`completed` 只是执行状态，不自动等于高分；`tool_error` 也不意味着最终任务一定失败。成员 3 应将保留下来的答案和轨迹交给 judge，不能直接把状态换算成分数或丢弃异常案例。

正式评分使用 `mode=live_model` 的运行；工具检查模式是预检，不是模型任务结果。在正式模型运行中，应保留包括失败在内的全部案例。

## 7. 三位开发成员的交接

- **成员 2**：按此格式交付知识包，负责真实的不更新、全量重写和选择性修补逻辑，以及更新成本记录。
- **成员 1**：已完成文件接入、防自动刷新、固定运行设置、原始轨迹和错误保存。
- **成员 3**：通过读取脚本收集全部案例，继续接入评分、重复实验和结果汇总。

阶段三已具备后续联调所需的输入输出接口；阶段四仍需使用成员 2 的真实策略产物进行联合实验。
