import os
import re
import subprocess
import time
from typing import Literal

import win32api
import win32con
import win32gui
from _ctypes import COMError

from dotenv import load_dotenv
from uiautomation import Control, WindowControl
import uiautomation as auto

from util.utils import clean_conv_name,retry
from fastmcp.exceptions import ToolError

load_dotenv(override=True)
WE_CHAT_PATH = os.getenv("WE_CHAT_PATH")

win_weChat = auto.WindowControl(Name="微信",ClassName="WeChatMainWndForPC")
CLASS_NAME="WeChatMainWndForPC"
WINDOW_NAME="微信"

def activate_window(control, class_name, maximize=True):
    """把（可能收到托盘/最小化的）窗口恢复并激活，默认全屏。

    先用 win32 按类名找句柄并恢复显示，再让 uiautomation 控件重新匹配。
    全屏保证列表可见区最大，虚拟化列表滚动更可靠。

    Args:
        control: uiautomation 窗口控件
        class_name: 窗口类名（微信主窗口/聊天窗口类名固定）
        maximize: 是否全屏，默认 True。列表扫描需要全屏；聊天窗口操作可关掉
    """
    hwnd = win32gui.FindWindow(class_name, None)
    if not hwnd:
        raise ToolError(f"找不到窗口（类名 {class_name}）")
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    if maximize:
        screen_w = win32api.GetSystemMetrics(0)
        screen_h = win32api.GetSystemMetrics(1)
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0,
                              screen_w, screen_h, win32con.SWP_NOACTIVATE)
    control.Refind()
    control.SetActive()
    return control


def restore_small_window(class_name, size=600):
    """把窗口缩小成 size×size 并居中。列表扫描后调用，避免窗口一直占满屏幕。

    Args:
        class_name: 窗口类名
        size: 窗口边长像素，默认 600
    """
    hwnd = win32gui.FindWindow(class_name, None)
    if not hwnd:
        return
    screen_w = win32api.GetSystemMetrics(0)
    screen_h = win32api.GetSystemMetrics(1)
    x = (screen_w - size) // 2
    y = (screen_h - size) // 2
    win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, x, y, size, size,
                          win32con.SWP_SHOWWINDOW)

#打开微信
def open_wechat(path:str|None = WE_CHAT_PATH):
    if path is None:
        raise ToolError("微信可执行文件路径缺失，请传入 path 或设置 WE_CHAT_PATH")
    try:
        subprocess.Popen(path)
    except Exception as e:
        raise ToolError(f"微信启动失败: {e}") from e
    try:
        win_weChat=auto.Control(Name="微信", ClassName="WeChatLoginWndForPC")
        win_weChat.SetFocus()
        win_weChat.ButtonControl(Name="进入微信").Click(simulateMove=False)
    except Exception as e:
        raise ToolError(f"窗口可能未正确打开，可能未正确匹配窗口控件: {e}") from e
    return True

#列出首页当前可见的会话（轻量，快，不滚动）。每个会话返回 名称/新消息数/最后一条消息
def _chat_item_info(item) -> dict:
    """从会话项提取 名称/新消息/最后一条消息。
    未读数直接取自名字后缀"NN条新消息"（最可靠）；最后一条消息取底部非徽标文本。"""
    nm = item.Name or ""
    m = re.search(r"(\d+)条新消息$", nm)
    unread = int(m.group(1)) if m else 0
    texts = []
    item_r = item.BoundingRectangle
    top_limit = item_r.top + item_r.height() * 0.6  # 徽标在项的上半部
    for c, depth in auto.WalkControl(item, maxDepth=4):
        if c.ControlTypeName == 'TextControl' and c.Name:
            r = c.BoundingRectangle
            if c.Name.isdigit() and r.top < top_limit:
                continue  # 未读数徽标（顶部小数字），不当作消息预览
            texts.append(c.Name)
    return {
        "名称": re.sub(r"\s*\d+条新消息$", "", nm),
        "新消息": unread,
        "最后一条消息": texts[-1] if texts else "",
    }


