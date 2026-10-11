#!/usr/bin/env python3
"""麦当劳 MCP 极简客户端(纯标准库)。

职责:鉴权、JSON-RPC 调用、响应文本中业务 JSON 的提取。
安全:Token 只从环境变量 MCD_MCP_TOKEN 或 ~/.mcd_token 读取,绝不硬编码、绝不打印。

与父 skill(mcd-what-to-eat-today)版本的差异,仅以下一处(2026-10-11 按 Mimosa
安全扫描要求加固,行为对合法端点不变):
- _assert_safe_url():仅允许 https + 域名白名单 mcd.mcd.cn,DNS 解析到
  非公网地址(内网/环回/链路本地)即拒绝,并禁用 HTTP 重定向(防 SSRF/DNS rebinding)。
"""
import ipaddress
import json
import os
import re
import socket
import urllib.request
from urllib.parse import urlsplit

BASE_URL = "https://mcp.mcd.cn"
ALLOWED_HOSTS = {"mcp.mcd.cn"}

_CALL_ID = [100]


def load_token() -> str:
    tok = os.environ.get("MCD_MCP_TOKEN")
    if tok and tok.strip():
        return tok.strip()
    path = os.path.expanduser("~/.mcd_token")
    if os.path.exists(path):
        with open(path) as f:
            tok = f.read().strip()
        if tok:
            return tok
    raise SystemExit(
        "未找到 MCP Token。请设置环境变量 MCD_MCP_TOKEN,或在本机写入 ~/.mcd_token(权限 600)。"
    )


def _assert_safe_url(url: str) -> None:
    """SSRF 边界:仅 https、仅白名单域名、解析结果必须全为公网 IP、禁重定向。"""
    u = urlsplit(url)
    if u.scheme != "https":
        raise RuntimeError(f"仅允许 https 请求,拒绝 scheme={u.scheme!r}")
    if u.hostname not in ALLOWED_HOSTS:
        raise RuntimeError(f"目标主机 {u.hostname!r} 不在白名单 {sorted(ALLOWED_HOSTS)}")
    try:
        infos = socket.getaddrinfo(u.hostname, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise RuntimeError(f"域名解析失败 {u.hostname}: {e}")
    for *_ , sa in infos:
        ip = ipaddress.ip_address(sa[0])
        if not ip.is_global:
            raise RuntimeError(f"{u.hostname} 解析到非公网地址 {ip},疑似内网或 DNS 劫持,已拒绝")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"禁止重定向(收到 {code} → {newurl})")


_OPENER = urllib.request.build_opener(_NoRedirect)


def _rpc(payload: dict, timeout: int = 30) -> dict:
    _assert_safe_url(BASE_URL)
    req = urllib.request.Request(
        BASE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {load_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        method="POST",
    )
    with _OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_business_json(text: str):
    """MCP 返回的 content[0].text 含 '## Original Response' 段,提取其中的业务 JSON。

    兜底:偶发情况下该段缺失,退化为在全文中扫描第一个可完整解析的 JSON 对象。
    """
    m = re.search(r"## Original Response\s*(\{.*)", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = decoder.raw_decode(text[i:])
                if isinstance(obj, dict) and ("data" in obj or "success" in obj):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def call_tool(name: str, arguments: dict | None = None, timeout: int = 30) -> dict:
    """调用一个 MCP 工具,返回解析后的业务 JSON;失败抛 RuntimeError。

    注意:券类工具(query-my-coupons / auto-bind-coupons / query-store-coupons /
    available-coupons)返回的是 **markdown 而非 JSON**,本函数会抛错。
    券类请改用 call_tool_text()。
    """
    _CALL_ID[0] += 1
    payload = {
        "jsonrpc": "2.0",
        "id": _CALL_ID[0],
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    data = _rpc(payload, timeout=timeout)
    if "error" in data:
        raise RuntimeError(f"{name} RPC 错误: {data['error']}")
    content = (data.get("result") or {}).get("content") or []
    text = content[0].get("text", "") if content else ""
    biz = _extract_business_json(text)
    if biz is None:
        raise RuntimeError(f"{name} 未返回业务 JSON(可能返回 markdown,改用 call_tool_text)。原文前 200 字: {text[:200]}")
    if biz.get("success") is False:
        raise RuntimeError(f"{name} 业务错误 {biz.get('code')}: {biz.get('message')}")
    return biz


def call_tool_text(name: str, arguments: dict | None = None, timeout: int = 30) -> str:
    """原样返回 content[0].text。用于券类等返回 markdown 的工具。

    ⚠️ 副作用警告:auto-bind-coupons 是**写操作**,它会真的领取全部可领券。
    """
    _CALL_ID[0] += 1
    payload = {
        "jsonrpc": "2.0",
        "id": _CALL_ID[0],
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    data = _rpc(payload, timeout=timeout)
    if "error" in data:
        raise RuntimeError(f"{name} RPC 错误: {data['error']}")
    content = (data.get("result") or {}).get("content") or []
    return content[0].get("text", "") if content else ""


def parse_coupons(markdown: str) -> list[dict]:
    """解析 query-my-coupons 的 markdown,抽取券名/优惠额/有效期/标签。

    实测格式(2026-10-10):
        # 您的优惠券列表
        共 5 张可用优惠券 | 第 1/1 页 | 每页 200 条
        ## 9.9元中杯冰美式
        - **优惠**: ¥9.9 (用券价格)
        - **有效期**: 2026-10-10 00:00-2026-10-16 23:59
        - **领取时间**: 今日收到
        - **标签**: 到店专用、外送专用
        <img ...>   ← 图片行含 base64 签名 URL,必须忽略

    只取 '## 券名' 与其后的 '- **键**: 值' 行,不解析 HTML。
    """
    coupons, cur = [], None
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            if cur:
                coupons.append(cur)
            cur = {"name": line[3:].strip()}
        elif cur and line.startswith("- **"):
            m = re.match(r"- \*\*(.+?)\*\*[:：]\s*(.+)", line)
            if m:
                cur[m.group(1).strip()] = m.group(2).strip()
    if cur:
        coupons.append(cur)
    return [c for c in coupons if len(c) > 1]


def list_tools() -> list[str]:
    """返回线上真实工具名清单(用于自检文档与线上是否一致)。"""
    _CALL_ID[0] += 1
    data = _rpc({"jsonrpc": "2.0", "id": _CALL_ID[0], "method": "tools/list", "params": {}})
    return [t["name"] for t in data["result"]["tools"]]


if __name__ == "__main__":
    print("\n".join(list_tools()))
