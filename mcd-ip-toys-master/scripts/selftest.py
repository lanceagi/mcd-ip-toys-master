#!/usr/bin/env python3
"""环境与结构自检(离线,零网络)。

python3 scripts/selftest.py          # 基础 38 项
python3 scripts/selftest.py --full   # 追加在线 3 项(真实 MCP,只读)
"""
import argparse
import json
import os
import py_compile
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(SKILL_ROOT, "scripts")
FAILS = []


def check(name, cond, detail=""):
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def a_structure():
    print("== A. 文件与编译 ==")
    for f in ("mcd_client.py", "channel.py", "order_builder.py",
              "render_mobile.py", "toys.py", "quick_order.py", "dialog.py",
              "intel_diff.py", "collection.py", "test_toys.py"):
        p = os.path.join(SCRIPTS, f)
        check(f"A1 {f} 存在", os.path.exists(p))
        if os.path.exists(p):
            try:
                py_compile.compile(p, doraise=True)
                check(f"A2 {f} 可编译", True)
            except py_compile.PyCompileError as e:
                check(f"A2 {f} 可编译", False, str(e)[:80])
    check("A3 assets/targets.json 存在",
          os.path.exists(os.path.join(SKILL_ROOT, "assets", "targets.json")))
    check("A4 SKILL.md 存在", os.path.exists(os.path.join(SKILL_ROOT, "SKILL.md")))


def b_targets():
    print("== B. 目标预置 ==")
    with open(os.path.join(SKILL_ROOT, "assets", "targets.json"), encoding="utf-8") as f:
        t = json.load(f)
    check("B1 targets 非空且 ≥2", len(t.get("targets", [])) >= 2)
    ids = [x["id"] for x in t["targets"]]
    check("B2 id 唯一", len(ids) == len(set(ids)))
    for x in t["targets"]:
        check(f"B3 {x['id']} 有 aliases+menu_keywords",
              bool(x.get("aliases")) and bool(x.get("menu_keywords")))
    check("B4 happymeal 声明 orderable_via_mcp=true",
          next(x for x in t["targets"] if x["id"] == "happymeal")
          .get("orderable_via_mcp") is True)
    check("B5 cap/scarf 如实声明 MCP 无 SKU",
          all(next(x for x in t["targets"] if x["id"] == i)
              .get("orderable_via_mcp") is False for i in ("cap", "scarf")))


def c_skill_md():
    print("== C. SKILL.md 合规 ==")
    p = os.path.join(SKILL_ROOT, "SKILL.md")
    if not os.path.exists(p):
        return
    with open(p, encoding="utf-8") as f:
        txt = f.read()
    check("C1 frontmatter 有 name", txt.startswith("---") and "name: mcd-ip-toys-master" in txt)
    desc_ok = any(k in txt for k in ("抢", "玩具")) and "description:" in txt
    check("C2 description 含触发词", desc_ok)
    check("C3 写操作门禁条款在文档里", "--confirm" in txt and "create-order" in txt)
    check("C4 渠道分流入口(dialog)与两渠道写进文档",
          "dialog.py" in txt and "到店自取" in txt and "麦乐送" in txt)


def d_invariants():
    print("== D. 关键不变量 ==")
    sys.path.insert(0, SCRIPTS)
    import quick_order as qo
    t1 = qo.make_token("s", "c", [{"productCode": "1"}], 100)
    t2 = qo.make_token("s", "c", [{"productCode": "1"}], 100)
    check("D1 确认令牌确定性", t1 == t2 and len(t1) == 8)
    check("D2 令牌算法为 sha256", "sha256" in open(os.path.join(SCRIPTS, "quick_order.py"),
                                                 encoding="utf-8").read())
    import toys
    check("D3 菜单关键词与活动关键词均非空",
          toys.MENU_KEYWORDS and toys.CALENDAR_KEYWORDS and toys.TOY_ROUND_KEYWORDS)
    import dialog as _dlg
    d = _dlg.Dialog(target="happymeal")
    t = d.open()
    check("D4 启动分流:买玩具/看玩具库",
          d.options == ["买玩具", "看看我的玩具库"])
    check("D5 品牌话术迎宾", "喜欢您来" in t.text)


def e_online():
    print("== E. 在线(真实 MCP,只读) ==")
    sys.path.insert(0, SCRIPTS)
    try:
        from mcd_client import call_tool_text
        md = call_tool_text("campaign-calendar", {})
        check("E1 campaign-calendar 可达且非空", len(md) > 100)
    except Exception as e:
        check("E1 campaign-calendar 可达且非空", False, str(e)[:80])
    try:
        import toys as _t
        acts = _t.parse_calendar(call_tool_text("campaign-calendar", {}))
        check("E2 真实日历可解析出活动块", len(acts) >= 1, f"got {len(acts)}")
    except Exception as e:
        check("E2 真实日历可解析出活动块", False, str(e)[:80])
    try:
        from mcd_client import list_tools
        tools = list_tools()
        check("E3 35 工具在列(create-order/campaign-calendar)",
              "create-order" in tools and "campaign-calendar" in tools, f"{len(tools)} tools")
    except Exception as e:
        check("E3 35 工具在列(create-order/campaign-calendar)", False, str(e)[:80])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="追加在线 3 项")
    args = ap.parse_args()
    a_structure()
    b_targets()
    c_skill_md()
    d_invariants()
    if args.full:
        e_online()
    print()
    if FAILS:
        print(f"❌ {len(FAILS)} 项失败: {FAILS}")
        return 1
    print("✅ 自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