#列出首页会话（轻量，快，不滚动）；full_scan=True 时全量滚动扫描（慢，和 list_user 一样）
@retry(retry_num=2)
def _scroll_to_top(lst):
    """把列表滚到最顶。连续 2 轮第一个项名字不变 = 到顶，停止。"""
    prev_first = None
    stable = 0
    for _ in range(50):  # 最多 50 次防死循环
        items = lst.GetChildren()
        first = items[0].Name if items else None
        if first == prev_first:  # 第一项没变，可能到顶了
            stable += 1
            if stable >= 1:
                break
        else:
            stable = 0
        prev_first = first
        lst.WheelUp(wheelTimes=20, interval=0.01)
        time.sleep(0.2)


def list_home_chats(full_scan:bool=False):
    activate_window(win_weChat, CLASS_NAME)
    lst = win_weChat.ListControl(Name="会话")
    if full_scan:
        result = _scroll_collect(lst, with_info=True)
        restore_small_window(CLASS_NAME)
        return result
    # 非全量：先滚到最顶，再取当前可见的（保证每次看到的是顶部开始的会话）
    _scroll_to_top(lst)
    children = lst.GetChildren()
    restore_small_window(CLASS_NAME)
    return [_chat_item_info(i) for i in children if i.Name]

#回滚到顶 + 自适应滚动收集（会话/联系人列表通用）。返回按真实扫描顺序（界面从上到下）的列表；
#with_info=True 时返回 dict 列表（{"名称","新消息","最后一条消息"}）。
def _scroll_collect(lst, with_info:bool=False):
    # ① 回滚到顶部
    _scroll_to_top(lst)
    # ② 从顶部向下滚动收集（自适应调速：小步起步 → 慢慢加快 → 够快后锁速划到底）
    seen_set = set()
    seen_order = []  # 首次扫描顺序 = 微信界面从上到下的真实顺序
    seen_info = {} if with_info else None
    empty_rounds = 0
    initial_clicks = 8  # 初始 8 格
    clicks = initial_clicks
    max_clicks = 30      # 速度上限，防失控
    accel = True        # 是否仍在加速
    first_round = True  # 第一轮没有"滚动效果"可参考，跳过调速
    for _ in range(60):  # 最多 60 轮防死循环
        # 收集当前可见，同时统计重复项（已见过的项）
        new_found = 0
        dups = 0
        visible = 0
        for item in lst.GetChildren():
            name = item.Name
            if not name:
                continue
            visible += 1
            if name in seen_set:
                dups += 1
            else:
                seen_set.add(name)
                seen_order.append(name)
                if with_info:
                    seen_info[name] = _chat_item_info(item)
                new_found += 1
        # 自适应调速：
        #   重复占比高（滚太慢，每轮都在原地打转）→ 逐步加快（每次 +1 格，慢慢加）；
        #   重复占比低（如 10 个里约 ≤2 个重复）→ 每轮都在大量吃新内容，够快了，锁住这个速度划到底
        if accel and not first_round and visible > 0:
            dup_ratio = dups / visible
            if dup_ratio <= 0.2:
                accel = False
            elif new_found > 0:
                # 增速放缓：每轮固定 +1 格，慢慢逼近上限（不再跳 2 格，避免滚太快漏扫）
                clicks = min(clicks + 1, max_clicks)
        first_round = False
        # 滚动
        lst.WheelDown(wheelTimes=clicks, interval=0.03)
        time.sleep(0.4)
        # 到底判断：连续 3 轮无新增
        if new_found == 0:
            empty_rounds += 1
            if empty_rounds >= 3:
                break
        else:
            empty_rounds = 0
    if with_info:
        return [seen_info[name] for name in seen_order]
    return seen_order

