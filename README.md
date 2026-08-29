<div align="center">

# 🌿 菟菚 · TZtuzhan

**一个菟丝子娘系 QQ 私人 AI 女友**

温柔 · 慵懒 · 病娇 · 爱晒太阳 · 爱黏人

[![Version](https://img.shields.io/badge/version-v1.1.1-8a5cf6?style=flat-square)](https://github.com) [![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org) [![NoneBot2](https://img.shields.io/badge/NoneBot2-2.x-4EC0D0?style=flat-square&logo=nonebot&logoColor=white)](https://nonebot.dev) [![License](https://img.shields.io/badge/license-MIT-important?style=flat-square)]()

> 固定单人格 · QQ 私聊 · 完整记忆 · 好感度 · 心情 · 日程 · 节日 · 识图/生图 · 热梗 · 主动消息

</div>

---

## ✨ 特色一览

| | 能力 | | 能力 |
|---|---|---|---|
| 🧠 | 完整记忆（短期+长期+语义向量） | 💕 | 好感度系统（四阶段+羁绊） |
| 🎭 | 心情系统（天气/时段/互动） | 📅 | 今日日程（LLM 随机生成） |
| 🎏 | 中国节日（公历+农历全覆盖） | 🖼️ | 识图 + 二次元生图 |
| 🔥 | 网络热梗 · 联网搜索 | 💬 | 主动消息（久别找你） |
| 🃏 | 状态卡片可视化（/好感 /心情 /日程 发图片卡片） | 🛡️ | 抗风控 · 掉线检测 |
| 👤 | 用户画像（结构化了解你的信息/喜好/习惯） | 🗣️ | 黑话·口头禅学习（自然用你的词） |
| 🎨 | 场景化表达风格（对应场景自然贴合） | 😂 | 表情包情绪匹配（按情绪回发收藏） |
| 🖥️ | Web 管理面板（仪表盘/功能开关/数据管理） | ✅ | 92 项自动化测试 |

---

## 📁 项目结构

```
TZtuzhan/
├── bot.py                  # NoneBot2 入口（python bot.py）
├── debug_cli.py            # 本地调试 CLI（不依赖 QQ）
├── requirements.txt        # Python 依赖
├── .env.example            # 配置模板（复制为 .env 填写）
├── napcat-guide.md         # Windows NapCat 部署指引
├── persona-菟菚.md         # 🌿 人格源文件（唯一人格来源）
├── tests/                  # pytest 自动化测试（88 项）
├── core/
│   ├── config.py           # .env 配置加载
│   ├── persona.py          # 人格加载 + 动态注入
│   ├── llm.py              # LLM 调用（超时 + 指数退避重试）
│   ├── userdb.py           # SQLite 数据层
│   ├── memory.py           # 短期上下文 + 长期记忆检索
│   ├── vector_store.py     # 稠密向量记忆
│   ├── affection.py        # 💕 好感度 v2
│   ├── mood.py             # 🎭 心情系统
│   ├── schedule.py         # 📅 今日日程（LLM 生成）
│   ├── holidays.py         # 🎏 中国节日系统
│   ├── context.py          # 上下文锚定（防跑题）
│   ├── rhythm.py           # 🛡️ 延迟抖动（抗风控）
│   ├── offline_alert.py    # 🛡️ 掉线检测
│   ├── daily.py            # 每日 LLM 总结
│   ├── date_memory.py      # 特殊日子自动识别
│   ├── search.py           # 联网搜索
│   ├── vision.py           # 识图
│   ├── sticker.py          # 表情包收藏（情绪标签 + 按情绪回发）
│   ├── imagegen.py         # 二次元生图
│   ├── draw_context.py     # 对话驱动生图
│   ├── profile.py          # 👤 用户画像系统
│   ├── terms.py            # 🗣️ 黑话/口头禅学习
│   ├── style.py            # 🎨 场景化表达风格
│   ├── features.py         # 功能开关（Web 面板控制）
│   ├── memes.py            # 网络热梗
│   ├── proactive.py        # 主动消息
│   ├── tasks.py            # 后台任务调度
│   └── log.py              # loguru 日志
├── webui.py                # 🖥️ Web 管理面板（独立进程，:8800）
└── plugins/private_chat/   # QQ 私聊主插件
```

---

## 🚀 部署指南（详细）

### 🧭 架构总览

```
  你的 QQ  ──私聊──▶  [bot QQ 号]
                       ▲
                       │ OneBot V11 正向 WebSocket (ws://127.0.0.1:3001)
                       │
                   ┌───┴───────────────┐
                   │   NapCat (QQNT 协议层)  │  ← 负责收发 QQ 消息，独立进程
                   └─────────┬─────────┘
                             │
                   ┌─────────▼─────────┐
                   │  bot.py (NoneBot2) │  ← 本项目的核心逻辑进程
                   │   · 人格 / 好感度  │
                   │   · 心情 / 日程    │
                   │   · 记忆 / 识图    │
                   │   · 生图 / 搜索    │
                   └────┬─────────┬────┘
                        │         │
        ┌───────────────▼───┐ ┌───▼──────────────┐
        │ LLM API（对话/日程/ │ │ 辅助 API          │
        │ 记忆/识图/生图…）    │ │ 搜索/天气/向量/热梗 │
        └───────────────────┘ └──────────────────┘
```

> 一句话：**NapCat 管"收发 QQ 消息"，bot.py 管"怎么回话"**，两者通过 OneBot WS 协议连接。API key 全部在 `.env` 里配，bot 启动时读取。

### 1️⃣ 系统要求

| 项目 | 要求 |
|---|---|
| Python | **3.10+**（实测 3.14；Windows / macOS / Linux 均可） |
| QQ | 一个**小号**（会被风控，别用主号）；NapCat 需要 QQNT（QQ 9.x 新版客户端） |
| 网络 | 能访问 `api.deepseek.com` / `api.siliconflow.cn` 等 API（国内直连即可） |
| 磁盘 | ≥ 300MB（venv + 依赖 + NapCat） |

### 2️⃣ 安装依赖

**一键脚本**（推荐，国内网络加 `-Mirror` 走清华镜像）：

```powershell
cd D:\DSH\TZtuzhan
powershell -ExecutionPolicy Bypass -File setup.ps1 -Mirror
```

或手动执行（Python 3.14 的 ensurepip 问题用 `--without-pip` 规避）：

```powershell
py -3.14 -m venv --without-pip .venv
py -3.14 -m pip --python .\.venv\Scripts\python.exe install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
py -3.14 -m pip --python .\.venv\Scripts\python.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 💡 如果本机 `py` 不可用，把 `py -3.14` 换成 `python`。

### 3️⃣ 配置 `.env`（API 全部在这里）

```powershell
Copy-Item .env.example .env
```

`.env` 是唯一需要填 API key 的地方，`bot.py` 启动时自动读取（`.env` 已加入 `.gitignore`，不会泄密）。

**最简可用配置（只要对话功能，只填这两个）：**

```
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-你的deepseek-key
```

其余可选能力对应关系：

| 能力 | 必需变量 | 不配置会怎样 |
|---|---|---|
| 💬 对话（核心） | `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` | 无法启动对话 |
| 🖼️ 识图/表情包描述 | `VISION_BASE_URL / VISION_API_KEY / VISION_MODEL` | 识图关闭，收到图片当普通表情包处理 |
| 🎨 生图 | `IMAGE_API_KEY`（`IMAGE_MODEL` 可选） | 生图命令 `/画` 不可用 |
| 🔎 联网搜索 | `SEARCH_ENABLED / SEARCH_ENGINE / SEARCH_API_KEY` | 搜索关闭 |
| 🧮 向量记忆 | 复用 `IMAGE_API_KEY` | 退化为纯关键词检索 |
| 🎭 心情天气 | `MOOD_CITY` | 心情按时间段兜底，不查天气 |
| 💬 主动消息 | `PROACTIVE_USER_ID` | 对最后说话的人发 |

> 🔑 **API 具体怎么申请、各提供方怎么填，见下方「🔑 API 配置详解」章节。**

### 4️⃣ 部署 NapCat（收发 QQ 消息）

NapCat 是 QQNT 的协议实现，负责把 bot 接到 QQ。详细图文见 [`napcat-guide.md`](napcat-guide.md)，这里是最简流程：

1. 下载安装 NapCat（本项目 Windows 实测 v4.18.19，需 QQNT 9.9.x 已登录一个小号）
2. 启动 NapCat，配置 **OneBot 11 正向 WebSocket**，监听 `127.0.0.1:3001`
3. 确认 `.env` 里 `ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]` 与 NapCat 端口一致
4. 用 bot 的 QQ 号登录 NapCat（首次扫码，之后自动登录）

Windows 一键启动脚本：

```powershell
cd D:\DSH\TZtuzhan
.\start-all.bat        # 同时拉起 NapCat + bot（防重复实例，双窗口）
```

### 5️⃣ 启动 bot 并验证

```powershell
.\.venv\Scripts\python.exe bot.py
```

日志出现 `OneBot V11 | Bot <你的botQQ> connected` 即连接成功。用**另一个 QQ** 私聊 bot 号：

- 发「你好」→ 应得到慵懒的回应
- 发 `/好感` → 显示好感度阶段
- 发 `/日程` → 显示今日日程
- 发 `/画 窗边的小橘猫` → 生图（需配置 `IMAGE_API_KEY`）

健康自检：`.\check-bot.ps1`；干净停止：`.\stop-bot.ps1`。

**🛡️ 长期守护（推荐）**：用 `watchdog.ps1` 常驻后台，bot 崩溃/掉线自动拉起、防重复实例：

```powershell
.\watchdog.ps1                       # 常驻守护（每 15s 检查），Ctrl+C 退出
.\watchdog.ps1 -RunOnce              # 自检一次就退出（适合定时任务）
.\watchdog.ps1 -WithNapCat -Interval 20   # 连带守护 NapCat（UAC 提权拉起）
```

开机自启可注册为 Windows 计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\install-watchdog.ps1          # 注册(登录自启 + 每2分钟兜底)
powershell -ExecutionPolicy Bypass -File .\install-watchdog.ps1 -Remove  # 取消自启
```

或手动：
```powershell
schtasks /create /tn "TZtuzhanWatchdog" /tr "powershell -NoProfile -ExecutionPolicy Bypass -File D:\DSH\TZtuzhan\watchdog.ps1" /sc onlogon /rl highest
schtasks /delete /tn "TZtuzhanWatchdog" /f   # 取消自启
```

watchdog 会把状态写到 `data/watchdog_state.json`，日志写到 `data/watchdog.log`。

### 6️⃣ 不接 QQ，先本地调试

跳过 NapCat，直接在命令行体验人格与全流程：

```powershell
.\.venv\Scripts\python.exe debug_cli.py --mock     # 模拟 LLM 回复，跑通全流程（不耗 API）
.\.venv\Scripts\python.exe debug_cli.py            # 使用真实 LLM
.\.venv\Scripts\python.exe debug_cli.py --reset    # 强制清除本地数据
```

> 🎯 调试命令：`/好感度` 查看当前，`/好感度 80` 直接设置 0-100。设置到 75+ 自动进入「恋人」阶段。

---

## 🔑 API 配置详解

本节逐个说明 `.env` 里每个 API 的申请、提供方选择和填写格式。**所有 key 都以 `sk-` 开头，均为 OpenAI 兼容的 HTTP 接口**，bot 内部统一用 OpenAI SDK 调用，因此任意兼容端点都能换。

### 💬 1. 对话 LLM（核心，必配）

| 变量 | 说明 |
|---|---|
| `LLM_BASE_URL` | OpenAI 兼容端点根地址，**必须带 `/v1`** |
| `LLM_API_KEY` | API 密钥 |
| `LLM_MODEL` | 模型名 |
| `LLM_TEMPERATURE` | 采样温度（0~2），默认 `0.8`，越高越放飞 |
| `LLM_MAX_TOKENS` | 单次回复最大 token，默认 `500` |

**备选提供方（任选其一，切注释即可）：**

```ini
# ① DeepSeek（默认，中文对话性价比高）
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-你的deepseek-key
LLM_MODEL=deepseek-chat

# ② 硅基流动 SiliconFlow（国内，兼容多家开源模型）
# LLM_BASE_URL=https://api.siliconflow.cn/v1
# LLM_API_KEY=sk-你的siliconflow-key
# LLM_MODEL=Qwen/Qwen3-32B

# ③ 通义千问 DashScope（阿里）
# LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# LLM_API_KEY=sk-你的dashscope-key
# LLM_MODEL=qwen-plus

# ④ OpenAI 官方
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_API_KEY=sk-你的openai-key
# LLM_MODEL=gpt-4o-mini
```

> 更换提供方时：**注释掉当前三行，取消注释目标一组**。`LLM_BASE_URL` 结尾必须有 `/v1`。

### 🖼️ 2. 识图（视觉模型，可选）

收到用户发来的图片/表情包时，用视觉模型描述内容，菟菚才能"看懂"并自然回应。**不配置则识图关闭**，图片当普通表情包处理。

| 变量 | 说明 |
|---|---|
| `VISION_BASE_URL` | 视觉模型 OpenAI 兼容端点 |
| `VISION_API_KEY` | 密钥 |
| `VISION_MODEL` | 支持图片输入的多模态模型名 |

```ini
# 例① 硅基流动 Qwen2.5-VL
VISION_BASE_URL=https://api.siliconflow.cn/v1
VISION_API_KEY=sk-你的siliconflow-key
VISION_MODEL=Qwen/Qwen2.5-VL-72B-Instruct

# 例② 通义千问 VL（DashScope）
# VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# VISION_API_KEY=sk-你的dashscope-key
# VISION_MODEL=qwen-vl-max
```

### 🎨 3. 图像生成（可选）

`/画 xxx` 命令 + 对话驱动的"想看"生图。**不配置则生图功能关闭。**

| 变量 | 说明 |
|---|---|
| `IMAGE_API_KEY` | SiliconFlow API key（**必须**，留空 = 生图关闭） |
| `IMAGE_MODEL` | 文生图模型，默认 `Qwen/Qwen-Image`（日系二次元风格） |
| `IMAGE_BASE_URL` | 默认 `https://api.siliconflow.cn/v1`，一般不用改 |

```ini
IMAGE_BASE_URL=https://api.siliconflow.cn/v1
IMAGE_API_KEY=sk-你的siliconflow-key
IMAGE_MODEL=Qwen/Qwen-Image
```

> 💡 `IMAGE_API_KEY` 同时被**向量记忆**复用（同用 SiliconFlow embedding），所以配了生图也就自动拥有了语义向量记忆。

### 🧮 4. 向量记忆（可选，复用生图 key）

用户"回忆"时，把问题扩展成关键词 + 用稠密向量检索长期记忆，同义表达也能召回。**用 `IMAGE_API_KEY`（SiliconFlow），无需单独配置**。`MEMORY_SEMANTIC=0` 可关闭退化为纯关键词检索。

```ini
MEMORY_SEMANTIC=1
```

### 🔎 5. 联网搜索（可选）

对话中命中新闻/天气/价格等会自动检索。默认用 Bing（无需 key，国内可访问），填了博查 key 优先用博查（更稳定）。

| 变量 | 说明 |
|---|---|
| `SEARCH_ENABLED` | `1` 开 / `0` 关，默认开 |
| `SEARCH_ENGINE` | `bing`（默认）或 `ddg`（DuckDuckGo，国内可能不可用） |
| `SEARCH_API_KEY` | 博查 AI key（可选，填了优先用博查） |

```ini
SEARCH_ENABLED=1
SEARCH_ENGINE=bing
# SEARCH_API_KEY=sk-你的博查key
```

### 🎭 6. 心情天气（可选）

心情系统按当日天气设定基线（晴→心情好、雨→低落）。**`MOOD_CITY` 填城市名**（如 `北京`/`襄阳`），留空则按时间段兜底。

```ini
MOOD_CITY=北京
```

### ⏱️ 7. 回复节奏（抗风控，可选调优）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEBOUNCE_SECONDS` | `4.0` | 用户连发消息的合并窗口（秒），窗口内到达的都并成一句整体理解 |
| `THINK_DELAY` | `2.0` | 收到消息后到发第一条回复的"酝酿"秒数 |
| `SEND_INTERVAL` | `3.0` | 多条回复之间的发送间隔（秒） |
| `DELAY_JITTER` | `0.4` | 上述延迟的随机抖动比例（0~1），避免固定节奏被风控识别 |

### 💬 8. 主动消息（可选）

久别后菟菚会主动找你。默认对"最后说话的人"发；也可指定白名单。

```ini
PROACTIVE_USER_ID=10001,10002        # 逗号分隔多个 QQ 号；留空 = 对最后说话的人发
PROACTIVE_IDLE_HOURS=4               # 几小时不聊算"久别"，默认 4
PROACTIVE_COOLDOWN_HOURS=8           # 两次主动之间的冷却，默认 8
PROACTIVE_CHECK_MINUTES=15           # 调度检查间隔（分钟）
```

### 🧬 9. 人格文件

```ini
PERSONA_FILE=persona-菟菚.md
```
唯一人格来源，改这里即可换性格（详见 [`persona-菟菚.md`](persona-菟菚.md)）。

### 🔌 10. OneBot / WS 连接

```ini
ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]   # 与 NapCat 正向 WS 端口一致
DRIVER=~aiohttp                           # 用 aiohttp driver 支持 WS 客户端
```

---

## 🗂️ 功能一览

### 💬 对话与人格

- 🧬 **固定人格**：全部对话共用「菟菚」人设（菟丝子娘，温柔慵懒病娇）
- 💭 **先思考再发言**：输出【思考】+【回复】两段，只把【回复】发给对方（兼容全角/六角/冒号多种格式）
- ⏳ **回复拟人化**：条数随内容 1-3 条自然变化；酝酿延迟 + 条间间隔（带随机抖动）
- 📨 **消息去抖合并**：连发多条自动合并处理，回复更连贯
- 🌙 **告别语境判断**：晚安/再见时简短收尾，不复读、不硬续聊
- 🎯 **上下文锚定**：识别"当前在聊什么"，检测话题切换，长上下文弱化旧话题——解决跑题、串味
- 💗 **称呼机制**：首次对话询问称呼；恋人阶段第二次确认；`/称呼 xxx` 手动设置
- 🕐 **时间感知**：贴合现实时间说话，但不反复念叨

### 💕 好感度系统 v2

- 🎚️ **四阶段 0~100**：初识 → 熟悉 → 亲密 → 恋人，影响对话尺度
- ⭐ **正向奖励**：用称呼 +1、关心 +1、回应主动 +2、深度对话 +2、共同回忆 +1（日限 1 次）
- 📆 **每日基础**：基础聊天 +1/条（日上限 10）、首次 +2、陪伴 +1、聊爱好 +1、尊重 +1（跨天防重复）
- ⚖️ **惩罚调优**：刷屏 -2、辱骂 -5、轻视 -3；单日扣分不超 -10
- 🎭 **心情联动**：心情好加分多（雀跃 ×1.5）、心情差扣分多（低落 ×0.6）
- 💞 **恋人羁绊**：眷恋 / 热恋 / 白头，注入更细腻的关系描述
- 📊 **进度条**：`/好感` 显示美观的图片卡片（好感度/阶段/羁绊/进度条）

### 🎭 心情系统

- 😶🌫️ **心情值 0-100**：低落 / 平淡 / 慵懒 / 开心 / 雀跃，初始 60
- 🌤️ **天气基线**：按当日天气设定基线（晴 75 / 雨 45 / 雷 40…），城市由 `MOOD_CITY` 指定
- 🕰️ **时段波动**：向基线漂移 + 随机扰动，模拟真人情绪起伏
- 💬 **互动影响**：趣事 +4、好消息 +5、关心 +3、冒犯 -12；冷落会掉心情
- 📅 **日程联动**：时段情绪（晚上想陪你 +5）+ 生日 +10 + 节日加成（春节 +10 / 中秋 +8）
- 💞 **好感度联动**：心情好加分多、心情差扣分多
- 🌬️ **自然流露**：心情在语气里自然体现，不直接报数值；`/心情` 查看

### 📅 今日日程表

- ✨ **LLM 随机生成**：每天首次对话时，由大模型按菟菚身份与性格生成当天 6 时段日程，每天不一样
- 📈 **阶段化**：初识疏离 → 恋人黏人，日程内容随之变化
- 🎏 **节日/天气/心情调剂**：中秋→晚上看月亮、雨天→听雨、生日→特别安排
- 🛟 **规则兜底**：LLM 生成失败自动退回规则模板
- 🗣️ **自然流露**：被问"在干嘛"时随口说出；`/日程` 查看

### 🎏 中国节日系统

- 🗓️ **全覆盖**：公历固定 + 农历换算（`zhdate`），除夕自动 = 春节前一天
- 💬 **对话注入**：节日当天自动提起（"今天是中秋节呀，月亮应该很圆"）
- 🎭 **心情/日程联动**：喜庆节日心情更好，日程带节日氛围
- 🔄 **自动更新**：农历节日每年自动跟随，无需手动维护

### 🧠 记忆

- 💾 **短期**：最近 30 轮完整对话
- 📚 **长期**：关键词检索 + LLM 事实提炼（喜好/约定，纯 SQLite）+ 风格学习
- 🔍 **语义检索**：疑似回忆时 LLM 查询扩展 + TF-IDF 余弦重排
- 🧮 **稠密向量**：SiliconFlow embedding + sqlite-vec，同义表达也能召回
- 🧹 **事实过滤**：只存值得长期记住的
- 🧩 **长会话压缩**：超 60 条自动摘要化，保留最近 14 条完整

### 🖼️ 图片

- 👀 **识图**：收到图片/表情包 → 视觉模型描述 → 自然回应
- 🎁 **表情包收藏**：自动下载收藏，之后按话题回发同款
- 🎨 **生图（命令）**：`/画 一只趴在窗台上的猫` → SiliconFlow **日系二次元风格**插画
- 💭 **生图（对话驱动）**：菟菚描述画面，你说"要看"自动画出来
- ⚠️ **错误分级**：区分密钥无效/余额不足/限流/服务端/描述问题

### 🌐 联网与热梗

- 🔎 **联网搜索**：命中新闻/天气/价格自动检索（博查/Bing/DuckDuckGo 回退）
- 🔥 **网络热梗**：每小时抓微博热搜 + LLM 提炼，合适时机自然使用

### 💬 主动消息

- 📞 **久别主动找**：几小时不说话，菟菚会主动发消息
- 🚫 **同日去重**：一天只主动一次
- 🎯 **时段话题**：按时段 + 近期话题 + 特殊日子生成"有由头"的发起
- 🔄 **频率控制**：检查间隔带随机抖动，越熟越主动

### 🛡️ 稳定性与抗风控

- 🔁 **LLM 重试**：超时/限流/5xx 自动指数退避重试
- 🗄️ **SQLite WAL**：并发读写不锁库
- 📨 **发送重试 + 降级**：失败自动重试；"消息体无法解析"降级为纯文本重发
- 🧊 **抗风控**：NapCat `o3HookMode=0` + 延迟随机抖动，模拟真人节奏
- 🚨 **掉线检测**：NapCat/QQ 掉线自动检测（60s 去抖），QQ 提醒 + 本地通知
- 🧪 **自动化测试**：pytest 覆盖 92 项

### 🖥️ Web 管理面板（可选，独立进程）

- 🌐 **访问**：启动后浏览器打开 `http://127.0.0.1:8800`（只监听本机）
- 🚀 **启动**：`python webui.py`（零新依赖，fastapi/uvicorn 由 nonebot2 自带）
- 📊 **仪表盘**：好感度/阶段/心情/画像/口头禅/风格/表情统计一览
- 🔧 **功能开关**：用户画像 / 口头禅·黑话 / 场景风格 / 表情情绪匹配，点击即时开关
- 👤 **画像管理**：查看/删除 LLM 提炼的用户画像条目
- 🗣️ **口头禅管理**：查看/删除学到的口头禅与黑话（含含义）
- 🎨 **风格管理**：查看/删除场景化表达风格
- 😂 **表情收藏**：查看收藏的表情及其情绪标签
- 💬 **对话记录**：最近 50 条聊天记录；📋 **日志**：bot/watchdog 日志尾部

---

## ⌨️ 常用命令

| 命令 | 作用 |
|---|---|
| `/称呼 [称呼]` | 设置/查看菟菚对你的称呼 |
| `/好感 [N]` / `/aff` | 查看好感度卡片（阶段/羁绊/进度条），或调节 0-100 |
| `/心情 [N]` / `/mood` / `/状态` | 查看心情卡片，或调节 |
| `/日程` / `/今日安排` / `/今天干啥` | 查看今日日程卡片 |
| `/画像` / `/你懂我吗` | 查看菟菚对你的用户画像（结构化了解） |
| `/口头禅` / `/学到的词` / `/黑话` | 查看菟菚记下的你的口头禅/黑话词 |
| `/风格` / `/表达方式` / `/你的观察` | 查看菟菚观察到的你的场景化表达风格 |
| `/表情 [情绪]` / `/来张表情` | 按情绪发一张收藏的表情包（如`/表情 开心`） |
| `/搜索 xxx` / `/搜 xxx` | 联网搜索 |
| `/主动` | 让菟菚主动发一条消息 |
| `/日子` | 查看特殊日子；`/日子 删除 1` 删除 |
| `/画 xxx` | 生图（如 `/画 窗边的小橘猫`） |
| 自然说"要看" | 对话驱动生图 |

---

## 📌 已知简化

- 🧮 长期记忆用 TF-IDF + 稠密向量融合，可换更大 embedding 模型
- 🗣️ 称呼提取用正则启发式 + `/称呼` 命令 + 每日总结兜底
- 🔥 热梗以 LLM 知识 + 微博热搜为主，超新梗可能滞后
- 👤 单人使用设计（数据按 user_id 隔离，天然多用户）
- 🗓️ 农历节日用 `zhdate`（1900-2100），跨世纪需升级

---

## ❓ 常见问题

<details>
<summary><b>Python 3.14 venv 报 ensurepip 错误</b></summary>

用 `py -3.14 -m venv --without-pip .venv` + `pip --python` 方式安装
</details>

<details>
<summary><b>HTTPS 连不上（SEC_E_NO_CREDENTIALS）</b></summary>

改用 Python（OpenSSL）访问，pip 不受影响
</details>

<details>
<summary><b>生图不工作</b></summary>

确认 `.env` 里 `IMAGE_API_KEY` 已填 SiliconFlow key；错误提示会说明具体原因
</details>

<details>
<summary><b>消息重复回复</b></summary>

多半是两个 bot 实例都连上了 WS；用 `check-bot.ps1` 自检，`stop-bot.ps1` 清理后重启
</details>

<details>
<summary><b>NapCat 频繁掉线</b></summary>

已启用抗风控（o3Hook=0 + 延迟抖动 + 掉线检测）；若仍频繁，可降级 NapCat 4.15.x + QQ 3.2.2x 组合
</details>

<details>
<summary><b>回复里出现〔思考〕这类括号</b></summary>

已修复（兼容多种括号格式），若再出现请反馈
</details>

---

<div align="center">

🌿 *"如果我说得轻一点、软一点、缠得紧一点，你是不是就不会走了。"*

</div>
