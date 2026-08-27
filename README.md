# 菟菚 bot（TZtuzhan）

固定单人格 · QQ 私聊 · 完整记忆（短期 + 长期）· 好感度系统

「菟菚」是一个菟丝子娘——温柔、慵懒、带一点病娇，爱晒太阳、爱黏人。她只用于 QQ **私聊**，不接入群聊。

## 项目结构

```
TZtuzhan/
├── bot.py                  # NoneBot2 入口（python bot.py）
├── debug_cli.py            # 本地调试 CLI（不依赖 QQ，终端直接聊天）
├── requirements.txt        # Python 依赖
├── .env.example            # 配置模板（复制为 .env 填写）
├── napcat-guide.md         # Windows NapCat 部署指引
├── core/
│   ├── config.py           # .env 配置加载
│   ├── persona.py          # 人格加载 + 动态注入（阶段/称呼/关系状态）
│   ├── llm.py              # OpenAI 兼容 LLM 调用
│   ├── userdb.py           # SQLite 数据层（用户/消息/长期记忆/好感度流水）
│   ├── memory.py           # 短期上下文 + 长期记忆检索
│   ├── affection.py        # 好感度规则（每日/刷屏/辱骂/恋人达成）
│   └── daily.py            # 每日 LLM 总结（爱好/尊重/轻视判定 + 称呼提取）
└── plugins/private_chat/   # QQ 私聊主插件
```

人格源文件：`persona-菟菚.md`（项目内，已纳入 git 管理，唯一人格来源，改它即可改人设）。
设计文档：`bot-design.md`（项目内）。

## 快速开始

### 1. 安装依赖（Python 3.10+）

**一键脚本**（推荐，国内网络加 `-Mirror` 走清华镜像）：

```powershell
cd D:\DSH\TZtuzhan
powershell -ExecutionPolicy Bypass -File setup.ps1 -Mirror
```

或手动执行：

```powershell
py -3.14 -m venv --without-pip .venv
py -3.14 -m pip --python .\.venv\Scripts\python.exe install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
py -3.14 -m pip --python .\.venv\Scripts\python.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

（如果本机 `py` 不可用，把 `py -3.14` 换成 `python`；`--without-pip` 方式是为了兼容 Python 3.14 的 ensurepip 问题）

### 2. 配置

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填入 LLM 的 `base_url / api_key / model`（任意 OpenAI 兼容端点均可）。
不接 QQ 想先试人格 → 跳过第 3 步，直接跑调试模式：

```powershell
.\.venv\Scripts\python.exe debug_cli.py --mock     # 模拟回复，跑通全流程
.\.venv\Scripts\python.exe debug_cli.py            # 使用真实 LLM（如有上次数据会询问是否清除）
.\.venv\Scripts\python.exe debug_cli.py --reset    # 强制清除本地数据（记忆/好感度/称呼），跳过询问
```

### 3. 部署 NapCat 并运行

1. 按 `napcat-guide.md` 部署 NapCat，开启正向 WebSocket（默认 `ws://127.0.0.1:3001`）
2. 确认 `.env` 中 `ONEBOT_WS_URLS` 与 NapCat 端口一致
3. 启动：

```powershell
.\.venv\Scripts\python.exe bot.py
```

## 功能一览

- **固定人格**：全部对话共用「菟菚」人设，见 persona 文件
- **称呼机制**：首次对话询问称呼；达成恋人（好感度 ≥75）后第二次确认；可用 `/称呼 xxx` 手动设置
- **好感度 0~100**：每日首次聊天 +2、当日陪伴 +1；刷屏 -2、辱骂 -5；每日 LLM 总结判定「聊爱好 +1 / 尊重喜好 +1 / 轻视 -3」
- **记忆**：短期保留最近 30 轮；长期记忆用关键词检索（v1 实现），可无缝替换为向量库
- **阶段行为**：初识(0-24) → 熟悉(25-49) → 亲密(50-74) → 恋人(75-100)，影响对话尺度

## 已知简化（后续可升级）

- 长期记忆 v1 用关键词命中检索，替换 chromadb / sqlite-vec 即可升级为向量检索
- 称呼提取用正则启发式（"叫我XX"）+ `/称呼` 命令 + 每日总结兜底，不保证 100% 准确
- 表情包：当前用 emoji/颜文字，QQ 图片表情包发送待二期
- 单人使用设计（数据按 user_id 隔离，天然支持多用户）

## 常见问题

- **Python 3.14 venv 报 ensurepip 错误**：用 `py -3.14 -m venv --without-pip .venv` + 上面 `pip --python` 方式安装
- **HTTPS 连不上**：curl/Invoke-WebRequest 报 SEC_E_NO_CREDENTIALS 时改用 Python（OpenSSL）访问，pip 不受影响
