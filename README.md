# Steins;Gate Token Dashboard

<p align="center"><a href="README_EN.md">English</a> · <strong>简体中文</strong></p>

## 命运石之门 Token 统计仪

一个本地、离线、以《Steins;Gate / 命运石之门》世界线为主题的 Claude Code 与 Codex token 用量分析仪。它读取本机保存的 JSONL 会话记录，展示 token、缓存、成本、项目和会话细节，帮助你回答：**我的 token 到底消耗在哪里？**

> **非官方声明：** 本项目是非官方、非商业的粉丝二次创作项目。《Steins;Gate / 命运石之门》的名称、角色和相关视觉素材属于各自权利人。本项目不代表任何官方合作、授权或背书。

![Steins;Gate Token Dashboard](9454887064605b5a3229d0bb3a5fc20c.png)

## 项目来源

本项目基于 [`nateherkai/token-dashboard`](https://github.com/nateherkai/token-dashboard) 修改，保留其本地 dashboard、JSONL 扫描、SQLite 缓存、会话分析和 MIT 许可。感谢上游项目提供了清晰的基础实现。

## 功能

- **总览**：总输入、输出、缓存读取、缓存写入、会话、轮次和估算费用。
- **提示词**：按 token 排序查看高消耗提示词，以及对应回复、工具调用和工具结果大小。
- **会话**：逐轮查看单个会话，包含模型、token 分桶和工具调用。
- **项目**：比较不同项目的 token、会话和文件触达情况。
- **技能**：统计 Claude Code / Codex 技能调用次数，并估算技能定义加载量。
- **建议**：根据重复读取、过大的工具结果和低缓存命中率给出节省 token 的建议。
- **设置**：在 API、Pro、Max 和 Max 20x 计划之间切换费用展示方式。
- **多模型统计**：同一个本地 dashboard 可以同时统计多个厂商、多个部署和多个模型，不受仓库内置价格表的模型列表限制。
- **Steins;Gate 主题**：世界线计数器、角色视觉和 divergence meter 风格的 token 展示。
- **隐私模式**：在页面内模糊提示词、项目名、会话标识和建议内容。

### 多模型支持（核心特点）

统计器按日志中的 `message.model` 原样分组，因此可以在同一个 SQLite 数据库中对比不同模型的输入、输出、缓存和成本。常见的模型示例包括（实际名称以你的日志为准）：

| 厂商 / 生态 | 模型示例 |
| --- | --- |
| OpenAI | GPT-5、GPT-4.1、o3、o4-mini |
| Anthropic | Claude Opus、Claude Sonnet、Claude Haiku |
| Google | Gemini Pro、Gemini Flash |
| DeepSeek | DeepSeek Chat、DeepSeek Reasoner |
| 阿里云 / 通义 | Qwen、Qwen3、Qwen-Max |
| Meta / Mistral | Llama、Mistral Large |

内置 [`pricing.json`](pricing.json) 只是可直接估算费用的示例价格配置，不是模型白名单。只要会话记录能提供模型名和用量字段，模型即使不在这个文件中也会正常计入 token；补充价格后才能计算成本。你可以把多个 Claude-compatible JSONL 根目录通过 `TOKDASH_PROJECTS_DIRS` 一起部署统计，也可以先用 Codex 桥接器转换其他本地记录。

## 相比上游的改进

统计逻辑针对真实会话记录做了整理和优化：

- 以真实线程、稳定事件键、`call_id`、`client_id` 和消息标识去重，避免重复计费。
- 去除流式输出时同一 assistant 消息产生的 2–3 个快照，只保留最终统计结果。
- 分开统计普通输入、缓存读取、5 分钟缓存写入、1 小时缓存写入、输出和 reasoning output tokens；reasoning output 是输出子集，不会被重复相加。
- 支持长上下文倍率和按 UTC 时间切换的历史价格，历史记录不会被今天的价格重新估算。
- 支持 Codex 与 Claude Code 的技能目录扫描、工具结果递归 token 估算和未归属结果标记。
- 增加项目、模型、会话、提示词、技能、工具、缓存和数据质量审计视图。
- 继续保持 stdlib-only、无遥测、无登录、无外部数据上传的本地运行方式。

## 快速开始

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

## 数据来源与配置

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

### 手动添加模型价格

价格表位于 [`pricing.json`](pricing.json)。它只负责成本估算，不限制可统计的模型。模型 key 必须与日志中的 `message.model` 完全一致，价格单位是美元/1,000,000 tokens：

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

修改后重新加载页面即可生效。需要历史价格时加入 `history` 数组，每项使用 UTC 的 `before` 时间；需要长上下文价格时加入 `long_context_threshold`、`long_context_input_multiplier` 和 `long_context_output_multiplier`。建议让 AI 根据模型官方价格页生成 JSON，再人工核对模型名称、缓存价格、货币和生效时间。未知模型仍会显示 token，但费用会标记为未知或估算，因此你可以先统计新模型，再补价格配置。

## 隐私与安全

- 所有数据处理都在本机完成，没有遥测、登录或上传用户会话的 API。
- 默认只监听 `127.0.0.1`。把 `HOST` 改成 `0.0.0.0` 会让局域网设备访问你的提示词历史。
- 仓库不会包含真实 JSONL 会话、SQLite 数据库、`.env` 文件、个人路径、密钥或密码。
- `.gitignore` 保留 `tests/fixtures/` 中的脱敏样例，用于测试解析和统计逻辑。
- 浏览器资源使用仓库内的静态文件，不依赖字体 CDN 或远程分析脚本。

## 测试与开发

```bash
python3 -m unittest discover tests
node --test tests/*.test.mjs
```

项目使用 Python 标准库、SQLite、`http.server`、原生 JavaScript 和本地 ECharts，不需要前端构建工具。架构为 `cli.py` → `token_dashboard/scanner.py` → SQLite → `token_dashboard/server.py` → `web/`。

## 素材与免责声明

本仓库中的《Steins;Gate / 命运石之门》角色和相关视觉素材用于非官方、非商业粉丝二创展示，不代表任何官方合作、授权或背书。角色、商标和原始作品版权归各自权利人所有。

`web/assets/divergence-meter/` 中的数字素材来源记录在该目录的 [README](web/assets/divergence-meter/README.md) 中。素材来源说明不等于版权许可；如果你是权利人并希望调整或移除相关素材，请通过 GitHub issue 联系维护者。

## 许可证

代码基于上游 [`nateherkai/token-dashboard`](https://github.com/nateherkai/token-dashboard) 的 MIT 许可进行修改，详见 [`LICENSE`](LICENSE)。主题角色和第三方视觉素材不因代码采用 MIT 许可而获得新的授权。

## 致谢

- [`nateherkai/token-dashboard`](https://github.com/nateherkai/token-dashboard)：基础 dashboard 和本地 token 分析实现。
- [`longsongline/Steins-Gate-Divergence-Meter-Clock-VisitorCounter`](https://github.com/longsongline/Steins-Gate-Divergence-Meter-Clock-VisitorCounter)：divergence meter 数字素材来源记录。

## Contributors

贡献成员按实际承担的项目职责列出：屿沐 / Vesper-lucky 负责项目维护与发布，OpenAI Codex 参与代码实现、统计逻辑优化、双语文档和开源整理。

<table>
  <tr>
    <td align="center" valign="top" width="160">
      <a href="https://github.com/Vesper-lucky">
        <img src="https://avatars.githubusercontent.com/u/273519167?v=4" width="80" alt="Vesper-lucky"/><br />
        <sub><b>屿沐 / Vesper-lucky</b></sub>
      </a><br />
      <sub>项目维护者</sub>
    </td>
    <td align="center" valign="top" width="160">
      <a href="https://openai.com/codex/">
        <img src="https://avatars.githubusercontent.com/u/14957082?v=4" width="80" alt="OpenAI Codex"/><br />
        <sub><b>OpenAI Codex</b></sub>
      </a><br />
      <sub>AI 编程助手</sub>
    </td>
  </tr>
</table>
