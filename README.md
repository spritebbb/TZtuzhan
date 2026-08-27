# 菟菚 bot（TZtuzhan）

固定单人格 · QQ 私聊 · 完整记忆（短期 + 长期 + 语义向量）· 好感度系统 · 识图/生图 · 网络热梗 · 主动消息

「菟菚」是一个菟丝子娘——温柔、慵懒、带一点病娇，爱晒太阳、爱黏人。她只用于 QQ **私聊**，不接入群聊。

## 项目结构

```
TZtuzhan/
├── bot.py                  # NoneBot2 入口（python bot.py）
├── debug_cli.py            # 本地调试 CLI（不依赖 QQ，终端直接聊天）
├── requirements.txt        # Python 依赖
├── .env.example            # 配置模板（复制为 .env 填写）
├── napcat-guide.md         # Windows NapCat 部署指引
├── tests/                  # pytest 自动化测试（好感度/记忆/向量/错误分类）
├── core/
│   ├── config.py           # .env 配置加载
│   ├── persona.py          # 人格加载 + 动态注入（阶段/称呼/时间/风格/羁绊）
│   ├── llm.py              # OpenAI 兼容 LLM 调用（超时 + 指数退避重试）
│   ├── userdb.py           # SQLite 数据层（用户/消息/事实/风格/日子/表情包/kv）
│   ├── memory.py           # 短期上下文 + 长期记忆检索（语义扩展 + TF-IDF）
│   ├── vector_store.py     # 稠密向量记忆（SiliconFlow embedding + sqlite-vec）
│   ├── affection.py        # 好感度 v2（正向奖励/惩罚上限/羁绊等级/进度条）
│   ├── daily.py            # 每日 LLM 总结（好感判定 + 长期事实提炼 + 日子复盘）
│   ├── date_memory.py      # 特殊日子自动识别（单句 + 每日复盘，支持相对日期推算）
│   ├── search.py           # 联网搜索（博查/Bing/DuckDuckGo）
│   ├── vision.py           # 识图（DeepSeek 多模态）
│   ├── sticker.py          # 表情包收藏（下载/描述/按话题回发）
│   ├── imagegen.py         # 生图（SiliconFlow 文生图，错误分级提示）
│   ├── draw_context.py     # 对话驱动生图（想看意图 + 画面提炼）
│   ├── memes.py            # 网络热梗（微博热搜 + LLM 提炼，定时刷新）
│   ├── proactive.py        # 主动发消息（多用户/阶段频率/随机抖动/表情推荐）
│   ├── tasks.py            # 后台任务调度（去重/失败隔离）
│   └── log.py              # loguru 日志（data/bot.log）
└── plugins/private_chat/   # QQ 私聊主插件（含消息去抖合并）
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

编辑 `.env`，填入：
- `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL`：对话模型（任意 OpenAI 兼容端点，默认 DeepSeek `deepseek-chat`）
- `VISION_*`：识图模型（DeepSeek 多模态 `deepseek-v4-flash-vision-exp`）
- `IMAGE_API_KEY / IMAGE_MODEL`：生图 + 向量记忆（SiliconFlow；填了 key 生图与语义记忆自动开启）
- `SEARCH_API_KEY`：联网搜索（博查 API；`SEARCH_ENABLED=0` 关闭）
- `PROACTIVE_USER_ID`：允许被主动发消息的 QQ 号，**逗号分隔可多个**
- `THINK_DELAY / SEND_INTERVAL`：回复节奏（酝酿秒数 / 条间间隔）

不接 QQ 想先试人格 → 跳过第 3 步，直接跑调试模式：

```powershell
.\.venv\Scripts\python.exe debug_cli.py --mock     # 模拟回复，跑通全流程
.\.venv\Scripts\python.exe debug_cli.py            # 使用真实 LLM（如有上次数据会询问是否清除）
.\.venv\Scripts\python.exe debug_cli.py --reset    # 强制清除本地数据（记忆/好感度/称呼），跳过询问
```

> 调试命令：`/好感度` 查看当前，`/好感度 80` 直接设置 0-100（QQ 私聊里同样可用 `/好感度 80`，别名 `/aff`）。设置到 75+ 会自动进入「恋人」阶段。

### 3. 部署 NapCat 并运行

1. 按 `napcat-guide.md` 部署 NapCat，开启正向 WebSocket（默认 `ws://127.0.0.1:3001`）
2. 确认 `.env` 中 `ONEBOT_WS_URLS` 与 NapCat 端口一致
3. 启动：

```powershell
.\.venv\Scripts\python.exe bot.py
```

> Windows 一键启动（防重复实例 + 双窗口）：双击 `start-all.bat`；健康自检 `check-bot.ps1`，干净停止 `stop-bot.ps1`

## 功能一览

### 对话与人格
- **固定人格**：全部对话共用「菟菚」人设（菟丝子娘，温柔慵懒病娇），见 persona 文件
- **先思考再发言**：输出【思考】+【回复】两段，只把【回复】发给对方，更走心
- **回复拟人化**：条数随内容 1-3 条自然变化、允许单长句；发前"酝酿"延迟 + 条间间隔（`THINK_DELAY`/`SEND_INTERVAL`）；偶尔带 QQ 表情
- **消息去抖合并**：你连发的多条消息会自动合并成一条处理，回复更连贯、更省调用
- **告别语境判断**：晚安/再见时简短收尾（1 条最多）、不复读、不硬续聊；倾诉/提问等才展开
- **称呼机制**：首次对话询问称呼；达成恋人（好感度 ≥75）后第二次确认；可用 `/称呼 xxx` 手动设置
- **时间感知**：贴合当前现实时间说话，但不会反复念叨"该睡了/熬夜"（只在你提及时顺一句）

