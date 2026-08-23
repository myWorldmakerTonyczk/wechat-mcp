import time

import uiautomation as auto
from dotenv import set_key


def retry(retry_num=2,recover=None):
    def deco(fn):
        def wrapper(*args, **kwargs):
            for i in range(retry_num):
                try:
                    value = fn(*args, **kwargs)
                    return value
                except Exception as e:
                    if i == retry_num - 1:
                        raise
                    if recover:
                        recover()
                    else:
                        time.sleep(0.5)
        return wrapper
    return deco

def dump_tree(win, max_depth=30, include_top=True, show_rect=False, show_id=True):
    """格式化输出控件树，返回字符串（agent tool 直接返回这个）。

    比 rprint(*tree) 安全：rprint 会 *tree 解包整个生成器，
    微信这种几百个节点的树直接刷屏/内存爆炸。这个按行逐条拼。
    """
    lines = []
    for c, depth in auto.WalkControl(win, includeTop=include_top, maxDepth=max_depth):
        indent = '  ' * depth
        name = c.Name
        cls = c.ClassName
        # 名字/类名都空时给个标记，别显示成裸类型
        tag = name or (f'<{cls}>' if cls else '')
        line = f'{indent}[d{depth}] {c.ControlTypeName} {tag}'.rstrip()
        if show_id and c.AutomationId:
            line += f'  [id={c.AutomationId}]'
        if show_rect:
            r = c.BoundingRectangle
            line += f'  {r}'
        lines.append(line)
    text = '\n'.join(lines)
    print(text)
    return text


def clean_conv_name(name: str) -> str:
    """去掉微信加在会话显示名上的标记后缀（已置顶/免打扰等）。"""
    return (name.replace('已置顶', '')
            .replace('免打扰', '')
            .strip())

def setDenv(envName:str, value:str):
    set_key(".env",envName,value)