import json
import os
import threading
import time

import uiautomation as auto
from dotenv import load_dotenv
from fastmcp.exceptions import ToolError

from util.we_chat_utils import (send_msg, _get_partner_control, get_msg_list, find_user,
                                monitor_setup, monitor_restore, monitor_scan_once)


def sendPartnerMsg(user_name:str, msg:str="", call:str|None=None):
    return send_msg(_get_partner_control(user_name), msg, call)

def getPartnerMsgList(user_name: str, load_more: bool = False, recent: int = 0):
    win = find_user(user_name)  # ChatWnd 存在则直接用，不存在则自动打开（同 openPartnerWindow）
    msgs = get_msg_list(win, load_more)
    if recent > 0:  # 只要最近 N 条纯文本消息（时间标签不计入条数）
        if isinstance(msgs, dict):  # load_more=True 且无更多历史时返回 {"提示", "全部消息"}
            msgs = msgs.get("全部消息", [])
        texts = [m for m in msgs if not m.startswith("[时间]：")]
        return texts[-recent:]
    return msgs


_CACHE_KEYS = {
    "partners": ("WE_CHAT_PARTNERS_LIST", "listWeChatPartners"),
    "contacts": ("WE_CHAT_CONTACTS_LIST", "listWeChatContacts"),
}


def get_cached_list(kind: str) -> list[str]:
    """读取上次全量扫描缓存在 .env 的列表（JSON 数组）。

    Args:
        kind: "partners" 读会话列表缓存；"contacts" 读联系人列表缓存。

    Returns:
        上次扫描到的名称列表（已排序）
    """
    key, scan_tool = _CACHE_KEYS.get(kind, (None, None))
    if key is None:
        raise ToolError("kind 只能是 'partners' 或 'contacts'")
    load_dotenv(override=True)  # 重新加载 .env，读到运行时写入的最新值
    raw = os.getenv(key)
    if not raw:
        raise ToolError(f"env 里还没有 {key}，请先调用 {scan_tool} 全量扫描一次")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ToolError(f"{key} 不是合法 JSON: {e}") from e


# ============ 主页消息监听（业务逻辑，main.py 里只是薄封装）============
# 注意：Claude Code 的 MCP 请求有 60 秒超时，长阻塞工具会超时被杀。
# 所以改成"后台 daemon 线程持续监听 + 三个秒回工具（启动/查询/停止）"。

_monitor_stop = threading.Event()     # monitor_stop 置位 → 后台循环检测到后优雅退出
_monitor_running = False              # 当前世代的监听是否在跑
_monitor_thread = None                # 当前监听线程引用（启动新监听前等旧线程退出）
_monitor_gen = 0                      # 世代号：每次启动 +1，旧循环发现世代不符就自动退出
_monitor_start_time = 0.0             # 启动时刻（算剩余秒数）
_monitor_duration = 120.0             # 监听总时长（秒）
_monitor_baseline = {}                # 当前基线快照 {会话名: {"最新消息", "未读数"}}
_monitor_changes = []                 # 累计变化 [{会话, 最新消息, 未读数}, ...]
_monitor_error = None                 # 后台扫描出错时记录，monitor_poll 返回


