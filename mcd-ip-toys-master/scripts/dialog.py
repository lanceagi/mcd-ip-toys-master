#!/usr/bin/env python3
"""功能2 前置对话:品牌点单话术的「到店自取 / 麦乐送」渠道分流。

## 为什么有这个
quick_order.py 的 --channel 默认「到店自取」静默生效——用户从没被问过
「到店拿还是麦乐送」,想外送还得自己知道要传 --channel 麦乐送。
门店点单不是表单,是串行对话(父 skill flow.py 2026-10-10 真人走查结论):
店员一句、顾客一句、推进一位。

## 流程(参考 mcd-what-to-eat-today/scripts/flow.py 的 S0-S4 纪律)
```
T0F  启动分流    「买玩具，还是看看您的玩具库？」(功能4 玩具库入口)
T1   渠道(买玩具分支) 「到店拿,还是麦乐送?」 🔴 渠道必问,不替用户默认
T2   门店(到店系) 默认店 1450523 确认 / 换一家(按关键词搜,只认营业中的店)
T2W  取餐方式   堂食 / 外带 —— 下单前在 quick_order 对照 takeWayList 校验(铁律5)
T3A  地址(外送系) 🔴 先确认送到哪,才查可送门店(S3A 纪律);分页,每页3个
T3B  门店(外送系) 复诵「送到哪、谁家送」(确认/换店/换地址);全打烊走 T3Z
T3Z  打烊分支   如实报每家开门时间:约开门后送 / 换地址 / 先不送了
T4   放置点     门口 / 前台 / 门口+电话 → create-order.remark
T5   出卡       参数交给 quick_order.run() 出确认卡+令牌(本对话零写操作)
TM   玩具库     藏品清单;空库→访谈邀请(现在录入/以后再说)
TI   访谈录入   口述藏品一次多件(、分隔),「先这些」收尾 → 回玩具库
```

## 硬纪律(继承父 skill flow.py)
1. 编号只在当轮有效(self.options 每轮重置),跨轮作废
2. 一次只问一件事;选项 ≤4;超移动端预算直接抛错(render_mobile 纪律)
3. 渠道必问;历史/默认只影响选项排序,不给免答权
4. 本对话零写操作:create-order 只在 quick_order --confirm 第二段(单一写路径);
   玩具库(TM/TI)是本地收藏写 assets/collection.json,不碰任何外部写
5. 网络调用集中在 ChannelApi,测试注入假 API 离线跑(test_toys.py T14-T22)

用法(每轮一条命令,--reply 按对话顺序重放):
    python3 scripts/dialog.py --target happymeal                          # T0F 启动分流
    python3 scripts/dialog.py --target happymeal --reply 买玩具           # → 渠道
    python3 scripts/dialog.py --target happymeal --reply 买玩具 --reply 1 # 到店→门店
    python3 scripts/dialog.py --target happymeal --reply 买玩具 --reply 1 --reply 1      # →取餐方式
    python3 scripts/dialog.py --target happymeal --reply 买玩具 --reply 1 --reply 1 --reply 2  # →出卡
    python3 scripts/dialog.py --target happymeal --reply 2                # 看看我的玩具库
    # 出卡后追加 --confirm <令牌> 重跑同一条命令,即两段式第二段下单
"""
import argparse
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_mobile as rm  # noqa: E402
import collection           # noqa: E402  功能4:本地玩具库(藏品资产,入库保存)
import quick_order as qo    # noqa: E402
import toys                 # noqa: E402
from channel import (addresses_rich, delivery_stores, nearby_stores,  # noqa: E402
                     next_slot, opens_next, pick_store, pick_when)

BRAND = "喜欢您来♥️"
FAREWELL = "喜欢您来，慢走。"
DEFAULT_STORE = "1450523"   # 与 quick_order/toys 的默认门店一致

