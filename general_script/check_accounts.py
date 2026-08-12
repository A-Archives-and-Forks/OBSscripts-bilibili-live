#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
B站账户过期检查工具（独立脚本）
功能：
- 读取 bili_live_cli_config/accounts.json 中的所有账户
- 对每个账户执行以下检查：
  1. 是否存在必要的 Cookie 字段（DedeUserID, SESSDATA, bili_jct）
  2. 通过调用 nav API 验证登录状态
  3. 记录 API 返回的 code 和 isLogin 字段
  4. 判断账户是否有效（过期或未过期）
- 输出详细的检查日志，每个步骤都清晰可读
依赖：requests
安装：pip install requests
"""

import os
import sys
import json
import time
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime

import requests

# ---------- 配置文件路径 ----------
def get_config_dir() -> Path:
    """获取脚本同目录下的配置文件夹（与主脚本共用）"""
    script_dir = Path(__file__).parent
    config_dir = script_dir / "bili_live_cli_config"
    return config_dir

def get_accounts_file() -> Path:
    return get_config_dir() / "accounts.json"

def load_accounts() -> Dict[str, Any]:
    """加载账户配置文件"""
    file_path = get_accounts_file()
    if not file_path.exists():
        return {"accounts": {}, "default_user": None}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"accounts": {}, "default_user": None}

# ---------- 核心检查函数 ----------
def check_account_cookies(cookies: Dict[str, str]) -> Dict[str, Any]:
    """
    检查单个账户的 Cookie 完整性和有效性
    返回字典包含检查结果
    """
    result = {
        "has_DedeUserID": False,
        "has_SESSDATA": False,
        "has_bili_jct": False,
        "has_buvid3": False,
        "has_b_nut": False,
        "cookies_valid": False,
        "login_status": False,
        "nav_code": None,
        "nav_isLogin": False,
        "nav_message": "",
        "error": None,
        "user_name": ""
    }

    # --- 第一步：检查必要字段是否存在 ---
    required = ['DedeUserID', 'SESSDATA', 'bili_jct']
    for field in required:
        if cookies.get(field):
            result[f"has_{field}"] = True

    # 检查辅助字段（非必需）
    if cookies.get('buvid3'):
        result['has_buvid3'] = True
    if cookies.get('b_nut'):
        result['has_b_nut'] = True

    # 判断基本 Cookie 是否完整
    if result['has_DedeUserID'] and result['has_SESSDATA'] and result['has_bili_jct']:
        result['cookies_valid'] = True
    else:
        result['cookies_valid'] = False
        result['error'] = "Cookie 缺少必要字段"
        return result

    # --- 第二步：调用 nav API 验证登录状态 ---
    uid = cookies.get('DedeUserID')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'cookie': "; ".join([f"{k}={v}" for k, v in cookies.items()])
    }
    try:
        resp = requests.get('https://api.bilibili.com/x/web-interface/nav', headers=headers, timeout=10)
        data = resp.json()
        result['nav_code'] = data.get('code')
        result['nav_message'] = data.get('message', '')
        # 检查登录状态
        if data.get('code') == 0:
            is_login = data.get('data', {}).get('isLogin', False)
            result['nav_isLogin'] = is_login
            if is_login:
                result['login_status'] = True
                result['user_name'] = data.get('data', {}).get('name', '')
            else:
                result['error'] = "API 返回 isLogin=false，账户已过期"
        elif data.get('code') == -101:
            result['error'] = "API 返回 -101，未登录或登录已过期"
        else:
            result['error'] = f"API 返回异常 code: {data.get('code')}"
    except Exception as e:
        result['error'] = f"网络请求异常: {str(e)}"

    return result

def print_check_result(uid: str, nickname: str, result: Dict[str, Any]) -> None:
    """打印单个账户的检查结果（详细日志）"""
    print(f"\n{'='*60}")
    print(f"检查账户: {uid} ({nickname})")
    print(f"{'='*60}")

    # 打印 Cookie 字段检查
    print("\n[1] Cookie 字段检查:")
    print(f"    DedeUserID : {'✅ 存在' if result['has_DedeUserID'] else '❌ 缺失'}")
    print(f"    SESSDATA   : {'✅ 存在' if result['has_SESSDATA'] else '❌ 缺失'}")
    print(f"    bili_jct   : {'✅ 存在' if result['has_bili_jct'] else '❌ 缺失'}")
    print(f"    buvid3     : {'✅ 存在' if result['has_buvid3'] else '❌ 缺失'}")
    print(f"    b_nut      : {'✅ 存在' if result['has_b_nut'] else '❌ 缺失'}")
    print(f"    基本字段完整: {'✅ 是' if result['cookies_valid'] else '❌ 否'}")

    if not result['cookies_valid']:
        print("\n[结论] ❌ Cookie 不完整，账户无效")
        return

    # 打印 API 验证结果
    print("\n[2] Nav API 验证:")
    print(f"    请求 URL  : https://api.bilibili.com/x/web-interface/nav")
    print(f"    响应 code : {result['nav_code']}")
    print(f"    响应 message: {result['nav_message']}")
    print(f"    isLogin   : {result['nav_isLogin']}")
    if result['user_name']:
        print(f"    用户昵称  : {result['user_name']}")

    if result.get('error'):
        print(f"    错误信息  : {result['error']}")

    # 最终判断
    print("\n[结论] ", end="")
    if result['login_status']:
        print(f"✅ 账户有效（已登录），用户: {result['user_name']}")
    else:
        print("❌ 账户已过期或登录失效")

def main():
    print("\n" + "=" * 50)
    print("     B站账户过期检查工具")
    print("     " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 50)

    accounts_data = load_accounts()
    accounts = accounts_data.get("accounts", {})
    default_user = accounts_data.get("default_user")

    if not accounts:
        print("\n⚠️ 未找到任何已保存的账户。")
        print("   请先使用主脚本登录账号并保存。")
        sys.exit(0)

    print(f"\n共发现 {len(accounts)} 个账户，正在逐一检查...")

    valid_count = 0
    expired_count = 0

    for uid, info in accounts.items():
        nickname = info.get('nickname', f'用户{uid}')
        cookies = info.get('cookies', {})
        if not cookies:
            print(f"\n⚠️ 账户 {uid} 没有保存的 Cookie，跳过")
            continue

        result = check_account_cookies(cookies)
        print_check_result(uid, nickname, result)

        if result['login_status']:
            valid_count += 1
        else:
            expired_count += 1

    # 汇总
    print("\n" + "=" * 50)
    print("检查完成")
    print(f"有效账户: {valid_count}")
    print(f"过期账户: {expired_count}")
    print("=" * 50)

if __name__ == "__main__":
    main()