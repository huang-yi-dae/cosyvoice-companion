# 架构说明（ARCHITECTURE）

> 最后核对：master @ `#29`（2026-08）。本文件描述**当前真实结构**，与代码一同更新；
> 若发现与代码不符，以代码为准并请更新此处。

本项目把「一段 QQ 聊天记录」端到端地变成「一个能用对方声音、以对方语气对话的陪伴体」。
它由三层组成：**数据流水线（voicekit）** → **Web 后端（FastAPI）** → **5 个前端页面**。

---

## 1. 端到端数据流

```
                        ┌─────────────────────────────────────────────┐
   真实数据流程（Windows，需管理员 + QQ 登录）
                        └─────────────────────────────────────────────┘

  NTQQ 进程          加密的 SQLCipher 库           明文库            聊天 JSON
  ┌────────┐  key   ┌──────────────┐  decrypt ┌──────────┐ export ┌──────────┐
  │ QQ 登录 │──────▶│ nt_msg.clean │─────────▶│ 明文 .db  │───────▶│ chat_log │
  └────────┘        └──────────────┘          └──────────┘        └────┬─────┘
   (extract:key)      (decrypt)                 (export)               │ (clean)
                                                                       ▼
                                              ┌───────────────────────────────┐
                                              │ chat_log_clean.json（清洗后）    │
                                              └───────┬───────────────┬────────┘
                                        voice 步骤     │               │  agent 步骤
                                        (SILK→WAV)     ▼               ▼
                                       ┌────────────────────┐  ┌───────────────────┐
                                       │ voices/wav/*.wav    │  │ agents/<name>/     │
                                       │ （原始语音样本）      │  │  SystemPrompt.txt  │
                                       └─────────┬──────────┘  │  knowledge-base/   │
                                                 │             └─────────┬─────────┘
                                                 │ 参考音频              │ 人设
                                                 ▼                      ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │  合成 / 陪伴（Web 触发）                                                     │
   │                                                                            │
   │  工作室 /  ── /api/generate ──▶ CosyVoice 零样本克隆 ──▶ voices/cloned、web_output│
   │  陪伴 /companion ── /api/chat ──▶ 角色扮演 LLM(文本) ──▶ /api/generate 朗读     │
   └──────────────────────────────────────────────────────────────────────────┘
```

流水线的 6 个步骤（`voicekit/pipeline.py` `STEPS`，可在 `/pipeline` 页勾选运行）：

| # | id | 步骤 | 说明 | 是否需人工前提 |
|---|------|------|------|------|
| 1 | `key`     | 提取解密密钥 | 调试 QQ 进程读取 SQLCipher key | 需管理员 + QQ 已登录 |
| 2 | `decrypt` | 解密数据库   | 用 key 解出明文 DB | 需已复制加密库 |
| 3 | `export`  | 导出聊天记录 | 明文 DB → 原始 JSON | 自动 |
| 4 | `clean`   | 清洗数据     | 去噪、规整为 `chat_log_clean.json` | 自动 |
| 5 | `voice`   | 转换语音格式 | SILK 语音 → WAV 样本 | 自动 |
| 6 | `agent`   | 生成角色扮演 Agent | 从文本统计出 SystemPrompt + 知识库 | 自动 |

> 想跳过整条真实流程先看效果：`python internal/src/scripts/seed_demo_data.py`
> 会造出可用的演示数据（见 README「快速体验」）。

---

## 2. 模块职责

### 2.1 `internal/src/voicekit/` — 领域逻辑（无 Web 依赖，可独立测试）

| 模块 | 职责 |
|------|------|
| `config.py` | 合并 `config.yaml` + `.env`，解析所有路径 / 用户 / 模型 / provider / 语言 / 鉴权 |
| `pipeline.py` | 编排上表 6 步，发出 `log`/`step`/`done` 事件（供 Web 实时展示） |
| `keyextract.py` / `extract.py` | 提取 SQLCipher 密钥 |
| `decrypt.py` | 用密钥解密 NTQQ 数据库 |
| `export_msgs.py` / `clean.py` | 导出 + 清洗聊天记录 |
| `wavstream.py` / `audio.py` | SILK→WAV、WAV 拼接、PCM→WAV 流式封装 |
| `cosyvoice_engine.py` | 本地 CosyVoice 零样本克隆引擎（惰性加载） |
| `dashscope_tts.py` | 阿里云百炼云端 TTS provider |
| `llm.py` | 陪伴页角色扮演对话客户端 |
| `agentgen.py` / `clone.py` / `models.py` | 生成人设 Agent、克隆封装、模型目录/下载 |

### 2.2 `internal/src/web/` — Web 层