#列出全部会话名称（回滚到顶 + 滚动收集，慢但全）
@retry(retry_num=2)
def list_user():
    activate_window(win_weChat, CLASS_NAME)
    lst = win_weChat.ListControl(Name="会话")
    result = _scroll_collect(lst)
    restore_small_window(CLASS_NAME)
    return result

#列出通讯录全部联系人（切到通讯录页 + 滚动收集，慢但全）
@retry(retry_num=2)
def list_contacts():
    activate_window(win_weChat, CLASS_NAME)
    win_weChat.ButtonControl(Name="通讯录").Click(simulateMove=False)
    time.sleep(1)  # 等联系人列表渲染出来
    lst = win_weChat.ListControl(Name="联系人")
    result = _scroll_collect(lst)
    # 切回聊天页，否则后续"会话"列表的工具（list_user/list_home_chats）会找不到列表
    win_weChat.ButtonControl(Name="聊天").Click(simulateMove=False)
    restore_small_window(CLASS_NAME)
    return result

def _find_chat_window(user_name: str) -> WindowControl:
    """按会话名匹配聊天窗口，窗口在则返回，否则抛 ToolError。"""
    try:
        win_chat_user = auto.WindowControl(RegexName=f".*{clean_conv_name(user_name)}.*", ClassName="ChatWnd")
        if win_chat_user.Exists(5):
            return win_chat_user
    except (LookupError, COMError) as e:
        raise ToolError(f"匹配聊天窗口失败 [{clean_conv_name(user_name)}]: {e}") from e
    raise ToolError(f"搜索后未找到会话 [{clean_conv_name(user_name)}]")


#点击打开聊天页面，并返回用户窗口对象
def find_user(user_name:str)->WindowControl:
    # ① 先查聊天窗口是否已存在，存在直接用（不需要重新搜索）
    try:
        win_chat_user = auto.WindowControl(RegexName=f".*{clean_conv_name(user_name)}.*", ClassName="ChatWnd")
        if win_chat_user.Exists(1):
            win_chat_user.SetActive()
            return win_chat_user
    except (LookupError, COMError):
        pass  # 窗口查询异常，继续走打开流程

    # ② 窗口不存在，走搜索框 + 双击打开
    try:
        activate_window(win_weChat, CLASS_NAME, maximize=False)
        win_chat = win_weChat.ButtonControl(Name="聊天")
        win_chat.Click(simulateMove=False)

        win_search = win_weChat.EditControl(Name="搜索")
        win_search.Click(simulateMove=False)
        win_search.SendKeys('{Ctrl}a')  # 全选
        win_search.SendKeys('{Delete}')  # 删掉
        win_search.SendKeys(clean_conv_name(user_name))
        # win_search.SendKeys('{Enter}')
    except (LookupError,COMError) as e:
        raise ToolError(f"微信窗口/搜索框操作失败，请确认微信已登录且在聊天界面: {e}") from e
    # 在搜索结果列表里定位目标会话并双击
    # （新版微信用"搜索结果浮层" @str:IDS_FAV_SEARCH_RESULT，目标不在"会话"列表里）
    target = None
    try:
        result_list = win_weChat.ListControl(SubName='@str:IDS_FAV_SEARCH_RESULT')
        for item in result_list.GetChildren():  # 优先精确全名（如"祥发-已置顶"）
            if item.ControlType == 50007 and item.Name == user_name:
                target = item
                break
        if target is None:  # 没精确匹配（传了简称）→ 取最上面有名字的项（聊天结果排最前）
            for item in result_list.GetChildren():
                if item.ControlType == 50007 and item.Name:
                    target = item
                    break
    except (LookupError, COMError, TypeError) as e:
        raise ToolError(f"定位搜索结果 [{user_name}] 失败: {e}") from e
    if target is None:
        raise ToolError(f"搜索结果里找不到会话 [{user_name}]")

    # 把双击拆成两次单击：第一次点搜索结果目标，隔半秒后在主窗口"会话"列表里找同名项再点一次
    try:
        target.Click(simulateMove=False)  # 第一次单击：搜索结果里的目标
    except (LookupError, COMError, TypeError):
        pass
    time.sleep(0.5)
    # 第二次：主窗口"会话"列表里同名项 双击（双击才打开 ChatWnd 窗口）
    target2 = None
    try:
        chat_list = win_weChat.ListControl(Name="会话")
        for item in chat_list.GetChildren():
            nm = (item.Name or '')
            if nm == user_name or nm == target.Name or user_name in nm:
                target2 = item
                break
        if target2 is not None:
            target2.DoubleClick(simulateMove=False)
    except (LookupError, COMError, TypeError):
        pass

    # ① 等窗口出现（给两次单击 3 秒生效时间）
    win_chat_user = auto.WindowControl(RegexName=f".*{clean_conv_name(user_name)}.*", ClassName="ChatWnd")
    if win_chat_user.Exists(3):
        return win_chat_user

    # ② 没出现 → 对最近点过的目标真实鼠标双击（simulateMove=True 会移动真实鼠标）
    try:
        (target2 or target).DoubleClick(simulateMove=True)
    except (LookupError, COMError, TypeError) as e:
        raise ToolError(f"双击打开会话 [{user_name}] 失败: {e}") from e
    return _find_chat_window(user_name)  # 再等 5 秒，仍无 → 抛"搜索后未找到会话"


