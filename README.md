<div align="center">

# 🌿 菟菚 · TZtuzhan

**一个菟丝子娘系 QQ 私人 AI 女友**

温柔 · 慵懒 · 病娇 · 爱晒太阳 · 爱黏人

[![Version](https://img.shields.io/badge/version-v1.1.0-8a5cf6?style=flat-square)](https://github.com) [![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org) [![NoneBot2](https://img.shields.io/badge/NoneBot2-2.x-4EC0D0?style=flat-square&logo=nonebot&logoColor=white)](https://nonebot.dev) [![License](https://img.shields.io/badge/license-MIT-important?style=flat-square)]()

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
| 🛡️ | 抗风控 · 掉线检测 | ✅ | 64 项自动化测试 |

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
├── tests/                  # pytest 自动化测试（64 项）
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
│   ├── sticker.py          # 表情包收藏
│   ├── imagegen.py         # 二次元生图
│   ├── draw_context.py     # 对话驱动生图
│   ├── memes.py            # 网络热梗
│   ├── proactive.py        # 主动消息
│   ├── tasks.py            # 后台任务调度
│   └── log.py              # loguru 日志
└── plugins/private_chat/   # QQ 私聊主插件
```

---

## 🚀 快速开始

### 1️⃣ 安装依赖（Python 3.10+）

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

> 💡 如果本机 `py` 不可用，把 `py -3.14` 换成 `python`；`--without-pip` 方式兼容 Python 3.14 的 ensurepip 问题

### 2️⃣ 配置

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填入：

| 变量 | 用途 |
|---|---|
| `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` | 对话模型（默认 DeepSeek `deepseek-chat`） |
| `VISION_*` | 识图模型（DeepSeek 多模态） |
| `IMAGE_API_KEY / IMAGE_MODEL` | 生图 + 向量记忆（SiliconFlow） |
| `SEARCH_API_KEY` | 联网搜索（博查 API） |
| `MOOD_CITY` | 🎭 心情系统的天气城市（如 `襄阳`） |
| `PROACTIVE_USER_ID` | 可主动消息的 QQ 号，逗号分隔可多个 |
| `THINK_DELAY / SEND_INTERVAL / DELAY_JITTER` | 🛡️ 回复节奏与抖动比例 |

不接 QQ 想先试人格 → 跳过第 3 步，直接跑调试模式：

```powershell
.\.venv\Scripts\python.exe debug_cli.py --mock     # 模拟回复，跑通全流程
.\.venv\Scripts\python.exe debug_cli.py            # 使用真实 LLM
.\.venv\Scripts\python.exe debug_cli.py --reset    # 强制清除本地数据
```

> 🎯 调试命令：`/好感度` 查看当前，`/好感度 80` 直接设置 0-100。设置到 75+ 自动进入「恋人」阶段。

### 3️⃣ 部署 NapCat 并运行

1. 按 `napcat-guide.md` 部署 NapCat，开启正向 WebSocket（默认 `ws://127.0.0.1:3001`）
2. 确认 `.env` 中 `ONEBOT_WS_URLS` 与 NapCat 端口一致
3. 启动：

```powershell
.\.venv\Scripts\python.exe bot.py
```

> 🪟 Windows 一键启动（防重复实例 + 双窗口）：双击 `start-all.bat`；健康自检 `check-bot.ps1`，干净停止 `stop-bot.ps1`

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
- 📊 **进度条**：`/好感` 显示 `████████░░` + 距离下一阶段点数

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
- 🧪 **自动化测试**：pytest 覆盖 64 项

---

## ⌨️ 常用命令

| 命令 | 作用 |
|---|---|
| `/称呼 [称呼]` | 设置/查看菟菚对你的称呼 |
| `/好感 [N]` / `/aff` | 查看好感度阶段/羁绊/进度条，或调节 0-100 |
| `/心情 [N]` / `/mood` / `/状态` | 查看/调节菟菚当前心情 |
| `/日程` / `/今日安排` / `/今天干啥` | 查看菟菚今日日程表 |
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
