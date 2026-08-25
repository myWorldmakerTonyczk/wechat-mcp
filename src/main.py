import json
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.tools import tool


from service.service import get_app_path as get_app_path_l
from service.service import list_desktop_apps as list_desktop_apps_l
from service.utilService import (sendPartnerMsg, getPartnerMsgList,
                                 get_recent_messages as get_recent_messages_l,
                                 get_cached_list)
from util.utils import setDenv
from util.we_chat_utils import (open_wechat, list_user, list_home_chats,
                                list_contacts, find_user, search_wechat, send_msg)

mcp = FastMCP("use_weChat",instructions=
                                        """
                                        这个工具能操控windows的微信

                                        【打开微信】
                                        openWeChat 打开微信（默认读配置 WE_CHAT_PATH）。失败时依次尝试：
                                          (i) list_desktop_apps 列出桌面应用路径，找到微信
                                          (ii) get_app_path 按名字查微信 exe 路径
                                          (iii) changeEnv 改配置（重要！非必要别自己动，让用户改）
                                          (iv) 重新 openWeChat

                                        【拿会话列表】三者选一，别搞混：
                                          listHomeChats      → 只要主页当前可见的（快，不滚动）
                                          listWeChatPartners → 要全部会话（慢，全量滚动扫描）
                                          getCachedList      → 要上次扫描的缓存（秒回，可能过期；kind="partners"）

                                        【拿联系人】：
                                          listWeChatContacts → 全量联系人（慢）
                                          getCachedList      → 缓存（秒回；kind="contacts"）
                                          searchWeChat      → 用微信自带搜索框搜关键字（联系人/群聊/公众号，支持拼音，快）

                                        【操作某个会话】必须先拿到会话名：
                                          1. listWeChatPartners 或 getCachedList 拿会话名
                                          2. openPartnerWindow 打开该会话窗口
                                          3. 之后才能 sendMsg / get_msg_list / get_recent_messages
                                        sendMsg：call=None 发文本 msg；call="voice"/"video" 发起语音/视频通话；call="hangup" 挂断当前通话

                                        【读消息】：
                                          get_msg_list        → 全量消息（含"[时间]："标签）；load_more=True 会先点"查看更多消息"把历史拉满
                                          get_recent_messages → 最近 n 条纯文本（适合监控，n 默认 10）

                                        【找其他软件】list_desktop_apps 列出全部；get_app_path 按名字查。
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
    同时把列表 JSON 序列化写入 .env 的 WE_CHAT_PARTNERS_LIST，便于复用。

    Returns:
        全部会话名称列表（已排序）
    """
    partners = list_user()
    setDenv("WE_CHAT_PARTNERS_LIST", json.dumps(partners, ensure_ascii=False))
    return partners



@mcp.tool(run_in_thread=False)
def openPartnerWindow(userName:str) :
    """
    通过方法listWeChatUsers可以找到名称，然后将那里的名称填入这个函数，可以打开具体用户的对话窗口

    Args:
        userName:会话名称，有的会话名称如“祥发-已置顶”请填入全名，不要填“祥发”
    """
    find_user(userName)

@mcp.tool(run_in_thread=False)
def searchWeChat(keyword: str) ->list[str]:
    """
    在微信主窗口的搜索框搜索关键字，返回搜索结果（联系人/群聊/公众号等）。和 openPartnerWindow 一样的搜索框流程。

    Args:
        keyword:要搜索的关键字

    Returns:
        搜索结果名称列表（带名字的结果项）
    """
    return search_wechat(keyword)


@mcp.tool(run_in_thread=False)
def sendMsg(userName:str, msg:str="", call:Literal["voice","video","hangup"]|None=None):
    """
    向特定已经打开的会话窗口发送消息或操作通话（需要先用openPartnerWindow打开特定窗口）

    Args:
        userName:会话名称，有的会话名称如“祥发-已置顶”请填入全名，不要填“祥发”，（通过方法listWeChatPartners获取）
        msg:需要发送的文本内容（call 为空时用）
        call:为"voice"发起语音通话；为"video"发起视频通话；为"hangup"挂断当前通话；为None发文本msg
    """
    return sendPartnerMsg(userName, msg, call)
@mcp.tool(run_in_thread=False)
def get_msg_list(userName:str, load_more:bool=False)->list[str]|dict:
    """
    获取已经打开窗口的用户会话的消息列表(若窗口未打开使用openPartnerWindow)

    Args:
        userName:会话名称，有的会话名称如“祥发-已置顶”请填入全名，不要填“祥发”，（通过方法listWeChatPartners获取）
        load_more:为True时先尝试把“查看更多消息”按钮点到底、加载全部历史。

    Returns:
        消息列表，每条带发送者前缀，如“[我]：你好”/“[祥发-]：视频通话 未应答”，
        穿插时间标签如：“[时间]：5分钟前”。
        load_more=True 且无更多历史时返回字典 {"提示":"没有更多消息了","全部消息":[...]}，
        其中“全部消息”就是全部消息列表
    """
    return getPartnerMsgList(userName, load_more)

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

@mcp.tool(run_in_thread=False)
def listWeChatContacts() ->list[str]:
    """
    扫描微信通讯录全部联系人（切到通讯录页 + 滚动收集）。较慢但完整。
    同时把列表 JSON 序列化写入 .env 的 WE_CHAT_CONTACTS_LIST，便于复用。

    Returns:
        全部联系人名称列表（已排序）
    """
    contacts = list_contacts()
    setDenv("WE_CHAT_CONTACTS_LIST", json.dumps(contacts, ensure_ascii=False))
    return contacts

@mcp.tool(run_in_thread=False)
def getCachedList(kind: Literal["partners", "contacts"]) ->list[str]:
    """
    读取上次全量扫描缓存在 .env 的列表（JSON 数组），比重新全量滚动扫描快得多。

    Args:
        kind: "partners" 读会话列表缓存（listWeChatPartners 的）；
              "contacts" 读联系人列表缓存（listWeChatContacts 的）

    Returns:
        上次扫描到的名称列表（已排序）
    """
    return get_cached_list(kind)

if __name__ == "__main__":
    mcp.run(transport="stdio")