def search_wechat(keyword: str) -> list[str]:
    """在微信主窗口搜索框搜关键字，返回搜索结果（联系人/群聊/公众号等）。

    流程和 find_user 一致：切聊天页 → 点搜索框 → 输入关键字 → 等结果 → 收集带名字的 ListItem → Esc 清理。
    """
    win_search = None
    try:
        activate_window(win_weChat, CLASS_NAME, maximize=False)
        win_weChat.ButtonControl(Name="聊天").Click(simulateMove=False)
        win_search = win_weChat.EditControl(Name="搜索")
        win_search.Click(simulateMove=False)
        win_search.SendKeys('{Ctrl}a')
        win_search.SendKeys('{Delete}')
        win_search.SendKeys(keyword)
        time.sleep(1.5)  # 等搜索结果渲染
        result_list = win_weChat.ListControl(SubName='@str:IDS_FAV_SEARCH_RESULT')
        results = []
        for item in result_list.GetChildren():
            if item.ControlType != 50007 or not item.Name:  # 只要 ListItemControl 且有名字
                continue
            if item.Name.startswith("显示全部") or item.Name.startswith("搜索 "):
                continue  # 跳过"显示全部"按钮和"搜索 xxx"的网页搜索项
            results.append(item.Name)
        return results
    except (LookupError, COMError, TypeError) as e:
        raise ToolError(f"微信搜索失败: {e}") from e
    finally:
        if win_search is not None:
            try:
                win_search.SendKeys('{Esc}')  # 清理搜索框，避免影响后续工具
            except Exception:
                pass


def _get_partner_control(user_name:str):
    try:
        win_chat_user=auto.WindowControl(RegexName=f".*{clean_conv_name(user_name)}.*",ClassName="ChatWnd")
        return win_chat_user
    except (LookupError,COMError) as e:
        raise ToolError(f"搜索后未找到会话 [{clean_conv_name(user_name)}]: {e}") from e


_CALL_WND_CLASSES = ("VoipWnd", "AudioWnd")  # 视频通话=VoipWnd，语音通话=AudioWnd


def _call_window():
    """返回当前通话窗口控件（视频=VoipWnd，语音=AudioWnd）。没有则返回 None。"""
    for cls in _CALL_WND_CLASSES:
        w = auto.WindowControl(ClassName=cls)
        if w.Exists(0.3):
            return w
    return None


