#!/usr/bin/env python3
"""离线测试(假 API,零网络)。fixture 全部取自 2026-10-11 01:20-01:22 真机探针数据。

跑法:python3 scripts/test_toys.py   → 退出码 0 = 全绿
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import channel as ch_mod          # noqa: E402
import collection as coll_mod     # noqa: E402
import dialog as dlg              # noqa: E402
import intel_diff as idiff        # noqa: E402
import order_builder as ob_mod    # noqa: E402
import quick_order as qo          # noqa: E402
import toys                       # noqa: E402

# ---------- fixture(真机实测样本) ----------

CAL_MD = """### 当前时间：2026-10-11 01:20:34

### 活动列表：


#### 2026年10月11日 今日




-   **活动标题**：超值𝟗.𝟗元早餐两件套陪你开工啦😋
    **活动内容介绍**：早八的快乐，一堡一咖已就位🍔☕
𝟏𝟎月𝟖日至𝟏𝟎月𝟐𝟏日
🍔周一至周五早餐堡轮流上早班
☕鲜萃咖啡搭档到位
凭券两件套只要9.9元

-   **活动标题**：麦当劳 X PEACEMINUSONE
    **活动内容介绍**：GD同款联名复古棒球帽
任意餐品消费加39.9元即可得

-   **活动标题**：第三周周边即将开售✨限定主题丝巾！
    **活动内容介绍**：丝巾搭配棒球帽的潮流谁懂😎
