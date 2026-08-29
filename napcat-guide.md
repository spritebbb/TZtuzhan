# NapCat 部署指引（Windows）

NapCat 是 QQNT 的协议实现，负责让 bot 能收发 QQ 私聊消息。
它与 bot 之间走 **OneBot 11 正向 WebSocket** 标准。

## ✅ 本机已配置完成（实测可用）

- NapCat：`D:\DSH\TZtuzhan\Napcat\NapCat.Shell.Windows.Node\`（v4.18.19）
- 启动脚本：**`napcat\launcher.bat`**（官方，带管理员提权；通过注册表找到 `D:\QQ\QQ.exe`）
- QQNT：`D:\QQ\QQ.exe`（版本 9.9.33，已注册到注册表，launcher 能自动找到）
- bot QQ 号：**（你的 bot 小号，见 .env 的 BOT_QQ）**
- OneBot 正向 WS：**端口 3001**（已写入 `napcat\config\onebot11_<BotQQ>.json`）
- WebUI：`http://127.0.0.1:6099`（token 见 `config\webui.json`）
- 配置文件（NapCat）已加入 `.gitignore`，不会进仓库

### 日常启动（两个终端）

**终端 ① —— NapCat（用官方 launcher.bat，会弹管理员/UAC 确认）：**
```powershell
cd D:\DSH\TZtuzhan\Napcat\NapCat.Shell.Windows.Node\napcat
launcher.bat
```
（它需要管理员权限注入 QQNT；登录过的小号一般会自动登录，若弹码就扫码。）

**终端 ② —— bot：**
```powershell
cd D:\DSH\TZtuzhan
.\.venv\Scripts\python.exe bot.py
```
日志出现 `OneBot V11 | Bot <你的botQQ> connected` 即连接成功。

### 验证
```powershell
Get-NetTCPConnection -LocalPort 3001 -State Listen   # NapCat 就绪
```
用另一个 QQ 私聊 bot 号，发"你好"、`/好感 80`、`/搜索 xxx` 测试。

---

> 以下为通用安装说明（首次安装参考）。

## 一、下载与安装

1. 打开 NapCat 官方仓库：<https://github.com/NapNeko/NapCatQQ/releases>
2. 下载 Windows 版本（建议 **WebUI 版** 或 **Win 安装版**），解压或安装到任意目录
3. 如果你更习惯图形界面，也可以在 Release 里找一键安装器

> 备用方案（均支持 OneBot 11）：Lagrange.OneBot（无需 QQNT 客户端，纯 C# 实现）、LLOneBot。

## 二、登录 QQ 小号

1. 运行 NapCat
2. 用**准备用作 bot 的 QQ 小号**扫码登录（⚠️ 不建议用主号，非官方协议有风控/封号风险）
3. 登录成功后 NapCat 会显示运行状态

## 三、开启 OneBot 正向 WS

1. 打开 NapCat 的配置面板（WebUI 或配置文件 `config/onebot11_<qq号>.json`）
2. 找到 **OneBot 11 设置**，开启「正向 WebSocket 服务端」（正向 WS）
3. 端口保持默认 **3001**（或自定义，但需同步修改 `TZtuzhan/.env` 里的 `ONEBOT_WS_URLS`）
4. 保存并重启 NapCat 使配置生效

`onebot11_<qq号>.json` 关键字段示例：

```json
{
  "network": {
    "enableWsServer": true,
    "wsServerPort": 3001
  }
}
```

## 四、验证

PowerShell 确认端口已监听：

```powershell
Get-NetTCPConnection -LocalPort 3001 -State Listen
```

有输出即成功。然后运行 bot：

```powershell
cd D:\DSH\TZtuzhan
.\.venv\Scripts\python.exe bot.py
```

启动日志里出现 `WebSocket 连接成功` 或类似字样后，用另一个 QQ 号给 bot 发私聊消息测试。

## 五、常见问题

| 现象 | 处理 |
|---|---|
| bot 启动但收不到消息 | 确认 NapCat 已登录、正向 WS 已开启、端口与 `.env` 一致 |
| 登录后提示风控/验证 | 换登录方式（扫码/短信），小号先养几天再上 |
| 发消息频繁被吞 | 降低发言频率，bot 侧已有刷屏检测 |
| NapCat 版本更新后连不上 | 重新确认 WS 配置与端口 |

## 六、安全提示

- **务必使用小号**，非官方协议存在封号风险
- 不要给 bot 号充值、不要用于重要账号
- 私聊场景风险低于群聊，但仍建议低调使用
