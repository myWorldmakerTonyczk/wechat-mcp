from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import tool


from service.service import get_app_path as get_app_path_l
from service.service import list_desktop_apps as list_desktop_apps_l
from service.utilService import sendPartnerMsg, getPartnerMsgList, get_recent_messages as get_recent_messages_l
from util.utils import setDenv
from util.we_chat_utils import open_wechat, list_user, list_home_chats, find_user, send_msg

mcp = FastMCP("use_weChat",instructions=
                                        """
                                        这个工具能操控windows的微信
                                        
                                        【操作流程】
                                        1，一般来说配置文件里有WE_CHAT_PATH，可以直接调用openWeChat打开软件，若失败，可以尝试：
                                                (i)调用list_desktop_apps列出桌面存在软件的路径，在其中找到微信的路径
                                                (ii)使用changeEnv更改配置文件中微信的路径名称
                                                (iii)openWeChat打开微信
                                        2，打开微信主页面后，若需要查看已存在的会话，调用listWeChatPartners
                                        3，一发送，接收消息的操作，必须先打开具体会话窗口，通过调用listWeChatPartners获取目标会话名称后，可以使用openPartnerWindow来打开这个窗口
                                        4，打开具体的会话窗口后，就可以调用sendMsg或get_msg_list来进行操作
                                        5,get_msg_list是全量查询，先get_msg_list后可以使用get_recent_messages获得一部分聊天记录，适合更新消息
                                        """
              )

@mcp.tool(run_in_thread=False)
def openWeChat(path:str|None=None):
    """
    打开微信，填入其他软件路径则打开其余软件（默认空参打开微信，配置文件已经写入微信地址）

    Args:
        path:应用路径，不填则默认打开微信
    """
    if path is None or path =="":
        return open_wechat()
    else:
        return open_wechat(path)

@mcp.tool(run_in_thread=False)
def listHomeChats() ->list[str]:
    """
    列出微信主页当前可见的会话名称（轻量，快）。只包含当前屏幕上渲染的会话，不滚动。

    Returns:
        当前可见会话名称列表
    """
    return list_home_chats()

@mcp.tool(run_in_thread=False)
def listWeChatPartners() ->list[str]:
    """
    列出微信全部会话名称（全量扫描，回滚到顶部后滚动收集）。较慢但完整。

    Returns:
        全部会话名称列表（已排序）
    """
    return list_user()

@mcp.tool(run_in_thread=False)
def openPartnerWindow(userName:str) :
    """
    通过方法listWeChatUsers可以找到名称，然后将那里的名称填入这个函数，可以打开具体用户的对话窗口

    Args:
        userName:会话名称，有的会话名称如“祥发-已置顶”请填入全名，不要填“祥发”
    """
    find_user(userName)


@mcp.tool(run_in_thread=False)
def sendMsg(msg:str,userName:str):
    """
    向特定已经打开的会话窗口发送消息（需要先用openPartnerWindow打开特定窗口）

    Args:
        msg:需要发送的内容
        userName:会话名称，有的会话名称如“祥发-已置顶”请填入全名，不要填“祥发”，（通过方法listWeChatPartners获取）
    """
    return sendPartnerMsg(msg,userName)
@mcp.tool(run_in_thread=False)
def get_msg_list(userName:str)->list[str]:
    """
    获取已经打开窗口的用户会话的消息列表(若窗口未打开使用openPartnerWindow)

    Args:
        userName:会话名称，有的会话名称如“祥发-已置顶”请填入全名，不要填“祥发”，（通过方法listWeChatPartners获取）

    Returns:
        返回值为消息列表，其中穿插时间标签如：“[时间]：5分钟前”为消息发送的时间
    """
    return getPartnerMsgList(userName)

@mcp.tool(run_in_thread=False)
def get_recent_messages(userName:str, n:int=10)->list[str]:
    """
    获取指定会话最近 n 条文本消息（时间标签不计入条数）。适合监控/查看最新对话。

    Args:
        userName:会话名称，有的会话名称如“祥发-已置顶”请填入全名，不要填“祥发”，（通过方法listWeChatPartners获取）
        n:返回的纯文本消息条数，默认 10

    Returns:
        最近 n 条消息列表（不含"[时间]："时间项），时间升序，末尾是最新的
    """
    return get_recent_messages_l(userName, n)

@mcp.tool(run_in_thread=False)
def list_desktop_apps()->dict[Any,Any]:
    """
    列出桌面应用的 exe 路径。只扫【桌面，菜单栏】里的快捷方式，解析 .lnk 指向的真实 exe。

    """
    return list_desktop_apps_l()

@mcp.tool(run_in_thread=False)
def get_app_path(app_name:str):
    """
    按软件名找 exe 全路径。优先使用list_desktop_apps列出应用列表

    Args:
        app_name: 需要查询app的名称，如 'WeChat.exe'（不区分大小写）

    """
    return get_app_path_l(app_name)

@mcp.tool(run_in_thread=False)
def changeEnv(env_name:str, value:str)->None:
    """
    更换或设置env配置文件中的值(重要！！！！，非必要时不要自己操作,让用户操作)

    Args:
        env_name:配置项的名称（目前有“WE_CHAT_PATH”）
        value:填入的值
    """
    setDenv(env_name, value)

if __name__ == "__main__":
    mcp.run(transport="stdio")