10月22日10:45开售
"""

MENU = {
    "9900016058": {"name": "鱼排堡开心乐园餐", "currentPrice": "24", "originalPrice": "24",
                   "canWithOrder": False},
    "9900016056": {"name": "麦乐鸡开心乐园餐", "currentPrice": "25", "originalPrice": "25",
                   "canWithOrder": False},
    "9900016057": {"name": "汉堡开心乐园餐", "currentPrice": "23.5", "originalPrice": "23.5",
                   "canWithOrder": False},
    "511781": {"name": "培根安格斯厚牛堡", "currentPrice": "28", "originalPrice": "28"},
    "5022": {"name": "猪柳蛋麦满分", "currentPrice": "18", "originalPrice": "18"},
}

DETAIL = {
    "name": "鱼排堡开心乐园餐", "price": None, "supportModify": False,
    "rounds": [
        {"id": 1, "name": "鱼排堡",
         "choices": [{"name": "鱼排堡", "code": "504642", "quantity": 1, "isDefault": 1}]},
        {"id": 2, "name": "迷你薯条",
         "choices": [{"name": "迷你薯条", "code": "504643", "quantity": 1, "isDefault": 1}]},
        {"id": 3, "name": "选择开心乐园餐小食",
         "choices": [{"name": "小杯玉米杯", "code": "4437", "quantity": 1, "isDefault": 1},
                     {"name": "苹果片一袋(60g)", "code": "6102", "quantity": 0, "isDefault": 1}]},
        {"id": 4, "name": "选择开心乐园餐饮料",
         "choices": [{"name": "纯牛奶", "code": "3755", "quantity": 1, "isDefault": 1},
                     {"name": "100%苹果汁", "code": "6362", "quantity": 0, "isDefault": 0}]},
        {"id": 5, "name": "海绵宝宝×航海王系列玩具",
         "choices": [{"name": "海绵宝宝×航海王系列玩具", "code": "521991", "quantity": 1,
                      "isDefault": 1}]},
    ],
}

QUOTE = {"originalPrice": 2400, "price": 2400, "discount": 0,
         "takeWayList": [{"title": "堂食", "subtitle": "eat-in", "code": "eat-in"},
                         {"title": "外带", "subtitle": "take-in-store",
                          "code": "take-in-store"}]}

MALL = [{"spuName": "麦当劳亲子读书会", "spuId": 1830, "point": "0", "price": "45",
         "catName": "读书会", "selling": "亲子阅读", "upTime": "2023-03-29 00:00:00",
         "downTime": "2026-12-30 23:59:59"},
        {"spuName": "限定玩具礼盒", "spuId": 99, "point": "0", "price": "39.9",
         "catName": "周边", "selling": "联名玩具", "upTime": "2026-10-01 00:00:00",
         "downTime": "2026-10-31 23:59:59"}]

# dialog 渠道分流 fixtures(形状按 channel.py 实测合同:
# delivery-query-addresses / delivery-query-stores / query-nearby-stores)
ADDRESSES = {"data": {"addresses": [
    # 地址为虚构示范数据(真实配送地址不进仓库;保留「上海市+区」前缀供城市解析)
    {"addressId": "ADDR-1", "fullAddress": "上海市静安区示范路1号"},
    {"addressId": "ADDR-2", "fullAddress": "上海市浦东新区示范大道2号"},
    {"addressId": "ADDR-3", "fullAddress": "上海市徐汇区示范街3号"},
    {"addressId": "ADDR-4", "fullAddress": "上海市黄浦区示范道4号"},
]}}

DELIVERY_STORES = {"data": [
    {"storeCode": "1450523", "storeName": "麦当劳上海静安沪太路341号餐厅",
     "beCode": "BE-A", "businessStartTime": "07:00", "businessEndTime": "23:00"},
    {"storeCode": "1450664", "storeName": "麦当劳上海和典创意园餐厅",
     "beCode": "BE-B", "businessStartTime": "07:00", "businessEndTime": "23:00"},
]}

CLOSED_DELIVERY_STORES = {"data": [
    {"storeCode": "1450900", "storeName": "麦当劳上海曲阳路餐厅",
     "beCode": "BE-C", "businessStartTime": "07:00", "businessEndTime": "23:00"},
]}

NEARBY = {"data": {"stores": DELIVERY_STORES["data"]}}

FAILS = []


def check(name, cond, detail=""):
    status = "✅" if cond else "❌"
    print(f"  {status} {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# ---------- T1-T6:发现链路 ----------

def t_calendar():
    acts = toys.parse_calendar(CAL_MD)
    check("T1a 日历解析出 3 个活动块", len(acts) == 3, f"got {len(acts)}")
    check("T1b 标题正确", acts[1]["title"] == "麦当劳 X PEACEMINUSONE", acts[1]["title"])
    hits = toys.scan_calendar(CAL_MD, toys.load_targets())
    check("T2a 活动命中 2 条(棒球帽+丝巾,早餐券无玩具关键词)", len(hits) == 2,
          str([h["title"] for h in hits]))
    scarf = next(h for h in hits if "丝巾" in h["title"])
    check("T2b 丝巾开售时间抽取", scarf["drop_time"] and "10:45" in scarf["drop_time"],
          str(scarf["drop_time"]))
    cap = next(h for h in hits if "PEACEMINUSONE" in h["title"])
    check("T2c 棒球帽命中本期目标 cap", "cap" in cap["preset_target_ids"],
          str(cap["preset_target_ids"]))


def t_menu():
    tg = toys.load_targets()
    hits = toys.scan_menu(MENU, tg)
    check("T3a 菜单命中 3 款乐园餐", len(hits) == 3, f"got {len(hits)}")
    hm = next(h for h in hits if h["code"] == "9900016058")
    check("T3b 乐园餐挂上本期目标 happymeal", "happymeal" in hm["preset_target_ids"])
    check("T3c code 保留(渠道相关)", hm["code"] == "9900016058")
    check("T3d 普通餐品不误报", not any("安格斯" in h["name"] for h in hits))
    trs = toys.toy_rounds(DETAIL)
    check("T4a 玩具轮次提取:第 5 轮", len(trs) == 1 and trs[0]["round_id"] == 5,
          str(trs))
    check("T4b 玩具款式 code", trs[0]["choices"][0]["code"] == "521991")
    mh = toys.scan_mall(MALL, tg)
    check("T5 商城关键词命中礼盒、读书会不误报", len(mh) == 1 and mh[0]["spu_id"] == 99,
          str(mh))
    ranked = toys.rank(toys.scan_menu(MENU, tg) + toys.scan_calendar(CAL_MD, tg)
                       + toys.scan_mall(MALL, tg))
    presets = [bool(e.get("preset_target_ids")) for e in ranked]
    check("T6 排序:本期目标命中全部排在非目标之前",
          presets == sorted(presets, reverse=True), str(presets))


# ---------- T7-T8:组装与令牌 ----------

def t_build():
    item = qo.build_combo_pick("9900016058", DETAIL)
    rl = item["roundList"]
    check("T7a roundList 5 轮且 round 为字符串",
          len(rl) == 5 and all(isinstance(r["round"], str) for r in rl))
    toy_round = next(r for r in rl if r["round"] == "5")
    check("T7b 玩具轮次进入下单结构",
          toy_round["comboItemList"][0]["code"] == "521991")
    food_round = next(r for r in rl if r["round"] == "3")
    check("T7c 小食轮取 quantity=1 的默认项(玉米杯)",
          food_round["comboItemList"][0]["code"] == "4437")
    try:
        qo.build_combo_pick("9900016058", DETAIL, toy_substr="不存在的款式")
        check("T7d --toy 无匹配时报错拒绝组装", False)
    except ValueError:
        check("T7d --toy 无匹配时报错拒绝组装", True)
    t1 = qo.make_token("1450523", "到店自取", [item], 2400)
    t2 = qo.make_token("1450523", "到店自取", [item], 2400)
    t3 = qo.make_token("1450523", "到店自取", [item], 2500)
    check("T8a 令牌确定性(同参同值)", t1 == t2)
    check("T8b 价格变化令牌失配", t1 != t3)
    check("T8c 令牌 8 位十六进制", len(t1) == 8 and all(c in "0123456789abcdef" for c in t1))


# ---------- T9-T11:quick_order.run() 门禁与载荷(假 API 全链路) ----------

class Args:
    def __init__(self, **kw):
        self.target = kw.get("target")
        self.code = kw.get("code")
        self.variant = kw.get("variant")
        self.toy = kw.get("toy")
        self.qty = kw.get("qty", 1)
        self.channel = kw.get("channel", "到店自取")
        self.store = kw.get("store", "1450523")
        self.city = kw.get("city", "上海市")
        self.address_id = kw.get("address_id")
        self.be_code = None
        self.when = "2026-10-12 12:30"
        self.reserve = kw.get("reserve")
        self.take_way = kw.get("take_way")
        self.remark = kw.get("remark")
        self.confirm = kw.get("confirm")
        self.show_pay_link = False


def install_fakes(create_calls, dstores=None, addresses=None, nearby=None):
    # 藏品文件指向本测试专用临时路径:dialog 玩具库/quick_order 自动入藏都不碰真藏品
    import tempfile as _tf
    _fd, _tmp = _tf.mkstemp(suffix=".collection.json")
    os.close(_fd)
    if os.path.exists(_tmp):
        os.unlink(_tmp)
    coll_mod.COLLECTION_PATH = _tmp

    def fake_call_tool(name, arguments=None, timeout=30):
        if name == "query-meals":
            return {"data": {"meals": MENU}}
        if name == "query-meal-detail":
            return {"data": DETAIL}
        if name == "calculate-price":
            return {"data": QUOTE}
        if name == "delivery-query-addresses":
            return addresses if addresses is not None else ADDRESSES
        if name == "delivery-query-stores":
            return dstores if dstores is not None else DELIVERY_STORES
        if name == "query-nearby-stores":
            return nearby if nearby is not None else NEARBY
        if name == "create-order":
            create_calls.append(dict(arguments))
            return {"data": {"orderId": "TEST_ORDER_1", "pickupCode": "28",
                             "expirePayTime": "2026-10-12 12:45:00"}}
        raise AssertionError(f"假 API 未覆盖 {name} {arguments}")

    def fake_text(name, arguments=None, timeout=30):
        if name == "campaign-calendar":
            return CAL_MD
        raise AssertionError(f"假 API(text) 未覆盖 {name}")

    ch_mod.call_tool = fake_call_tool
    toys.call_tool = fake_call_tool
    toys.call_tool_text = fake_text
    qo.call_tool = fake_call_tool
    ob_mod.call_tool = fake_call_tool


def t_run_gate():
    create_calls = []
    install_fakes(create_calls)
    rc = qo.run(Args(target="happymeal"))
    check("T9a 无 --confirm:只出确认卡,rc=0", rc == 0)
    check("T9b 无 --confirm:零写操作", not create_calls)
    rc = qo.run(Args(target="happymeal", confirm="deadbeef"))
    check("T9c 错令牌:rc=1", rc == 1)
    check("T9d 错令牌:零写操作", not create_calls)
    # 正确令牌:run() 默认选最便宜乐园餐(汉堡 9900016057 ¥23.5),令牌按实际选中项算
    token = qo.make_token("1450523", "到店自取",
                          [qo.build_combo_pick("9900016057", DETAIL)], 2400)
    rc = qo.run(Args(target="happymeal", confirm=token))
    check("T9e 正确令牌:rc=0 且恰好一次 create-order", rc == 0 and len(create_calls) == 1,
          f"rc={rc} calls={len(create_calls)}")
    if create_calls:
        a = create_calls[0]
        check("T10a 载荷含 storeCode/orderType/beType",
              a.get("storeCode") == "1450523" and a.get("orderType") == 1
              and a.get("beType") == 1, str(a))
        check("T10b 即时单不传 reservationDate", "reservationDate" not in a)
        check("T10c takeWayCode 取自试算 takeWayList(实测 code 为字符串)",
              a.get("takeWayCode") == "eat-in")
        it = a["items"][0]
        check("T10d items 走 roundList(字符串 round)",
              isinstance(it.get("roundList"), list)
              and it["roundList"][0]["round"] == "1")
        check("T10e 玩具轮次在载荷里(round=5, code=521991)",
              any(r["round"] == "5" and r["comboItemList"][0]["code"] == "521991"
                  for r in it["roundList"]))


def t_run_cap_boundary():
    create_calls = []
    install_fakes(create_calls)
    rc = qo.run(Args(target="cap"))
    check("T11a cap 无 SKU:rc=1 如实退出", rc == 1)
    check("T11b cap 无 SKU:零写操作", not create_calls)
    rc = qo.run(Args(target="cap", code=["511781"]))
    token = qo.make_token("1450523", "到店自取",
                          [{"productCode": "511781", "quantity": 1}], 2400)
    rc2 = qo.run(Args(target="cap", code=["511781"], confirm=token))
    check("T11c cap --code 显式下单:确认后可成单(满足加价购条件的餐品单)",
          rc == 0 and rc2 == 0 and len(create_calls) == 1,
          f"rc={rc} rc2={rc2} calls={len(create_calls)}")


def t_when_ladder():
    w = toys.auto_when(now=toys.datetime(2026, 10, 11, 1, 20))
    check("T12a 深夜时间梯:先 now+5min",
          w[0][1] == "当前+5min" and w[0][0] == "2026-10-11 01:25", str(w[0]))
    check("T12b 次档为次日 11:30 正餐", w[1][0] == "2026-10-12 11:30", str(w[1]))


# ---------- T13-T17:quick_order 铁律5 + dialog 渠道分流(品牌点单话术) ----------

def _capture_checkout(d):
    """跑 d.checkout(),截获传给 quick_order.run 的参数(不触网、零写操作)。"""
    captured = {}
    real_run = qo.run

    def fake_run(a):
        captured.update(vars(a))
        return 0
    qo.run = fake_run
    try:
        d.checkout()
    finally:
        qo.run = real_run
    return captured


def t_takeway_guard():
    create_calls = []
    install_fakes(create_calls)
    token = qo.make_token("1450523", "到店自取",
                          [qo.build_combo_pick("9900016057", DETAIL)], 2400)
    rc = qo.run(Args(target="happymeal", confirm=token, take_way="no-such-way"))
    check("T13a 铁律5:--take-way 不在试算 takeWayList 里 → 拒绝", rc == 1)
    check("T13b 拒绝时零写操作", not create_calls)
    rc = qo.run(Args(target="happymeal", confirm=token, take_way="take-in-store"))
    check("T13c 合法 take-way 放行成单", rc == 0 and len(create_calls) == 1,
          f"rc={rc} calls={len(create_calls)}")
    if create_calls:
        check("T13d 载荷 takeWayCode=用户所选外带",
              create_calls[0].get("takeWayCode") == "take-in-store")


def t_dialog_instore():
    create_calls = []
    install_fakes(create_calls)
    d = dlg.Dialog(target="happymeal", at=toys.datetime(2026, 10, 12, 12, 0))
    t = d.open()
    check("T14a 启动分流:买玩具/看玩具库", d.options == ["买玩具", "看看我的玩具库"],
          str(d.options))
    check("T14b 品牌话术迎宾(喜欢您来+玩具上新啦)",
          "喜欢您来" in t.text and "玩具上新啦" in t.text, t.text.splitlines()[0])
    t = d.reply("买玩具")
    check("T14a2 买玩具分支→渠道必问", d.state == "T1"
          and d.options == ["到店自取", "麦乐送"], f"{d.state} {d.options}")
    t = d.reply("1")
    check("T14c 到店分支先确认门店(默认店)", d.state == "T2"
          and d.options == ["就这家", "换一家"] and d.store_code == "1450523",
          f"{d.state} {d.store_code}")
    check("T14c2 默认门店显示店名而非裸编码", "沪太路" in t.text
          and "门店 1450523" not in t.text, t.text.splitlines()[0])
    t = d.reply("换一家")
    check("T14d 换一家轮换到关键词门店", d.store_code == "1450664", str(d.store_code))
    check("T14e 换店轮展示店名(预算内)", "和典" in t.text)
    t = d.reply("就这家")
    check("T14f 门店确认后问取餐方式", d.state == "T2W"
          and d.options == ["堂食", "外带"], f"{d.state} {d.options}")
    t = d.reply("外带")
    check("T14g 选完取餐方式→T5 出卡就绪", d.ready and d.state == "T5"
          and d.take_way == "take-in-store")
    cap = _capture_checkout(d)
    check("T14h 出卡参数透传:渠道/门店/取餐方式",
          cap.get("channel") == "到店自取" and cap.get("store") == "1450664"
          and cap.get("take_way") == "take-in-store", str(cap))
    check("T14i 到店单不带地址与放置点",
          cap.get("address_id") is None and cap.get("remark") is None)
    check("T14j 不变量全过", d.invariants() == [], str(d.invariants()))
    check("T14k 对话全程零写操作", not create_calls)


def t_dialog_delivery():
    create_calls = []
    install_fakes(create_calls)
    d = dlg.Dialog(target="happymeal", at=toys.datetime(2026, 10, 12, 12, 0))
    d.open()
    d.reply("买玩具")
    d.reply("2")
    check("T15a 外送分支先问地址(S3A 纪律:先地址后门店)",
          d.state == "T3A" and len(d.options) == 4 and d.options[3] == "更多地址",
          str(d.options))
    t = d.reply("更多地址")
    check("T15b 地址分页:第2页只剩第4个", d.options == ["黄浦区示范道4号"],
          str(d.options))
    t = d.reply("1")
    check("T15c 地址确认后复诵门店(确认/换店/换地址)",
          d.state == "T3B" and d.options == ["确认", "换店", "换地址"]
          and "沪太路" in t.text, f"{d.state} {d.options}")
    d.reply("换店")
    check("T15d 换店轮换到另一家可送门店", d.store_code == "1450664",
          str(d.store_code))
    t = d.reply("确认")
    check("T15e 确认后问放置点(→remark)",
          d.state == "T4" and d.options == ["门口", "前台", "门口+电话"],
          str(d.options))
    d.reply("门口")
    cap = _capture_checkout(d)
    check("T15f 出卡参数:麦乐送/地址/放置点/门店",
          cap.get("channel") == "麦乐送" and cap.get("address_id") == "ADDR-4"
          and cap.get("remark") == "放门口" and cap.get("store") == "1450664",
          str(cap))
    check("T15g 外送单不带堂食/外带取餐方式", cap.get("take_way") is None)
    check("T15h 不变量全过", d.invariants() == [], str(d.invariants()))
    check("T15i 对话全程零写操作", not create_calls)


def t_dialog_closed():
    create_calls = []
    install_fakes(create_calls, dstores=CLOSED_DELIVERY_STORES)
    d = dlg.Dialog(target="happymeal", at=toys.datetime(2026, 10, 12, 2, 0))
    d.open()
    d.reply("买玩具")
    d.reply("2")
    t = d.reply("1")
    check("T16a 可送门店全打烊→T3Z 如实报开门时间",
          d.state == "T3Z" and "开门" in t.text
          and d.options == ["约开门后送", "换地址", "先不送了"],
          f"{d.state} {d.options}")
    d.reply("约开门后送")
    check("T16b 约开门后送→预约单→放置点", d.state == "T4" and d.reserve)
    d.reply("前台")
    cap = _capture_checkout(d)
    check("T16c 预约时刻与放置点透传",
          cap.get("reserve") == d.reserve and cap.get("remark") == "放前台",
          f"reserve={cap.get('reserve')}")
    d2 = dlg.Dialog(target="happymeal", at=toys.datetime(2026, 10, 12, 2, 0))
    d2.open()
    d2.reply("买玩具")
    d2.reply("2")
    d2.reply("1")
    t = d2.reply("先不送了")
    check("T16d 先不送了→品牌送客语收尾",
          d2.state == "T9" and "喜欢您来" in t.text, d2.state)


def t_dialog_no_address():
    create_calls = []
    install_fakes(create_calls, addresses={"data": {"addresses": []}})
    d = dlg.Dialog(target="happymeal", at=toys.datetime(2026, 10, 12, 12, 0))
    d.open()
    d.reply("买玩具")
    t = d.reply("2")
    check("T17a 无配送地址:如实报告不崩溃", d.state == "T3A" and "地址" in t.text,
          d.state)
    check("T17b 给出路:重新选渠道", d.options == ["重新选渠道"], str(d.options))
    t = d.reply("重新选渠道")
    check("T17c 回到渠道分流重问", d.state == "T1"
          and d.options == ["到店自取", "麦乐送"], f"{d.state} {d.options}")


# ---------- T18:intel_diff 情报变化监测(纯函数,零网络) ----------

def t_store_display():
    check("T19a store_display 已知编码→店名(编码)",
          toys.store_display("1450523") == "上海静安沪太路341号(1450523)",
          toys.store_display("1450523"))
    check("T19b store_name 问题行用短店名(不含编码括号)",
          toys.store_name("1450523") == "上海静安沪太路341号")
    check("T19c 未知编码不编造,原样返回",
          toys.store_display("9999999") == "9999999"
          and toys.store_name(None) == "")


def t_intel_diff():
    old = {
        "cal|麦当劳 X PEACEMINUSONE": {"kind": "cal", "label": "麦当劳 X PEACEMINUSONE",
                                       "sig": {"drop_time": "2026年10月11日 10:45"}},
        "menu|9900016057": {"kind": "menu", "label": "汉堡开心乐园餐",
                            "sig": {"price": "23.5",
                                    "toy_rounds": ["海绵宝宝×航海王系列玩具:海绵宝宝×航海王系列玩具"]}},
        "mall|6370": {"kind": "mall", "label": "麦当劳过家家派对",
                      "sig": {"price": "55", "point": "0", "down_time": "2027-05-22 23:59:59"}},
    }
    same = json.loads(json.dumps(old))
    check("T18a 完全一致 → 零变化", idiff.diff_states(old, same) == [])
    new = json.loads(json.dumps(old))
    new["cal|麦当劳 X PEACEMINUSONE"]["sig"]["drop_time"] = "2026年10月22日 10:45"
    new["menu|9900016057"]["sig"]["price"] = "25.5"
    new["cal|全新联名活动"] = {"kind": "cal", "label": "全新联名活动",
                              "sig": {"drop_time": "2026年10月30日 10:45"}}
    del new["mall|6370"]
    ch = idiff.diff_states(old, new)
    ops = sorted((c["op"], c["kind"]) for c in ch)
    check("T18b 三类变化各检出一条", ops == [("change", "cal"), ("change", "menu"),
                                            ("gone", "mall"), ("new", "cal")], str(ops))
    drop = next(c for c in ch if c["op"] == "change" and c["field"] == "drop_time")
    check("T18c 开售时间变化带旧值新值",
          drop["old"] == "2026年10月11日 10:45"
          and drop["new"] == "2026年10月22日 10:45")
    # 拉取失败结转:日历报错时旧活动条目不被误报消失(商城路正常、条目仍在)
    snap_new_err = {"calendar_error": "timeout", "hits": {
        "menu|9900016057": new["menu|9900016057"],
        "mall|6370": old["mall|6370"]}}
    carried = idiff.carry_forward({"hits": old}, json.loads(json.dumps(snap_new_err)))
    gone = [c for c in idiff.diff_states(old, carried["hits"]) if c["op"] == "gone"]
    check("T18d 日历拉取失败→旧活动条目结转,零误报消失",
          "cal|麦当劳 X PEACEMINUSONE" in carried["hits"] and not gone)
    # 玩具轮次款式变化(随机→多款式换期)
    new2 = json.loads(json.dumps(old))
    tr = new2["menu|9900016057"]["sig"]["toy_rounds"]
    new2["menu|9900016057"]["sig"]["toy_rounds"] = [
        "海绵宝宝×航海王系列玩具:海绵宝宝+航海王+派大星"]
    ch2 = idiff.diff_states(old, new2)
    check("T18e 玩具轮次款式变化检出",
          len(ch2) == 1 and ch2[0]["field"] == "toy_rounds", str(ch2))
    # 快照路径防御
    try:
        idiff.safe_snapshot_path("/tmp/evil.json")
        check("T18f 快照路径越界被拒", False)
    except ValueError:
        check("T18f 快照路径越界被拒", True)


# ---------- T20-T22:玩具库(功能4) ----------

def t_collection():
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".collection.json")
    os.close(fd)
    if os.path.exists(p):
        os.unlink(p)
    try:
        check("T20a 空库加载不报错", coll_mod.load(p) == [])
        coll_mod.add("海绵宝宝×航海王系列玩具", series="海绵宝宝×航海王", path=p)
        many = coll_mod.add_many("麦当劳大盘鸡限定公仔、小丸子玩偶", series="口述", path=p)
        check("T20b add_many 按、拆多件",
              [e["toy"] for e in many] == ["麦当劳大盘鸡限定公仔", "小丸子玩偶"],
              str([e["toy"] for e in many]))
        s = coll_mod.stats(coll_mod.load(p))
        check("T20f stats 件数/系列数(删前 3 件 2 系列)",
              s["count"] == 3 and s["series"] == 2, str(s))
        hit = coll_mod.remove(1, path=p)
        check("T20c remove 按入藏编号移除",
              hit is not None and hit["no"] == 1 and len(coll_mod.load(p)) == 2)
        check("T20d 编号不重排(删#1 后仍 #2/#3)",
              [e["no"] for e in coll_mod.load(p)] == [2, 3],
              str([e["no"] for e in coll_mod.load(p)]))
        txt = coll_mod.render(coll_mod.load(p))
        check("T20e render 含件数与藏品名", "2 件藏品" in txt and "大盘鸡" in txt)
    finally:
        if os.path.exists(p):
            os.unlink(p)


def t_dialog_museum():
    create_calls = []
    install_fakes(create_calls)   # 藏品路径已指向空临时文件
    d = dlg.Dialog(target="happymeal", at=toys.datetime(2026, 10, 12, 12, 0))
    t = d.open()
    check("T21a 启动分流两选项", d.options == ["买玩具", "看看我的玩具库"],
          str(d.options))
    check("T21b 品牌迎宾保留", "玩具上新啦" in t.text)
    t = d.reply("看看我的玩具库")
    check("T21c 空库→访谈邀请", d.state == "TM"
          and d.options == ["现在录入", "以后再说"], f"{d.state} {d.options}")
    d.reply("现在录入")
    check("T21d 访谈轮就位(先这些收尾)", d.state == "TI"
          and d.options == ["先这些"], f"{d.state} {d.options}")
    t = d.reply("海绵宝宝×航海王系列玩具、麦当劳大盘鸡限定公仔")
    check("T21e 口述一次两件全部入藏", len(coll_mod.load()) == 2,
          str(len(coll_mod.load())))
    t = d.reply("先这些")
    check("T21f 回看藏品清单(件数+入藏编号)", "2 件藏品" in t.text and "#1" in t.text)
    d.reply("回去买玩具")
    check("T21g 回去买玩具→渠道必问", d.state == "T1"
          and d.options == ["到店自取", "麦乐送"], f"{d.state} {d.options}")
    check("T21h 只看库不算跳渠道(不变量)", d.invariants() == [],
          str(d.invariants()))
    check("T21i 玩具库路径零外部写", not create_calls)


def t_order_autocollect():
    create_calls = []
    install_fakes(create_calls)
    token = qo.make_token("1450523", "到店自取",
                          [qo.build_combo_pick("9900016057", DETAIL)], 2400)
    rc = qo.run(Args(target="happymeal", confirm=token))
    entries = coll_mod.load()
    check("T22a 下单成功自动入藏玩具", rc == 0 and len(entries) == 1,
          f"rc={rc} entries={len(entries)}")
    if entries:
        e = entries[0]
        check("T22b 入藏字段:订单来源/订单号/款式名",
              e["source"] == "order" and e["order_id"] == "TEST_ORDER_1"
              and e["toy"] == "海绵宝宝×航海王系列玩具", str(e))
        check("T22c 门店存店名(编码)", "沪太路" in (e.get("store") or ""),
              str(e.get("store")))


# ---------- T23-T24:换期半自动 + 藏品编辑/对账 ----------

def t_refresh_targets():
    import tempfile
    import shutil as _sh
    CAL2 = """### 当前时间：2026-10-11 20:00:00

