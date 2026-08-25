import json
import os

from dotenv import load_dotenv
from fastmcp.exceptions import ToolError

from util.we_chat_utils import send_msg, _get_partner_control, get_msg_list


def sendPartnerMsg(user_name:str, msg:str="", call:str|None=None):
    return send_msg(_get_partner_control(user_name), msg, call)

def getPartnerMsgList(user_name:str, load_more:bool=False):
    return get_msg_list(_get_partner_control(user_name), load_more)


def get_recent_messages(user_name: str, n: int = 10) -> list[str]:
    """返回指定会话最近 n 条文本消息（时间标签不计入条数）。

    get_msg_list 返回的列表里穿插着"[时间]：xxx"的时间项，
    这里先过滤掉，再取尾部 n 条纯文本消息，保证语义连续。

    Args:
        user_name: 会话名称（用 listWeChatPartners 返回的完整名称）
        n: 返回的纯文本消息条数，默认 10
    """
    msgs = get_msg_list(_get_partner_control(user_name))
    texts = [m for m in msgs if not m.startswith("[时间]：")]
    return texts[-n:]


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



