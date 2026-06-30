# -*- coding: utf-8 -*-
"""
================================================================================
Linux.do Cookie 导出工具
================================================================================

用途：
    本地启动一个有头浏览器，由你手动完成登录（含验证码），
    然后把 linux.do 的 cookies 导出为 JSON 字符串，
    粘贴到 GitHub Secrets（LINUXDO_COOKIES）即可。

使用：
    python extract_cookies.py

可选参数：
    --output cookies.json   把 cookies 同时写入文件
    --proxy 127.0.0.1:7897  使用代理打开页面

流程：
    1. 脚本会自动打开浏览器，跳到 https://linux.do/login
    2. 你在浏览器里手动登录（账号密码 / OAuth / 邮箱验证码都行）
    3. 登录成功后回到终端按回车
    4. 脚本会读取 cookies 并打印一行 JSON，复制它去 GitHub Secrets

================================================================================
"""

import argparse
import json
import os
import platform
import sys

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
except ImportError:
    print("错误: 请先安装 DrissionPage")
    print("运行: pip install DrissionPage")
    sys.exit(1)


BASE_URL = "https://linux.do"
# 只导出这些域名下的 cookie，避免把无关 cookie 也带进 Secret
COOKIE_DOMAINS = ("linux.do", ".linux.do", "connect.linux.do")
# 这些 cookie 跟客户端 IP / User-Agent 强绑定，带到 GitHub Actions 上反而会
# 让 Cloudflare 直接拒绝。剔除掉，让 Actions 用自己的 IP 重新过盾。
STRIP_COOKIES = {
    "cf_clearance",  # Cloudflare 过盾凭证（IP+UA 绑定）
    "_cfuvid",       # Cloudflare 访客 ID
    "__cfuvid",      # 同上（不同域）
}


def _find_chrome_path():
    """探测 Chrome 二进制路径，返回找到的第一个存在的路径，没找到返回 None"""
    # 用户显式指定优先
    env = os.environ.get("CHROME_PATH")
    if env and os.path.exists(env):
        return env

    system = platform.system()
    candidates = []
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/System/Volumes/Data/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser(
                "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            ),
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        ]
    elif system == "Linux":
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
    elif system == "Windows":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]

    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def extract_cookies(proxy=None, output=None, chrome_path=None):
    print("启动浏览器...")
    opts = ChromiumOptions()
    opts.set_argument("--window-size=1280,900")

    # 显式指定 Chrome 路径，DrissionPage 默认只看 PATH 和少数固定路径
    chrome = chrome_path or _find_chrome_path()
    if chrome:
        print(f"使用 Chrome: {chrome}")
        opts.set_browser_path(chrome)
    else:
        print("警告: 未自动找到 Chrome 路径，DrissionPage 会用默认探测，"
              "若启动失败请设置 CHROME_PATH 环境变量或加 --chrome-path 参数。")

    if proxy:
        opts.set_proxy(proxy)
        print(f"使用代理: {proxy}")

    page = ChromiumPage(opts)

    try:
        page.get(f"{BASE_URL}/login")
        print()
        print("=" * 60)
        print("请在弹出的浏览器中手动完成登录（账号密码 / 验证码都可以）")
        print("登录成功后，回到此终端按回车继续...")
        print("=" * 60)
        input()

        # 再访问一次首页，确保 session cookie 被刷新
        page.get(BASE_URL)

        # 拿全部 cookies；DrissionPage 返回的是 list[dict]
        all_cookies = page.cookies(all_domains=True, all_info=True)
        cookies = [
            c
            for c in all_cookies
            if any(d in (c.get("domain") or "") for d in COOKIE_DOMAINS)
        ]

        if not cookies:
            print("未抓到任何 linux.do 的 cookie，请确认登录成功后再试。")
            return 1

        # 剔除 IP/UA 绑定的 Cloudflare cookie，避免在 GitHub Actions 上反而被 CF 直接拒
        stripped = [c["name"] for c in cookies if c.get("name") in STRIP_COOKIES]
        cookies = [c for c in cookies if c.get("name") not in STRIP_COOKIES]
        if stripped:
            print(f"已剔除 {len(stripped)} 条 IP/UA 绑定的 cookie: {', '.join(stripped)}")

        # 只保留 DrissionPage set.cookies 真正需要的字段，避免噪音
        keep_fields = {"name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}
        cleaned = [{k: v for k, v in c.items() if k in keep_fields} for c in cookies]

        compact = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))

        print()
        print("=" * 60)
        print(f"成功导出 {len(cleaned)} 条 cookie")
        print("=" * 60)
        print()
        print("【复制下面这一行整体到 GitHub Secrets: LINUXDO_COOKIES】")
        print()
        print(compact)
        print()

        if output:
            with open(output, "w", encoding="utf-8") as f:
                f.write(compact)
            print(f"已写入文件: {output}")

        # 检查关键字段
        names = {c["name"] for c in cleaned}
        if "_t" not in names:
            print("警告: 未检测到 _t cookie，登录态可能不完整。")
        else:
            print("OK: 已包含 _t（论坛登录态）")

        return 0
    finally:
        try:
            page.quit()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="导出 linux.do cookies 用于 GitHub Actions")
    parser.add_argument("--output", "-o", help="同时写入文件的路径，例如 cookies.json")
    parser.add_argument("--proxy", help="代理地址，如 127.0.0.1:7897")
    parser.add_argument(
        "--chrome-path",
        help="Chrome 可执行文件完整路径，覆盖自动探测；也可用 CHROME_PATH 环境变量",
    )
    args = parser.parse_args()

    sys.exit(
        extract_cookies(
            proxy=args.proxy, output=args.output, chrome_path=args.chrome_path
        )
    )


if __name__ == "__main__":
    main()