def _call_exists(timeout:float=0.2) -> bool:
    """检测通话窗口是否存在。优先 win32gui（Win32 层最可靠），uiautomation 兜底。"""
    for cls in _CALL_WND_CLASSES:
        if win32gui.FindWindow(cls, None):
            return True
    try:
        return any(auto.WindowControl(ClassName=cls).Exists(timeout) for cls in _CALL_WND_CLASSES)
    except Exception:
        return False


def _visible_wechat_windows() -> list[str]:
    """列出当前可见的微信相关窗口（类名/title），用于排错。"""
    out = []
    def cb(h, r):
        if win32gui.IsWindowVisible(h):
            c = win32gui.GetClassName(h)
            t = win32gui.GetWindowText(h)
            if "Voip" in c or "WeChat" in c or t in ("微信",):
                out.append(f"{c} title={t!r}")
    win32gui.EnumWindows(cb, out)
    return out


def send_msg(user_control:WindowControl, msg:str="",
             call:Literal["voice","video","hangup"]|None=None):
    # 挂断通话分支：直接操作通话窗口，不依赖会话窗口
    if call == "hangup":
        if not _call_exists():
            return True  # 本来就没通话 → 幂等，直接成功
        call_wnd = _call_window()
        call_wnd.SetActive()
        try:
            call_wnd.ButtonControl(Name="挂断").Click(simulateMove=False)
        except Exception as e:
            raise ToolError(f"挂断失败: {e}") from e
        time.sleep(1)
        if not _call_exists():
            return True
        raise ToolError("挂断后通话窗口仍存在")
    # 发起通话分支：点聊天窗口里的 语音聊天/视频聊天 按钮
    if call in ("voice", "video"):
        btn_name = "语音聊天" if call == "voice" else "视频聊天"
        try:
            activate_window(user_control, "ChatWnd", maximize=False)
            user_control.ButtonControl(Name=btn_name).Click(simulateMove=False)
        except Exception as e:
            raise ToolError(f"发起{btn_name}失败: {e}") from e
        # 验证：轮询等通话窗口 VoipWnd 出现（视频通话窗口可能延迟几秒才弹出）
        deadline = time.time() + 15
        while time.time() < deadline:
            if _call_exists():
                return True
            time.sleep(1)
        # 报错时带上当前可见的微信窗口，便于排查到底弹了什么
        raise ToolError("通话窗口未出现，可能未成功发起通话。"
                        f"当前相关窗口: {'; '.join(_visible_wechat_windows()) or '无'}")
    # 文本发送分支（原逻辑）
    try:
        activate_window(user_control, "ChatWnd", maximize=False)
        input_win=user_control.EditControl(Name="输入")
        input_win.SetFocus()
        input_win.Click(simulateMove=False)
        input_win.SendKeys(text=msg)
        user_control.ButtonControl(Name="发送(S)").Click(simulateMove=False)
    except Exception as e:
        raise ToolError(f"发送消息失败: {e}") from e
    # 发送成功后验证是否真的发出去了（自己发的消息前缀是"[我]："）
    if get_msg_list(user_control)[-1]==f"[我]：{msg}":
        return True
    else:
        raise ToolError("消息发送后未在聊天记录中匹配到，可能未成功发送")

def _find_sender(m) -> str | None:
    """从消息项里找头像按钮，返回发送者名（自己→"我"）。

    消息项结构：ListItemControl → PaneControl → ButtonControl(头像，Name=发送者昵称)。
    头像在右 = 自己发的，在左 = 对方发的。
    头像必须贴着消息项左右边缘；居中的按钮（如"查看更多消息"）不是头像，跳过。
    """
    try:
        item = m.BoundingRectangle
        item_mid = item.left + item.width() / 2
        edge = item.width() * 0.3  # 头像必须落在左右各 30% 的边缘区
        for c in m.GetChildren():  # 第 0 层：Pane
            for sub in c.GetChildren():  # 第 1 层：头像/气泡
                if sub.ControlType == 50000 and sub.Name:  # 候选按钮
                    r = sub.BoundingRectangle
                    on_left = r.right < item.left + edge   # 贴左边
                    on_right = r.left > item.right - edge  # 贴右边
                    if not (on_left or on_right):
                        continue  # 居中的按钮（如"查看更多消息"）不是头像
                    is_self = r.left > item_mid  # 右=自己
                    return "我" if is_self else sub.Name
    except (LookupError, COMError, TypeError):
        pass
    return None  # 系统行（查看更多消息等）没有头像


