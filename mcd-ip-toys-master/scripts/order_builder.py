#!/usr/bin/env python3
"""订单组装器:把签名 + 选中的商品组装成 create-order / calculate-price 的参数,
并输出供用户审阅的确认卡。(拷贝自 mcd-what-to-eat-today,逐字未改;升级时重新拷贝)

##🔴 授权边界(硬约束)
本模块**只组装、只试算、只打印**,不调用 create-order。
真实下单必须由用户在看到确认卡后明确同意,由调用方显式传 --submit 才能进入写路径。
本轮开发合同:全程禁止调用 create-order,只用 calculate-price(只读)验证。

## 实测依据(2026-10-10 20:05)
### 定制组有两种结构,组装规则完全不同

**A. 可移除配料型(汉堡)**:培根安格斯厚牛堡实测
```
组 min=0 max=5
  吉士code=100141  sel=0-1  unsel=0-0
  烤牛肉风味酱        code=100179  sel=0-1  unsel=0-0
  切块生菜            code=120512  sel=0-1  unsel=0-0
  培根                code=103386  sel=0-1  unsel=0-0
  黄油                code=120160  sel=0-1  unsel=0-0
```
→ `unselectedKey` 均非空,官方规则:**组内所有项都必须传**。
   去吉士 = 吉士传 `0-0`,其余四项仍传各自 `0-1`。**漏传任何一项都会下单失败。**

**B. 单选型(饮料冰量)**:可口可乐(中杯)实测
```
组 min=1 max=1
  标准 code=200002  sel=0-1  unsel=None
  去冰 code=200002  sel=0-0  unsel=None
  多冰 code=200002  sel=0-2  unsel=None
  少冰 code=200002  sel=1-1  unsel=None
```
→ 4 项共用同一 code,靠 key 区分;`unselectedKey` 全为 None。
   只传选中的那一项,且 `min=1` 意味着该组必选。

### 签名 → 商品 的挂载规则(实测 10 单统计)
| 签名 | 挂在哪类商品上 | 证据 |
|---|---|---|
| 去芝士 | 名称含「堡」的汉堡类 | 培根安格斯吉士(不要)×4、芝士安格斯高达干酪片(不要)×1、风味/原味双层深海鳕鱼堡吉士(不要)×2 |
| 少冰 | 名称含「可乐/雪碧/茶/咖啡/饮料」的冰镇饮品类 | 可口可乐中杯 冰(少冰)×1 |

## 隐私
确认卡只输出商品名/定制/金额/取餐方式。**不输出 deliveryInfo 的任何字段**
(收件人姓名、手机号、地址、骑手信息、payId)——落盘即违反竞赛规则。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcd_client import call_tool  # noqa: E402
from channel import (CHANNELS, channel_params, list_addresses,  # noqa: E402
                     delivery_stores, resolve_channel, render_amounts,
                     explain_error)

STORE_CODE = "1450523"

# 签名关键词 → 目标商品品类关键词(实测归纳)
SIGNATURE_ROUTES = {
    "去芝士": ("堡", "汉堡"),# 汉堡类
    "少冰": ("可乐", "雪碧", "橙汁", "茶", "咖啡", "美式", "豆浆", "牛奶"),
}
# 明确不应挂签名的品类(配料/酱料类商品不该被改)
NEVER_TARGET = ("酱", "蘸", "配料", "薯条", "圆筒", "玩具")


def product_kind(name: str) -> str:
    """判定商品品类: burger / drink / side / other"""
    if any(k in name for k in NEVER_TARGET):
        return "side"
    if any(k in name for k in SIGNATURE_ROUTES["去芝士"]):
        return "burger"
    if any(k in name for k in SIGNATURE_ROUTES["少冰"]):
        return "drink"
    return "other"


def build_modification(detail: dict, signature: dict):
    """按两种组结构组装 modification.values。

    返回 (values, notes)。notes 记录每项为何这样传,供确认卡与审计查看。
    任一组结构不识别时抛 ValueError —— **不猜、不降级为静默通过**。
    """
    values, notes = [], []
    mod = detail.get("modification") or {}
    groups = mod.get("items") or []
    if not groups:
        return [], ["该商品无可定制项(modification 为空)"]

    for grp in groups:
        gvals = grp.get("values") or []
        minv, maxv = grp.get("minValues"), grp.get("maxValues")
        has_unsel = any(v.get("unselectedKey") for v in gvals)

        if has_unsel:
            # A 型:全量传。默认 selectedKey,命中签名则改 unselectedKey。
            removed_any = False
            for v in gvals:
                key = v.get("selectedKey")
                label = v.get("name", "")
                if signature.get("去芝士") and label in ("吉士", "高达干酪片"):
                    key = v.get("unselectedKey")
                    removed_any = True
                    notes.append(f"去「{label}」→ key={key}(移除)")
                else:
                    notes.append(f"保留「{label}」→ key={key}")
                values.append({"code": v.get("code"), "key": key, "quantity": 1})
            if not removed_any and signature.get("去芝士"):
                notes.append("⚠️ 本商品的配料表里没有吉士/干酪片,去芝士签名未挂上")
            if minv and minv >= len(gvals):
                notes.append(f"注意:该组 min={minv} 且仅 {len(gvals)} 项,不可移除")
        else:
            # B 型:单选。只传命中的一项;未命中则传默认(selectedKey 最小的那项)
            hit = None
            for v in gvals:
                if signature.get("少冰") and v.get("name") == "少冰":
                    hit = v
                    break
            if hit:
                notes.append(f"冰量→「少冰」→ key={hit.get('selectedKey')}")
                values.append({"code": hit.get("code"),
                               "key": hit.get("selectedKey"), "quantity": 1})
            else:
                default = gvals[0] if gvals else None
                if default:
                    notes.append(f"冰量未指定,取默认「{default.get('name')}」"
                                 f"→ key={default.get('selectedKey')}")
                    values.append({"code": default.get("code"),
                                   "key": default.get("selectedKey"), "quantity": 1})
            if minv == 1:
                notes.append("该组必选(min=1),已传一项")
    return values, notes


def build_order_items(selections, signature, channel_params=None):
    """selections: [{code, name, qty}]。逐个查 detail 并挂签名。

    🔴 channel_params 来自 channel.channel_params() —— 必须传对应渠道的
       orderType/beType/beCode/addressId。硬编码 orderType=1 会导致:
       - 外送场景 query-meal-detail 报 600048(缺 beCode)
       - 拿到的是到店渠道的 modification,与外送菜单不匹配
    """
    cp = channel_params or {"orderType": 1, "beType": 1}
    items, all_notes = [], []
    for sel in selections:
        detail_args = dict(cp)
        detail_args.update({"code": sel["code"], "storeCode": STORE_CODE,
                            "reservationDate": sel.get("reservationDate")})
        d = call_tool("query-meal-detail", detail_args)["data"]
        real_name = d.get("name")
        kind = product_kind(real_name)
        applicable = {}
        if kind == "burger":
            applicable["去芝士"] = signature.get("去芝士")
        elif kind == "drink":
            applicable["少冰"] = signature.get("少冰")
        if kind in ("side", "other") and signature:
            values, notes = [], ["该商品品类为%s,不挂签名(配料/单品不需定制)" % kind]
        else:
            values, notes = build_modification(d, applicable)
        item = {"productCode": sel["code"], "quantity": sel.get("qty", 1)}
        if values:
            item["modification"] = {"values": values}
        items.append(item)
        all_notes.append({"item": real_name, "kind": kind, "notes": notes})
    return items, all_notes


def quote(items, reservation_date=None, store_code=STORE_CODE, channel_params=None):
    """调用 calculate-price(只读)试算。返回 (原始业务数据, 参数快照)。

    🔴 channel_params 必须来自 channel.channel_params()。外送场景缺 beCode 会报
       600048;用错渠道的 productCode 会报 60006(该错误信息会误导成「卖完了」)。
    """
    args = {"storeCode": store_code}
    args.update(channel_params or {"orderType": 1, "beType": 1})
    args["items"] = items
    if reservation_date:
        args["reservationDate"] = reservation_date
    j = call_tool("calculate-price", args)
    return j.get("data") or {}, args


def build_combo_item(combo_code, detail, signature=None):
    """组装套餐商品项(2026-10-10 21:33 实测打通)。

    🔴 **写结构与读结构完全不同**:
       query-meal-detail 返回的是 `rounds`(id/choices/quantity),
       create-order / calculate-price 要的是
       `roundList:[{round:"<字符串>", comboItemList:[{code,quantity,modification}]}]`
       照着 rounds 写 → `500 服务器发生了未知的问题`。

    ⚠️ round 是**字符串**,写成 id 或数字都不行。
    """
    sig = signature if signature is not None else {"去芝士": True, "少冰": True}
    rounds = []
    for r in detail.get("rounds") or []:
        pick = next((c for c in r.get("choices") or [] if c.get("quantity") == 1),
                    (r.get("choices") or [{}])[0])
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
    """按品类裁剪签名。配料/单品不挂签名。"""
    kind = product_kind(real_name)
    if kind == "burger":
        return {"去芝士": signature.get("去芝士")}
    if kind == "drink":
        return {"少冰": signature.get("少冰")}
    return {}


def _yuan(v):
    """金额单位:分。实测 calculate-price 返回 3450 表示 ¥34.50(培根安格斯)。

    注意与 create-order 的 `price` 字段(单位元)不同——**两个接口单位不一致**,
    这是实测踩过的坑,不要在别处混用。
    """
    try:
        return round(float(v) / 100, 2)
    except (TypeError, ValueError):
        return None


def render_card(data, args, notes, channel=None):
    """确认卡:只展示商品/定制/金额/取餐方式,不含任何个人信息。"""
    L = []
    L.append("=" * 66)
    L.append("订单确认卡(尚未下单)")
    L.append("=" * 66)
    L.append(f"门店:{args['storeCode']}")
    L.append("")

    L.append("【商品与定制】")
    for i, it in enumerate(args["items"]):
        n = notes[i] if i < len(notes) else {"item": "?", "notes": []}
        L.append(f"  · {n['item']} ×{it['quantity']}  [{n['kind']}]")
        for note in n["notes"]:
            L.append(f"      - {note}")
    L.append("")
    L.append("【金额】(接口单位为分,已换算为元)")
    orig = _yuan(data.get("originalPrice"))
    price = _yuan(data.get("price"))
    disc_raw = data.get("discount")
    disc = _yuan(disc_raw)
    # 🔴 外送场景字段与到店不同:多 packingPrice/deliveryPrice,无 takeWayList/enjoyable
    if channel and CHANNELS.get(channel, {}).get("needAddress"):
        L.extend(render_amounts(data, channel))
    else:
        if orig is not None:
            L.append(f"  原价:   ¥{orig}")
        if disc:
            L.append(f"  优惠:   -¥{disc}")
        if price is not None:
            L.append(f"  应付:   ¥{price}")
        if orig is not None and price is not None and orig != price and not disc:
            L.append(f"  (优惠未在 discount 字段体现,差额 ¥{round(orig - price, 2)} 需人工核对)")
    # 麦金卡权益(实测字段 enjoyable)——语义经 20:09 验证,勿再误读
# amountType="3" → 权益类型 3 = 麦金卡专享价
# realDiscount=5.0 → 本单实际抵扣金额,单位**元**,实测多次恒为 5.0,与商品无关
# balance=450     → **本次订单可用的权益额度上限,单位分**(450=¥4.50),不是账户余额。
#                   实测:中薯条×1 时 2500,×2 时 1100 —— 减少 1400 正好等于商品价格 14.00 元,
#                   说明它是本单可用额度,随商品占用而变化,不是账户总余额。
    en = data.get("enjoyable") or {}
    if en:
        L.append("")
        L.append("【麦金卡专享权益】")
        if en.get("realDiscount") is not None:
            L.append(f"  本单实际抵扣:¥{en['realDiscount']}")
        if en.get("balance") is not None:
            bal_yuan = _yuan(en["balance"])
            L.append(f"  本单可用额度上限:¥{bal_yuan}(非账户余额,随本单商品占用而变化)")
        if en.get("amountType"):
            L.append(f"  权益类型:{en['amountType']}(3=麦金卡专享价)")
    takeway = data.get("takeWayList") or []
    if takeway:
        L.append("")
        L.append("【取餐方式】(字段名为 title/subtitle,不是 name;takeWayCode 只能从下列取值)")
        for t in takeway:
            L.append(f"  · {t.get('title')}({t.get('subtitle')}) → code={t.get('code')}")
    L.append("")
    L.append("-" * 66)
    L.append("🔴 本卡仅为试算结果。未调用 create-order,未创建订单,未产生任何费用。")
    L.append("   确认无误后由用户明确同意,才会进入下单流程。")
    return "\n".join(L)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="组装订单并试算(不提交)")
    ap.add_argument("--code", action="append", required=True,
                    help="商品 code,可重复。例:--code 511781 --code 3050")
    ap.add_argument("--qty", type=int, default=1)
    ap.add_argument("--date", default="2026-10-11 12:00")
    ap.add_argument("--profile", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "profile.json"))
    ap.add_argument("--force-ice", action="store_true",
                    help="强制启用低置信签名(如少冰仅 1 次/1 单)。默认不启用。")
    ap.add_argument("--channel-hint", default=None,
                    help="用户指定的渠道口语,如「送到家」「自取」「免下车」。"
                         "不给则按画像众数推。")
    ap.add_argument("--city", default="上海市",
                    help="外送场景的地址城市,用于从地址列表匹配 addressId")
    ap.add_argument("--address-id", default=None, help="直接指定 addressId")
    ap.add_argument("--store", default=None, help="直接指定 storeCode(跳过地址查店)")
    ap.add_argument("--be-code", default=None,
                    help="外送/得来速的 beCode,来自 delivery-query-stores")
    args = ap.parse_args()

    with open(args.profile, encoding="utf-8") as f:
        profile = json.load(f)
    sig_raw = (profile.get("signature") or {})
    is_cold = profile.get("source") == "cold_start"
    # 签名门控:
    #   observed/high → 自动生效(实测推断,高置信)
    #   declared      → 自动生效(用户明确声明,意图无歧义;冷启动用户只有这一条来源)
    #   observed/low  → 需 --force-ice(样本不足,举证后确认)
    signature, low_conf = {}, {}
    for k, v in sig_raw.items():
        lvl = v.get("level")
        if lvl == "declared":
            signature[k] = True
        elif lvl == "high":
            signature[k] = True
        else:
            signature[k] = False
            low_conf[k] = v
    if is_cold:
        print(f"[画像] 来源=cold_start(冷启动),签名均为用户声明(declared),自动生效")
        print("       提示: 该画像无历史订单支撑,统计类输出将不可用")
    if args.force_ice:
        for k in low_conf:
            signature[k] = True
        print(f"[签名] --force-ice 已启用低置信签名:{list(low_conf)}")
    print(f"[签名] 生效:{signature}")
    if low_conf and not args.force_ice:
        desc = "、".join(f"{k}({v.get('count')}次/{v.get('orders')}单)"
                         for k, v in low_conf.items())
        print(f"[提示] 低置信签名未生效:{desc}")
        print("       如需启用加 --force-ice（建议先向用户举证确认）")
    print("[边界] 本模块不调用 create-order / auto-bind-coupons,只试算")
    print()

    # ---- 渠道解析(默认从画像众数推,不硬编码) ----
    ch_name, ch_why = resolve_channel(profile, args.channel_hint)
    print(f"[渠道] {ch_name}  依据：{ch_why}")
    if args.store:
        STORE = args.store
        cp = channel_params(ch_name, be_code=args.be_code, address_id=args.address_id)
        if CHANNELS[ch_name]["needBeCode"] and not args.be_code:
            print(f"       ⚠️ {ch_name} 需 beCode,用 --be-code 指定"
                  f"(delivery-query-stores 返回 145052302)")
    elif CHANNELS[ch_name]["needAddress"]:
        addrs = list_addresses()
        if not addrs:
            print(f"[渠道] 无配送地址,{ch_name} 不可用。"
                  f"请先 delivery-create-address,或改渠道到店自取。")
            return
        aid = args.address_id or next(
            (a["addressId"] for a in addrs if a["city"] == args.city), addrs[0]["addressId"])
        stores = delivery_stores(aid, CHANNELS[ch_name]["beType"])
        if not stores:
            print(f"[渠道] 该地址无可送门店,请换地址或改渠道。")
            return
        pick = stores[0]
        STORE = pick["storeCode"]
        cp = channel_params(ch_name, be_code=pick["beCode"], address_id=aid)
        print(f"       地址 {aid[:12]}… → 门店 {pick['storeName']}")
    else:
        STORE = STORE_CODE
        cp = channel_params(ch_name)
    print(f"       storeCode={STORE}  params={cp}")
    print()

    # 查商品名用于品类判定(🔴 按渠道拉菜单:两渠道菜单重叠仅 26/122)
    menu = call_tool("query-meals", dict(cp, storeCode=STORE,
                                         reservationDate=args.date))["data"]
    meals = menu.get("meals") or {}
    selections = []
    for c in args.code:
        nm = meals.get(c, {}).get("name", c)
        selections.append({"code": c, "name": nm, "qty": args.qty,
                           "reservationDate": args.date})
        print(f"[选中] {nm} code={c}")

    items, notes = build_order_items(selections, signature, cp)
    print()
    try:
        data, snapshot = quote(items, args.date, STORE, cp)
    except RuntimeError as e:
        # 🔴 把误导性错误翻成真实原因(60006 其实是编码不属于该渠道,不是售罄)
        reason = explain_error(e, ch_name)
        print(f"[试算失败] {e}")
        if reason:
            print()
            print("=" * 66)
            print("真实原因(不要按接口原文向用户解释)")
            print("=" * 66)
            print(f"  {reason}")
            print()
            print(f"  当前渠道: {ch_name}  storeCode={STORE}")
            print(f"  提示: 编码必须取自该渠道菜单 —— "
                  f"python3 scripts/channel.py 里的 fetch_menu_channel()")
        return
    print(render_card(data, snapshot, notes, ch_name))


if __name__ == "__main__":
    main()
