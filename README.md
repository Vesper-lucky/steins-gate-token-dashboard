# Steins;Gate Token Dashboard

## 命运石之门 Token 统计仪 | Steins;Gate Token Usage Dashboard

一个本地、离线、以《Steins;Gate / 命运石之门》世界线为主题的 Claude Code 与 Codex token 用量分析仪。它读取本机保存的 JSONL 会话记录，展示 token、缓存、成本、项目和会话细节，帮助你回答：**我的 token 到底消耗在哪里？**

A local, offline Claude Code and Codex token usage dashboard inspired by the world lines of *Steins;Gate*. It reads JSONL session records stored on your machine and shows token usage, cache activity, estimated cost, projects, and sessions so you can answer one question: **where are my tokens going?**

> **中文声明：** 本项目是非官方、非商业的粉丝二次创作项目。《Steins;Gate / 命运石之门》的名称、角色和相关视觉素材属于各自权利人。本项目不代表任何官方合作、授权或背书。
>
> **English disclaimer:** This is an unofficial, non-commercial fan-made derivative. Steins;Gate names, characters, and related visual assets belong to their respective rights holders. This project is not affiliated with or endorsed by the rights holders.

![Steins;Gate Token Dashboard](9454887064605b5a3229d0bb3a5fc20c.png)

## 项目来源 | Origin

