#!/usr/bin/env python3
"""情报快照与差异 —— 「现在/未来有什么玩具」的变化监测。

信息更新是这个 skill 的第一要点:菜单四路情报每次跑都是实时拉取,
但「**变化**」要靠两次观测做差——新联名冒出来没有?开售时间改了没有?
玩具下架了没有?本脚本:跑一次 discover(全只读) → 与上次快照 diff →
报变化 → 落新快照。配合每日定时任务即「信息自动刷新」。

用法:
    python3 scripts/intel_diff.py                # 默认渠道/门店,快照 scripts/.intel-snapshot.json
    python3 scripts/intel_diff.py --json         # 机器可读(给 Agent 链)
    python3 scripts/intel_diff.py --reset        # 丢弃旧快照,重建基线
    python3 scripts/intel_diff.py --channel 麦乐送

diff 规则(只看玩具/周边相关 hits,即 discover() 已过滤的四路命中):
    🆕 新增  上次没有的活动/菜单项/商城项(新联名、新上架玩具)
    🔁 变化  活动开售时间(drop_time)变化;菜单价格变化;玩具轮次款式变化;
             商城价格/积分/下架时间变化
    👋 消失  上次有、现在没有(下架/活动结束)

诚实规则:某路情报源本次拉取失败(calendar_error/mall_error)时,
该路的旧条目**原样结转**,不误报「消失」;报告里注明结转原因。
快照文件一律限定在 scripts/ 目录内(路径规范化校验,拒绝越界)。
"""
import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import toys  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.realpath(__file__))
DEFAULT_SNAPSHOT = os.path.join(SCRIPTS_DIR, ".intel-snapshot.json")

KIND_BY_SOURCE = {"campaign-calendar": "cal", "query-meals": "menu",
                  "mall-points-products": "mall"}


def safe_snapshot_path(p: str) -> str:
    """快照落点防御:规范化后必须位于 scripts/ 目录内,拒绝穿越。"""
    real = os.path.realpath(os.path.abspath(p))
    if real != SCRIPTS_DIR and not real.startswith(SCRIPTS_DIR + os.sep):
        raise ValueError(f"快照路径越界,只允许 {SCRIPTS_DIR} 内: {p}")
    return real


# ---------- 观测 → 快照 ----------

def hit_key(h: dict) -> str:
    """稳定主键:活动按标题,菜单按 code(渠道相关!快照带渠道/门店口径),
    商城按 spuId。"""
    kind = KIND_BY_SOURCE.get(h.get("source"))
    if kind == "cal":
        return f"cal|{h.get('title')}"
    if kind == "menu":
        return f"menu|{h.get('code')}"
    if kind == "mall":
        return f"mall|{h.get('spu_id')}"
    return None


def hit_label(h: dict) -> str:
    return h.get("title") or h.get("name") or h.get("spu_id") or "?"


def _rounds_sig(h: dict):
    """玩具轮次签名:轮次名 + 款式名集合(检测「随机玩具→多款式」这类换期)。"""
    return sorted(
        f"{r.get('round_name')}:{'+'.join(sorted(c.get('name') or '?'
                                                 for c in r.get('choices') or []))}"
        for r in h.get("toy_rounds") or [])


def hit_sig(h: dict) -> dict:
    kind = KIND_BY_SOURCE.get(h.get("source"))
    if kind == "cal":
        return {"drop_time": h.get("drop_time")}
    if kind == "menu":
        return {"price": h.get("price"), "toy_rounds": _rounds_sig(h)}
    if kind == "mall":
        return {"price": h.get("price"), "point": h.get("point"),
                "down_time": h.get("down_time")}
    return {}


def snapshot_of(d: dict) -> dict:
    hits = {}
    for h in d.get("hits") or []:
        k = hit_key(h)
        if k:
            hits[k] = {"kind": KIND_BY_SOURCE[h["source"]],
                       "label": hit_label(h), "sig": hit_sig(h)}
    return {
        "generated_at": d.get("generated_at"),
        "channel": d.get("channel"), "store_code": d.get("store_code"),
        "menu_when": d.get("menu_when"),
        "calendar_error": d.get("calendar_error"),
        "mall_error": d.get("mall_error"),
        "hits": hits,
    }


# ---------- 纯函数 diff(离线可测) ----------

def diff_states(old_hits: dict, new_hits: dict) -> list[dict]:
    """两次快照的 hits → 变更列表。old/new: {key: {kind,label,sig}}。"""
    out = []
    for k, n in new_hits.items():
        o = old_hits.get(k)
        if o is None:
            out.append({"op": "new", "key": k, "label": n["label"], "kind": n["kind"],
                        "sig": n["sig"]})
            continue
        for f, nv in (n.get("sig") or {}).items():
            ov = (o.get("sig") or {}).get(f)
            if ov != nv:
                out.append({"op": "change", "key": k, "label": n["label"],
                            "kind": n["kind"], "field": f, "old": ov, "new": nv})
    for k, o in old_hits.items():
        if k not in new_hits:
            out.append({"op": "gone", "key": k, "label": o["label"], "kind": o["kind"]})
    return out


