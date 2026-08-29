import json
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.tools import tool


from service.service import get_app_path as get_app_path_l
from service.service import list_desktop_apps as list_desktop_apps_l
from service.utilService import (sendPartnerMsg, getPartnerMsgList,
                                 get_cached_list,
                                 monitor_start as monitor_start_l,
                                 monitor_poll as monitor_poll_l)
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

                                        【拿会话列表】：
                                          listHomeChats(full_scan=False) → 主页当前可见会话（快，含 名称/未读数/最后一条消息）
                                          listHomeChats(full_scan=True)  → 全部会话（慢，滚动全扫，同样带信息）
                                          getCachedList("partners")      → 上次全量扫描的缓存会话名（秒回，可能过期）

                                        【拿联系人】：
                                          listWeChatContacts → 全量联系人（慢）
                                          getCachedList("contacts") → 缓存（秒回）
                                          searchWeChat      → 用搜索框搜关键字（联系人/群聊/公众号，支持拼音，快）

                                        【读/发消息】先拿到会话名（listHomeChats/getCachedList）：
                                          get_msg_list(userName, load_more, recent) → 读会话消息，窗口没开会自动打开
                                            recent=N 只要最近 N 条纯文本（去时间标签）；0=全量（含"[时间]："标签）
                                            load_more=True 每次点一次"查看更多消息"加载更早的一批
                                          sendMsg(userName, msg, call) → 发文本/语音视频通话/挂断；需要窗口已开（先 get_msg_list 或 openPartnerWindow）
                                          openPartnerWindow(userName) → 显式打开会话窗口（get_msg_list 已自动开，一般不必手动调）

                                        【监听主页新消息】：
                                          monitorStart(duration, interval, after) → 启动后台监听（秒回）；返回"初始未读"（当前有未读的会话）
                                            duration 监听秒数；interval 刷新间隔(建议≥3)；after 窗口处置 keep/minimize/hide
                                          monitorPoll(stop=False) → 查状态+累计变化（秒回）
                                            有变化会自动停止监听并清空本次变化（agent 要操作窗口，避免打架）；stop=True 强制立刻停
                                          monitorHomeChats 是 monitorStart 的兼容别名
                                          注意：MCP 单次调用有 60s 超时，别用长阻塞；监听用 start+poll 组合。

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
def listHomeChats(full_scan:bool=False) ->list[dict]:
    """
    列出微信主页的会话（每个会话含 名称/新消息/最后一条消息）。

    Args:
        full_scan: False=只要当前可见的（快，不滚动）；True=全量滚动扫描全部会话（慢，和 listWeChatPartners 一样）

    Returns:
        每个会话一条：{"名称":会话名, "新消息":未读数(0=无), "最后一条消息":消息预览}
    """
    return list_home_chats(full_scan)

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
def get_msg_list(userName:str, load_more:bool=False, recent:int=10)->list[str]|dict:
    """
    获取已经打开窗口的用户会话的消息列表(若窗口未打开使用openPartnerWindow)

    Args:
        userName:会话名称，有的会话名称如”祥发-已置顶”请填入全名，不要填”祥发”，（通过方法listWeChatPartners获取）
        load_more:为True时先点一次”查看更多消息”加载更多（每次调用加载一批）。
        recent:最近 N 条纯文本消息（时间标签不计入条数）；0=返回全部消息（含时间标签）(目前已经加载的全部消息，load_more可加载更多)。

    Returns:
        recent=0：消息列表，每条带发送者前缀，如”[我]：你好”/”[祥发-]：视频通话 未应答”，
          穿插时间标签如：”[时间]：5分钟前”。
          load_more=True 且无更多历史时返回字典 {“提示”:”没有更多消息了”,”全部消息”:[...]}，
          其中”全部消息”就是全部消息列表
        recent>0：最近 N 条纯文本消息（去掉时间标签，语义连续）
    """
    return getPartnerMsgList(userName, load_more, recent)


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
def changeEnv(env_name: Literal["WE_CHAT_PATH"], value:str)->None:
    """
    更换或设置env配置文件中的值(重要！！！！，非必要时不要自己操作,让用户操作)

    Args:
        env_name:配置项的名称（目前只有“WE_CHAT_PATH”）
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

@mcp.tool(run_in_thread=False)
def monitorStart(duration: float = 120, interval: float = 5,
                 after: Literal["keep", "minimize", "hide"] = "keep") -> dict:
    """
    启动后台监听微信主页会话的最新消息变化（秒回，不阻塞）。

    Args:
        duration: 监听总时长（秒），默认 120。到点自动结束。
        interval: 刷新间隔（秒），默认 5。每次扫描约需 1~2 秒，太短没意义，建议 ≥3。
        after: 每次扫描后窗口怎么处置 —— "keep"保持不动(推荐) / "minimize"最小化 / "hide"托盘隐藏(有风险)。

    Returns:
        立即返回 {"状态": "监听已启动", "初始未读": 首轮就带未读标签的会话列表, ...}。
        之后用 monitorPoll 查累计变化，monitorStop 中途停止。
    """
    return monitor_start_l(duration, interval, after)


@mcp.tool(run_in_thread=False)
def monitorHomeChats(duration: float = 1200, interval: float = 10,
                     after: Literal["keep", "minimize", "hide"] = "keep") -> dict:
    """
    【兼容旧名】等价于 monitorStart：启动后台监听微信主页会话的最新消息变化（秒回，不阻塞）。

    Args:
        duration: 监听总时长（秒），默认 1200。到点自动结束。
        interval: 刷新间隔（秒），默认 10。每次扫描约需 1~2 秒，太短没意义，建议 ≥3。
        after: 每次扫描后窗口怎么处置 —— "keep"保持不动(推荐) / "minimize"最小化 / "hide"托盘隐藏(有风险)。

    Returns:
        立即返回 {"状态": "监听已启动", "初始未读": 首轮就带未读标签的会话列表, ...}。
        之后用 monitorPoll 查累计变化，monitorStop 中途停止。
    """
    return monitor_start_l(duration, interval, after)


@mcp.tool(run_in_thread=False)
def monitorPoll(stop: bool = False) -> dict:
    """
    查询后台监听状态 + 累计变化（秒回）。

    stop=False（默认）：只查询；若有变化且监听仍在跑，会自动停止监听并清空本次已返回的变化，
    避免 agent 操作窗口时与监听线程打架、也避免已处理消息残留。
    stop=True：立刻强制停止监听（即使还没有变化）。

    Returns:
        {"状态": "监听中"/"已结束"/"已自动停止"/"已停止", "剩余秒数": N, "累计变化": [...], "监控会话数": N, "错误": None/str}
    """
    return monitor_poll_l(stop)


if __name__ == "__main__":
    mcp.run(transport="stdio")