本项目基于 [`nateherkai/token-dashboard`](https://github.com/nateherkai/token-dashboard) 修改，保留其本地 dashboard、JSONL 扫描、SQLite 缓存、会话分析和 MIT 许可。感谢上游项目提供了清晰的基础实现。

This project is a modified derivative of [`nateherkai/token-dashboard`](https://github.com/nateherkai/token-dashboard). It keeps the upstream local dashboard, JSONL scanner, SQLite cache, session analysis, and MIT license. Many thanks to the upstream project for providing a clear foundation.

## 功能 | Features

- **总览 Overview**：总输入、输出、缓存读取、缓存写入、会话、轮次和估算费用。 Shows total input/output/cache tokens, sessions, turns, and estimated cost.
- **提示词 Prompts**：按 token 排序查看高消耗提示词，以及对应回复、工具调用和工具结果大小。 Ranks expensive prompts and shows their responses, tool calls, and tool-result sizes.
- **会话 Sessions**：逐轮查看单个会话，包含模型、token 分桶和工具调用。 Inspects a session turn by turn with model, token buckets, and tool calls.
- **项目 Projects**：比较不同项目的 token、会话和文件触达情况。 Compares token usage, sessions, and touched files across projects.
- **技能 Skills**：统计 Claude Code / Codex 技能调用次数，并估算技能定义加载量。 Counts Claude Code / Codex skill invocations and estimates loaded skill-definition tokens.
- **建议 Tips**：根据重复读取、过大的工具结果和低缓存命中率给出节省 token 的建议。 Suggests ways to reduce usage based on repeated reads, large tool results, and low cache-hit rates.
- **设置 Settings**：在 API、Pro、Max 和 Max 20x 计划之间切换费用展示方式。 Switches cost display between API, Pro, Max, and Max 20x plans.
- **Steins;Gate 主题 Theme**：世界线计数器、角色视觉和 divergence meter 风格的 token 展示。 Includes a world-line counter, character visuals, and divergence-meter-style token display.
- **隐私模式 Privacy mode**：在页面内模糊提示词、项目名、会话标识和建议内容。 Blurs prompts, project names, session identifiers, and tips in the UI.

## 相比上游的改进 | Improvements over upstream

统计逻辑针对真实会话记录做了整理和优化：

The accounting logic has been refined for real-world session records:

- 以真实线程、稳定事件键、`call_id`、`client_id` 和消息标识去重，避免重复计费。 Deduplicates by real threads, stable event keys, `call_id`, `client_id`, and message identifiers to avoid double counting.
- 去除流式输出时同一 assistant 消息产生的 2–3 个快照，只保留最终统计结果。 Removes the 2–3 streaming snapshots often written for one assistant message and keeps the final tally.
- 分开统计普通输入、缓存读取、5 分钟缓存写入、1 小时缓存写入、输出和 reasoning output tokens；reasoning output 是输出子集，不会被重复相加。 Separates ordinary input, cache reads, 5-minute cache writes, 1-hour cache writes, output, and reasoning-output tokens; reasoning output is an output subset and is never added twice.
- 支持长上下文倍率和按 UTC 时间切换的历史价格，历史记录不会被今天的价格重新估算。 Supports long-context multipliers and UTC-based historical pricing, so old usage is not recalculated with today’s rates.
- 支持 Codex 与 Claude Code 的技能目录扫描、工具结果递归 token 估算和未归属结果标记。 Scans Codex and Claude Code skill directories, estimates recursive tool-result tokens, and marks unassigned results explicitly.
- 增加项目、模型、会话、提示词、技能、工具、缓存和数据质量审计视图。 Adds project, model, session, prompt, skill, tool, cache, and data-quality audit views.
- 继续保持 stdlib-only、无遥测、无登录、无外部数据上传的本地运行方式。 Remains stdlib-only, telemetry-free, login-free, and local-only.

## 快速开始 | Quick start

### 中文

要求：Python 3.8+、至少运行过一次 Claude Code 或 Codex，以及一个现代浏览器。不需要 `pip install`、Node.js 或构建步骤。

```bash
git clone https://github.com/Vesper-lucky/steins-gate-token-dashboard.git
cd steins-gate-token-dashboard
python3 cli.py dashboard
```

首次运行会扫描默认的 `~/.claude/projects/`，然后在 `http://127.0.0.1:8081` 启动本地 dashboard。停止服务使用 `Ctrl+C`。Windows 如果没有 `python3`，可以将命令替换为 `py -3`。

常用命令：

```bash
python3 cli.py scan          # 扫描并刷新本地 SQLite 缓存
python3 cli.py today         # 查看北京时间今天的统计
python3 cli.py stats         # 查看全部统计
python3 cli.py tips          # 查看节省 token 建议
python3 cli.py audit         # 查看数据质量和 token 守恒报告
python3 cli.py dashboard --no-open
```

### English

Requirements: Python 3.8+, at least one Claude Code or Codex session, and a modern browser. No `pip install`, Node.js, or build step is required.

```bash
git clone https://github.com/Vesper-lucky/steins-gate-token-dashboard.git
cd steins-gate-token-dashboard
python3 cli.py dashboard
```

The first run scans `~/.claude/projects/` and starts the local dashboard at `http://127.0.0.1:8081`. Stop it with `Ctrl+C`. On Windows, use `py -3` instead of `python3` if needed.

Common commands:

```bash
python3 cli.py scan          # scan and refresh the local SQLite cache
python3 cli.py today         # show today's totals in Beijing time
python3 cli.py stats         # show all-time totals
python3 cli.py tips          # show token-saving suggestions
python3 cli.py audit         # show data-quality and conservation checks
python3 cli.py dashboard --no-open
```

## 数据来源与配置 | Data sources and configuration

### 中文

Claude Code 会把会话写入以下位置：

| 系统 | 默认路径 |
| --- | --- |
| macOS / Linux | `~/.claude/projects/<project-slug>/<session-id>.jsonl` |
| Windows | `C:\Users\<you>\.claude\projects\<project-slug>\<session-id>.jsonl` |

Codex 桥接器也可以把本机 Codex 记录转换成相同的统计输入。程序只读取这些文件，不会修改它们；SQLite 缓存默认写入 `~/.claude/token-dashboard.db`。

可用环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | 本地服务监听地址。除非你清楚网络风险，否则不要改为 `0.0.0.0`。 |
| `PORT` | `8081` | 本地服务端口。 |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects` | Claude JSONL 根目录。 |
| `TOKDASH_PROJECTS_DIRS` | 未设置 | 用 `os.pathsep` 分隔的多个会话根目录。 |
| `TOKEN_DASHBOARD_DB` | `~/.claude/token-dashboard.db` | SQLite 缓存路径。 |

### English

Claude Code stores sessions at:

| OS | Default path |
| --- | --- |
| macOS / Linux | `~/.claude/projects/<project-slug>/<session-id>.jsonl` |
| Windows | `C:\Users\<you>\.claude\projects\<project-slug>\<session-id>.jsonl` |

The Codex bridge can convert local Codex records into the same dashboard input format. The scanner only reads these files and never modifies them. The SQLite cache defaults to `~/.claude/token-dashboard.db`.

Available environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Local bind address. Do not change it to `0.0.0.0` unless you understand the network risk. |
| `PORT` | `8081` | Local server port. |
| `CLAUDE_PROJECTS_DIR` | `~/.claude/projects` | Claude JSONL root directory. |
| `TOKDASH_PROJECTS_DIRS` | unset | Multiple session roots separated by `os.pathsep`. |
| `TOKEN_DASHBOARD_DB` | `~/.claude/token-dashboard.db` | SQLite cache path. |

### 手动添加模型价格 | Adding model prices manually

中文：价格表位于 [`pricing.json`](pricing.json)。模型 key 必须与日志中的 `message.model` 完全一致，价格单位是美元/1,000,000 tokens：

English: Pricing lives in [`pricing.json`](pricing.json). The model key must exactly match the `message.model` value in your logs. Prices are USD per 1,000,000 tokens:

```json
{
  "models": {
    "your-model-name": {
      "tier": "custom",
      "input": 1.0,
      "output": 5.0,
      "cache_read": 0.1,
      "cache_create_5m": 1.25,
      "cache_create_1h": 1.25
    }
  }
}
```

中文：修改后重新加载页面即可生效。需要历史价格时加入 `history` 数组，每项使用 UTC 的 `before` 时间；需要长上下文价格时加入 `long_context_threshold`、`long_context_input_multiplier` 和 `long_context_output_multiplier`。建议让 AI 根据模型官方价格页生成 JSON，再人工核对模型名称、缓存价格、货币和生效时间。未知模型仍会显示 token，但费用会标记为未知或估算。

English: Reload the page after editing the file. Add a `history` array with UTC `before` timestamps for historical rates. Add `long_context_threshold`, `long_context_input_multiplier`, and `long_context_output_multiplier` for long-context pricing. You can ask an AI to draft the JSON from the model’s official pricing page, but manually verify the model name, cache rates, currency, and effective time. Unknown models still show token counts, while their cost is marked unknown or estimated.

## 隐私与安全 | Privacy and security

- 中文：所有数据处理都在本机完成，没有遥测、登录或上传用户会话的 API。 English: All processing happens locally; there is no telemetry, login, or API that uploads your sessions.
- 中文：默认只监听 `127.0.0.1`。把 `HOST` 改成 `0.0.0.0` 会让局域网设备访问你的提示词历史。 English: The default bind address is `127.0.0.1`. Setting `HOST=0.0.0.0` can expose your prompt history to other devices on the network.
- 中文：仓库不会包含真实 JSONL 会话、SQLite 数据库、`.env` 文件、个人路径、密钥或密码。 English: The repository does not include real JSONL sessions, SQLite databases, `.env` files, personal paths, keys, or passwords.
- 中文：`.gitignore` 保留 `tests/fixtures/` 中的脱敏样例，用于测试解析和统计逻辑。 English: `.gitignore` keeps only sanitized samples under `tests/fixtures/` for parser and accounting tests.
- 中文：浏览器资源使用仓库内的静态文件，不依赖字体 CDN 或远程分析脚本。 English: Browser assets are served from the repository and do not depend on a font CDN or remote analytics script.

## 测试与开发 | Testing and development

```bash
python3 -m unittest discover tests
node --test tests/*.test.mjs
```

中文：项目使用 Python 标准库、SQLite、`http.server`、原生 JavaScript 和本地 ECharts，不需要前端构建工具。架构为 `cli.py` → `token_dashboard/scanner.py` → SQLite → `token_dashboard/server.py` → `web/`。

English: The project uses the Python standard library, SQLite, `http.server`, vanilla JavaScript, and a vendored ECharts build. No frontend build tool is required. The data flow is `cli.py` → `token_dashboard/scanner.py` → SQLite → `token_dashboard/server.py` → `web/`.

## 素材与免责声明 | Assets and disclaimer

中文：本仓库中的《Steins;Gate / 命运石之门》角色和相关视觉素材用于非官方、非商业粉丝二创展示，不代表任何官方合作、授权或背书。角色、商标和原始作品版权归各自权利人所有。

English: Steins;Gate characters and related visual assets in this repository are used in an unofficial, non-commercial fan-made derivative. They do not indicate official cooperation, authorization, or endorsement. Characters, trademarks, and the original work remain the property of their respective rights holders.

中文：`web/assets/divergence-meter/` 中的数字素材来源记录在该目录的 [README](web/assets/divergence-meter/README.md) 中。素材来源说明不等于版权许可；如果你是权利人并希望调整或移除相关素材，请通过 GitHub issue 联系维护者。

English: The source of the digit assets in `web/assets/divergence-meter/` is documented in that directory’s [README](web/assets/divergence-meter/README.md). A source reference is not a copyright license. Rights holders who want an asset adjusted or removed can contact the maintainer through a GitHub issue.

## 许可证 | License

中文：代码基于上游 [`nateherkai/token-dashboard`](https://github.com/nateherkai/token-dashboard) 的 MIT 许可进行修改，详见 [`LICENSE`](LICENSE)。主题角色和第三方视觉素材不因代码采用 MIT 许可而获得新的授权。

English: The code is modified from [`nateherkai/token-dashboard`](https://github.com/nateherkai/token-dashboard) under the MIT License; see [`LICENSE`](LICENSE). The MIT license for the code does not grant new rights to the themed characters or third-party visual assets.

## 致谢 | Acknowledgements

- [`nateherkai/token-dashboard`](https://github.com/nateherkai/token-dashboard)：基础 dashboard 和本地 token 分析实现。 Upstream dashboard and local token analytics foundation.
- [`longsongline/Steins-Gate-Divergence-Meter-Clock-VisitorCounter`](https://github.com/longsongline/Steins-Gate-Divergence-Meter-Clock-VisitorCounter)：divergence meter 数字素材来源记录。 Source reference for the divergence-meter digit assets.

## 贡献者 | Contributors

- **屿沐 (Vesper-lucky)**：项目维护者、主题设计和发布。 Project maintainer, theme direction, and release owner.
- **OpenAI Codex**：AI coding assistant，协助文档整理、隐私检查、测试验证和发布准备。 AI coding assistant that helped with documentation, privacy checks, test verification, and release preparation; all changes were reviewed and published by the maintainer.
