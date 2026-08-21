from typing import Any

from fastmcp import FastMCP
from fastmcp.tools import tool
import uiautomation as auto
from service import get_app_path as get_app_path_l
from service import list_desktop_apps as list_desktop_apps_l

mcp = FastMCP("use_weChat")




@tool
def list_desktop_apps()->dict[Any,Any]:
    """
    列出桌面应用的 exe 路径。只扫【桌面，菜单栏】里的快捷方式，解析 .lnk 指向的真实 exe。

    """
    return list_desktop_apps_l()

@tool
def get_app_path(app_name):
    """
    按软件名找 exe 全路径。优先使用list_desktop_apps列出应用列表

    Args:
        app_name: 需要查询app的名称，如 'WeChat.exe'（不区分大小写）

    """
    return get_app_path_l(app_name)