def _click_load_more(user_control) -> bool:
    """滚到消息列表顶部，真实鼠标点击"查看更多消息"按钮。点到了返回 True。

    注意：微信的"查看更多消息"按钮没接 UIA InvokePattern（invoke 成功返回但无效），
    只能先滚到列表顶把它拉进屏幕，再真实鼠标点击才能触发加载。
    """
    try:
        msg_win = user_control.ListControl(Name="消息")
        # ① 滚到列表最顶，把"查看更多消息"按钮拉进可视区
        try:
            scroll = msg_win.GetPattern(auto.PatternId.ScrollPattern)
            scroll.SetScrollPercent(0, 0)
            time.sleep(1)
        except Exception:
            pass  # 没有 ScrollPattern 就跳过，按钮可能已在可视区
        # ② 找按钮，点它的中心（必须已在屏幕内）
        user_control.Refind()
        msg_win = user_control.ListControl(Name="消息")
        for m in msg_win.GetChildren():
            if m.Name == "查看更多消息":
                r = m.BoundingRectangle
                cx, cy = r.left + r.width() // 2, r.top + r.height() // 2
                if cx <= 0 or cy <= 0:
                    continue  # 还在屏幕外，点不到
                auto.SetCursorPos(cx, cy)
                auto.Click(cx, cy)
                return True
        return False
    except (LookupError, COMError, TypeError):
        return False


def _load_more_history(user_control:WindowControl) -> bool:
    """点一次"查看更多消息"加载更多（不循环点到底）。返回是否确实加载了。"""
    try:
        activate_window(user_control, "ChatWnd", maximize=False)
        if _click_load_more(user_control):
            time.sleep(1.5)  # 等微信加载
            return True
        return False
    except (LookupError, COMError, TypeError):
        return False


def get_msg_list(user_control:WindowControl, load_more:bool=False):
    loaded_any = False
    if load_more:
        loaded_any = _load_more_history(user_control)  # 点一次加载更多
    msg_list=[]
    try:
        activate_window(user_control, "ChatWnd", maximize=False)
        msg_win = user_control.ListControl(Name="消息")
        for m in msg_win.GetChildren():
            if m.Name == "查看更多消息":
                continue  # 加载更多按钮不是真消息
            kids = m.GetChildren()
            if not kids:
                continue
            if kids[0].ControlType==50033:#PaneControl
                sender = _find_sender(m)
                if sender:
                    msg_list.append(f"[{sender}]：{m.Name}")
                else:
                    msg_list.append(m.Name)
            elif kids[0].ControlType==50020:#TextControl
                msg_list.append("[时间]："+m.Name)
            else:
                raise ToolError(f"聊天列表出现了未知的类型：{m.ControlType}")
    except Exception as e:
        raise ToolError(f"获取消息列表失败: {e}") from e
    # load_more=True 但没加载到更多（没有"查看更多消息"按钮/invoke 失败）→ 提示 + 全部消息一起返回
    if load_more and not loaded_any:
        return {"提示": "没有更多消息了", "全部消息": msg_list}
    return msg_list


# ============ 主页消息监听（monitorHomeChats 用的轻量读取）============

