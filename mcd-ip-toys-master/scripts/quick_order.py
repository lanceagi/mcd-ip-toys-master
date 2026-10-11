#!/usr/bin/env python3
"""功能2:快速下单抢购热门玩具。

两段式节奏(开售前预热 → 开售瞬间确认):
    第 1 步(预热,可提前跑):
        python3 scripts/quick_order.py --target happymeal
        → 拉菜单/详情/试算,打印订单确认卡 + 8 位确认令牌(不产生任何写操作)
    第 2 步(抢购,回贴令牌即逐单确认):
        python3 scripts/quick_order.py --target happymeal --confirm <令牌>
        → 全链路重验(菜单仍在售/价格一致)后调 create-order,打印订单号与支付时限

🔴 安全门禁(硬规则,继承父 skill):
- create-order 是写操作:必须先看到完整确认卡,再以 --confirm 令牌逐单确认;
  令牌 = sha256(门店+渠道+商品+应付价) 前 8 位,价格/商品变了令牌必然失配,拒绝下单。
- 禁止批量下单、禁止代客确认、不自动支付。MCP 全链路无扣款,
  create-order 后不付款订单会自动关闭(实测 test-3)。

本期目标(assets/targets.json,2026-10-11 实测):
- happymeal 开心乐园餐(玩具是套餐内轮次,MCP 可直接下单)
- cap     联名棒球帽(MCP 无 SKU:「任意餐品消费+39.9」的加价购在 APP/到店;
          本命令负责把「任意餐品」那一单快速下好,用 --code/--with 指定餐品)
- scarf   限定丝巾(同 cap,10月22日10:45开售)

用法:
    python3 scripts/quick_order.py --target happymeal
    python3 scripts/quick_order.py --target happymeal --variant 麦乐鸡 --toy 海绵宝宝
    python3 scripts/quick_order.py --target cap --code 511781        # 满足加价购的餐品单
    python3 scripts/quick_order.py --target happymeal --confirm a1b2c3d4
    python3 scripts/quick_order.py --code 9900016058 --reserve "2026-10-12 12:30"
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcd_client import call_tool  # noqa: E402
from channel import CHANNELS, explain_error  # noqa: E402
from order_builder import build_modification, product_kind  # noqa: E402
import collection  # noqa: E402  功能4:下单成功自动收藏玩具(失败不阻断下单)
import toys  # noqa: E402


# ---------- 组装(复用父 skill 实测规则,签名一律空:玩具单不做口味定制) ----------

def build_combo_pick(combo_code: str, detail: dict, toy_substr: str = None):
    """套餐组装。与 order_builder.build_combo_item 同规则,差异仅一点:
    玩具轮次可用 --toy 子串指定款式(本期单款式则该参数无效果)。

    🔴 写结构铁律:test-3 实测 create-order 要
       roundList:[{round:"<字符串>", comboItemList:[...]}],round 是字符串。
    """
    sig = {}
    rounds = []
    for r in detail.get("rounds") or []:
        choices = r.get("choices") or []
        pick = next((c for c in choices if c.get("quantity") == 1), None)
        rname = r.get("name") or ""
        is_toy_round = bool(toys.hit_keywords(rname, toys.TOY_ROUND_KEYWORDS))
        if is_toy_round and toy_substr:
            named = next((c for c in choices if toy_substr in (c.get("name") or "")), None)
            if named is None:
                names = "、".join(c.get("name") or "?" for c in choices)
                raise ValueError(f"玩具轮次「{rname}」没有匹配「{toy_substr}」的款式,可选:{names}")
            pick = named
        if pick is None:
            pick = choices[0] if choices else None
        if not pick or not pick.get("code"):
            continue
        entry = {"code": pick["code"], "quantity": 1}
        vals, _ = build_modification(pick, _applicable(sig, pick.get("name", "")))
        if vals:
            entry["modification"] = {"values": vals}
        rounds.append({"round": str(r["id"]), "comboItemList": [entry]})
    if not rounds:
        raise ValueError(f"套餐 {combo_code} 没有可选轮次,拒绝组装空 roundList")
    return {"productCode": combo_code, "quantity": 1, "roundList": rounds}


def _applicable(signature, real_name):
    kind = product_kind(real_name)
    if kind == "burger":
        return {"去芝士": signature.get("去芝士")}
    if kind == "drink":
        return {"少冰": signature.get("少冰")}
    return {}


def build_single(code: str, when: str, store: str, cp: dict, qty: int = 1):
    """单品组装:B 型必选组传默认值(如饮料冰量),A 型按默认保留。🔴 用本单门店查 detail。"""
    d = call_tool("query-meal-detail", dict(cp, code=code, storeCode=store,
                                            reservationDate=when)).get("data") or {}
    item = {"productCode": code, "quantity": qty}
    vals, _ = build_modification(d, {})
    if vals:
        item["modification"] = {"values": vals}
    return item, d.get("name") or code


# ---------- 确认令牌 ----------

def make_token(store: str, channel: str, items: list, pay_fen) -> str:
    canon = json.dumps({"store": store, "channel": channel, "items": items,
                        "pay": pay_fen}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:8]


def yuan(fen):
    try:
        return round(float(fen) / 100, 2)
    except (TypeError, ValueError):
        return None


# ---------- 主链路 ----------

def run(args) -> int:
    targets = toys.load_targets()
    tgt = next((t for t in targets["targets"] if t["id"] == args.target), None)
    if args.target and tgt is None:
        print(f"[受阻] 未知目标 {args.target},可选: "
              f"{[t['id'] for t in targets['targets']]} 或 --code 直接下单")
        return 2

    # 1. 渠道/门店
    name, store, cp, notes = toys.resolve_anchor(
        args.channel, args.store, args.city, args.address_id, args.be_code)
    for n in notes:
        print(f"  {n}")

    # 2. 菜单(时间梯)
    meals, when, why, _ = toys.fetch_menu_ladder(name, store, args.when,
                                                 cp.get("beCode"), cp.get("addressId"))
    print(f"  菜单 {len(meals)} 项 @ {when}({why})")

    # 3. 目标匹配
    codes = list(args.code or [])
    item_names = []
    toy_pairs = []          # [(轮次名, 款式名)] 下单成功后入藏玩具库
    combo_detail, combo_code = None, None
    if tgt:
        kws = tgt.get("menu_keywords", [])
        hits = {c: m for c, m in meals.items()
                if any(k in (m.get("name") or "") for k in kws)}
        if hits:
            if args.variant:
                hits = {c: m for c, m in hits.items()
                        if args.variant in (m.get("name") or "")} or hits
            combo_code, m = sorted(hits.items(), key=lambda kv: float(kv[1].get("currentPrice") or 9e9))[0]
            item_names.append(f"{m['name']}(¥{m['currentPrice']})")
            combo_detail = call_tool("query-meal-detail", dict(
                cp, code=combo_code, storeCode=store,
                reservationDate=when)).get("data") or {}
            trs = toys.toy_rounds(combo_detail)
            for tr in trs:
                ch = "、".join(c["name"] for c in tr["choices"])
                print(f"  玩具轮次: {tr['round_name']} → {ch}")
                pick = next((c for c in tr["choices"] if c.get("quantity") == 1),
                            (tr["choices"] or [{}])[0])
                if pick.get("name"):
                    toy_pairs.append((tr["round_name"], pick["name"]))
            if not trs:
                print("  ⚠️ 该套餐详情里没有玩具轮次(本期玩具可能未随该套餐)")
        else:
            if not codes:
                print(f"[未在售] 「{tgt['label']}」不在当前渠道/时段菜单({when})。")
                if tgt.get("mechanism"):
                    print(f"  机制: {tgt['mechanism']}")
                if tgt.get("orderable_via_mcp") is False:
                    print("  该周边 MCP 无 SKU:加价购入口在麦当劳 APP 下单页/到店。")
                    print("  本命令能做的:把你那份「任意餐品」单下好(满足加价购条件),")
                    print("  例: python3 scripts/quick_order.py --target cap --code <餐品code>")
                else:
                    print("  可换 --when / --channel / --store,或 --watch 盯上架"
                          "(python3 scripts/toys.py --watch 30)。")
                return 1
            print(f"  ⚠️ 目标 {tgt['id']} 不在菜单,按显式 --code 下单")
    if not codes and not combo_code:
        print("[受阻] 没有可下单的商品:给 --target 或 --code。")
        return 2

    # 4. 组装 + 试算
    items = []
    if combo_code:
        items.append(build_combo_pick(combo_code, combo_detail, args.toy))
    for c in codes:
        it, nm = build_single(c, when, store, cp, args.qty)
        items.append(it)
        item_names.append(nm)
    try:
        data, snap = (lambda: (_quote(items, args, store, cp, when)))()
    except RuntimeError as e:
        print(f"[试算失败] {e}")
        reason = explain_error(e, name)
        if reason:
            print(f"  转译: {reason}")
        return 1
    pay = data.get("price")
    token = make_token(store, name, items, pay)
    print()
    print(_card(item_names, data, store, name, when, args, token))

    # 5. 确认门禁
    if not args.confirm:
        print("确认无误后,原命令追加 --confirm "
              f"{token} 即完成逐单确认并下单。")
        return 0
    if args.confirm != token:
        print(f"[拒绝] 令牌失配(收到 {args.confirm},本单应为 {token})。"
              "商品或价格已变化,请重跑不带 --confirm 的命令看新确认卡。")
        return 1

    # 6. create-order(唯一写操作;两段式第二段=用户逐单确认)
    order_args = {"storeCode": store, "orderType": cp["orderType"], "beType": cp["beType"]}
    if cp.get("beCode"):
        order_args["beCode"] = cp["beCode"]
    if cp.get("addressId"):
        order_args["addressId"] = cp["addressId"]
    order_args["items"] = items
    if args.reserve:
        order_args["reservationDate"] = args.reserve
    if args.remark and cp["orderType"] == 2:
        order_args["remark"] = args.remark
    tw = data.get("takeWayList") or []
    tw_codes = [t.get("code") for t in tw]
    if args.take_way:
        # 🔴 铁律5:takeWayCode 只能取试算返回的 takeWayList。
        #    凭记忆/别单的 code 传进来,轻则 500,重则错误取餐方式成单。
        if args.take_way not in tw_codes:
            print(f"[拒绝] --take-way {args.take_way} 不在本单试算返回的取餐方式里"
                  f"({tw_codes or '空'})。取餐方式只能取试算返回值(铁律5),"
                  "请改用其中之一后重跑。")
            return 1
        order_args["takeWayCode"] = args.take_way
    elif tw:
        order_args["takeWayCode"] = tw[0].get("code")
        print(f"[取餐方式] 默认取试算返回第一项: {tw[0].get('title')}({tw[0].get('code')}),"
              "可用 --take-way 覆盖")
    try:
        j = call_tool("create-order", order_args)
    except RuntimeError as e:
        print(f"[下单失败] {e}")
        reason = explain_error(e, name)
        if reason:
            print(f"  转译: {reason}")
        if "600054" in str(e):
            print("  600054=预约时间不在窗口:去掉 --reserve 改即时单(test-3 已验证即时单可成)")
        return 1
    od = j.get("data") or {}
    print()
    print("=" * 66)
    print("✅ 订单已创建(未扣款)")
    print("=" * 66)
    print(f"  orderId: {od.get('orderId')}")
    if od.get("pickupCode"):
        print(f"  取餐码: {od.get('pickupCode')}")
    if od.get("expirePayTime"):
        print(f"  支付时限: {od.get('expirePayTime')}(不付自动关闭,不扣钱)")
    if args.show_pay_link and od.get("payH5Url"):
        print(f"  支付链接(仅本人使用): {od.get('payH5Url')}")
    else:
        print("  支付:打开麦当劳 APP「我的订单」付款(默认不回显支付链接)")
    print("  付款后可回查: python3 scripts/quick_order.py --query-order <orderId>")
    if toy_pairs:
        # 功能4:默默收藏。🔴 记录失败绝不影响订单,只提示。
        try:
            es = collection.record_order_toys(
                [n for _, n in toy_pairs],
                series="、".join(sorted({r for r, _ in toy_pairs})),
                store=toys.store_display(store), channel=name,
                order_id=od.get("orderId"))
            print(f"🧸 玩具已默默记入本地玩具库(assets/collection.json,本次 {len(es)} 件;"
                  "未付款取消的可用 collection.py remove 清理)")
        except Exception as e:
            print(f"⚠️ 玩具库记录失败(不影响订单): {e}")
    return 0


def _quote(items, args, store, cp, when):
    from order_builder import quote
    return quote(items, when if args.reserve is None else args.reserve,
                 store, cp)


def _card(item_names, data, store, channel, when, args, token) -> str:
    L = []
    L.append("=" * 66)
    L.append("抢购订单确认卡(尚未下单)")
    L.append("=" * 66)
    L.append(f"门店:{toys.store_display(store)}  渠道:{channel}")
    L.append(f"菜单口径:{when}" + (f"  预约下单:{args.reserve}" if args.reserve else "  即时单(不传 reservationDate)"))
    L.append("")
    L.append("【商品】")
    for n in item_names:
        L.append(f"  · {n} ×{args.qty if not args.target else 1}")
    L.append("")
    L.append("【金额】")
    pay, orig = yuan(data.get("price")), yuan(data.get("originalPrice"))
    if orig is not None:
        L.append(f"  原价: ¥{orig}")
    if data.get("discount"):
        L.append(f"  优惠: -¥{yuan(data.get('discount'))}")
    if pay is not None:
        L.append(f"  应付: ¥{pay}")
    tw = data.get("takeWayList") or []
    if tw:
        L.append(f"  取餐方式候选: " + " / ".join(
            f"{t.get('title')}({t.get('code')})" for t in tw))
    L.append("")
    L.append(f"确认令牌: {token}")
    L.append("-" * 66)
    L.append("🔴 未下单。追加 --confirm <令牌> 才会调 create-order(写操作)。")
    return "\n".join(L)


def query_order(order_id: str) -> int:
    j = call_tool("query-order", {"orderId": order_id})
    d = j.get("data") or {}
    print(f"orderId: {d.get('orderId')}")
    print(f"状态: {d.get('orderStatus')}")
    print(f"金额: 原价 {d.get('totalAmount')} / 实付 {d.get('payAmount')}")
    print(f"创建时间: {d.get('createTime')}")
    print("(按隐私红线,不输出 deliveryInfo / payId)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="快速下单抢购热门玩具(两段式确认)")
    ap.add_argument("--target", default=None,
                    help="targets.json 里的目标 id:happymeal/cap/scarf")
    ap.add_argument("--code", action="append",
                    help="直接按 code 下单(渠道相关),可重复")
    ap.add_argument("--variant", default=None, help="乐园餐变体子串,如 麦乐鸡/鱼排堡/汉堡")
    ap.add_argument("--toy", default=None, help="玩具轮次款式子串(多款式期用)")
    ap.add_argument("--qty", type=int, default=1)
    ap.add_argument("--channel", default="到店自取")
    ap.add_argument("--store", default=None)
    ap.add_argument("--city", default="上海市")
    ap.add_argument("--address-id", default=None)
    ap.add_argument("--be-code", default=None)
    ap.add_argument("--when", default=None, help="菜单时间口径(query-meals 用)")
    ap.add_argument("--reserve", default=None,
                    help="预约下单时间(create-order 的 reservationDate);不给则即时单")
    ap.add_argument("--take-way", default=None, help="takeWayCode,只能取试算返回值")
    ap.add_argument("--remark", default=None, help="外送备注(如 放门口),仅 orderType=2")
    ap.add_argument("--confirm", default=None, metavar="TOKEN", help="确认令牌=逐单确认")
    ap.add_argument("--show-pay-link", action="store_true", help="回显支付链接(默认不)")
    ap.add_argument("--query-order", default=None, metavar="ORDER_ID")
    args = ap.parse_args()
    if args.query_order:
        sys.exit(query_order(args.query_order))
    if not args.target and not args.code:
        ap.error("必须给 --target 或 --code 之一")
    sys.exit(run(args))


if __name__ == "__main__":
    main()
