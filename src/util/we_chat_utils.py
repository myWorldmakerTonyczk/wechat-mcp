import os
import subprocess
import time

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

#列出首页当前可见的会话名称（轻量，快，不滚动）
@retry(retry_num=2)
def list_home_chats():
    activate_window(win_weChat, CLASS_NAME)
    win1 = win_weChat.ListControl(Name="会话")
    children = win1.GetChildren()
    restore_small_window(CLASS_NAME)
    return [i.Name for i in children if i.Name]

#列出全部会话名称（回滚到顶 + 滚动收集，慢但全）
@retry(retry_num=2)
def list_user():
    activate_window(win_weChat, CLASS_NAME)
    lst = win_weChat.ListControl(Name="会话")
    # ① 回滚到顶部：连续 2 轮第一个项名字不变 = 到顶，停止
    prev_first = None
    stable = 0
    for _ in range(50):  # 最多 50 次防死循环
        items = lst.GetChildren()
        first = items[0].Name if items else None
        if first == prev_first:  # 第一项没变，可能到顶了
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        prev_first = first
        lst.WheelUp(wheelTimes=10, interval=0.01)
        time.sleep(0.2)
    # ② 从顶部向下滚动收集
    seen = set()
    empty_rounds = 0
    for _ in range(60):  # 最多 60 轮防死循环
        # 收集当前可见
        for item in lst.GetChildren():
            name = item.Name
            if name and name not in seen:
                seen.add(name)
        # 动态测当前框高，滚半屏（方案二：校准）
        hs = [it.BoundingRectangle.height() for it in lst.GetChildren()
              if it.BoundingRectangle.height() > 0]
        item_h = sum(hs) / len(hs) if hs else 96
        view_h = lst.BoundingRectangle.height()
        target_px = max(view_h // 2, item_h)
        clicks = max(1, round(target_px / 25))  # 每格按 25px 粗估，保守
        lst.WheelDown(wheelTimes=clicks, interval=0.03)
        time.sleep(0.4)
        # ③ 校准：滚动后有无新增
        changed = False
        for item in lst.GetChildren():
            name = item.Name
            if name and name not in seen:
                seen.add(name)
                changed = True
        if changed:
            empty_rounds = 0
        else:
            empty_rounds += 1
            if empty_rounds >= 3:
                break
    restore_small_window(CLASS_NAME)
    return sorted(seen)

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
    try:
        time.sleep(1)
        win_user = win_weChat.ListControl(Name="会话").ListItemControl(Name=user_name)
        win_user.DoubleClick(simulateMove=False)
    except (LookupError, COMError, TypeError):
        # 对照实验发现：聊天窗口已存在时，ListItem 几何信息被微信吞掉(rect=0×0)，
        # DoubleClick 抛 TypeError。此时窗口其实已打开，直接匹配聊天窗口兜底。
        window_control = _find_chat_window(user_name)
        window_control.SetActive()
        return window_control
    # DoubleClick 成功，匹配聊天窗口
    return _find_chat_window(user_name)


def _get_partner_control(user_name:str):
    try:
        win_chat_user=auto.WindowControl(RegexName=f".*{clean_conv_name(user_name)}.*",ClassName="ChatWnd")
        return win_chat_user
    except (LookupError,COMError) as e:
        raise ToolError(f"搜索后未找到会话 [{clean_conv_name(user_name)}]: {e}") from e


def send_msg(msg:str,user_control:WindowControl):
    try:
        activate_window(user_control, "ChatWnd", maximize=False)
        input_win=user_control.EditControl(Name="输入")
        input_win.SetFocus()
        input_win.Click(simulateMove=False)
        input_win.SendKeys(text=msg)
        user_control.ButtonControl(Name="发送(S)").Click(simulateMove=False)
    except Exception as e:
        raise ToolError(f"发送消息失败: {e}") from e
    # 发送成功后验证是否真的发出去了
    if get_msg_list(user_control)[-1]==msg:
        return True
    else:
        raise ToolError("消息发送后未在聊天记录中匹配到，可能未成功发送")

def get_msg_list(user_control:WindowControl):
    msg_list=[]
    try:
        activate_window(user_control, "ChatWnd", maximize=False)
        msg_win = user_control.ListControl(Name="消息")
        for m in msg_win.GetChildren():
            kids = m.GetChildren()
            if not kids:
                continue
            if kids[0].ControlType==50033:#PaneControl
                msg_list.append(m.Name)
            elif kids[0].ControlType==50020:#TextControl
                msg_list.append("[时间]："+m.Name)
            else:
                raise ToolError(f"聊天列表出现了未知的类型：{m.ControlType}")
    except Exception as e:
        raise ToolError(f"获取消息列表失败: {e}") from e
    return msg_list

