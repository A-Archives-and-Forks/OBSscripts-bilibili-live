#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
B站直播推流获取工具 (独立版)
功能：
- 账户管理（保存/选择/删除账户）
- 扫码登录，完整 Cookie 提取
- 自动检测直播间直播状态，支持停止当前直播
- 开播时根据平台自动设置 User-Agent 和额外参数
- 详细日志输出（请求/响应 Headers、Params、Body、Cookies）
- 推流地址复制到剪贴板
依赖：requests, qrcode, pyperclip
安装：pip install requests qrcode pyperclip
"""

import sys
import json
import time
import hashlib
import uuid
from typing import Dict, Any
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from datetime import datetime

import requests
import pyperclip
from qrcode.main import QRCode
from qrcode.constants import ERROR_CORRECT_L

# ---------- 全局配置 ----------
VERBOSE = True  # 打印详细日志（其他部分）

# ---------- 配置文件管理 ----------
def get_config_dir() -> Path:
    script_dir = Path(__file__).parent
    config_dir = script_dir / "bili_live_cli_config"
    config_dir.mkdir(exist_ok=True)
    return config_dir

def get_accounts_file() -> Path:
    return get_config_dir() / "accounts.json"

def load_accounts() -> Dict[str, Any]:
    file_path = get_accounts_file()
    if not file_path.exists():
        return {"accounts": {}, "default_user": None}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"accounts": {}, "default_user": None}

def save_accounts(data: Dict[str, Any]) -> None:
    with open(get_accounts_file(), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_default_account() -> str:
    return load_accounts().get("default_user")

def set_default_account(user_id: str) -> None:
    data = load_accounts()
    data["default_user"] = user_id
    save_accounts(data)

def get_all_accounts() -> Dict[str, Dict]:
    return load_accounts().get("accounts", {})

def save_account_cookies(user_id: str, cookies: Dict[str, str], nickname: str = "") -> None:
    data = load_accounts()
    if "accounts" not in data:
        data["accounts"] = {}
    user_data = data["accounts"].get(user_id, {})
    user_data["cookies"] = cookies
    user_data["nickname"] = nickname or f"用户{user_id}"
    data["accounts"][user_id] = user_data
    if data.get("default_user") is None:
        data["default_user"] = user_id
    save_accounts(data)

def delete_account(user_id: str) -> bool:
    data = load_accounts()
    if user_id not in data.get("accounts", {}):
        return False
    del data["accounts"][user_id]
    if data.get("default_user") == user_id:
        data["default_user"] = list(data["accounts"].keys())[0] if data["accounts"] else None
    save_accounts(data)
    return True

def get_account_cookies(user_id: str) -> Dict[str, str]:
    data = load_accounts()
    accounts = data.get("accounts", {})
    return accounts.get(user_id, {}).get("cookies", {})

def get_account_nickname(user_id: str) -> str:
    data = load_accounts()
    accounts = data.get("accounts", {})
    return accounts.get(user_id, {}).get("nickname", f"用户{user_id}")

# ---------- 工具函数 ----------
def print_qr_ascii(data: str) -> None:
    qr = QRCode(version=1, box_size=2, border=2, error_correction=ERROR_CORRECT_L)
    qr.add_data(data)
    qr.make(fit=True)
    qr.print_ascii(tty=False, invert=False)

def parse_cookie(cookie_str: str) -> Dict[str, str]:
    cookie_dict = {}
    for pair in cookie_str.split(';'):
        pair = pair.strip()
        if not pair or '=' not in pair:
            continue
        k, v = pair.split('=', 1)
        cookie_dict[k.strip()] = v.strip()
    return cookie_dict

def dict_to_cookie_string(data_dict: Dict[str, Any]) -> str:
    return "; ".join([f"{k}={v}" for k, v in data_dict.items()])

def log_request(title: str, method: str, url: str, headers: Dict, params: Dict = None, data: Any = None):
    if not VERBOSE:
        return
    print(f"\n[{title}] {method} {url}")
    if headers:
        print(f"[{title}] Headers: {json.dumps(dict(headers), indent=2, ensure_ascii=False)}")
    if params:
        print(f"[{title}] Params: {json.dumps(params, indent=2, ensure_ascii=False)}")
    if data:
        print(f"[{title}] Data: {json.dumps(data, indent=2, ensure_ascii=False)}")

def log_response(title: str, response: requests.Response):
    if not VERBOSE:
        return
    print(f"[{title}] Status: {response.status_code}")
    print(f"[{title}] Headers: {json.dumps(dict(response.headers), indent=2, ensure_ascii=False)}")
    set_cookie = response.headers.get('Set-Cookie', '')
    if set_cookie:
        print(f"[{title}] Set-Cookie: {set_cookie}")
    print(f"[{title}] Cookies (from response.cookies): {response.cookies.get_dict()}")
    content = response.text[:500] if response.text else ''
    if content:
        print(f"[{title}] Body preview: {content}...")

# ---------- B站 API 类 ----------
class BilibiliLogInRegister:
    def __init__(self, headers: Dict[str, str], verify_ssl: bool = True):
        self.headers = headers
        self.verify_ssl = verify_ssl

    def generate(self) -> Dict[str, Any]:
        api = 'https://passport.bilibili.com/x/passport-login/web/qrcode/generate'
        try:
            resp = requests.get(api, headers=self.headers, verify=self.verify_ssl, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') != 0:
                return {'success': False, 'error': data.get('message', '未知错误')}
            return {'success': True, 'data': data['data']}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def poll(self, qrcode_key: str, verbose: bool = True) -> Dict[str, Any]:
        """
        轮询扫码状态
        :param qrcode_key: 二维码密钥
        :param verbose: 是否打印详细的请求和响应日志（即使状态无变化也打印）
        """
        api = f'https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key={qrcode_key}'
        if verbose:
            log_request("Poll", "GET", api, self.headers)
        try:
            resp = requests.get(api, headers=self.headers, verify=self.verify_ssl, timeout=10)
            resp.raise_for_status()
            if verbose:
                log_response("Poll", resp)
            data = resp.json()
            return {'success': True, 'data': data.get('data', {})}
        except Exception as e:
            if verbose:
                print(f"[Poll Error] {e}")
            return {'success': False, 'error': str(e)}

class BilibiliApiGeneric:
    def __init__(self, headers: Dict[str, str], verify_ssl: bool = True):
        self.headers = headers
        self.verify_ssl = verify_ssl

    def get_room_info_old(self, mid: int) -> Dict[str, Any]:
        api = "https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld"
        params = {"mid": mid}
        try:
            resp = requests.get(api, headers=self.headers, params=params, verify=self.verify_ssl, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') != 0:
                return {'success': False, 'error': data.get('message', '未知错误')}
            return {'success': True, 'data': data.get('data', {})}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_room_base_info(self, room_id: int) -> Dict[str, Any]:
        api = "https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo"
        params = {"req_biz": "web_room_componet", "room_ids": room_id}
        try:
            resp = requests.get(api, headers=self.headers, params=params, verify=self.verify_ssl, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') != 0:
                return {'success': False, 'error': data.get('message', '未知错误')}
            by_room_ids = data.get('data', {}).get('by_room_ids', {})
            if not by_room_ids:
                return {'success': False, 'error': '未找到房间信息'}
            room_info = next(iter(by_room_ids.values()), None)
            if not room_info:
                return {'success': False, 'error': '房间信息为空'}
            return {'success': True, 'data': room_info}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def get_area_list(self) -> Dict[str, Any]:
        api = "https://api.live.bilibili.com/room/v1/Area/getList"
        try:
            resp = requests.get(api, headers=self.headers, verify=self.verify_ssl, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') != 0:
                return {'success': False, 'error': data.get('message', '未知错误')}
            return {'success': True, 'data': data.get('data', [])}
        except Exception as e:
            return {'success': False, 'error': str(e)}

class BilibiliCSRFAuthenticator:
    def __init__(self, headers: Dict[str, str], verify_ssl: bool = True):
        self.headers = headers
        self.verify_ssl = verify_ssl
        self.cookie = headers.get('cookie', '')
        self.cookies = parse_cookie(self.cookie)
        self.csrf = self.cookies.get('bili_jct', '')
        self.user_id = self.cookies.get('DedeUserID', '')
        self.buvid3 = self.cookies.get('buvid3', '')

    def start_live(self, room_id: int, area_id: int, platform: str = "pc_link", build: str = "10819", version: str = "7.64.0.10819") -> Dict[str, Any]:
        """
        开播请求，支持额外参数，模拟官方客户端行为
        """
        api = "https://api.live.bilibili.com/room/v1/Room/startLive"
        headers = self.headers.copy()
        csrf = self.csrf
        ts = str(int(time.time()))

        data = {
            "access_key": "",
            "appkey": "aae92bc66f3edfab",
            "platform": platform,
            "room_id": room_id,
            "area_v2": area_id,
            "build": build,
            "backup_stream": 0,
            "csrf": csrf,
            "csrf_token": csrf,
            "ts": ts,
            "type": 2,
            "version": version,
        }

        sorted_params = sorted(data.items(), key=lambda x: x[0])
        query_string = "&".join(f"{k}={v}" for k, v in sorted_params)
        sign_string = query_string + "af125a0d5279fd576c1b4418a3e8276d"
        md5_sign = hashlib.md5(sign_string.encode('utf-8')).hexdigest()
        data["sign"] = md5_sign

        if platform == "pc_link":
            headers["X-Event-TraceID"] = f"PC_LINK:{uuid.uuid4()}:{int(time.time() * 1000)}"
        if self.buvid3:
            headers["buvid"] = self.buvid3
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        log_request("StartLive", "POST", api, headers, params=data)
        try:
            resp = requests.post(api, headers=headers, params=data, verify=self.verify_ssl, timeout=30)
            resp.raise_for_status()
            log_response("StartLive", resp)
            result = resp.json()
            if result.get('code') == 0:
                return {'success': True, 'data': result.get('data', {})}
            else:
                return {'success': False, 'error': result.get('message', '未知错误'), 'code': result.get('code')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def stop_live(self, room_id: int, platform: str = "pc_link") -> Dict[str, Any]:
        """
        停止直播
        """
        api = "https://api.live.bilibili.com/room/v1/Room/stopLive"
        headers = self.headers.copy()
        csrf = self.csrf

        data = {
            "platform": platform,
            "room_id": room_id,
            "csrf": csrf,
            "csrf_token": csrf,
        }

        log_request("StopLive", "POST", api, headers, data=data)
        try:
            resp = requests.post(api, headers=headers, data=data, verify=self.verify_ssl, timeout=30)
            resp.raise_for_status()
            log_response("StopLive", resp)
            result = resp.json()
            if result.get('code') == 0:
                return {'success': True, 'data': result.get('data', {})}
            else:
                return {'success': False, 'error': result.get('message', '未知错误'), 'code': result.get('code')}
        except Exception as e:
            return {'success': False, 'error': str(e)}

# ---------- 交互式登录 ----------
def login_flow() -> Dict[str, str]:
    print("\n" + "=" * 40)
    print("    开始扫码登录")
    print("=" * 40 + "\n")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    verify_ssl = True

    login_obj = BilibiliLogInRegister(headers, verify_ssl)
    gen_result = login_obj.generate()
    if not gen_result['success']:
        print(f"❌ 获取二维码失败: {gen_result['error']}")
        return {}

    qr_data = gen_result['data']
    url = qr_data['url']
    qrcode_key = qr_data['qrcode_key']

    print("✅ 二维码生成成功，请使用 B站APP 扫描下方二维码登录")
    print("提示：请将终端窗口调大，确保二维码完整显示\n")
    print_qr_ascii(url)
    print("\n" + "-" * 40)

    print("\n是否在轮询二维码时详细输出每次请求和响应（即使状态无变化也输出）？")
    print("  [Y] 详细输出（适合调试）")
    print("  [N] 简洁输出（仅当状态变化时提示）")
    poll_verbose_choice = input("请选择 (Y/N，默认 N): ").strip().upper()
    poll_verbose = poll_verbose_choice == 'Y'
    print(f"轮询详细日志: {'开启' if poll_verbose else '关闭'}\n")

    print("\n⏳ 等待扫码 (每2秒检测一次)...")
    max_tries = 120
    poll_interval = 2

    for i in range(max_tries):
        poll_result = login_obj.poll(qrcode_key, verbose=poll_verbose)
        if not poll_result['success']:
            if poll_verbose:
                print(f"⚠️ 轮询出错: {poll_result['error']}")
            time.sleep(poll_interval)
            continue

        scan_data = poll_result['data']
        scan_code = scan_data.get('code')

        if poll_verbose or scan_code in (0, 86038, 86090, 86101):
            status_map = {
                0: "✅ 登录成功",
                86038: "❌ 二维码已失效",
                86090: "📱 已扫码，请确认登录",
                86101: "⏳ 等待扫码..."
            }
            status_text = status_map.get(scan_code, f"未知状态码: {scan_code}")
            print(f"[轮询] {status_text}")

        if scan_code == 0:
            login_url = scan_data.get('url', '')
            if not login_url:
                print("❌ 登录成功但未返回 url，无法提取 cookie")
                return {}

            parsed = urlparse(login_url)
            query_params = parse_qs(parsed.query)
            gourl = query_params.get('gourl', ['https://www.bilibili.com'])[0]

            print(f"\n🔍 登录回调 URL: {login_url}")
            print(f"🔍 目标跳转地址 (gourl): {gourl}")
            print("🔄 正在依次访问回调地址和目标地址以获取完整 Cookie...\n")

            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'cross-site',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'Referer': 'https://passport.bilibili.com/',
                'Origin': 'https://passport.bilibili.com'
            })

            log_request("请求1", "GET", login_url, session.headers)
            resp1 = session.get(login_url, allow_redirects=False, timeout=10)
            log_response("响应1", resp1)

            if resp1.status_code in (301, 302, 303, 307, 308):
                location = resp1.headers.get('Location')
                if location:
                    print(f"[响应1] 重定向到: {location}")
                    log_request("请求2", "GET", location, session.headers)
                    resp2 = session.get(location, allow_redirects=True, timeout=10)
                    log_response("响应2", resp2)
                else:
                    print("[响应1] 没有 Location 头，但状态码为 30x？")
            else:
                print("[响应1] 非重定向响应，直接访问 gourl")
                log_request("请求2", "GET", gourl, session.headers)
                resp2 = session.get(gourl, allow_redirects=True, timeout=10)
                log_response("响应2", resp2)

            cookies_dict = session.cookies.get_dict()
            print(f"\n[全部] session.cookies: {cookies_dict}")

            cookies = {
                'DedeUserID': cookies_dict.get('DedeUserID', ''),
                'DedeUserID__ckMd5': cookies_dict.get('DedeUserID__ckMd5', ''),
                'SESSDATA': cookies_dict.get('SESSDATA', ''),
                'bili_jct': cookies_dict.get('bili_jct', ''),
                'buvid3': cookies_dict.get('buvid3', ''),
                'b_nut': cookies_dict.get('b_nut', ''),
            }
            for k, v in cookies_dict.items():
                if k not in cookies:
                    cookies[k] = v

            required_basic = ['DedeUserID', 'SESSDATA', 'bili_jct']
            if any(not cookies.get(k) for k in required_basic):
                print("❌ 提取的基础 cookie 不完整")
                return {}

            print("✅ 扫码登录成功，完整 Cookie 提取完成")
            return cookies

        elif scan_code == 86038:
            print("❌ 二维码已失效，请重新运行")
            return {}
        time.sleep(poll_interval)

    print("❌ 扫码超时")
    return {}

# ---------- 主函数 ----------
def main():
    print("\n" + "=" * 40)
    print("     B站直播推流获取工具")
    print("=" * 40 + "\n")

    accounts = get_all_accounts()
    default_user = get_default_account()
    current_user_id = None
    cookies = {}

    while True:
        print("\n当前已保存的账户:")
        if accounts:
            for uid, info in accounts.items():
                is_default = " (默认)" if uid == default_user else ""
                print(f"  [{uid}] {info.get('nickname', '未知')}{is_default}")
            print("  [N] 登录新账号")
            print("  [D] 删除账户")
            print("  [Q] 退出")
        else:
            print("  (无已保存账户)")
            print("  [N] 登录新账号")
            print("  [Q] 退出")

        choice = input("请选择: ").strip()

        if choice.upper() == 'Q':
            print("退出")
            sys.exit(0)

        if choice.upper() == 'D' and accounts:
            uid = input("请输入要删除的账户ID: ").strip()
            if delete_account(uid):
                print(f"账户 {uid} 已删除")
                accounts = get_all_accounts()
                default_user = get_default_account()
            else:
                print("账户不存在")
            continue

        if choice.upper() == 'N':
            cookies = login_flow()
            if not cookies:
                continue
            uid = cookies.get('DedeUserID')
            if not uid:
                continue
            nickname = input("请输入该账户的备注名（留空使用默认）: ").strip()
            save_account_cookies(uid, cookies, nickname)
            print(f"账户 {uid} 保存成功")
            current_user_id = uid
            accounts = get_all_accounts()
            default_user = get_default_account()
            break

        if choice in accounts:
            current_user_id = choice
            cookies = get_account_cookies(choice)
            if not cookies:
                print("账户 Cookie 已失效，请重新登录")
                continue
            set_default_account(choice)
            print(f"已选择账户: {get_account_nickname(choice)}")
            break

        print("无效选择，请重新输入")

    if not cookies or not current_user_id:
        print("未能获取有效账户，退出")
        sys.exit(1)

    # 构建基础 headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'cookie': dict_to_cookie_string(cookies)
    }
    verify_ssl = True

    # 获取用户昵称
    try:
        resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=headers, verify=verify_ssl, timeout=10)
        if resp.status_code == 200 and resp.json().get('code') == 0:
            nickname = resp.json().get('data', {}).get('name', '未知')
            print(f"当前登录用户: {nickname} ({current_user_id})")
    except:
        pass

    # ---- 新增：检测直播间直播状态 ----
    api_generic = BilibiliApiGeneric(headers, verify_ssl)
    room_info = api_generic.get_room_info_old(int(current_user_id))
    if not room_info['success']:
        print(f"❌ 获取房间信息失败: {room_info['error']}")
        sys.exit(1)

    room_data = room_info['data']
    room_id = room_data.get('roomid')
    live_status = room_data.get('liveStatus', 0)  # 0=未开播，1=直播中

    if not room_id:
        print("❌ 该账号尚未开通直播间")
        sys.exit(1)

    print(f"直播间ID: {room_id}")

    if live_status == 1:
        print("\n⚠️ 检测到该账号当前正在直播中！")
        print("  [1] 停止直播并继续开播")
        print("  [2] 取消开播，退出")
        stop_choice = input("请选择: ").strip()
        if stop_choice == '1':
            print("🔄 正在停止直播...")
            # 获取当前使用的平台（此处默认使用 pc_link，因为直播中无法确定平台，但停止接口通常与平台无关）
            auth = BilibiliCSRFAuthenticator(headers, verify_ssl)
            stop_result = auth.stop_live(room_id, platform="pc_link")
            if stop_result['success']:
                print("✅ 直播已停止")
                # 等待状态更新
                time.sleep(2)
                # 重新获取状态确认
                room_info = api_generic.get_room_info_old(int(current_user_id))
                if room_info['success'] and room_info['data'].get('liveStatus', 1) == 0:
                    print("✅ 确认直播已停止")
                else:
                    print("⚠️ 无法确认直播是否已停止，但继续执行...")
            else:
                print(f"❌ 停止直播失败: {stop_result.get('error', '未知错误')}")
                sys.exit(1)
        else:
            print("退出程序")
            sys.exit(0)

    # 询问是否继续获取推流信息
    print("\n是否继续获取推流信息？")
    print("  [1] 继续")
    print("  [2] 退出")
    if input("请输入数字: ").strip() != '1':
        print("退出")
        sys.exit(0)

    # 选择平台
    print("\n请选择开播平台:")
    print("  [1] pc_link (直播姬PC版)")
    print("  [2] web_link (网页在线直播)")
    print("  [3] android_link (bililink)")
    platform_choice = input("请输入数字 [1-3]: ").strip()
    platform_map = {'1': 'pc_link', '2': 'web_link', '3': 'android_link'}
    platform = platform_map.get(platform_choice, 'pc_link')
    print(f"已选择平台: {platform}")

    # 根据平台设置 User-Agent 和版本参数
    if platform == 'pc_link':
        headers['User-Agent'] = 'LiveHime/8.2.0.10943 os/Windows pc_app/livehime build/10943 osVer/10.0.19045_x86_64'
        build = '10943'
        version = '8.2.0.10943'
    elif platform == 'web_link':
        headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        build = '9343'
        version = ''
    elif platform == 'android_link':
        headers['User-Agent'] = 'BiliApp/7.20.0 (Android 13; Pixel 6)'
        build = '9343'
        version = '7.20.0'
    else:
        build = '9343'
        version = ''
    print(f"当前 User-Agent: {headers['User-Agent']}")

    # 获取分区列表
    area_result = api_generic.get_area_list()
    if not area_result['success']:
        print("❌ 获取分区列表失败，使用默认分区 255")
        area_id = 255
    else:
        areas = area_result['data']
        print("\n请选择二级分区（输入序号）:")
        for area in areas:
            for sub in area.get('list', []):
                print(f"  [{sub['id']}] {area['name']} - {sub['name']}")
        area_id_input = input("请输入分区ID: ").strip()
        if area_id_input.isdigit():
            area_id = int(area_id_input)
        else:
            print("输入无效，使用默认分区 255")
            area_id = 255

    print(f"使用分区ID: {area_id}")

    # 开播
    print(f"\n🔄 正在以平台 [{platform}] 开播并获取推流地址...")
    auth = BilibiliCSRFAuthenticator(headers, verify_ssl)
    start_result = auth.start_live(room_id, area_id, platform=platform, build=build, version=version)

    if not start_result['success']:
        error_msg = start_result.get('error', '未知错误')
        print(f"❌ 开播失败: {error_msg}")
        if '身份验证' in error_msg or '人脸' in error_msg:
            print("💡 需要人脸认证，请打开以下链接完成认证：")
            print(f"https://www.bilibili.com/blackboard/live/face-auth-middle.html?source_event=400&mid={current_user_id}")
        sys.exit(1)

    rtmp_data = start_result['data'].get('rtmp', {})
    rtmp_addr = rtmp_data.get('addr', '')
    rtmp_code = rtmp_data.get('code', '')
    if not rtmp_addr or not rtmp_code:
        print("❌ 未获取到推流地址或推流码")
        sys.exit(1)

    # 输出结果
    print("\n" + "=" * 40)
    print("         推流信息")
    print("=" * 40)
    print(f"推流地址: {rtmp_addr}")
    print(f"推流码  : {rtmp_code}")
    print("=" * 40)

    try:
        pyperclip.copy(f"{rtmp_addr}\n{rtmp_code}")
        print("✅ 已复制推流地址和推流码到剪贴板")
    except Exception as e:
        print(f"⚠️ 复制到剪贴板失败: {e}")

if __name__ == "__main__":
    main()