### 活动列表：

#### 2026年10月25日

-   **活动标题**：第三周周边即将开售✨限定主题丝巾！
    **活动内容介绍**：丝巾搭配棒球帽的潮流谁懂😎
10月25日10:45开售

#### 2026年10月11日 今日

-   **活动标题**：麦当劳 X PEACEMINUSONE
    **活动内容介绍**：GD同款联名复古棒球帽
任意餐品消费加39.9元即可得

-   **活动标题**：麦当劳 X 全新IP联名
    **活动内容介绍**：全新联名玩具即将开售
2026年11月1日10:45开售
"""
    fd, p = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    if os.path.exists(p):
        os.unlink(p)
    try:
        _sh.copyfile(toys.TARGETS_PATH, p)
        r = toys.refresh_targets(path=p, cal_md=CAL2)
        upd, news = r["updates"], r["news"]
        check("T23a 丝巾开售时间变化检出(→10-25)",
              any(u["id"] == "scarf" and u["new"] == "2026-10-25 10:45"
                  for u in upd), str(upd))
        check("T23b 日历新活动只提案", any("全新IP联名" in n["title"] for n in news))
        check("T23c cap 无 drop_time 字段不误更新",
              not any(u["id"] == "cap" for u in upd))
        bak = toys.apply_refresh(p, r["targets"], upd)
        scarf = next(t for t in toys.load_targets(p)["targets"]
                     if t["id"] == "scarf")
        check("T23d --apply 写回且留备份",
              os.path.exists(bak) and scarf["drop_time"] == "2026-10-25 10:45",
              scarf.get("drop_time"))
        check("T23e 新活动未被自动写入",
              not any("全新" in json.dumps(t) for t in toys.load_targets(p)["targets"]))
        r2 = toys.refresh_targets(path=p, cal_md=CAL2)
        check("T23f 应用后再跑零更新", r2["updates"] == [], str(r2["updates"]))
    finally:
        for f in (p, p + ".bak"):
            if os.path.exists(f):
                os.unlink(f)


def t_collection_edit_reconcile():
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    if os.path.exists(p):
        os.unlink(p)
    try:
        coll_mod.add("麦当劳对讲机", series="对讲机", path=p)
        coll_mod.add("海绵宝宝×航海王系列玩具", series="海绵宝宝×航海王",
                     source="order", order_id="ORD-PAID", path=p)
        coll_mod.add("麦当劳点单铃", series="点单铃", source="order",
                     order_id="ORD-CANCEL", path=p)
        e = coll_mod.edit(1, note="2024年5月首批", date="2024-05-01", path=p)
        check("T24a edit 补日期备注(编号不动)",
              e["acquired_at"] == "2024-05-01" and e["no"] == 1
              and "2024年5月" in e["note"], str(e))

        def fake_q(oid):
            return {"status": "订单已取消" if oid == "ORD-CANCEL" else "订单已送达"}

        rep = coll_mod.reconcile(path=p, query=fake_q)
        check("T24b 对账:取消单标注不删,访谈件不动",
              {r["result"] for r in rep} == {"cancelled", "ok"}
              and len(coll_mod.load(p)) == 3, str(rep))
        rep2 = coll_mod.reconcile(path=p, query=fake_q, prune=True)
        check("T24c --prune 清取消单,其余保留",
              any(r["result"] == "pruned" for r in rep2)
              and [x["toy"] for x in coll_mod.load(p)] ==
              ["麦当劳对讲机", "海绵宝宝×航海王系列玩具"], str(rep2))

        def bad_q(oid):
            raise RuntimeError("boom")

        rep3 = coll_mod.reconcile(path=p, query=bad_q, prune=True)
        check("T24d 查询失败不瞎删(query_failed 保留)",
              all(r["result"] == "query_failed" for r in rep3)
              and len(coll_mod.load(p)) == 2, str(rep3))
    finally:
        if os.path.exists(p):
            os.unlink(p)


def t_watch():
    """T25:watch 双模式(watch 此前零测试,本组为首测)。
    轮次菜单由 call 计数驱动:seq[0]=第1轮菜单,之后沿用最后一个。"""
    import contextlib
    import io

    def run_watch(seq, **kw):
        """按 seq 逐轮换菜单跑 watch,返回 (rc, 输出)。
        discover 的 query-meals 走 channel.call_tool(逐轮换菜单),
        mall 走 toys.call_tool(install_fakes 未覆盖,这里补静态返回)。"""
        create_calls = []
        install_fakes(create_calls)
        real_ch, real_toys = ch_mod.call_tool, toys.call_tool
        state = {"n": 0}

        def varying_ch(name, arguments=None, timeout=30):
            if name == "query-meals":
                m = seq[min(state["n"], len(seq) - 1)]
                state["n"] += 1
                return {"data": {"meals": m}}
            return real_ch(name, arguments, timeout)

        def varying_toys(name, arguments=None, timeout=30):
            if name == "mall-points-products":
                return {"data": MALL}
            return real_toys(name, arguments, timeout)
        ch_mod.call_tool = varying_ch
        toys.call_tool = varying_toys
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = toys.watch(0, kw.pop("max_rounds", 3), **kw)
        finally:
            ch_mod.call_tool = real_ch
            toys.call_tool = real_toys
        return rc, buf.getvalue()

    # 目标模式(默认):菜单里已有本期目标(乐园餐) → 第1轮即响铃
    rc, out = run_watch([MENU])
    check("T25a 目标模式:本期目标在菜单即响铃(rc=0)",
          rc == 0 and "🚨" in out and "目标命中 3" in out, f"rc={rc}")
    check("T25b 目标模式:响铃给 dialog 抢购命令",
          "dialog.py --target happymeal" in out, out[-200:])

    # 全量模式:首轮 3 款乐园餐为基线;第2轮冒出非目标新玩具项 → 响铃
    new_menu = dict(MENU)
    new_menu["9900099999"] = {"name": "限定周边玩具礼盒套餐", "currentPrice": "39.9",
                              "originalPrice": "39.9"}
    rc, out = run_watch([MENU, new_menu], all_keywords=True)
    check("T25c 全量模式:首轮建基线,基线项不响铃",
          "建基线:在售玩具关键词菜单项 3 个" in out and "🚨" not in out.split("建基线")[1].split("第 2 轮")[0],
          out)
    check("T25d 全量模式:基线外新玩具项出现即响铃(rc=0)",
          rc == 0 and "🚨 上架: 限定周边玩具礼盒套餐" in out, f"rc={rc}")
    check("T25e 全量模式:非本期目标引导换期提案而非直接下单",
          "不在 targets.json" in out and "refresh-targets" in out
          and "dialog.py" not in out, out[-300:])

    # 全量模式:菜单不变 → 走满轮次退出 rc=1
    rc, out = run_watch([MENU, MENU, MENU], all_keywords=True, max_rounds=3)
    check("T25f 全量模式:无新出现时到最大轮次退出(rc=1)",
          rc == 1 and "🚨" not in out and "到达最大轮次" in out, f"rc={rc}")

    # 全量模式:基线轮不含乐园餐,第2轮乐园餐(本期目标)新出现 → 同样响铃(超集语义)
    no_toy_menu = {k: v for k, v in MENU.items() if "乐园餐" not in v["name"]}
    rc, out = run_watch([no_toy_menu, MENU], all_keywords=True)
    check("T25g 全量模式:本期目标中途出现也算新出现并给 dialog 命令",
          rc == 0 and "🚨 上架: 鱼排堡开心乐园餐" in out
          and "dialog.py --target happymeal" in out, f"rc={rc}")

    # 参数门禁:--watch-all 不带 --watch → argparse 报错退出 2
    old_argv = sys.argv
    sys.argv = ["toys.py", "--watch-all"]
    try:
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                toys.main()
                code = 0
            except SystemExit as e:
                code = e.code
    finally:
        sys.argv = old_argv
    check("T25h --watch-all 单独使用被拒绝(exit 2)", code == 2, f"exit={code}")


def main():
    print("== test_toys:发现链路 ==")
    t_calendar()
    t_menu()
    print("== test_toys:组装与令牌 ==")
    t_build()
    print("== test_toys:quick_order 门禁(假 API) ==")
    t_run_gate()
    print("== test_toys:cap 边界 ==")
    t_run_cap_boundary()
    print("== test_toys:时间梯 ==")
    t_when_ladder()
    print("== test_toys:watch 盯上架(目标/全量双模式) ==")
    t_watch()
    print("== test_toys:铁律5 取餐方式校验 ==")
    t_takeway_guard()
    print("== test_toys:dialog 渠道分流·到店 ==")
    t_dialog_instore()
    print("== test_toys:dialog 渠道分流·麦乐送 ==")
    t_dialog_delivery()
    print("== test_toys:dialog 打烊与无地址边界 ==")
    t_dialog_closed()
    t_dialog_no_address()
    print("== test_toys:情报变化监测 ==")
    t_intel_diff()
    print("== test_toys:门店显示 ==")
    t_store_display()
    print("== test_toys:玩具库(功能4) ==")
    t_collection()
    t_dialog_museum()
    t_order_autocollect()
    print("== test_toys:换期半自动与藏品维护 ==")
    t_refresh_targets()
    t_collection_edit_reconcile()
    print()
    if FAILS:
        print(f"❌ {len(FAILS)} 项失败: {FAILS}")
        return 1
    print("✅ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
