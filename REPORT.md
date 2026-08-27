# 菟菚（TZtuzhan）—— QQ 私聊 AI 女友 bot 项目报告

> 项目：`D:\DSH\TZtuzhan`
> 版本：迭代开发中 · Git 已初始化（30 个文件，`data/bot.db` 已清空待开始）

---

## 一、项目简介

「菟菚」是一个固定人设的 **QQ 私聊 AI 伴侣**，只接入私聊、不处理群聊。她是一个"菟丝子娘"——温柔、慵懒、带一点病娇，像网友一样隔着屏幕陪你聊天。项目从零搭建，包含完整的**人格、好感度、记忆、联网搜索、识图、主动消息**等能力。

## 二、技术栈

| 层 | 技术 |
|---|---|
| 平台接入 | QQ 私聊（OneBot 11 / NapCat + QQNT） |
| Bot 框架 | NoneBot2（aiohttp driver）+ nonebot-adapter-onebot |
| LLM | DeepSeek（`deepseek-chat` 对话 + `deepseek-v4-flash-vision-exp` 识图） |
| 联网搜索 | 博查 AI 搜索 API（Bing/DuckDuckGo 自动回退） |
| 存储 | Python 内置 SQLite（`data/bot.db`），零外部依赖 |
| 运行环境 | Windows + Python 3.14 + Node(附带，NapCat 用) |

## 三、核心功能

1. **固定人格**：菟丝子娘、网友距离感、温柔慵懒病娇；含背景身世（被留下的孤独 → 黏人占有欲）
2. **四阶段好感度**：初识(冷淡疏远)→熟悉(推拉)→亲密(害羞)→恋人(黏人放开)，`/好感 N` 可调节
3. **先思考再发言**：输出【思考】+【回复】，只把【回复】发给对方，更走心
4. **说话风格**：短句分条发送、不用句号、偶尔发 QQ 表情、逐句学习你的说话风格
5. **称呼机制**：首次/恋人二次确认、净化、拒绝过分称呼（爸爸/傻逼等）
6. **记忆**：短期 30 轮上下文 + 长期事实/风格提炼（事实表 + 风格档案）
7. **联网搜索**：命中新闻/天气/价格等自动检索，按她口吻回答
8. **识图**：收到表情包/图片 → DeepSeek 视觉模型描述内容 → 自然回应
9. **主动消息**：久别后主动找你（只对指定 QQ 号），可 `/主动` 手动触发
10. **特殊规则**：过早表白/辱骂/刷屏/过度打扰等处理

## 四、架构

```
QQ 小号 ⇄ NapCat(注入 QQNT) ⇄ OneBot WS :3001 ⇄ NoneBot2(bot.py)
                                                     ├─ plugins/private_chat  QQ 事件 + 表情/识图
                                                     └─ core/                对话流水线
                                                          ├─ persona.py   人格注入(阶段/称呼/时间/风格)
                                                          ├─ pipeline.py  主流程(思考→回复→拆条)
                                                          ├─ affection.py 好感度规则
                                                          ├─ userdb.py    SQLite(用户/消息/事实/风格)
                                                          ├─ daily.py     每日提炼(事实+风格)
                                                          ├─ memory.py    短期+长期检索
                                                          ├─ search.py    联网搜索(博查/Bing/ddg)
                                                          ├─ vision.py    识图(DeepSeek多模态)
                                                          └─ proactive.py 主动发消息
```

## 五、运行方式

```powershell
# 一键启动（自动提权 + NapCat + bot 两窗口）
双击 D:\DSH\TZtuzhan\start-all.bat

# 或手动：终端① NapCat，终端② bot
cd D:\DSH\TZtuzhan\Napcat\NapCat.Shell.Windows.Node\napcat & launcher.bat
cd D:\DSH\TZtuzhan & .\.venv\Scripts\python.exe bot.py
```

配置：`.env`（LLM key、博查 key、视觉模型、主动对象 PROACTIVE_USER_ID 等）。
测试工具：`test_stages.py`（四阶段）、`test_memory.py`、`import_logs.py`（聊天记录风格导入）。

## 六、测试结果（四阶段验收）

| 阶段 | "我好喜欢你" | "我们是恋人了吗" | "抱一下" |
|---|---|---|---|
| 初识 | 才认识没多久吧 | 我们什么时候成恋人了？ | 还没熟到那种程度吧 |
| 熟悉 | 这话可不能随便说，我会当真 | 你心里已经把我当恋人了？ | 等见面了再说 |
| 熟悉/亲密 | 说得我脸都热了 | 跑不掉，我也不急 | 心痒痒的，等见面再抱 |
| 恋人 | 我心跳漏了一拍，我也喜欢你 | 是恋人了，可以缠着你了 | 抱紧，现在是我的了 |

## 七、当前状态与说明

- **开发完成**，本地 + QQ 私聊实测可用（有回复、识图、主动消息均验证过）
- **未做开机自启服务**：当前用 `start-all.bat` 手动启动，需保持两个窗口
- **长期记忆**：事实/风格提炼（LLM，约每 10 条消息 + 每日），纯 SQLite；如需语义检索可接向量库
- **安全提示**：NapCat 用 QQ 小号（非官方协议有封号风险）；API key（DeepSeek/博查）在 `.env` 已 gitignore
