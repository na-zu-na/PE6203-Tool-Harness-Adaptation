# PE6203 Tool Harness Adaptation

PE6203 选题 4：研究工具环境发生变化后，如何更新 Agent 的工具知识，并比较不更新、全量重写和选择性修补三种策略。

本项目基于 [Octobrist/MCPEvol-Bench](https://github.com/Octobrist/MCPEvol-Bench)，保留基准代码和任务数据。上游基准说明见 [UPSTREAM_README.md](UPSTREAM_README.md)。

## 当前进度

- [x] 阶段一：搭建环境、接入方舟模型、运行一个原始任务并保存真实轨迹。
- [ ] 阶段二：完善 Early、Middle、Late 三版本运行与固定任务清单。
- [ ] 阶段三：接入三种工具知识更新策略。
- [ ] 阶段四：联调、评分、实验分析与交付。

阶段一已使用火山方舟 `deepseek-v4-flash-ga-260731` 运行任务 156，3 次工具调用均成功，模型答案与计算器结果一致。当前结果是运行连通性验证，尚未完成正式三策略对比和 TF / PE / ECS 评分。

## 开始运行

环境安装、模型配置和实际验证过的命令见 [成员 1 运行说明](member1/README.md)。

安装依赖并在本地配置 `.env` 后，在仓库根目录打开两个 PowerShell 窗口：

```powershell
# 窗口一：启动时间工具和计算器
& .\member1\start_mcp.ps1
```

```powershell
# 窗口二：运行任务 156
.venv\Scripts\python.exe -X utf8 member1/run_task.py
```

测试命令：

```powershell
.venv\Scripts\python.exe -X utf8 -m pytest -q
```

## 主要文件

| 路径 | 内容 |
| --- | --- |
| `member1/README.md` | 阶段一环境和运行说明 |
| `member1/run_task.py` | 复用基准 Agent 的单任务运行入口 |
| `member1/evidence/success/` | 真实成功运行的原始结果与轨迹 |
| `member1/evidence/provenance.json` | 运行命令、上游版本和代码哈希 |
| `member1/requirements-lock.txt`、`package-lock.json` | 本次运行依赖版本 |
| `docs/member1-development-plan.md` | 成员 1 开发计划及阶段一完成记录 |
| `src/`、`servers/`、`anotation_path/` | 上游基准代码、服务配置和任务资源 |

`.env`、本机运行时凭证、虚拟环境、Node 依赖和临时输出均通过 `.gitignore` 排除。仓库提供不含密钥的 `.env.example`；每位组员在本地配置自己的凭证。

## 来源与实验约定

- 上游仓库：`https://github.com/Octobrist/MCPEvol-Bench`
- 使用的上游 commit：`888c779a0fe735f612ca62bdd1fdd7c9e6bf8701`
- 本组新增代码主要位于 `member1/`，Agent 兼容性调整及停止规则详见运行说明。
- 后续三种策略须使用相同模型、推理参数、任务集、停止规则与 judge 协议。
