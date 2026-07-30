# QQ 语音分析与克隆项目

QQ 聊天记录分析 + 基于 CosyVoice-300M 的语音克隆（个人研究用途，Windows / Python 3.11）。

本项目采用**配置驱动 + 隐私分离**架构：所有隐私数据集中在 gitignore 的 `private/`
目录，切换分析对象只需修改配置，无需改代码。

## 快速开始

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
$py = "internal/env/voice-clone-env/Scripts/python.exe"
& $py internal/src/scripts/extract_voice.py            # 使用 .env 的 ACTIVE_QQ
& $py internal/src/scripts/extract_voice.py --user <qq> # 或临时指定其他用户
```

### 4. 克隆语音

```powershell
& $py internal/src/scripts/clone_voice.py --user <qq> --text "你好呀"
```

### 5. 启动 Web 应用

```powershell
& $py internal/src/web/app.py
```

访问 http://localhost:8000 （host/port 可在 `config/config.yaml` 调整）。

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
├── reports/deep-research-report.md   # 技术方案文档（无隐私，提交）
├── internal/
│   ├── env/voice-clone-env/    # Python venv（gitignore）
│   └── src/
│       ├── voicekit/           # 公共包：config / audio / cosyvoice_engine / extract / clone
│       ├── scripts/            # 瘦 CLI 入口（--user 参数化）
│       ├── web/                # FastAPI 应用 + index.html
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
- Python：3.11（venv 在 `internal/env/voice-clone-env`）

## 注意事项

1. 仅限个人研究使用，不得用于商业用途
2. 不得侵犯他人隐私，须获得对方授权
3. `private/` 与 `.env` 已被 gitignore，切勿提交任何隐私数据