# 主页会话行右上角的时间/日期标签，判断"最后一条消息"时要排除，避免"10:30→昨天"这类误报
_TIME_LABEL_RE = re.compile(
    r"^(刚刚|昨天|前天|星期[一二三四五六日]|"
    r"\d{1,2}:\d{2}|"
    r"\d+分钟前|\d+小时前|\d+天前|\d+月前|\d+年前|"
    r"\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日)$")

_monitor_saved_rect = None  # 监听前微信窗口原始矩形，监听结束后还原


def _monitor_item_preview(item) -> str:
    """从主页会话项里取"最后一条消息"预览（排除未读徽标和时间标签，取最底部文本）。"""
    item_r = item.BoundingRectangle
    top_limit = item_r.top + item_r.height() * 0.6  # 徽标/时间在项的上半部
    texts = []
    for c, depth in auto.WalkControl(item, maxDepth=4):
        if c.ControlTypeName != 'TextControl' or not c.Name:
            continue
        nm = c.Name.strip()
        if not nm:
            continue
        r = c.BoundingRectangle
        if nm.isdigit() and r.top < top_limit:
            continue  # 未读徽标（右上角小数字）
        if _TIME_LABEL_RE.match(nm):
            continue  # 时间标签
        texts.append(nm)
    return texts[-1] if texts else ""


def monitor_setup():
    """监听开始：确保窗口可见，摆到"当前宽度 + 满高 + 靠右"（微信当前所在显示器）。记住原矩形。"""
    global _monitor_saved_rect
    hwnd = win32gui.FindWindow(CLASS_NAME, None)
    if not hwnd:
        raise ToolError("找不到微信主窗口，请确认微信已登录")
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    _monitor_saved_rect = win32gui.GetWindowRect(hwnd)
    monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    work = win32api.GetMonitorInfo(monitor)['Work']  # pywin32 键名是 'Work'，不是 API 结构体的 'rcWork'
    w = _monitor_saved_rect[2] - _monitor_saved_rect[0]  # 保持当前宽度
    x = work[2] - w  # 靠右
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, x, work[1], w,
                          work[3] - work[1], win32con.SWP_SHOWWINDOW)


def monitor_restore():
    """监听结束：把微信窗口还原到监听前的位置/大小。"""
    global _monitor_saved_rect
    if not _monitor_saved_rect:
        return
    hwnd = win32gui.FindWindow(CLASS_NAME, None)
    if hwnd:
        r = _monitor_saved_rect
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, r[0], r[1],
                              r[2] - r[0], r[3] - r[1], win32con.SWP_SHOWWINDOW)
    _monitor_saved_rect = None


def monitor_scan_once(after: str = "keep") -> dict:
    """扫描一次主页：滚到顶 + 读可见会话。

    after: 扫描后窗口处置 —— "keep"保持不动 / "minimize"最小化 / "hide"托盘隐藏(有风险)。
    返回 {会话名: {"最新消息": 预览, "未读数": n}}。
    """
    hwnd = win32gui.FindWindow(CLASS_NAME, None)
    if not hwnd:
        raise ToolError("微信主窗口不存在")
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    # 必须在当前线程新建 WindowControl：uiautomation 的 COM 不能跨线程用别的线程创建的控件
    win = auto.WindowControl(Name=WINDOW_NAME, ClassName=CLASS_NAME)
    win.SetActive()  # 滚轮滚动需要窗口在最前
    lst = win.ListControl(Name="会话")
    _scroll_to_top(lst)  # 滚动条滚到最上面（新消息会话会跳到顶部，保证可见）
    result = {}
    for item in lst.GetChildren():
        nm = item.Name
        if not nm:
            continue
        m = re.search(r"(\d+)条新消息$", nm)
        result[re.sub(r"\s*\d+条新消息$", "", nm)] = {
            "最新消息": _monitor_item_preview(item),
            "未读数": int(m.group(1)) if m else 0,
        }
    if after == "minimize":
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    elif after == "hide":
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
    return result

