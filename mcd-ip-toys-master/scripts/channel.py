#!/usr/bin/env python3
"""渠道解析与下单参数组装。(拷贝自 mcd-what-to-eat-today,逐字未改;升级时重新拷贝)

🔴 核心实测结论(2026-10-10 20:45,全部真机验证):

1. **productCode 是渠道相关的,不是全局唯一**
   同一商品「培根安格斯厚牛堡」:
     到店渠道 code = 511781
     外送渠道 code = 902060
   用错渠道的 code 会报 `60006 商品已售罄或不可售` —— 这条错误信息会误导人,
   实际是「编码不属于该渠道」,不是「卖完了」。

2. **菜单随渠道大幅变化**
   同一门店 1450523:外送 122 项 / 到店 107 项,**重叠仅 26 项**。
   跨渠道复用菜单会推荐出买不到的东西。

3. **beCode 是外送的硬要求**(官方 schema 写了,但每个接口都强制校验):
   query-meals / calculate-price / query-meal-detail 报
   `600048 外送场景下,beType=2/5/6时必传beCode`
   beCode 来自 delivery-query-stores,**不能凭空填**。

4. **modification 的 code/key 两渠道完全一致**
   培根安吉斯在到店与外送的 modification 结构逐字段相同:
   吉士100141 / 烤牛肉风味酱100179 / 切块生菜120512 / 培根103386 / 黄油120160
   → **签名代码无需区分渠道,只换 productCode 即可**。

5. **配送费有起送门槛**
   单点饮料:productPrice ¥17 + 配送费 ¥6
   组合单:productPrice ¥47.5 + 配送费 ¥0
   → 试算时必须读 deliveryPrice,不能假设「有商品就有配送费」。

6. **外送试算的返回字段与到店不同**
   到店: takeWayList(取餐方式) / enjoyable(权益) 有值
   外送: takeWayList=None, enjoyable=null, 多了 packingPrice/packingOriginalPrice
   → 确认卡渲染必须按渠道分支,外送不显示取餐方式。

用法:
    python3 order_builder.py --code 511781
    python3 order_builder.py --channel 麦乐送 --code 902060 --code 903050
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcd_client import call_tool  # noqa: E402

# ---------- 渠道定义(官方 create-order schema 原文) ----------
# orderType: 1-到店(含到店自取+得来速) / 2-外送(含麦乐送+企业团餐)
# beType:    1-到店取餐 / 2-麦乐送到家 / 5-得来速 / 6-企业团餐
CHANNELS = {
    "到店自取": {"orderType": 1, "beType": 1, "needBeCode": False, "needAddress": False},
    "得来速":   {"orderType": 1, "beType": 5, "needBeCode": True,  "needAddress": False},
    "麦乐送":   {"orderType": 2, "beType": 2, "needBeCode": True,  "needAddress": True},
    "企业团餐": {"orderType": 2, "beType": 6, "needBeCode": True,  "needAddress": True},
}
DEFAULT_CHANNEL = "到店自取"


def list_addresses():
    """取配送地址列表。只返回 addressId 与城市,不返回姓名/电话/门牌(隐私红线)。

    实测返回 data.addresses[]:addressId / contactName / fullAddress / phone
    → 本函数只透出 addressId + 解析出的城市名。

    ⚠️ 这是**内部取数**用的。要向用户复述地址,走 addresses_rich()。
    """
    return [{"addressId": a["addressId"], "city": a.get("cityLabel")}
            for a in raw_addresses()]


def raw_addresses():
    """delivery-query-addresses 原始返回,**只在本模块内流转,禁止落盘/输出**。"""
    import re
    d = call_tool("delivery-query-addresses", {}) or {}
    out = []
    for a in d.get("data", {}).get("addresses") or []:
        full = (a.get("fullAddress") or "").strip()
        m = re.search(r"(.+?市)", full)
        out.append({
            "addressId": a.get("addressId"),
            "cityLabel": m.group(1) if m else None,
            # 🔴 实测(2026-10-10):10 条 fullAddress 全部不含 contactName,
            #    是纯地理信息 → 可回显给用户本人。
            #    contactName / phone **一律不进这个 dict**,拿不到也传不出去。
            "label": full,
        })
    return out


def addresses_rich(city=None, limit=None):
    """给用户看的地址选项。**只输出 fullAddress**,永不输出姓名与手机号。

    参赛规则禁的是「他人个人信息」。用户本人的地址回显给他本人、
    只存在于当轮对话、不落盘、不进提交材料 —— 合规。
    """
    addrs = raw_addresses()
    if city:
        addrs = [a for a in addrs if a.get("cityLabel") == city] or addrs
    if limit:
        addrs = addrs[:limit]
    return [{"addressId": a["addressId"], "label": a["label"]} for a in addrs]


def pick_address(address_id, addresses=None):
    for a in (addresses or raw_addresses()):
        if a["addressId"] == address_id:
            return a
    return None


def delivery_stores(address_id, be_type=2):
    """外送可送门店。返回 storeCode / storeName / beCode / 营业时段。

    ⚠️ beCode 只能从这里取,凭空填会被接口拒(600048)。
    """
    d = call_tool("delivery-query-stores", {"addressId": address_id, "beType": be_type}) or {}
    return d.get("data") or []


def nearby_stores(be_type=1, city="上海市", keyword=None):
    """到店/得来速场景的门店。

    🔴 **实测纠正(2026-10-10 22:00)**:早前这里写的是「故意不实现,需经纬度」。
       真机跑通后发现两点:
       1. `searchType` 默认值是 1(搜索**收藏**餐厅),用户没收藏记录时报
          `600050 收藏餐厅列表为空，请您提供城市+关键词进行搜索`。
          必须显式 `searchType=2` + `city` + `keyword`。
       2. 返回对象的 `longitude` / `latitude` **恒为 0.0** —— 它是关键词搜索,
          不是真正的「附近」。`distance` 是关键词命中后的相对值。
          → 产品话术只能说「你搜的关键词命中的门店」,**不能承诺「附近的门店」**。
    """
    if not keyword:
        raise ValueError("query-nearby-stores 必须给 keyword(searchType=2 时必填)")
    d = call_tool("query-nearby-stores",
                  {"beType": be_type, "searchType": 2,
                   "city": city, "keyword": keyword}) or {}
    data = d.get("data")
    lst = data if isinstance(data, list) else \
        (data.get("stores") or data.get("list") or [])
    return [s for s in lst if s.get("storeCode")]


def store_hours(store):
    """取门店营业时段。三个字段缺一不可,少读一个晚上就会撞 600057。"""
    if not store:
        return None
    if store.get("businessStatus") is False:
        return {"open": False}
    st, et = store.get("businessStartTime"), store.get("businessEndTime")
    if not st or not et:
        return None
    return {"open": True, "start": st, "end": et}


def pick_when(store, force=None, at=None):
    """按营业时段算一个合法的 reservationDate。

    🔴 **实测(2026-10-10 21:53)**:「当前时间+2h」这种算法在晚上必挂,
       `query-meals` 报 `600057 门店可能已关闭或不在营业时间`。
       门店对象带 businessStatus / businessStartTime / businessEndTime,
       必须读。

    四档:营业中取+5min / 未到营业取开门 / 已过营业改约次日 / 已打烊直接报。
    """
    from datetime import datetime, timedelta
    if force:
        return force, "已钉死(与上一次同参数)"
    now = at or datetime.now()
    h = store_hours(store) if store else None
    if h is None:
        return (now + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M"), \
           "营业时间未知,+30min"
    if not h.get("open", True):
        raise RuntimeError(f"{store.get('storeName')} 已打烊")
    sm = int(h["start"][:2]) * 60 + int(h["start"][3:5])
    em = int(h["end"][:2]) * 60 + int(h["end"][3:5])
    nm = now.hour * 60 + now.minute
    span = f"{h['start']}-{h['end']}"
    if nm >= em:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d") + f" {h['start']}", \
               "已过营业,改约明天"
    if nm < sm:
        return f"{now:%Y-%m-%d} {h['start']}", "未到营业,取开门"
    return (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M"), \
           "营业中,+5min"


def _hm(s):
    """'HH:MM' → 当日分钟数。⚠️ 字符串只有 5 个字符,切片用 [3:5] 不是 [5:7]。"""
    return int(s[:2]) * 60 + int(s[3:5])


def _open_now(store, at=None):
    """此刻是否真的在营业。

    🔴 2026-10-10 23:15 实测坑:`businessStatus` 是**静态字段**,23:15 时
       曲阜路大悦城(22:00 闭店)的 businessStatus 仍为 true。
       → 必须把 businessStartTime / businessEndTime 和当前时刻一起算。
    """
    from datetime import datetime
    if store.get("businessStatus") is False:
        return False
    st, et = store.get("businessStartTime"), store.get("businessEndTime")
    if not st or not et:
        return bool(store.get("businessStatus", True))
    now = at or datetime.now()
    nm = now.hour * 60 + now.minute
    return _hm(st) <= nm < _hm(et)


_SLOT_RE = re.compile(r"(\d{2}:\d{2})至(\d{2}:\d{2})")


def next_slot(store, at=None):
    """从门店今日 reservationTimeOptions 里取**下一个可预约时刻**。

    🔴 铁律1的另一半:营业时段 ≠ 可预约时段。沪太路341号 06:30 开门,
       但今日可约窗口从 07:00 起 —— 约开门即送必须落在窗口里,否则 600054。
       返回 ("YYYY-MM-DD HH:MM", 依据) 或 (None, None)。
    """
    from datetime import datetime, timedelta
    now = at or datetime.now()
    nm = now.hour * 60 + now.minute
    opts = (store or {}).get("reservationTimeOptions") or []
    today = next((r for r in opts if r.get("today")), None)
    starts = [_hm(m.group(1)) for m in
              _SLOT_RE.finditer((today or {}).get("reservationOptionText") or "")]
    nxt = min((s for s in starts if s > nm), default=None)
    if nxt is not None:
        return now.strftime("%Y-%m-%d") + f" {nxt // 60:02d}:{nxt % 60:02d}", "约今日下一可送时段"
    tmr = next((r for r in opts if not r.get("today")), None)
    starts2 = [_hm(m.group(1)) for m in
               _SLOT_RE.finditer((tmr or {}).get("reservationOptionText") or "")]
    if starts2:
        s = min(starts2)
        return (now + timedelta(days=1)).strftime("%Y-%m-%d") + \
            f" {s // 60:02d}:{s % 60:02d}", "今日无可约时段,改约明日"
    return None, None


def opens_next(store, at=None):
    """下一次开门的 ("HH:MM", 是否明天)。打烊如实报用,不猜「附近」。"""
    from datetime import datetime
    now = at or datetime.now()
    st = (store or {}).get("businessStartTime")
    if not st:
        return None, False
    et = (store or {}).get("businessEndTime")
    nm = now.hour * 60 + now.minute
    if et and nm >= _hm(et):
        return st, True
    return st, False


# 临近打烊的余量阈值(分钟)。低于这个值就不再传 reservationDate。
IMMEDIATE_MARGIN = 30


def is_immediate(store, at=None, margin=IMMEDIATE_MARGIN):
    """该不该走**即时单**(create-order 不传 reservationDate)?

    🔴 2026-10-10 23:19 实测缺陷 D2(test/test-3):
       `pick_when()` 按「营业中 → 当前+5min」产出 reservationDate,
       但 23:19 算出的 23:24 **超出服务端可预约窗口**,create-order 报
       `600054 预约时间不在可预约时间范围`。
       → 「在营业时段内」不等于「可预约」。临近打烊必须走即时单。
       实测即时单(不传 reservationDate)可成功建单。
    """
    from datetime import datetime
    h = store_hours(store) if store else None
    if not h or not h.get("open", True):
        return True
    now = at or datetime.now()
    nm = now.hour * 60 + now.minute
    em = _hm(h["end"])
    return (em - nm) < margin


def pick_store(stores, prefer_code=None, at=None):
    """从候选门店里挑一家。

    优先级:此刻真在营业 > 历史主店 > businessStatus 为 true > 第一家。
    ⚠️ 不允许因为「没有营业中的店」就返回一个已打烊的 ——
       那会让 pick_when 抛「已打烊」,流程直接断在那里。
    """
    if not stores:
        return None
    now_open = [s for s in stores if _open_now(s, at)]
    if not now_open:
        return None            # 🔴 宁可返回 None,也不给打烊门店
    for s in now_open:
        if s.get("storeCode") == prefer_code:
            return s
    flag = [s for s in now_open if s.get("businessStatus", True)]
    return (flag or now_open)[0]


def resolve_channel(profile, user_hint=None):
    """给出**建议渠道**,不是替用户做决定。

    🔴 2026-10-10 21:27 走查返工:这一行曾经直接把 confidence=high 的历史众数
       当成「不用问用户」的理由,整程没问过「店里吃还是送到家」。
       渠道猜错的代价不对称 —— 送错要退单重做。
       现在它的唯一用途是:**在 S1 那一轮决定哪个选项排在最前 / 加星标**。
       S1 依然必须问。

    优先级:用户明确指定 > 历史众数(占比≥0.6 才算高置信)> 到店自取。
    """
    if user_hint:
        # 🔴 必须先判「用户是否真的指定了渠道」,再走历史兜底。
        #   否则「送到家」会命中 CHANNELS 里的「麦乐送」,却报「历史占比」的理由。
        for name in CHANNELS:
            if name in user_hint:
                return name, "用户指定"
        if any(k in user_hint for k in ("送到家", "外送", "送餐", "外卖", "快递")):
            return "麦乐送", "用户指定"
        if any(k in user_hint for k in ("到店", "自取", "堂食", "打包带走", "外带")):
            return "到店自取", "用户指定"
        if "得来速" in user_hint or "免下车" in user_hint:
            return "得来速", "用户指定"
    ch = (profile or {}).get("channel") or {}
    top = ch.get("default")
    if top and ch.get("confidence") == "high":
        return top, f"历史 {ch.get('ratio')} 占比(仅用于排序,仍需问)"
    if top:
        return top, f"历史众数但置信度低({ch.get('ratio')})(仅用于排序,仍需问)"
    return DEFAULT_CHANNEL, "无历史,默认到店自取(仍需问)"


def channel_params(channel, be_code=None, address_id=None):
    """组装 query-meals / calculate-price 用的渠道参数。

    🔴 beType=2/5/6 时 beCode 必传,否则接口报 600048。
    🔴 orderType=2 时 addressId 必传(create-order 明确要求)。
    """
    spec = CHANNELS.get(channel)
    if not spec:
        raise ValueError(f"未知渠道:{channel},可选 {list(CHANNELS)}")
    p = {"orderType": spec["orderType"], "beType": spec["beType"]}
    if spec["needBeCode"]:
        if not be_code:
            raise ValueError(
                f"{channel} 场景必传 beCode(来自 delivery-query-stores)。"
                "凭空填会被接口拒:600048"
            )
        p["beCode"] = be_code
    if spec["needAddress"]:
        if not address_id:
            raise ValueError(
                f"{channel} 场景必传 addressId(来自 delivery-query-addresses)。"
                "用户无地址时需先 delivery-create-address。"
            )
        p["addressId"] = address_id
    return p


def fetch_menu_channel(channel, store_code, when, be_code=None, address_id=None):
    """按渠道拉菜单。

    🔴 同一门店两渠道菜单重叠仅 26/122(实测),跨渠道复用会推荐出买不到的品。
    """
    p = {"storeCode": store_code, "reservationDate": when}
    p.update(channel_params(channel, be_code, address_id))
    return (call_tool("query-meals", p) or {}).get("data", {}).get("meals", {})


def explain_error(exc, channel=None):
    """把接口的误导性错误信息翻译成真实原因。

    🔴 实测踩坑(2026-10-10):`60006 商品已售罄或不可售` 实际是
       **productCode 不属于该渠道**,不是卖完了。
       同一商品「培根安格斯厚牛堡」到店 code=511781 / 外送 code=902060,
       用到店码调外送 → 报 60006。若照字面解释成「卖完了」,
       Agent 会说「这个商品卖完了,换一个」——这是错的,且用户无法自行解决。
    """
    msg = str(exc)
    if "60006" in msg:
        return ("该商品编码不属于"
                + (f"「{channel}」" if channel else "当前渠道")
                + "渠道。同一商品在不同渠道编码不同(productCode 是渠道相关的),"
                  "需重新从该渠道菜单取 code。**不是售罄**,不要按售罄解释。")
    if "600048" in msg or "60048" in msg:
        return ("外送/得来速/团餐场景必传 beCode(来自 delivery-query-stores),"
                "且不能凭空填。")
    return None


def render_amounts(data, channel):
    """按渠道渲染金额。

    实测差异:
      到店 — 有 takeWayList(取餐方式)与 enjoyable(麦金卡权益)
      外送 — takeWayList=None, enjoyable=null, 多 packingPrice(打包费)
    → 外送不显示取餐方式;打包费只在非零时显示。
    """
    L = []

    def yuan(v):
        return f"¥{(v or 0) / 100:.2f}"

    L.append(f"  商品小计: {yuan(data.get('productPrice'))}")
    if data.get("packingPrice"):
        L.append(f"  打包费:   {yuan(data.get('packingPrice'))}")
    dp = data.get("deliveryPrice")
    if dp:
        L.append(f"  配送费:   {yuan(dp)}"
                 + ("  (已达起送门槛,本单免配送费)" if dp == 0 else ""))
    elif "deliveryPrice" in data:
        L.append("  配送费:   ¥0.00")
    if data.get("discount"):
        L.append(f"  优惠:    -{yuan(data.get('discount'))}")
    L.append(f"  应付:     {yuan(data.get('price'))}")

    if CHANNELS.get(channel, {}).get("needAddress"):
        L.append("  配送:     外送到家(orderType=2)")
    else:
        tw = data.get("takeWayList") or []
        if tw:
            L.append("  取餐方式: " + " / ".join(
                f"{t.get('title')}({t.get('code')})" for t in tw))
    en = data.get("enjoyable")
    if en:
        L.append(f"  麦金卡权益: 本单抵扣 ¥{en.get('realDiscount')}"
                 f" / 本单可用额度上限 ¥{(en.get('balance') or 0) / 100:.2f}")
    return L


if __name__ == "__main__":
    print(__doc__)
    print("=" * 70)
    print("本模块为工具库,由 order_builder.py 调用。可直接运行本文件查看接口说明。")