# T1 两个分流选项。得来速/团餐不进选项:链路未真机验证(SKILL.md U5),不承诺。
CHANNEL_MENU = [
    {"key": "到店自取", "channel": "到店自取"},
    {"key": "麦乐送", "channel": "麦乐送"},
]
# 取餐方式。eat-in/take-in-store 是实测 takeWayList 取值(父 skill SKILL.md);
# 出卡下单前 quick_order 会对照本单 takeWayList 再校验,不在表里就拒绝。
TAKEWAYS = [("堂食", "eat-in"), ("外带", "take-in-store")]
DROPOFF = [("门口", "放门口"), ("前台", "放前台"),
           ("门口+电话", "放门口,电话联系")]
ADDR_PAGE_SIZE = 3   # ≤4 选项协议:一页 3 个地址,留 1 个位置给「更多地址」


# ------------------------------------------------------------------ API 注入
class ChannelApi:
    """真实 MCP 调用(只读)。网络访问集中在这里,测试用假 API 替换。"""

    def addresses(self, city=None):
        return addresses_rich(city)

    def delivery_stores(self, address_id):
        return delivery_stores(address_id, 2)

    def nearby(self, city, keyword):
        return nearby_stores(1, city, keyword)


# ------------------------------------------------------------------ 工具(取自父 skill flow.py,逐字同义)
_ADDR_NOTE = re.compile(r"[（(][^）)]*[）)]")


def compact_address(full, limit=13):
    """地址压成能进编号选项的短标签。完整地址在 T3B 复诵轮展示。"""
    s = re.sub(r"^(广东省|上海市|北京市|天津市|重庆市)?", "", full or "")
    s = re.sub(r".*?市", "", s, count=1)
    s = s.strip()
    if rm.width(s) <= limit:
        return s
    head, tail = s[:int(limit * 0.6)], s[-int(limit * 0.3):]
    return f"{head}…{tail}"


def store_label(s, limit=12):
    """门店短标签。「麦当劳上海静安沪太路341号餐厅」→「上海静安沪太路341号」。
    超长保留尾部——地址区分度在后面那截。"""
    n = re.sub(r"^麦当劳", "", (s or {}).get("storeName") or "?")
    n = re.sub(r"(餐厅|得来速餐厅)$", "", n)
    if rm.width(n) <= limit:
        return n
    return n[-int(limit):]


