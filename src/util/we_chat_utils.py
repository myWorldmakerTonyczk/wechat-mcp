import os
import subprocess

from dotenv import load_dotenv
from uiautomation import Control
import uiautomation as auto

from src.util.utils import clean_conv_name

load_dotenv(override=True)
WE_CHAT_PATH = os.getenv("WE_CHAT_PATH")

win_weChat = auto.WindowControl(Name="微信",ClassName="WeChatMainWndForPC")
#打开微信
def open_wechat(path:str|None = WE_CHAT_PATH):
    if path is None:
        raise ValueError("微信可执行文件路径缺失，请传入 path 或设置 WE_CHAT_PATH")
    try:
        subprocess.Popen(path)
    except Exception as e:
        print("微信启动失败",e)
    try:
        win_weChat=auto.Control(Name="微信", ClassName="WeChatLoginWndForPC")
        win_weChat.SetFocus()
        win_weChat.ButtonControl(Name="进入微信").Click(simulateMove=False)
    except Exception as e:
        print(f"窗口可能未正确打开，可能未正确匹配窗口控件")


def list_user():
    win_weChat.Refind()
    win1 = win_weChat.ListControl(Name="会话")
    children =win1.GetChildren()
    user_list = [i.Name for i in children]
    return user_list

def find_user(user_name:str):
    win_weChat.Refind()
    win_weChat.SetActive()
    win_chat = win_weChat.ButtonControl(Name="聊天")
    win_chat.Click(simulateMove=False)

    win_search = win_weChat.EditControl(Name="搜索")
    win_search.Click(simulateMove=False)
    win_search.SendKeys('{Ctrl}a')  # 全选
    win_search.SendKeys('{Delete}')  # 删掉
    win_search.SendKeys(clean_conv_name(user_name))
    win_search.SendKeys('{Enter}')

    win_user = win_weChat.ListControl(Name="会话").ListItemControl(Name=user_name)
    win_user.DoubleClick(simulateMove=False)

find_user("祥发-已置顶")


