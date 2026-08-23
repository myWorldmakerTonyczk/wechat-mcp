from util.we_chat_utils import send_msg, _get_partner_control, get_msg_list


def sendPartnerMsg(msg:str,user_name:str):
    return send_msg(msg,_get_partner_control(user_name))

def getPartnerMsgList(user_name:str):
    return get_msg_list(_get_partner_control(user_name) )


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



