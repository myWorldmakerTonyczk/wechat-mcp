import os
import winreg
from pathlib import Path


def _program_data_dir() -> Path:
    """取 ProgramData 目录。env 缺失时（MCP 子进程环境常被清掉）用 SystemDrive 兜底。"""
    d = os.environ.get('ProgramData') or os.environ.get('SystemDrive', 'C:') + '\\ProgramData'
    return Path(d)


def get_app_path(app_name):
    """按软件名找 exe 全路径。app_name: 如 'WeChat.exe'（不区分大小写）"""
    app_name_l = app_name.lower()

    # ① App Paths（Windows 官方"按名字找程序"机制）
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        key_path = rf'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app_name}'
        try:
            with winreg.OpenKey(hive, key_path) as k:
                p = winreg.QueryValueEx(k, '')[0]
                if p and os.path.exists(p):
                    return p
        except OSError:
            pass

    # ② 卸载信息：DisplayIcon(直接是exe) / InstallLocation(目录，拼exe名)
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for base in (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                     r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
            try:
                with winreg.OpenKey(hive, base) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        sub = winreg.EnumKey(key, i)
                        try:
                            with winreg.OpenKey(key, sub) as k:
                                # DisplayIcon：必须是【同名 exe】才算命中
                                try:
                                    v = winreg.QueryValueEx(k, 'DisplayIcon')[0]
                                except OSError:
                                    v = None
                                if v:
                                    cand = v.split(',')[0].strip('"')
                                    if (os.path.basename(cand).lower() == app_name_l
                                            and os.path.exists(cand)):
                                        return cand
                                # InstallLocation：目录拼上 exe 名，存在即命中
                                try:
                                    v = winreg.QueryValueEx(k, 'InstallLocation')[0]
                                except OSError:
                                    v = None
                                if v:
                                    cand = os.path.join(v.strip('"'), app_name)
                                    if os.path.exists(cand):
                                        return cand
                        except OSError:
                            pass
            except OSError:
                pass

    # ③ 开始菜单快捷方式（兜底，覆盖绿色软件）
    appdata = os.environ.get('APPDATA') or (os.environ.get('USERPROFILE')
                                            or os.environ.get('SystemDrive', 'C:') + '\\Users') + '\\AppData\\Roaming'
    for base in (_program_data_dir() / 'Microsoft/Windows/Start Menu/Programs',
                 Path(appdata) / 'Microsoft/Windows/Start Menu/Programs'):
        for lnk in base.rglob('*.lnk'):
            if app_name_l in lnk.stem.lower():
                return str(lnk)

    return None

def list_desktop_apps():
    """列出桌面应用的 exe 路径。

    只扫【桌面 】里的快捷方式，解析 .lnk 指向的真实 exe。
    """
    from comtypes.client import CreateObject

    wsh = CreateObject('WScript.Shell', dynamic=True)   # 解析 .lnk 需要
    by_path = {}                                        # path -> name（去重）

    system_drive = os.environ.get('SystemDrive', 'C:')
    userprofile = os.environ.get('USERPROFILE') or system_drive + '\\Users'
    appdata = os.environ.get('APPDATA') or userprofile + '\\AppData\\Roaming'
    public = os.environ.get('PUBLIC') or system_drive + '\\Users\\Public'
    dirs = [
        Path(appdata) / 'Microsoft/Windows/Start Menu/Programs',
        _program_data_dir() / 'Microsoft/Windows/Start Menu/Programs',
        Path(userprofile) / 'Desktop',                 # 我的桌面
        Path(public) / 'Desktop',                      # 公共桌面
    ]
    for d in dirs:
        if not d.exists():
            continue
        for lnk in d.rglob('*.lnk'):
            try:
                target = wsh.CreateShortcut(str(lnk)).TargetPath
            except Exception:
                continue
            if target.lower().endswith('.exe') and os.path.exists(target):
                by_path.setdefault(target, lnk.stem)    # 同路径只留第一个名字

    return by_path