| 文件 | 职责 |
|------|------|
| `app.py` | FastAPI 组合根：路由 + 鉴权中间件 + 后台任务状态（pipeline/download）。**注**：仍偏大，是持续瘦身目标（见下） |
| `services.py` | 后端单例：引擎 / 云 provider / LLM 缓存 + `providers_info`（仅依赖 cfg，与路由解耦，便于测试 mock） |
| `jobs.py` | 统一后台任务状态：`BackgroundJob`（线程安全的 running/ok/logs/时间戳 + extra 字段），pipeline / download 共用 |
| `routers/pages.py` | 静态页面路由（`/` `/manage` `/pipeline` `/models` `/companion`）；`build_router(cfg)` 工厂，app.py include（架构评审 §4 首个抽离切片） |
| `routers/tasks.py` | 后台任务路由：pipeline（steps/start/status）+ 模型下载（catalog/download/status）；`build_router(cfg)` 内部构造两个 `BackgroundJob` |
| `routers/cloud_voices.py` | 云端音色管理路由（DashScope 枚举/创建/删除）；`build_router(cfg, get_dashscope_provider)`，仅依赖 cfg + provider accessor |
| `routers/audio.py` | 音频文件路由（`/api/audio` 播放、`/api/save` 保存、`/api/saved` 列表、`/api/voice/{id:path}`）；`build_router(output_dir, saved_dir, resolve_voice_path)` |
| `static/api.js` | 前端共享：统一 `/api` 调用 + `friendlyError` 错误归类 |
| `static/ui.js` | 前端共享：toast / 活跃用户 chip / QQ 记忆 / 骨架屏 |
| `static/studio.css` | Glass Studio 设计系统（tokens + 组件样式） |
| `*.html` | 5 个页面（见下），各自内联页面专属 JS，公共部分走上面两个共享库 |

### 2.3 页面地图

| 路由 | 页面 | 主要 API |
|------|------|---------|
| `/` | 工作室（选样本 → 合成） | `/api/voices`、`/api/generate[/stream]`、`/api/saved` |
| `/manage` | 管理台（语音消息、人设编辑/重生成） | `/api/users/{qq}/messages`、`/api/users/{qq}/prompt[/regenerate]` |
| `/pipeline` | 自动化（勾选步骤、实时日志） | `/api/pipeline/steps`、`/api/pipeline/start`、`/api/pipeline/status` |
| `/models` | 模型管理（目录、下载、已用时/预估） | `/api/models/catalog`、`/api/models/download[/status]` |
| `/companion` | 陪伴对话（人设驱动 + 朗读） | `/api/chat` → `/api/generate` |

API 契约以 FastAPI 自动生成的 OpenAPI 为准：启动服务后访问 **`/docs`**。
关键读端点（`/api/users`、`/api/models`、`/api/voices`）已声明 `response_model`。

---

## 3. 关键设计约束与取舍

- **本地优先、隐私优先**：`private/` 与 `.env` 全部 gitignore；默认绑定 `127.0.0.1`，
  对局域网开放（`0.0.0.0`）时**必须**设 `WEB_AUTH_TOKEN`（`app.py` 启动会警告）。
- **重资源惰性加载**：CosyVoice 模型只在首次合成时加载；UI 与列表接口不依赖 `torch`，
  因此演示/浏览无需 GPU 或下载权重。
- **后台长任务**：pipeline / 模型下载在后台线程运行，状态由统一的 `BackgroundJob`
  （`web/jobs.py`）持有——线程安全的 `running/ok/logs/started_at/finished_at` +
  任务特有的 `extra` 字段，前端轮询 `.../status`。**已知局限**：无法安全强杀线程，
  故不提供「取消」；`/models` 改为展示「已用时 + 预估耗时」让进度可见（见 PR #28）。
- **无状态对话**：`/api/chat` 不在后端存历史，由前端携带 `history` 传入。

---

## 4. 已知技术债 / 后续方向

- **`app.py` 继续瘦身**：已抽出 `services.py`（PR #27）与统一后台任务抽象
  `web/jobs.py::BackgroundJob`（pipeline / download 已复用，直连单元测试覆盖）。
  路由按域拆为 `routers/` 已启动：静态页面路由已抽到 `routers/pages.py`，后台任务路由
  （pipeline + 模型下载）已抽到 `routers/tasks.py`（均用 `build_router(cfg)` 工厂 + app.py
  include）。云端音色、音频文件路由已分别抽到 `routers/cloud_voices.py`、`routers/audio.py`
  （音频路由把 `resolve_voice_path` 作为 callable 注入，避免耦合用户配置路径 helper）。
  剩余 synth（generate/stream）/ chat（chat + 用户 messages/prompt）路由待续拆。
- **前端共享库**：`api.js` / `ui.js` 已在**全部 5 个页面**接入完成
  （PR #24、#25、#31、#32、#33）——chip / QQ 记忆 / toast 统一委托，无重复实现。
- **测试金字塔**：已补 API 层集成测试（PR #29）。可继续覆盖 pipeline 事件状态机、
  错误分支。
- **配置拆分**：`config.py` 可按域拆为 `PathsConfig / TTSConfig / ModelConfig`。

（本文件是"当前状态"的活文档；改动结构时请同步更新第 1-2 节与顶部核对戳。）