def carry_forward(old_snap: dict, new_snap: dict) -> dict:
    """某路情报源本次失败 → 该路旧条目结转进要落盘的快照,防误报消失。"""
    for err_field, kind in (("calendar_error", "cal"), ("mall_error", "mall")):
        if new_snap.get(err_field):
            for k, v in (old_snap.get("hits") or {}).items():
                if v.get("kind") == kind and k not in new_snap["hits"]:
                    new_snap["hits"][k] = v
    return new_snap


# ---------- 渲染 ----------

_FIELD_CN = {"drop_time": "开售时间", "price": "价格", "toy_rounds": "玩具轮次",
             "point": "积分", "down_time": "下架时间"}


def render_diff(changes: list[dict], snap_old: dict, snap_new: dict) -> str:
    L = []
    L.append("=" * 66)
    L.append(f"玩具情报变化 · {snap_new['generated_at']}"
             f"(上次 {snap_old.get('generated_at') if snap_old else '无(建基线)'})")
    L.append("=" * 66)
    L.append(f"  渠道 {snap_new['channel']}  门店 {toys.store_display(snap_new['store_code'])}"
             f"  菜单口径 {snap_new['menu_when']}")
    if snap_new.get("calendar_error"):
        L.append(f"  ⚠️ 活动日历拉取失败,该路旧条目已结转: {str(snap_new['calendar_error'])[:60]}")
    if snap_new.get("mall_error"):
        L.append(f"  ⚠️ 积分商城拉取失败,该路旧条目已结转: {str(snap_new['mall_error'])[:60]}")
    if not changes:
        L.append("  无变化。")
    for c in changes:
        if c["op"] == "new":
            L.append(f"  🆕 新增[{c['kind']}] {c['label']}")
            if c["kind"] == "cal" and (c.get("sig") or {}).get("drop_time"):
                L.append(f"      开售: {c['sig']['drop_time']}")
            if c["kind"] == "menu":
                L.append(f"      价格 ¥{(c.get('sig') or {}).get('price')}"
                         f"(code 渠道相关,已含本次口径)")
        elif c["op"] == "change":
            L.append(f"  🔁 变化[{c['kind']}] {c['label']} "
                     f"{_FIELD_CN.get(c['field'], c['field'])}: {c['old']} → {c['new']}")
        else:
            L.append(f"  👋 消失[{c['kind']}] {c['label']}(下架/活动结束)")
    return "\n".join(L)


# ---------- 主链路 ----------

def run(args) -> int:
    snap_path = safe_snapshot_path(args.snapshot)
    d = toys.discover(channel_hint=args.channel, store=args.store,
                      city=args.city, deep=not args.no_deep)
    snap_new = snapshot_of(d)

    snap_old = None
    if not args.reset and os.path.exists(snap_path):
        try:
            with open(snap_path, encoding="utf-8") as f:
                snap_old = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ 旧快照损坏({e}),按建基线处理")
            snap_old = None

    baseline = snap_old is None
    if snap_old and (snap_old.get("channel") != snap_new.get("channel")
                     or snap_old.get("store_code") != snap_new.get("store_code")):
        print(f"⚠️ 渠道/门店口径变了({snap_old.get('channel')}/{snap_old.get('store_code')}"
              f" → {snap_new.get('channel')}/{snap_new.get('store_code')}),"
              "菜单 code 不可比,按建基线处理")
        baseline = True

    if baseline:
        snap_to_store = carry_forward({}, snap_new)
        changes = []
    else:
        # 消失判定在「结转后」视图上做:拉取失败的路结转了旧条目,就不会误报 gone。
        snap_to_store = carry_forward(snap_old, snap_new)
        changes = diff_states(snap_old["hits"], snap_to_store["hits"])

    if args.json:
        print(json.dumps({"baseline": baseline, "changes": changes,
                          "generated_at": snap_new["generated_at"],
                          "channel": snap_new["channel"],
                          "store_code": snap_new["store_code"],
                          "menu_when": snap_new["menu_when"]},
                         ensure_ascii=False, indent=2))
    else:
        print(render_diff(changes, {} if baseline else snap_old, snap_to_store))
        if baseline:
            print(f"  (基线已建立,共 {len(snap_to_store['hits'])} 条;下次运行起报变化)")

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(snap_path), suffix=".snap.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snap_to_store, f, ensure_ascii=False, indent=2)
        os.replace(tmp, snap_path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return 0


def main():
    ap = argparse.ArgumentParser(description="玩具情报快照与差异(只读;自动落新快照)")
    ap.add_argument("--channel", default=None)
    ap.add_argument("--store", default=None)
    ap.add_argument("--city", default="上海市")
    ap.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    ap.add_argument("--reset", action="store_true", help="丢弃旧快照重建基线")
    ap.add_argument("--no-deep", action="store_true",
                    help="跳过套餐 detail(更快,不查玩具款式变化)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    sys.exit(run(a))


if __name__ == "__main__":
    main()