### 好感度系统 v2
- **四阶段 0~100**：初识(0-24) → 熟悉(25-49) → 亲密(50-74) → 恋人(75-100)，影响对话尺度
- **正向互动奖励**（每天各上限 1 次）：用菟菚的称呼 +1、关心菟菚（"你累不累/辛苦了"）+1、
  回应主动消息 +2、深度/走心对话 +2、引用共同回忆 +1——越投入好感度涨得越快
- **每日基础**：首次聊天 +2、陪伴 +1、聊爱好 +1、尊重 +1（每日 LLM 判定）
- **惩罚调优**：刷屏 -2、辱骂 -5、轻视 -3；单日扣分不超 -10（防被打成负数）
- **恋人羁绊等级**：75-84 眷恋 / 85-94 热恋 / 95-100 白头，prompt 注入更细腻的关系描述
- **进度条**：`/好感` 显示 `████████░░` + 距下一阶段点数 + 羁绊等级
- **越熟越主动**：主动消息冷却随阶段缩短，恋人阶段最黏人

### 记忆
- **短期**：保留最近 30 轮完整对话；连发消息合并处理
- **长期**：原文关键词检索 + LLM 事实提炼（自动记住你的喜好/约定，纯 SQLite）+ 说话风格学习
- **语义检索**：疑似回忆时（"上次/之前/还记得"）LLM 查询扩展 + TF-IDF 稀疏向量余弦重排
- **稠密向量记忆**：接 SiliconFlow embedding + sqlite-vec，同义表达也能召回（如"下雨天好美"命中"喜欢下雨天"）
- **事实过滤**：提炼时区分"长期事实 vs 一次性话题"，只存值得长期记住的（今天吃什么不会污染记忆）
- **长会话压缩**：总消息超 60 条自动把旧部分摘要化，保留最近 14 条完整，长聊不掉线

### 情感记忆
- **特殊日子自动识别**：日常对话里说"我生日是5月20号"自动记住（含相对日期"后天/下个月"推算）；`/日子` 查看/删除兜底
- **日子提醒**：到日子 prompt 自动注入，菟菚自然提起；主动消息优先用它做由头

### 图片
- **识图**：收到图片/表情包 → 视觉模型描述内容 → 自然回应
- **表情包收藏**：你发纯表情包时自动下载收藏（`data/stickers/`），之后按话题回发同款
- **表情包主动推荐**：主动找你时，偶尔会带一张你最近收藏的表情包
- **生图（命令）**：`/画 一只趴在窗台上的猫` → SiliconFlow 生成治愈系插画发给你
- **生图（对话驱动）**：菟菚聊到"眼前的花田"，你说"要看"，她自动提炼画面并画出来发给你
- **生图错误分级**：失败时区分密钥无效/余额不足/限流/服务端/描述问题，给可操作的提示

### 联网与热梗
- **联网搜索**：命中新闻/天气/价格等自动检索后回答；`/搜索 <关键词>` 手动触发（博查/Bing/DuckDuckGo 自动回退）
- **网络热梗**：每 1 小时自动抓**微博热搜** + LLM 知识，提炼成「梗名+含义+人设用例」注入对话，菟菚在合适时机自然使用

### 主动消息
- **久别主动找**：几小时不说话，菟菚会主动发消息（只对 `PROACTIVE_USER_ID` 指定号，**支持多个**）
- **时段话题**：按时段（凌晨/早晨/上午/中午/下午/傍晚/晚上）+ 近期话题 + 特殊日子生成"有由头"的发起
- **频率控制**：检查间隔带随机抖动（避免死板节奏），越熟越主动；`/主动` 手动触发

### 稳定性
- **LLM 重试**：超时/限流/5xx 自动指数退避重试（最多 2 次），网络抖动不打断聊天
- **自动化测试**：pytest 覆盖好感度/记忆/向量检索/错误分类/重试判定（`python -m pytest tests/`）

## 常用命令

| 命令 | 作用 |
|---|---|
| `/称呼 [称呼]` | 设置/查看菟菚对你的称呼 |
| `/好感 [N]` / `/aff` | 查看好感度阶段/羁绊/进度条，或调节 0-100 |
| `/搜索 xxx` / `/搜 xxx` | 联网搜索 |
| `/主动` | 让菟菚主动发一条消息 |
| `/日子` | 查看特殊日子；`/日子 删除 1` 删除 |
| `/画 xxx` | 生图（如 `/画 窗边的小橘猫`） |
| 自然说"要看" | 对话驱动生图（菟菚描述画面后你说要看） |

## 已知简化（后续可升级）

- 长期记忆检索用 TF-IDF + 稠密向量（sqlite-vec）融合；如需更强的语义可换更大的 embedding 模型（现用 Qwen3-Embedding-0.6B）
- 称呼提取用正则启发式（"叫我XX"）+ `/称呼` 命令 + 每日总结兜底，不保证 100% 准确
- 网络热梗以 LLM 知识 + 微博热搜为主，当天刚爆的超新梗可能滞后（可再接热榜数据源增强）
- 单人使用设计（数据按 user_id 隔离，天然支持多用户）

## 常见问题

- **Python 3.14 venv 报 ensurepip 错误**：用 `py -3.14 -m venv --without-pip .venv` + 上面 `pip --python` 方式安装
- **HTTPS 连不上**：curl/Invoke-WebRequest 报 SEC_E_NO_CREDENTIALS 时改用 Python（OpenSSL）访问，pip 不受影响
- **生图不工作**：确认 `.env` 里 `IMAGE_API_KEY` 已填 SiliconFlow key（SiliconFlow 国内直连，无需代理）；错误提示会说明具体原因
- **消息重复回复**：多半是两个 bot 实例都连上了 WS；用 `check-bot.ps1` 自检，`stop-bot.ps1` 清理后重启