def _mins(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


# ------------------------------------------------------------------ 对话
class Turn:
    def __init__(self, state, text, options=None, meta=None):
        self.state = state
        self.text = text
        self.options = list(options or [])
        self.meta = meta or {}

    def __repr__(self):
        return f"<Turn {self.state} opts={self.options}>"


class Dialog:
    def __init__(self, target=None, codes=None, variant=None, toy=None, qty=1,
                 city="上海市", keyword=None, api=None, at=None):
        self.qo_args = {"target": target, "code": codes, "variant": variant,
                        "toy": toy, "qty": qty}
        self.api = api or ChannelApi()
        self.city = city
        self.keyword = keyword or city
        self.now = at or datetime.now()
        self.state = "T1"
        self.options = []          # 🔴 每轮重置,编号不跨轮
        self.turns = []
        self.ready = False         # True = 参数齐了,可 checkout() 出卡
        self.channel = None
        self.store_code = None     # 到店系:门店 code(默认 1450523)
        self.address = None        # 外送系:{"addressId","label"}
        self.dropoff = None        # 外送系:放置点 → remark
        self.take_way = None       # 到店系:eat-in / take-in-store
        self.reserve = None        # T3Z 约开门后送 → reservationDate
        self._nearby = []          # 到店系换店候选缓存
        self._dstores = []         # 外送系可送门店缓存
        self._dstore = None        # 外送系当前选中门店对象
        self._earliest = None      # T3Z 最早开门门店
        self._addrs = None
        self._addr_start = 0
        self._addr_page = []

    # -------------------------------------------------- 内部
    def _mark(self, new_state):
        self.state = new_state
        self.turns.append(new_state)
        return new_state

    def _pick(self, reply):
        """用户回复 → 当轮选项索引。🔴 只认本轮 options,防串轮(父 skill 同款)。"""
        s = (reply or "").strip()
        if not s:
            return None
        m = re.fullmatch(r"\s*([1-9])\s*", s)
        if m:
            i = int(m.group(1)) - 1
            return i if 0 <= i < len(self.options) else None
        for i, o in enumerate(self.options):
            if o and (o in s or s in o):
                return i
        return None

    def _toy_fact(self):
        """迎宾 facts 里的一句话:本期玩具轮次名(有就报,没有不编)。"""
        try:
            tg = toys.load_targets()
        except Exception:
            return None
        t = next((x for x in tg.get("targets", [])
                  if x.get("id") == self.qo_args.get("target")), None)
        obs = (t or {}).get("toy_observed") or {}
        return obs.get("round_name")

    # -------------------------------------------------- T0F 启动分流 + T1 渠道
    def open(self):
        """第一轮:品牌迎宾 + 启动分流(买玩具 / 看看我的玩具库)。"""
        greet = rm.turn(f"{BRAND} 玩具上新啦!", facts=[self._toy_fact()])
        self._mark("T0F")
        self.options = ["买玩具", "看看我的玩具库"]
        fork = rm.turn("买玩具，还是看看您的玩具库？", options=self.options)
        return Turn(self.state, f"{greet}\n\n{fork}", options=self.options)

    def ask_channel(self):
        """🔴 渠道必问(买玩具分支的入口)。"""
        self._mark("T1")
        self.options = [c["key"] for c in CHANNEL_MENU]
        return Turn(self.state, rm.turn("到店拿，还是麦乐送？", options=self.options))

    # -------------------------------------------------- 玩具库 TM/TI(功能4)
    def museum_view(self):
        """藏品清单;空库→访谈邀请(首装冷启动:订单里拿不到玩具维度)。"""
        entries = collection.load()
        self._mark("TM")
        if not entries:
            self.options = ["现在录入", "以后再说"]
            return Turn(self.state, rm.turn(
                "玩具库还空着，要录入吗？",
                facts=["订单里拿不到玩具维度"],
                options=self.options))
        self.options = ["回去买玩具", "继续录入"]
        return Turn(self.state,
                    collection.render(entries) + "\n\n" +
                    rm.turn("接下来？", options=self.options))

    def start_intake(self):
        self._mark("TI")
        self.options = ["先这些"]
        return Turn(self.state, rm.turn(
            "都有什么？几件一起说也行。",
            facts=["多件用、隔开"],
            options=self.options))

    def _intake_add(self, text):
        """口述 → 入藏(一次多件)。藏品名是长中文串,走 soft 豁免。"""
        added = collection.add_many(text) if collection.split_names(text) else []
        if not added:
            return Turn(self.state, rm.turn("没听清，再说一遍？",
                                            options=self.options))
        self._intake_total = getattr(self, "_intake_total", 0) + len(added)
        names = [e["toy"] for e in added]
        return Turn(self.state, rm.turn(
            f"入藏 {len(added)} 件。", facts=names,
            options=self.options, soft=1 + len(names)))

    # -------------------------------------------------- 到店系 T2/T2W
    def ask_store_instore(self, swapped=False):
        if self.store_code is None:
            self.store_code = DEFAULT_STORE
        self._mark("T2")
        self.options = ["就这家", "换一家"]
        name = store_label(self._current_instore()) if swapped \
            else toys.store_name(self.store_code)
        if swapped:
            head = f"换到{name}"
            facts = None
        else:
            head = f"{name}，到店拿？"
            facts = ["默认门店，到店单常用", f"编码 {self.store_code}"]
        return Turn(self.state, rm.turn(head, facts=facts, options=self.options))

    def _current_instore(self):
        """换店后从 nearby 缓存里找当前门店对象(拿名字/时段);默认店无对象。"""
        return next((s for s in self._nearby
                     if s.get("storeCode") == self.store_code), {})

    def swap_store_instore(self):
        if not self._nearby:
            self._nearby = self.api.nearby(self.city, self.keyword)
        if not self._nearby:
            self.options = ["就这家"]
            return Turn(self.state, rm.turn(
                "按这个关键词没搜到门店。",
                facts=[f"关键词:{self.keyword}", "换关键词用 --keyword"],
                options=self.options, soft=1))
        ids = [s.get("storeCode") for s in self._nearby]
        try:
            i = ids.index(self.store_code)
        except ValueError:
            i = -1
        rotated = self._nearby[(i + 1) % len(self._nearby):] + self._nearby[:i + 1]
        nxt = pick_store(rotated)
        if nxt is None:
            self.options = ["就这家"]
            return Turn(self.state, rm.turn("搜到的门店此刻都打烊了。",
                                            options=self.options))
        self.store_code = nxt.get("storeCode")
        return self.ask_store_instore(swapped=True)

    def ask_takeway(self):
        self._mark("T2W")
        self.options = [k for k, _ in TAKEWAYS]
        return Turn(self.state, rm.turn("堂食还是外带？", options=self.options))

    # -------------------------------------------------- 外送系 T3A/T3B/T3Z
    def ask_address(self):
        if self._addrs is None:
            self._addrs = self.api.addresses(self.city)
            if not self._addrs:
                self._mark("T3A")
                self.options = ["重新选渠道"]
                return Turn(self.state, rm.turn(
                    "想外送，得先有地址。",
                    facts=["账户里一个都没有", "先在APP添加地址再外送"]),
                    meta={"unavailable": True})
        start = self._addr_start
        if start >= len(self._addrs):
            start = self._addr_start = 0
        page = self._addrs[start:start + ADDR_PAGE_SIZE]
        more = start + ADDR_PAGE_SIZE < len(self._addrs)
        self._addr_page = page
        labels = [compact_address(_ADDR_NOTE.sub("", a["label"]).strip())
                  for a in page]
        self._mark("T3A")
        self.options = labels + (["更多地址"] if more else [])
        return Turn(self.state, rm.turn(
            "送到哪个地址？", facts=[f"共{len(self._addrs)}个"],
            options=self.options))

    def ask_store_delivery(self):
        """🔴 地址已确认才查可送门店(S3A 纪律)。"""
        self._dstores = self.api.delivery_stores(self.address["addressId"])
        if not self._dstores:
            self._mark("T3B")
            self.options = ["换地址"]
            return Turn(self.state, rm.turn("这个地址没有可送门店，换一个？",
                                            options=self.options))
        self._dstore = pick_store(self._dstores, at=self.now)
        if self._dstore is None:
            return self._closed_stores_turn()
        return self._confirm_store_turn()

    def _confirm_store_turn(self, swapped=False):
        when, why = pick_when(self._dstore, at=self.now)
        self.store_code = self._dstore.get("storeCode")   # 🔴 出卡要用用户选的店
        self._mark("T3B")
        self.options = ["确认", "换店", "换地址"]
        label = compact_address(_ADDR_NOTE.sub("", self.address["label"]).strip())
        head = f"换{store_label(self._dstore)}送" if swapped else f"送到{label}"
        return Turn(self.state, rm.turn(
            f"{head}，{store_label(self._dstore)}送。",
            facts=[why], options=self.options, soft=1))

    def _closed_stores_turn(self):
        """全部打烊:如实报每家开门时间,给「约开门后送」的出路(父 skill S3Z 同款)。"""
        def _key(s):
            t, tmr = opens_next(s, self.now)
            return (1 if tmr else 0, _mins(t or "23:59"))

        ranked = sorted(self._dstores, key=_key)
        facts = []
        for s in ranked[:3]:
            t, tmr = opens_next(s, self.now)
            if not t:
                facts.append(f"{store_label(s, 8)} 营业时间未知")
                continue
            facts.append(f"{store_label(s, 8)} {'明日' if tmr else '今日'}{t}开门")
        self._earliest = ranked[0]
        self._mark("T3Z")
        self.options = ["约开门后送", "换地址", "先不送了"]
        return Turn(self.state, rm.turn("这个点还没有店在送：",
                                        facts=facts, options=self.options))

    def swap_store_delivery(self):
        ids = [s.get("storeCode") for s in self._dstores]
        cur = (self._dstore or {}).get("storeCode")
        i = next((k for k, s in enumerate(self._dstores)
                  if s.get("storeCode") == cur), -1)
        rotated = self._dstores[(i + 1) % len(self._dstores):] + self._dstores[:i + 1]
        nxt = pick_store(rotated, at=self.now)
        if nxt is None:
            return self._closed_stores_turn()
        self._dstore = nxt
        return self._confirm_store_turn(swapped=True)

    def reserve_earliest(self):
        """打烊分支选「约开门后送」:预约时刻必须落在可预约窗口(铁律1)。"""
        self._dstore = self._earliest or self._dstore
        self.store_code = self._dstore.get("storeCode")
        when = next_slot(self._dstore, at=self.now)
        if not when:
            when, _ = pick_when(self._dstore, at=self.now)
        self.reserve = when
        return self.ask_dropoff()

    def _page_next_address(self):
        self._addr_start = self._addr_start + ADDR_PAGE_SIZE
        return self.ask_address()

    # -------------------------------------------------- T4 放置点
    def ask_dropoff(self):
        self._mark("T4")
        self.options = [k for k, _ in DROPOFF]
        return Turn(self.state, rm.turn("放哪儿？", options=self.options))

    # -------------------------------------------------- T5 出卡 / T9 送客
    def _ready_turn(self):
        self._mark("T5")
        self.options = []
        self.ready = True
        how = "送到家" if self.channel == "麦乐送" else "到店拿"
        return Turn(self.state, rm.turn(f"好嘞，{how}。出确认卡 ↓"))

    def farewell(self):
        self._mark("T9")
        self.options = []
        return Turn(self.state, rm.turn(FAREWELL))

    def checkout(self, confirm=None) -> int:
        """把问到的参数交给 quick_order 出确认卡/下单。本函数前零写操作;
        --confirm 透传后,create-order 仍走 quick_order 的令牌门禁。"""
        if not self.ready:
            raise RuntimeError("对话没走完,先回完选项")
        a = argparse.Namespace(
            target=self.qo_args.get("target"), code=self.qo_args.get("code"),
            variant=self.qo_args.get("variant"), toy=self.qo_args.get("toy"),
            qty=self.qo_args.get("qty", 1),
            channel=self.channel, store=self.store_code, city=self.city,
            address_id=(self.address or {}).get("addressId"), be_code=None,
            when=None, reserve=self.reserve, take_way=self.take_way,
            remark=self.dropoff, confirm=confirm, show_pay_link=False)
        return qo.run(a)

    # -------------------------------------------------- 调度
    def reply(self, text):
        i = self._pick(text)
        # TI 访谈轮:自由文本即藏品口述(不匹配「先这些」就走入藏,不报「没看懂」)
        if self.state == "TI" and (i is None or self.options[i] != "先这些"):
            return self._intake_add(text)
        if i is None:
            n = len(self.options)
            tip = f"没看懂，回 1-{n}。" if n else "说什么都行。"
            return Turn(self.state, rm.turn(tip, options=self.options or None))
        if self.state == "T0F":
            if self.options[i] == "买玩具":
                return self.ask_channel()
            return self.museum_view()
        if self.state == "TM":
            if self.options[i] == "回去买玩具":
                return self.ask_channel()
            if self.options[i] == "以后再说":
                return self.farewell()
            return self.start_intake()          # 现在录入 / 继续录入
        if self.state == "TI":
            return self.museum_view()          # 只剩「先这些」→ 回看藏品
        if self.state == "T1":
            self.channel = CHANNEL_MENU[i]["channel"]
            if self.channel == "麦乐送":
                return self.ask_address()
            return self.ask_store_instore()
        if self.state == "T2":
            if self.options[i] == "换一家":
                return self.swap_store_instore()
            return self.ask_takeway()
        if self.state == "T2W":
            self.take_way = TAKEWAYS[i][1]
            return self._ready_turn()
        if self.state == "T3A":
            if self.options[i] == "更多地址":
                return self._page_next_address()
            if self.options[i] == "重新选渠道":
                return self.open_reask()
            self.address = {"addressId": self._addr_page[i]["addressId"],
                            "label": self._addr_page[i]["label"]}
            return self.ask_store_delivery()
        if self.state == "T3B":
            if not self._dstores:     # 无可送门店分支:换地址
                return self._page_next_address()
            if i == 1:
                return self.swap_store_delivery()
            if i == 2:
                return self._page_next_address()
            return self.ask_dropoff()
        if self.state == "T3Z":
            if i == 1:
                return self._page_next_address()
            if i == 2:
                return self.farewell()
            return self.reserve_earliest()
        if self.state == "T4":
            self.dropoff = DROPOFF[i][1]
            return self._ready_turn()
        if self.state in ("T5", "T9"):
            return Turn(self.state, rm.turn("已经问完了。"))
        return Turn(self.state, rm.turn("已经问完了。"))

    def open_reask(self):
        """无地址等受阻分支回 1:回到渠道问题重来(编号重发,不沿用旧轮)。"""
        self._mark("T1")
        self.options = [c["key"] for c in CHANNEL_MENU]
        return Turn(self.state, rm.turn("那就到店拿，还是麦乐送？",
                                        options=self.options))

    # -------------------------------------------------- 不变量(test_toys.py 直接用)
    def invariants(self):
        bad = []
        if (self.ready or self.channel) and "T1" not in self.turns:
            bad.append("I1 渠道询问被跳过")   # 只看玩具库不买,不算跳过
        if self.channel == "麦乐送" and self.ready:
            if not self.address:
                bad.append("I2 外送未确认地址")
            if not self.dropoff:
                bad.append("I2 外送未确认放置点")
        if self.channel == "到店自取" and self.ready and not self.take_way:
            bad.append("I3 到店未选取餐方式")
        if len(self.options) > 4:
            bad.append("I4 选项超过 4 个")
        return bad


def main():
    ap = argparse.ArgumentParser(
        description="品牌话术渠道分流对话(到店自取/麦乐送),问完出确认卡")
    ap.add_argument("--target", default=None, help="targets.json 目标 id")
    ap.add_argument("--code", action="append", default=None,
                    help="直接按 code 下单(透传 quick_order),可重复")
    ap.add_argument("--variant", default=None, help="乐园餐变体子串")
    ap.add_argument("--toy", default=None, help="玩具轮次款式子串")
    ap.add_argument("--qty", type=int, default=1)
    ap.add_argument("--city", default="上海市")
    ap.add_argument("--keyword", default=None,
                    help="到店换一家时搜门店的关键词(默认=城市名)")
    ap.add_argument("--reply", action="append", default=[],
                    help="用户应答(数字或选项名),按对话顺序,可重复")
    ap.add_argument("--at", default=None, help="模拟时刻,如 '2026-10-12 07:05'")
    ap.add_argument("--confirm", default=None, metavar="TOKEN",
                    help="确认令牌:对话重放+出卡后走两段式第二段")
    a = ap.parse_args()
    at = datetime.strptime(a.at, "%Y-%m-%d %H:%M") if a.at else None
    d = Dialog(target=a.target, codes=a.code, variant=a.variant, toy=a.toy,
               qty=a.qty, city=a.city, keyword=a.keyword, at=at)
    if not (a.target or a.code):
        ap.error("必须给 --target 或 --code 之一")
    t = d.open()
    print(t.text)
    for r in a.reply:
        t = d.reply(r)
        print()
        print(t.text)
    if d.ready:
        rc = d.checkout(a.confirm)
        if rc == 0 and not a.confirm:
            print("〔分流流程〕两段式第二段 = 本条命令末尾追加 "
                  "--confirm <确认卡上的令牌> 重跑即下单。")
        sys.exit(rc)


if __name__ == "__main__":
    main()
