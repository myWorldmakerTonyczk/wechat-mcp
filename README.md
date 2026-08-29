# wechat-mcp

基于 **FastMCP + uiautomation** 的 Windows 微信 MCP 服务器。让 Claude Code / 任意 MCP 客户端能直接操控 Windows 微信：读会话、读/发消息、监听新消息。

## 功能

- 📋 **会话 / 联系人**：主页可见会话（含未读数、最新消息预览）、全量会话、全量联系人、缓存读取
- 💬 **读消息**：按会话读取（带发送者前缀 + 时间标签）；`recent=N` 只要最近 N 条；`load_more` 逐批加载更早历史
- ✉️ **发消息 / 通话**：发送文本、发起 / 挂断语音视频通话
- 🔍 **搜索**：用微信自带搜索框搜联系人 / 群聊 / 公众号（支持拼音）
- 📡 **监听新消息**：后台线程轮询主页会话，`monitorStart` + `monitorPoll` 组合，发现新消息自动停止并返回

## 环境要求

- Windows + 已登录的微信 PC 版（微信窗口要能打开）
- Python 3.10+（实测 3.14）

## 安装

```bash
cd agent_use_weChat
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

配置微信路径（写入 `.env`）：

```
WE_CHAT_PATH=C:\你的\WeChat.exe
```

## 注册到 Claude Code

```bash
claude mcp add use_weChat -- <项目路径>\.venv\Scripts\python.exe <项目路径>\src\main.py
```

## 工具一览

| 工具 | 作用 |
|---|---|
| `openWeChat` | 打开微信 |
| `listHomeChats(full_scan)` | 主页会话（含未读 / 预览；`full_scan=True` 全量） |
| `listWeChatContacts` / `getCachedList` | 全量联系人 / 缓存列表 |
| `searchWeChat` | 搜索联系人 / 群聊 / 公众号 |
| `get_msg_list(userName, load_more, recent)` | 读消息（窗口没开会自动打开） |
| `sendMsg(userName, msg, call)` | 发文本 / 语音视频通话 / 挂断 |
| `openPartnerWindow(userName)` | 显式打开会话窗口 |
| `monitorStart` / `monitorPoll` | 监听主页新消息 |

## 说明

- `get_msg_list` 窗口没开会自动打开；`sendMsg` 需要窗口已开（先 `get_msg_list` 或 `openPartnerWindow`）
- 监听用 `monitorStart` + `monitorPoll` 组合（MCP 单次调用有 60s 超时，别用长阻塞调用）
- 基于 uiautomation 界面自动化驱动微信：无注入、无解库、不碰进程内存
