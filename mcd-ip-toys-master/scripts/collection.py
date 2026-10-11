#!/usr/bin/env python3
"""功能4:我的玩具库 —— 像博物馆一样在本地长期收藏买过的玩具。

## 定位
用户是麦当劳玩具收藏者。藏品是**长期资产**,不是运行时状态:
- 存储在 `assets/collection.json`,**随仓库保存**(不像情报快照那样 gitignore);
  每件藏品有入藏编号(#1 起,只增不减,博物馆式 accession number)。
- 两个来源:
  a) **下单自动收藏**(默默保存):quick_order 两段式下单成功且套餐含玩具轮次时,
     自动 append(source=order,带订单号)。未付款取消的订单也会留下记录——
     藏品文件可 `remove` 清理,宁多记不漏记。
  b) **访谈录入**(首装冷启动):订单历史拿不到玩具维度,由用户口述、agent 录入。

## 用法
    python3 scripts/collection.py list                 # 藏品清单(默认)
    python3 scripts/collection.py add --toy 海绵宝宝×航海王系列玩具 [--series 海绵宝宝×航海王] [--note 随餐]
    python3 scripts/collection.py add-many 海绵宝宝系列、大盘鸡公仔、小丸子玩偶
    python3 scripts/collection.py remove 3             # 按入藏编号移除(先显示再删)
    python3 scripts/collection.py stats                # 件数/系列数
    python3 scripts/collection.py --json               # 机器可读
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime

SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
COLLECTION_PATH = os.path.join(os.path.dirname(SCRIPTS_DIR),
                               "assets", "collection.json")


def load(path=None) -> list:
    p = path or COLLECTION_PATH
    if not os.path.exists(p):
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save(entries: list, path=None):
    """原子落盘(临时文件+replace),藏品是长期资产,不能写一半。"""
    p = path or COLLECTION_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), suffix=".col.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def add(toy: str, series=None, source="manual", note=None,
        store=None, channel=None, order_id=None, at=None, path=None) -> dict:
    """入藏一件。返回新条目(含入藏编号)。同名单品不去重——两份同款也是两件藏品。"""
    entries = load(path)
    entry = {
        "no": len(entries) + 1,
        "toy": (toy or "").strip(),
        "series": series,
        "acquired_at": at or datetime.now().strftime("%Y-%m-%d"),
        "source": source,          # manual=访谈录入 / order=下单自动收藏
        "store": store, "channel": channel, "order_id": order_id,
        "note": note,
    }
    entries.append(entry)
    save(entries, path)
    return entry


def add_many(names, series=None, source="manual", path=None, **kw) -> list:
    """一次口述多件:按 、，,;；/ 拆分,空段丢弃。"""
    out = []
    for n in split_names(names):
        out.append(add(n, series=series, source=source, path=path, **kw))
    return out


def split_names(text) -> list:
    import re
    parts = re.split(r"[、，,;；/\n]+", text or "")
    return [p.strip() for p in parts if p.strip()]


def remove(no: int, path=None):
    """按入藏编号移除一件。返回被移除条目;编号不存在返回 None。"""
    entries = load(path)
    hit = next((e for e in entries if e.get("no") == no), None)
    if hit is None:
        return None
    # 🔴 只删条目,不改后续编号(博物馆式:编号是历史,不重排)
    save([e for e in entries if e.get("no") != no], path)
    return hit


def edit(no: int, toy=None, series=None, note=None, date=None, path=None):
    """按入藏编号修改字段(编号永不改)。返回更新后条目;编号不存在返回 None。"""
    entries = load(path)
    hit = next((e for e in entries if e.get("no") == no), None)
    if hit is None:
        return None
    if toy is not None:
        hit["toy"] = toy
    if series is not None:
        hit["series"] = series
    if note is not None:
        hit["note"] = note
    if date is not None:
        hit["acquired_at"] = date
    save(entries, path)
    return hit


def reconcile(path=None, query=None, prune=False) -> list:
    """对账:source=order 的藏品逐条回查订单状态(只读;--prune 才动文件)。

    - 已取消订单 → 报告(prune=True 时移除该藏品,编号不重排)
    - 查询失败   → 如实标注 query_failed 并保留(不瞎删)
    - 非订单来源(访谈录入) → 不查不动
    query: 注入查询函数 orderId -> {"status": str}(离线测试用);
           默认走 mcd_client 的 query-order。
    """
    def _default_query(oid):
        from mcd_client import call_tool
        d = (call_tool("query-order", {"orderId": oid}).get("data") or {})
        return {"status": d.get("orderStatus")}

    q = query or _default_query
    entries = load(path)
    report, kept = [], []
    for e in entries:
        if e.get("source") != "order" or not e.get("order_id"):
            kept.append(e)
            continue
        try:
            st = str(q(e["order_id"]).get("status") or "?")
        except Exception as ex:
            report.append({"no": e.get("no"), "toy": e.get("toy"),
                           "order_id": e.get("order_id"),
                           "result": "query_failed", "detail": str(ex)[:60]})
            kept.append(e)
            continue
        if "取消" in st:
            report.append({"no": e.get("no"), "toy": e.get("toy"),
                           "order_id": e.get("order_id"),
                           "result": "pruned" if prune else "cancelled",
                           "status": st})
            if not prune:
                kept.append(e)
        else:
            report.append({"no": e.get("no"), "toy": e.get("toy"),
                           "order_id": e.get("order_id"),
                           "result": "ok", "status": st})
            kept.append(e)
    if prune and len(kept) != len(entries):
        save(kept, path)
    return report


def stats(entries=None) -> dict:
    entries = entries if entries is not None else load()
    series = {e.get("series") or e.get("toy") for e in entries}
    return {"count": len(entries), "series": len(series)}


def render(entries=None) -> str:
    """藏品清单(66 字符宽,与确认卡同一渲染家族)。空库也有诚实的空态。"""
    entries = entries if entries is not None else load()
    L = []
    L.append("=" * 66)
    s = stats(entries)
    L.append(f"🧸 我的玩具库 · {s['count']} 件藏品 · {s['series']} 个系列")
    L.append("=" * 66)
    if not entries:
        L.append("  (还空着——首装冷启动:订单里拿不到玩具维度,")
        L.append("   让用户口述藏品,用 add/add-many 录入)")
        return "\n".join(L)
    for e in entries:
        head = f"  #{e.get('no', '?')} {e.get('toy', '?')}"
        if e.get("series") and e["series"] != e["toy"]:
            head += f"  ·{e['series']}"
        L.append(head)
        tail = f"      {e.get('acquired_at', '?')}"
        if e.get("source") == "order":
            tail += " ·下单收藏"
            if e.get("order_id"):
                tail += f" ·{e['order_id'][:12]}…"
        else:
            tail += " ·访谈录入"
        if e.get("store"):
            tail += f" ·{e['store']}"
        if e.get("note"):
            tail += f" ·{e['note']}"
        L.append(tail)
    return "\n".join(L)


def record_order_toys(toy_names, series=None, store=None, channel=None,
                      order_id=None, path=None) -> list:
    """quick_order 下单成功后的自动收藏钩子。🔴 收藏失败绝不阻断下单——
    由调用方 try/except,本函数自身不抛出收藏类错误之外的东西。"""
    out = []
    for n in toy_names or []:
        out.append(add(n, series=series, source="order", store=store,
                       channel=channel, order_id=order_id, path=path,
                       note="下单即录,未付款取消可 remove"))
    return out


def main():
    ap = argparse.ArgumentParser(description="我的玩具库(本地长期藏品)")
    ap.add_argument("cmd", nargs="?", default="list",
                    choices=["list", "add", "add-many", "remove", "edit",
                             "reconcile", "stats"])
    ap.add_argument("--toy", default=None, help="藏品名(add/edit 用)")
    ap.add_argument("--series", default=None, help="所属系列")
    ap.add_argument("--note", default=None, help="备注(如 随餐/加价购/门店赠)")
    ap.add_argument("--date", default=None, help="入手日期(edit 用,如 2024-05-01)")
    ap.add_argument("--prune", action="store_true",
                    help="配合 reconcile:移除已取消订单的藏品")
    ap.add_argument("names", nargs="*", help="add-many 口述串 / edit·remove 编号")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.cmd == "list":
        print(json.dumps(load(), ensure_ascii=False, indent=2) if a.json
              else render())
    elif a.cmd == "add":
        if not a.toy:
            ap.error("add 需要 --toy")
        e = add(a.toy, series=a.series, note=a.note)
        print(json.dumps(e, ensure_ascii=False) if a.json
              else f"🧸 已入藏 #{e['no']} {e['toy']}")
    elif a.cmd == "add-many":
        text = " ".join(a.names)
        if not text:
            ap.error("add-many 需要口述串,如: 海绵宝宝系列、大盘鸡公仔")
        es = add_many(text, series=a.series, note=a.note)
        print(f"🧸 已入藏 {len(es)} 件:" if not a.json else
              json.dumps(es, ensure_ascii=False))
        if not a.json:
            for e in es:
                print(f"  #{e['no']} {e['toy']}")
    elif a.cmd == "remove":
        if not a.names or not a.names[0].isdigit():
            ap.error("remove 需要入藏编号,如: remove 3")
        hit = remove(int(a.names[0]))
        print(f"已移除 #{hit['no']} {hit['toy']}" if hit else
              "该编号不存在(编号不重排,用 list 核对)")
    elif a.cmd == "edit":
        if not a.names or not a.names[0].isdigit():
            ap.error("edit 需要入藏编号,如: edit 1 --date 2024-05-01")
        e = edit(int(a.names[0]), toy=a.toy, series=a.series,
                 note=a.note, date=a.date)
        print(json.dumps(e, ensure_ascii=False) if e else "该编号不存在")
    elif a.cmd == "reconcile":
        rep = reconcile(prune=a.prune)
        if not rep:
            print("没有需要对账的订单来源藏品。")
        for r in rep:
            mark = {"ok": "✅", "cancelled": "⚠️ 已取消(未删,--prune 可清)",
                    "pruned": "🗑 已移除", "query_failed": "❓ 查询失败(保留)"}[r["result"]]
            print(f"  {mark} #{r['no']} {r['toy']} ·订单{r['order_id'][:12]}…"
                  + (f" ·{r['status']}" if r.get("status") else
                     f" ·{r.get('detail', '')}"))
    elif a.cmd == "stats":
        s = stats()
        print(json.dumps(s, ensure_ascii=False) if a.json
              else f"藏品 {s['count']} 件 / {s['series']} 个系列")


if __name__ == "__main__":
    main()