def monitor_start(duration: float = 120, interval: float = 5, after: str = "keep") -> dict:
    """启动后台监听：摆窗口 + 首扫建基线 + 起后台线程轮询。秒回，不阻塞。

    若已有监听在跑：先置停止位 + 等旧线程真正退出（join，最多 3 秒），
    再世代号 +1 开新循环——保证任何时刻只有 1 个循环，避免并发扫描同一窗口互相打架。
    """
    global _monitor_running, _monitor_stop, _monitor_start_time, _monitor_duration
    global _monitor_baseline, _monitor_changes, _monitor_error, _monitor_thread, _monitor_gen
    # 停掉旧监听：置停止位 + 等旧线程真正退出
    if _monitor_thread and _monitor_thread.is_alive():
        _monitor_stop.set()
        _monitor_thread.join(timeout=3)
    _monitor_gen += 1               # 世代号 +1；旧线程若 join 超时残留，检测到世代不符也会自行退出
    gen = _monitor_gen
    _monitor_stop.clear()
    _monitor_running = True
    _monitor_start_time = time.time()
    _monitor_duration = duration
    _monitor_changes = []
    _monitor_error = None
    try:
        monitor_setup()  # 摆窗口 + 记住原矩形
    except Exception as e:
        _monitor_running = False
        return {"错误": f"监听前准备失败: {e}"}
    try:
        _monitor_baseline = monitor_scan_once(after)  # 首轮扫描 = 基线
    except Exception as e:
        _monitor_running = False
        try:
            monitor_restore()
        except Exception:
            pass
        return {"错误": f"首次扫描失败: {e}"}
    if not _monitor_baseline:
        _monitor_running = False
        return {"错误": "主页没读到任何会话，请确认微信已登录且在主界面"}
    # 首轮就把带未读标签的会话报出来（不再忽略初始未读）；基线已按首扫建立，后续变化在此基础上累加
    initial_unread = []
    for name, info in _monitor_baseline.items():
        if info["未读数"] > 0:
            item = {"会话": name, "最新消息": info["最新消息"], "未读数": info["未读数"]}
            _monitor_changes.append(item)
            initial_unread.append(item)
    _monitor_thread = threading.Thread(target=_monitor_loop, args=(interval, after, gen), daemon=True)
    _monitor_thread.start()
    return {"状态": "监听已启动", "预计监听秒数": duration, "刷新间隔": interval,
            "监控会话数": len(_monitor_baseline), "初始未读": initial_unread}


def _monitor_loop(interval: float, after: str, gen: int):
    """后台轮询循环（daemon 线程）。发现变化就累计进 _monitor_changes。

    必须在线程内先初始化 UIA：uiautomation 的 COM 对象不能跨线程使用，
    直接复用主线程创建的控件会抛 COM 错误导致循环崩溃。
    """
    global _monitor_running, _monitor_error, _monitor_baseline, _monitor_changes
    try:
        with auto.UIAutomationInitializerInThread():
            while time.time() - _monitor_start_time < _monitor_duration:
                if gen != _monitor_gen:  # 有更新的监听顶掉了自己 → 退出
                    break
                if _monitor_stop.wait(interval):  # 睡 interval 秒，或被 set() 立刻唤醒 → 即时停止
                    break
                if gen != _monitor_gen:  # 睡醒后再确认一次（防止 wait 期间被顶掉还继续跑）
                    break
                try:
                    data = monitor_scan_once(after)
                except Exception as e:
                    _monitor_error = str(e)  # 扫描挂了，记录并停
                    break
                found = []
                for name, info in data.items():
                    old = _monitor_baseline.get(name)
                    if old is None or old["最新消息"] != info["最新消息"] or info["未读数"] > old["未读数"]:
                        found.append({"会话": name, "最新消息": info["最新消息"], "未读数": info["未读数"]})
                if found:
                    _monitor_changes.extend(found)
                _monitor_baseline = data
    finally:
        if gen == _monitor_gen:  # 只有当前世代负责翻转运行状态（旧线程的 finally 不碰）
            _monitor_running = False
        try:
            monitor_restore()  # 还原窗口
        except Exception:
            pass


def monitor_poll(stop: bool = False) -> dict:
    """查询后台监听状态 + 累计变化。秒回。

    stop=False（默认）：只查询；若有变化且监听仍在跑，自动停止并清空本次已返回的变化
    （agent 将操作窗口，避免两线程打架、也避免已处理消息残留）。
    stop=True：立刻强制停止监听（即使还没有变化）。
    """
    global _monitor_changes
    if stop and _monitor_running:
        _monitor_stop.set()   # 强制停
    remaining = max(0, round(_monitor_duration - (time.time() - _monitor_start_time)))
    if _monitor_running and (stop or _monitor_changes):
        _monitor_stop.set()   # 强制停（stop=True）或有变化 → 本次就让监听停
        state = "已停止" if stop else "已自动停止"
    else:
        state = "监听中" if _monitor_running else "已结束"
    changes = _monitor_changes
    result = {"状态": state, "剩余秒数": remaining,
              "累计变化": changes,
              "监控会话数": len(_monitor_baseline),
              "错误": _monitor_error}
    if changes:  # 变化已随本次返回交付，清空避免残留
        _monitor_changes = []
    return result





