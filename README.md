# QQ 语音分析与克隆项目

[![CI](https://github.com/huang-yi-dae/cosyvoice-companion/actions/workflows/ci.yml/badge.svg)](https://github.com/huang-yi-dae/cosyvoice-companion/actions/workflows/ci.yml)

QQ 聊天记录分析 + 基于 CosyVoice-300M 的语音克隆（个人研究用途，Windows / Python 3.11）。

本项目采用**配置驱动 + 隐私分离**架构：所有隐私数据集中在 gitignore 的 `private/`
目录，切换分析对象只需修改配置，无需改代码。

## 快速开始

### 0. 一键初始化环境（首次运行）

项目自带的虚拟环境改为**按需动态创建**。首次拿到仓库时，在项目根目录运行：

```powershell
./setup.ps1        # 检测/创建 venv + 安装 requirements.txt 依赖
./run.ps1          # 就绪后启动 Web 控制台（会先自动跑一遍 setup）
```

- `setup.ps1`：若项目根目录的 `.venv/` 不存在，用系统 Python 自动创建，
  然后在其中安装依赖；已存在则跳过（`-Reinstall` 强制重装依赖，`-Force` 重建 venv）。
- `run.ps1`：先确保环境就绪，再用该 venv 启动 `internal/src/web/app.py`
  （加 `-SkipSetup` 可跳过环境检查直接启动）。
- 密钥提取需要管理员权限，若要用该功能，请**以管理员身份**打开 PowerShell 再运行 `./run.ps1`。

> 首次执行 PowerShell 脚本若被策略拦截，可在当前会话放行：
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`。

### 1. 配置

```powershell
# 复制并填写本地密钥/用户
Copy-Item .env.example .env
# 编辑 .env：设置 ACTIVE_QQ、SQLCIPHER_KEY 等
```

`config/config.yaml` 保存非敏感的默认路径与参数（可提交）；`.env` 保存敏感值
（QQ 号、SQLCipher 密钥、姓名，已 gitignore，切勿提交）。

### 2. 准备某个用户的数据

在 `private/users/<qq>/` 下放入该用户的数据：

```
private/users/<qq>/
├── decrypted/chat_log.json   # 该用户的聊天记录
├── raw/                      # 原始 NTQQ Ptt 语音目录
├── voices/{silk,wav,cloned}/ # 处理产物（脚本自动生成）
└── reports/                  # 分析报告
```

### 3. 提取并转换语音

```powershell
$py = ".venv/Scripts/python.exe"
& $py internal/src/scripts/extract_voice.py            # 使用 .env 的 ACTIVE_QQ
& $py internal/src/scripts/extract_voice.py --user <qq> # 或临时指定其他用户
```

### 4. 克隆语音

```powershell
& $py internal/src/scripts/clone_voice.py --user <qq> --text "你好呀"
```

### 5. 启动 Web 应用

```powershell
./run.ps1                       # 推荐：确保环境就绪后启动
# 或直接用 venv 启动（环境已就绪时）：
& $py internal/src/web/app.py
```

访问 http://localhost:8000 （host/port 可在 `config/config.yaml` 调整）。

页面导航：**工作室**（合成）・**管理台**（数据）・**自动化**（流水线）・**模型**（下载管理）。

### 合成语言选择

工作室的「合成文本」面板新增**合成语言**下拉（中/英/日/粤/韩，默认“自动”）：

- 选「自动（跟随样本）」：使用零样本克隆（`zero_shot`），语言跟随参考音色；
- 选具体语言：使用**跨语种合成**（`cross_lingual`），为文本自动加上语言标记
  （如 `<|zh|>`/`<|en|>`），让发音更贴合所选语言，改善跨语种文本的准确度与自然度。

语言列表在 `config/config.yaml` 的 `tts.languages` 中配置（`code` / `tag` / `label`）。

### 模型管理（/models）

打开 http://localhost:8000/models 管理可选模型（CosyVoice 全系列）：

- 每个模型卡片显示类型、描述、体积、预估下载时间与**下载状态**（已下载/未下载）；
- 已下载：可直接到工作室在模型下拉中选用；
- 未下载：点击「下载」弹出确认框，显示**模型大小**与**预估下载时间**，确认后从
  ModelScope 后台下载，并实时显示进度与日志；完成后自动刷新状态。

模型目录下载到 `paths.models_root`（`internal/src/CosyVoice/pretrained_models`）下。
候选清单与估算网速在 `config/config.yaml` 的 `models`（`catalog` / `est_speed_mbps`）中配置。

## 全流程自动化（解密 → 克隆）

除**登录 QQ 软件**外，从提取密钥到生成角色 Agent 的所有步骤都已自动化，可通过
Web 仪表盘一键运行，或用命令行逐步执行。

### 唯一的手动前提

1. **登录 QQ**：保持 QQ（NTQQ）在本机运行且已登录目标账号（密钥提取需要读取其进程）。
2. **准备加密数据库**：把 NTQQ 数据目录下的 `nt_msg.clean.db` 复制到
   `private/users/<qq>/decrypted/nt_msg.clean.db`（若流水线提示找不到会给出确切路径）。

### 前置条件

| 条件 | 说明 |
| --- | --- |
| 管理员权限 | 密钥提取通过调试 QQ 进程读取寄存器，须**以管理员身份**启动 PowerShell / 本服务（需 SeDebugPrivilege） |
| QQ 已登录 | 密钥提取时 QQ 必须在运行且已登录 |
| Python venv | `.venv/Scripts/python.exe`（项目根目录，脚本以绝对路径调用） |
| SQLCipher | 解密需要 `sqlcipher3-binary`：`& $py -m pip install sqlcipher3-binary` |
| .env | 至少设置 `ACTIVE_QQ`；`SQLCIPHER_KEY` 可由密钥提取步骤自动写入 |

### 步骤总览（哪些自动 / 哪些手动）

| # | 步骤 | 方式 | 命令 / 说明 |
| --- | --- | --- | --- |
| 0 | 登录 QQ + 复制加密库 | **手动** | 见上「唯一的手动前提」 |
| 1 | 提取解密密钥 | 自动（需管理员+QQ登录） | `extract_key.py`，成功后写入 `.env` 的 `SQLCIPHER_KEY` |
| 2 | 解密数据库 | 自动 | 流水线 `decrypt` 步骤，导出明文 SQLite |
| 3 | 导出聊天记录 | 自动 | `export_msgs.py` → `chat_log.json` |
| 4 | 清洗数据 | 自动 | `clean_chat.py` → `chat_log_clean.json` |
| 5 | 转换语音格式 | 自动 | `extract_voice.py`（SILK → WAV） |
| 6 | 生成角色扮演 Agent | 自动 | `gen_agent.py` → `SystemPrompt.txt` + 知识库 |

### 方式 A：Web 仪表盘（推荐，含外部预览）

```powershell
# 以管理员身份打开 PowerShell（密钥提取需要），再启动服务
# 首次会自动创建 venv 并安装依赖，随后启动 Web
./run.ps1
# （环境已就绪时也可直接：& ".venv/Scripts/python.exe" internal/src/web/app.py）
```

浏览器打开 http://localhost:8000/pipeline ：

- 右上角选择目标 QQ 用户；
- 勾选要运行的步骤（默认全选），点击「▶ 开始运行」；
- 实时查看每步状态（待运行 / 运行中 / 完成 / 失败 / 需人工 / 跳过）与日志；
- 遇到「需人工」（如未以管理员启动、QQ 未登录、加密库未复制）会暂停并给出提示，
  处理后再次点击「开始运行」即可继续（已完成步骤会自动跳过或快速通过）；
- 完成后在结果区一键跳转到「管理台」查看数据、到「工作室」合成语音。

> **外部预览**：想让同一局域网的其它设备访问，把 `config/config.yaml` 里 `web.host`
> 设为 `0.0.0.0`，然后用本机 IP 访问 `http://<本机IP>:8000/pipeline`（注意放行防火墙、
> 仅在可信网络使用，因为页面可触发解密流程）。

### 方式 B：命令行流水线

```powershell
$py = ".venv/Scripts/python.exe"

# 一键跑完整条流水线（使用 .env 的 ACTIVE_QQ）
& $py internal/src/scripts/run_pipeline.py

# 指定用户 / 只跑部分步骤 / 出错继续
& $py internal/src/scripts/run_pipeline.py --user <qq>
& $py internal/src/scripts/run_pipeline.py --steps clean,agent
& $py internal/src/scripts/run_pipeline.py --continue-on-error
```

也可单独运行任意一步：

```powershell
& $py internal/src/scripts/extract_key.py            # 提取密钥并写入 .env（需管理员+QQ登录）
& $py internal/src/scripts/extract_key.py --no-write  # 只打印不写入
& $py internal/src/scripts/export_msgs.py --user <qq> # 明文库 → chat_log.json
& $py internal/src/scripts/clean_chat.py  --user <qq> # 清洗
& $py internal/src/scripts/extract_voice.py --user <qq> # SILK → WAV
& $py internal/src/scripts/gen_agent.py   --user <qq> # 生成角色 Prompt + 知识库
```

### 故障排查

| 现象 | 原因 / 解决 |
| --- | --- |
| 密钥步骤提示 `Run as Administrator` | 未以管理员启动。关闭后用「管理员身份」重开 PowerShell 再启动服务 |
| 密钥步骤提示 QQ 未登录 | 先登录 QQ 客户端并保持运行，再重试 |
| 解密提示 `Encrypted DB not found` | 按提示把 `nt_msg.clean.db` 复制到指定路径 |
| 解密报 `sqlcipher3` 相关错误 | `& $py -m pip install sqlcipher3-binary` |
| 解密提示 `SQLCIPHER_KEY missing` | 先跑密钥步骤，或手动在 `.env` 填入密钥 |
| 语音步骤提示找不到聊天记录 / Ptt | 确认已完成导出，并用 `--ptt-dir` 指定原始 Ptt 目录 |
| 流水线「正在运行中」(409) | 上一次尚未结束，等待或刷新状态页 |

### 让 AI 助手接管整个流程（可粘贴 Prompt）

把下面这段贴给你的 AI 编程助手（在本仓库根目录下运行），它会自动完成除登录 QQ
外的全部步骤，并在需要人工时暂停提示：

```text
仓库：<在此粘贴仓库下载/克隆链接，暂留空>

你是本项目的自动化执行助手。请在仓库根目录（Windows / PowerShell，命令用 `;` 分隔，
不要用 &&）帮我把 QQ 消息解密到语音克隆的全流程自动跑完。规则：

1. 先初始化环境：
   - 在仓库根目录运行 `./setup.ps1`（自动检测/创建 `.venv/` 并安装依赖）；
   - 确认存在 `.env`（否则 `Copy-Item .env.example .env` 并提示我填 `ACTIVE_QQ`）；
   - `sqlcipher3` 与 `modelscope` 已在 requirements.txt 中，如仍缺失则单独安装。
2. 逐步执行，全部通过：
   `internal/src/scripts/run_pipeline.py`（可加 `--user <qq>`）。
3. 关键手动前提由你判断并在需要时暂停提示我，不要擅自跳过：
   - 密钥提取需「管理员身份」运行且 QQ 已登录；
   - 解密需要我先把 `nt_msg.clean.db` 复制到 `private/users/<qq>/decrypted/`。
4. 每一步都要给出清晰的状态反馈（成功 / 失败 / 需人工），失败时给出原因与修复建议，
   修复后从流水线继续（已完成步骤会自动跳过）。
5. 全部完成后，用管理员 PowerShell 运行 `./run.ps1` 启动服务，并告诉我打开
   http://localhost:8000/pipeline 查看进度与结果、http://localhost:8000/manage 查看数据。
```

## 切换分析对象

无需修改任何代码：

1. 在 `private/users/<新QQ>/` 下放入该用户的 `decrypted/chat_log.json` 与原始语音；
2. 修改 `.env` 的 `ACTIVE_QQ`，或在命令行传 `--user <新QQ>`。

## 项目结构

```
voice/
├── config/config.yaml          # 非敏感配置（提交）
├── .env.example                # 配置模板（提交）
├── .env                        # 本地密钥（gitignore）
├── requirements.txt
├── setup.ps1                   # 一键初始化：检测/创建 venv + 安装依赖
├── run.ps1                     # 确保环境就绪后启动 Web 控制台
├── reports/deep-research-report.md   # 技术方案文档（无隐私，提交）
├── .venv/                      # Python venv（项目根目录，gitignore）
├── internal/
│   └── src/
│       ├── voicekit/           # 公共包：config / audio / cosyvoice_engine / extract / clone
│       │                       #   + 自动化：keyextract / decrypt / export_msgs / clean / agentgen / pipeline
│       ├── scripts/            # 瘦 CLI 入口（--user 参数化；run_pipeline / extract_key / export_msgs / clean_chat / gen_agent 等）
│       ├── web/                # FastAPI 应用 + index.html / manage.html / pipeline.html / models.html
│       ├── tools/              # 二进制工具（silk_v3_decoder.exe 等）
│       ├── CosyVoice/          # vendored CosyVoice 仓库（模型 gitignore）
│       └── _legacy/            # 归档的旧脚本（gitignore）
└── private/                    # 全部隐私数据（gitignore）
    ├── users/<qq>/{raw,decrypted,voices,reports}/
    ├── shared/{web_output,saved}/
    ├── decrypted/              # 多账号共享解密数据
    ├── agents/                 # companion agent 的 prompt 与知识库
    └── misc/                   # Registry、风格分析、清洗报告等
```

## 技术栈

- 语音克隆：CosyVoice-300M（阿里开源）
- 格式转换：silk_v3_decoder.exe（SILK v3 → WAV）
- Web 框架：FastAPI + Uvicorn
- 配置：PyYAML + python-dotenv
- Python：3.11（venv 在项目根目录 `.venv`，脚本以绝对路径调用）

## 注意事项

1. 仅限个人研究使用，不得用于商业用途
2. 不得侵犯他人隐私，须获得对方授权
3. `private/` 与 `.env` 已被 gitignore，切勿提交任何隐私数据
