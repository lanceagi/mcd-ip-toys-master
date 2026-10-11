#!/usr/bin/env python3
"""功能1:发现当前热门玩具。

三个只读情报源(全部实测可用,2026-10-11 01:20 真机验证):
1. campaign-calendar   活动日历(返回 markdown)——联名/周边/开售时间的第一来源
2. query-meals         门店渠道菜单——玩具 SKU / 开心乐园餐(玩具是套餐内轮次)
3. query-meal-detail   套餐详情——提取「玩具轮次」及可选款式
4. mall-points-products 积分商城——周边类商品扫描

排序原则:命中 assets/targets.json 本期目标 > 活动日历联动 > 菜单玩具关键词。
每条输出都带证据(活动原文/菜单字段),查不到就如实说查不到。

用法:
    python3 scripts/toys.py                          # 默认:到店自取 + 默认门店
    python3 scripts/toys.py --channel 麦乐送         # 外送菜单(需地址,自动解析)
    python3 scripts/toys.py --store 1450523 --when "2026-10-12 12:30"
    python3 scripts/toys.py --watch 30               # 每30秒盯一次目标上架(只读)
    python3 scripts/toys.py --watch 30 --watch-all   # 全量模式:盯基线外新出现的玩具项
    python3 scripts/toys.py --json                   # 机器可读输出(给 Agent 用)
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcd_client import call_tool, call_tool_text  # noqa: E402
from channel import (CHANNELS, channel_params, list_addresses,  # noqa: E402
                     delivery_stores, fetch_menu_channel, explain_error)

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGETS_PATH = os.path.join(SKILL_ROOT, "assets", "targets.json")
DEFAULT_STORE = "1450523"          # 与父 skill 同默认门店(静安沪太路,实测乐园餐在售)

# 编码→店名静态映射。来源:父 skill profile.json topStore 实测(2026-10-11,52% 订单主店);
# nearby/delivery 两个检索接口均不返回该编码的名字,只能静态映射。换默认店时同步改这里。
KNOWN_STORES = {"1450523": "麦当劳上海静安沪太路341号餐厅"}


def store_name(code) -> str:
    """编码→短店名(去麦当劳前缀/餐厅后缀)。🔴 查不到返回编码本身,不编造;
    对话问题行用这个(16 字预算放不下「店名(编码)」全写法)。"""
    code = str(code or "")
    raw = KNOWN_STORES.get(code)
    if not raw:
        return code
    n = re.sub(r"^麦当劳", "", raw)
    return re.sub(r"(餐厅|得来速餐厅)$", "", n)


def store_display(code) -> str:
    """日志/确认卡里的门店写法:店名(编码),一处看全。"""
    code = str(code or "")
    n = store_name(code)
    return n if n == code else f"{n}({code})"

# 活动日历关键词(宽口径:活动标题/内容短文本,噪音可控)
CALENDAR_KEYWORDS = ("玩具", "帽", "丝巾", "徽章", "盲盒", "积木", "公仔", "手办",
                     "周边", "联名", "限定", "乐园餐", "礼盒")
# 菜单关键词(窄口径:菜单名是餐品,「联名/限定」会大量误中餐品,不入)
MENU_KEYWORDS = ("玩具", "帽", "盲盒", "积木", "公仔", "手办", "周边",
                 "礼盒", "开心乐园餐", "丝巾", "徽章")
# 套餐 detail 内判定为「玩具轮次」的关键词
TOY_ROUND_KEYWORDS = ("玩具", "系列玩具", "公仔", "盲盒")

# 「开售」时间抽取:10月22日10:45开售 / 10月22日 10:45 开售
_DROP_RE = re.compile(r"(\d{1,2}月\d{1,2}日)\s*(\d{1,2}:\d{2})?\s*开售")


def load_targets(path=TARGETS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------- 活动日历 ----------

def parse_calendar(md: str) -> list[dict]:
    """campaign-calendar 的 markdown → 活动块列表。

    实测格式(2026-10-11 01:20):
        ### 当前时间：2026-10-11 01:20:34
        ### 活动列表：
        #### 2026年10月11日 今日
        -   **活动标题**：麦当劳 X PEACEMINUSONE
            **活动内容介绍**：GD同款联名复古棒球帽
            任意餐品消费加39.9元即可得
    """
    acts, cur, section = [], None, ""
    for raw in md.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if s.startswith("####"):
            section = s.lstrip("# ").strip()
            continue
        if s.startswith("-   **活动标题**") or s.startswith("- **活动标题**"):
            if cur:
                acts.append(cur)
            m = re.match(r"-\s+\*\*活动标题\*\*[:：]\s*(.+)", s)
            cur = {"section": section, "title": (m.group(1).strip() if m else ""),
                   "content": []}
            continue
        if cur is not None:
            if s.startswith("-   **") or s.startswith("- **"):   # 下一个字段块,仍归本活动
                cur["content"].append(s)
            elif s:
                cur["content"].append(s)
    if cur:
        acts.append(cur)
    for a in acts:
        a["text"] = a["title"] + " " + " ".join(a["content"])
    return acts


def hit_keywords(text: str, keywords) -> list[str]:
    return [k for k in keywords if k in text]


def scan_calendar(md: str, targets: dict) -> list[dict]:
    out = []
    for a in parse_calendar(md):
        kws = hit_keywords(a["text"], CALENDAR_KEYWORDS)
        if not kws:
            continue
        preset = [t for t in targets.get("targets", [])
                  if any(al in a["text"] or k in a["text"]
                         for al in t.get("aliases", []) for k in t.get("menu_keywords", []))]
        m = _DROP_RE.search(a["text"])
        out.append({
            "source": "campaign-calendar", "section": a["section"],
            "title": a["title"], "keywords": kws,
            "drop_time": (a["section"] + " " + m.group(2)) if (m and m.group(2)) else None,
            "evidence": " / ".join(a["content"][:3])[:120],
            "preset_target_ids": [t["id"] for t in preset],
        })
    return out


# ---------- 菜单 ----------

def scan_menu(meals: dict, targets: dict) -> list[dict]:
    """菜单玩具扫描。🔴 code 是渠道相关的,必须连同渠道+门店一起输出。"""
    out = []
    for code, m in meals.items():
        name = m.get("name") or ""
        kws = hit_keywords(name, MENU_KEYWORDS)
        if not kws:
            continue
        preset = [t for t in targets.get("targets", [])
                  if any(k in name for k in t.get("menu_keywords", []))]
        cur, orig = m.get("currentPrice"), m.get("originalPrice")
        out.append({
            "source": "query-meals", "code": code, "name": name,
            "price": cur, "original_price": orig,
            "can_with_order": m.get("canWithOrder"),
            "keywords": kws,
            "preset_target_ids": [t["id"] for t in preset],
            "is_combo": "套餐" in name or "乐园餐" in name,
        })
    return out


def toy_rounds(detail: dict) -> list[dict]:
    """从套餐 detail 里提取玩具轮次。实测乐园餐第 5 轮是「海绵宝宝×航海王系列玩具」。"""
    out = []
    for r in detail.get("rounds") or []:
        rname = r.get("name") or ""
        if not hit_keywords(rname, TOY_ROUND_KEYWORDS):
            continue
        out.append({
            "round_id": r.get("id"), "round_name": rname,
            "choices": [{"name": c.get("name"), "code": c.get("code"),
                         "default": c.get("isDefault")}
                        for c in (r.get("choices") or [])],
        })
    return out


# ---------- 积分商城 ----------

def scan_mall(points_products: list, targets: dict) -> list[dict]:
    out = []
    for p in points_products or []:
        text = f"{p.get('spuName','')} {p.get('catName','')} {p.get('selling','')}"
        kws = hit_keywords(text, MENU_KEYWORDS)
        if not kws:
            continue
        out.append({
            "source": "mall-points-products", "spu_id": p.get("spuId"),
            "name": p.get("spuName"), "point": p.get("point"),
            "price": p.get("price"), "up_time": p.get("upTime"),
            "down_time": p.get("downTime"), "keywords": kws,
            "preset_target_ids": [],
        })
    return out


# ---------- 菜单时间梯(铁律1:菜单随时段变;深夜拉不到正餐菜单) ----------

def auto_when(ladder=None, now=None):
    """query-meals 的时间梯:now+5min → 次日 10:30(正餐) → 次日开门。
    返回 (when, 依据)。只算时间,不发请求;失败重试由 fetch_menu_ladder 负责。
    """
    now = now or datetime.now()
    ladder = ladder or [
        (now + timedelta(minutes=5), "当前+5min"),
        ((now + timedelta(days=1)).replace(hour=11, minute=30), "次日11:30(正餐时段,实测乐园餐在售;10:30前是早餐菜单)"),
        ((now + timedelta(days=1)).replace(hour=7, minute=0), "次日07:00(早餐兜底)"),
    ]
    return [(w.strftime("%Y-%m-%d %H:%M"), why) for w, why in ladder]


def fetch_menu_ladder(channel, store_code, when_hint=None, be_code=None,
                      address_id=None, now=None):
    """按时间梯拉菜单,返回 (meals, when, 依据, 走过的失败)。"""
    if when_hint:
        return fetch_menu_channel(channel, store_code, when_hint, be_code, address_id), \
            when_hint, "用户指定", []
    failures = []
    for when, why in auto_when(now=now):
        try:
            meals = fetch_menu_channel(channel, store_code, when, be_code, address_id)
            return meals, when, why, failures
        except RuntimeError as e:
            if "600057" in str(e) or "60054" in str(e):
                failures.append(f"{when}: {e}")
                continue
            raise
    raise RuntimeError("时间梯全部失败(600057):\n  " + "\n  ".join(failures))


# ---------- 渠道/门店解析 ----------

def resolve_anchor(channel_hint=None, store=None, city="上海市",
                   address_id=None, be_code=None):
    """定 (渠道名, storeCode, 渠道参数, 备注行)。外送自动取地址→可送门店。"""
    name = channel_hint or "到店自取"
    for n in CHANNELS:
        if n in name:
            name = n
            break
    else:
        if any(k in name for k in ("送到家", "外送", "外卖")):
            name = "麦乐送"
        elif "得来速" in name or "免下车" in name:
            name = "得来速"
        else:
            name = "到店自取"
    spec = CHANNELS[name]
    notes = [f"渠道 {name}"]
    if spec["needAddress"]:
        addrs = list_addresses()
        if not addrs:
            raise RuntimeError("无配送地址,麦乐送不可用;请改 --channel 到店自取 或先创建地址")
        aid = address_id or next((a["addressId"] for a in addrs if a["city"] == city),
                                 addrs[0]["addressId"])
        stores = delivery_stores(aid, spec["beType"])
        if not stores:
            raise RuntimeError("该地址无可送门店,请换地址或改渠道")
        pick = next((s for s in stores if s.get("storeCode") == store), stores[0])
        cp = channel_params(name, be_code=pick.get("beCode"), address_id=aid)
        notes.append(f"地址 {aid[:10]}… → 门店 {pick.get('storeName')}({pick.get('storeCode')})")
        return name, pick["storeCode"], cp, notes
    cp = channel_params(name, be_code=be_code)
    st = store or DEFAULT_STORE
    notes.append(f"门店 {store_display(st)}" + ("" if store else "(默认)"))
    return name, st, cp, notes


# ---------- 汇总与渲染 ----------

def rank(entries: list[dict]) -> list[dict]:
    """本期目标(preset)命中优先,其次活动联动,再按来源稳定性。"""
    def score(e):
        s = 0
        if e.get("preset_target_ids"):
            s += 100
        if e.get("source") == "campaign-calendar":
            s += 30
        if e.get("source") == "query-meals":
            s += 20
        if e.get("toy_rounds"):
            s += 10
        return -s
    return sorted(entries, key=score)


def discover(channel_hint=None, store=None, city="上海市", address_id=None,
             be_code=None, when=None, deep=True, now=None) -> dict:
    targets = load_targets()
    name, store_code, cp, notes = resolve_anchor(
        channel_hint, store, city, address_id, be_code)
    meals, used_when, why, _ = fetch_menu_ladder(name, store_code, when,
                                                 cp.get("beCode"), cp.get("addressId"), now)
    menu_hits = scan_menu(meals, targets)

    # deep:对乐园餐/疑似套餐逐个拉 detail,提取玩具轮次
    for h in menu_hits:
        h["toy_rounds"] = []
        if not deep or not h["is_combo"]:
            continue
        try:
            d = call_tool("query-meal-detail", dict(cp, code=h["code"],
                                                    storeCode=store_code,
                                                    reservationDate=used_when)).get("data") or {}
            h["toy_rounds"] = toy_rounds(d)
        except RuntimeError as e:
            reason = explain_error(e, name)
            h["detail_error"] = reason or str(e)

    cal_hits = []
    cal_err = None
    try:
        cal_hits = scan_calendar(call_tool_text("campaign-calendar", {}), targets)
    except RuntimeError as e:
        cal_err = str(e)

    mall_hits, mall_err = [], None
    try:
        mall_hits = scan_mall(call_tool("mall-points-products", {}).get("data") or [], targets)
    except RuntimeError as e:
        mall_err = str(e)

    ranked = rank(menu_hits + cal_hits + mall_hits)
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "channel": name, "store_code": store_code, "menu_when": used_when,
        "menu_when_why": why, "notes": notes, "menu_total": len(meals),
        "calendar_error": cal_err, "mall_error": mall_err,
        "targets": targets.get("targets", []),
        "hits": ranked,
    }


def render(d: dict) -> str:
    L = []
    L.append("=" * 66)
    L.append(f"热门玩具扫描 · {d['generated_at']}")
    L.append("=" * 66)
    for n in d["notes"]:
        L.append(f"  {n}")
    L.append(f"  菜单时间口径: {d['menu_when']}({d['menu_when_why']}),菜单共 {d['menu_total']} 项")
    if not d["hits"]:
        L.append("")
        L.append("  本轮未发现玩具类目标(菜单+活动日历+积分商城)。")
        L.append("  如在开售前运行属正常;可 --watch 盯上架。")
    for i, h in enumerate(d["hits"], 1):
        L.append("")
        tag = ",".join(h.get("preset_target_ids") or []) or "-"
        if h["source"] == "query-meals":
            price = h.get("price") or "?"
            L.append(f"[{i}] 🎯 {h['name']}  (本期目标:{tag})")
            L.append(f"    渠道 {d['channel']}  code={h['code']}  ¥{price}"
                     + (f"(原价¥{h['original_price']})" if h.get("original_price") and h["original_price"] != price else ""))
            if h.get("can_with_order"):
                L.append("    可随单购(canWithOrder=True)")
            for tr in h.get("toy_rounds") or []:
                ch = "、".join(f"{c['name']}(code={c['code']})" for c in tr["choices"])
                L.append(f"    玩具轮次: {tr['round_name']} → {ch}")
            if h.get("detail_error"):
                L.append(f"    ⚠️ 详情拉取失败: {h['detail_error']}")
            if any(t["id"] == (h.get("preset_target_ids") or [""])[0]
                   and t.get("orderable_via_mcp") for t in d["targets"]):
                L.append(f"    抢购: python3 scripts/quick_order.py --target "
                         f"{(h.get('preset_target_ids') or ['?'])[0]} --channel {d['channel']}"
                         + (f" --store {d['store_code']}" if d["channel"] != "麦乐送" else ""))
        elif h["source"] == "campaign-calendar":
            L.append(f"[{i}] 📅 活动: {h['title']}  (本期目标:{tag})")
            L.append(f"    {h['section']}  关键词:{'/'.join(h['keywords'])}")
            if h.get("drop_time"):
                L.append(f"    ⏰ 开售: {h['drop_time']}")
            L.append(f"    证据: {h['evidence']}")
            for tid in h.get("preset_target_ids") or []:
                t = next((x for x in d["targets"] if x["id"] == tid), {})
                if t.get("mechanism"):
                    L.append(f"    机制: {t['mechanism'][:100]}")
                if t.get("orderable_via_mcp") is False:
                    L.append("    ⚠️ MCP 无该 SKU:先下「任意餐品」单满足加价购条件,"
                             "加价购动作在麦当劳 APP/到店完成")
        else:
            L.append(f"[{i}] 🛍️ 商城: {h['name']}  (本期目标:{tag})")
            L.append(f"    spuId={h['spu_id']} 积分={h['point']} 价格={h['price']}"
                     f" 有效期 {h.get('up_time')}~{h.get('down_time')}")
    for err_key, label in (("calendar_error", "活动日历"), ("mall_error", "积分商城")):
        if d.get(err_key):
            L.append(f"  ⚠️ {label}拉取失败(不影响菜单结论): {d[err_key]}")
    return "\n".join(L)


def _ring(hits: list[dict]):
    """响铃输出:上架项 + 下一步建议(本期目标给 dialog 命令,非目标走换期提案)。"""
    for h in hits:
        print(f"  🚨 上架: {h['name']} code={h['code']} ¥{h.get('price') or '?'}")
    presets = [h for h in hits if h.get("preset_target_ids")]
    if presets:
        print("  立即执行(品牌话术渠道分流,渠道它会问):")
        for h in presets:
            print(f"  python3 scripts/dialog.py --target {h['preset_target_ids'][0]}")
    if any(not h.get("preset_target_ids") for h in hits):
        print("  其中非本期目标(不在 targets.json):先跑 python3 scripts/toys.py 看四路全量情报;")
        print("  确认要抢再人工把新目标加进 assets/targets.json(可用 --refresh-targets 看提案)。")


def watch(seconds: int, max_rounds: int, all_keywords: bool = False, **kw):
    """盯上架:每 N 秒扫一次菜单,只读。两种模式:
    - 默认·目标模式:本期目标关键词(preset_target_ids)出现在菜单即响铃退出
    - all_keywords·全量模式:首轮把在售玩具关键词菜单项记为基线,只对
      **基线外新出现**的玩具项响铃——盯「不在 targets.json 里的新周边/新玩具」
      (盲区补齐;基线占第 1 轮,有效盯守轮数 = max_rounds-1)"""
    import time
    targets = load_targets()
    if all_keywords:
        print(f"[watch] 每 {seconds}s 扫一次菜单,全量玩具关键词模式"
              f"(首轮建基线,只盯基线外新出现;最多 {max_rounds} 轮,只读)")
    else:
        kwds = [k for t in targets["targets"] for k in t.get("menu_keywords", [])]
        print(f"[watch] 每 {seconds}s 扫一次菜单,目标关键词: {kwds}"
              f"(最多 {max_rounds} 轮,只读)")
    baseline = None
    for i in range(1, max_rounds + 1):
        d = discover(deep=False, **kw)
        menu_hits = [h for h in d["hits"] if h["source"] == "query-meals"]
        if all_keywords:
            if baseline is None:
                baseline = {h["code"] for h in menu_hits}
                print(f"[watch] 第 {i} 轮建基线:在售玩具关键词菜单项 {len(baseline)} 个"
                      + (f"({','.join(sorted(baseline))})" if baseline else ""))
            else:
                fresh = [h for h in menu_hits if h["code"] not in baseline]
                print(f"[watch] 第 {i} 轮 {d['generated_at']} 菜单 {d['menu_total']} 项,"
                      f"玩具关键词 {len(menu_hits)},新出现 {len(fresh)}")
                if fresh:
                    _ring(fresh)
                    return 0
        else:
            hits = [h for h in menu_hits if h.get("preset_target_ids")]
            print(f"[watch] 第 {i} 轮 {d['generated_at']} 菜单 {d['menu_total']} 项,"
                  f"目标命中 {len(hits)}")
            if hits:
                _ring(hits)
                return 0
        if i < max_rounds:
            time.sleep(seconds)
    print("[watch] 到达最大轮次,未上架。")
    return 1


# ---------- 换期半自动(--refresh-targets) ----------

_CN_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})")


def normalize_drop(text):
    """「2026年10月22日 10:45」→「2026-10-22 10:45」;解析不了原样返回。"""
    m = _CN_DATE.search(text or "")
    if not m:
        return text
    y, mo, d, hh, mm = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d} {int(hh):02d}:{mm}"


def refresh_targets(path=None, cal_md=None):
    """活动日历 → targets.json 换期提案(只读,不改文件)。

    半自动边界(v1.1):
    - ✅ 自动提案、--apply 可应用:**既有目标的 drop_time 更新**(同一目标多段
      日历按最后一段,即最新信息);只对**已有 drop_time 字段**的目标提案——
      没有该字段的目标(如 cap 已开售)可能是同活动族的新一弹(徽章),写进去就是错数据
    - ❌ 只提案、永不自动写入:日历新活动(新目标需人工定 id/aliases/menu_keywords)
    """
    path = path or TARGETS_PATH
    tg = load_targets(path)
    md = cal_md if cal_md is not None else call_tool_text("campaign-calendar", {})
    hits = scan_calendar(md, tg)
    by_id = {t["id"]: t for t in tg["targets"]}
    updates, news = {}, []
    for h in hits:
        drop = normalize_drop(h.get("drop_time") or "")
        if h["preset_target_ids"]:
            # 🔴 一条活动文案可同时命中多个目标(实测:「丝巾搭配棒球帽」
            #    同时挂 cap+scarf)——只看 [0] 会漏掉真目标,必须逐个判。
            for tid in h["preset_target_ids"]:
                t = by_id[tid]
                if drop and t.get("drop_time") and drop != t["drop_time"]:
                    # 同目标多段(同名活动跨日期)后写覆盖:日历按时间排,最后=最新
                    updates[tid] = {"id": tid, "label": t.get("label"),
                                    "field": "drop_time", "old": t["drop_time"],
                                    "new": drop,
                                    "evidence": (h.get("evidence") or "")[:80]}
        else:
            news.append({"title": h["title"], "drop_time": drop or None,
                         "keywords": h.get("keywords"),
                         "evidence": (h.get("evidence") or "")[:80]})
    return {"updates": list(updates.values()), "news": news, "targets": tg,
            "path": path}


def apply_refresh(path, tg, updates) -> str:
    """应用 drop_time 更新:先备份 .bak,再原子写回。返回备份路径。
    临时文件用 tempfile 在目标目录内创建,不做路径字符串拼接(穿越防护)。"""
    import shutil
    import tempfile
    by_id = {t["id"]: t for t in tg["targets"]}
    for u in updates:
        by_id[u["id"]][u["field"]] = u["new"]
    bak = path + ".bak"
    if os.path.exists(path):
        shutil.copy2(path, bak)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)),
                               suffix=".targets.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return bak


def cmd_refresh_targets(apply_flag=False) -> int:
    r = refresh_targets()
    updates, news = r["updates"], r["news"]
    print("=" * 66)
    print("换期提案(活动日历 vs assets/targets.json)")
    print("=" * 66)
    if not updates and not news:
        print("  无变化:既有目标开售时间一致,日历也没有新活动。")
        return 0
    for u in updates:
        print(f"  🔁 {u['id']}({u['label']}) 开售时间: {u['old']} → {u['new']}")
        print(f"      证据: {u['evidence']}")
    for n in news:
        print(f"  🆕 新活动(只提案,需人工定 id/aliases 后手工加入): {n['title']}")
        print(f"      开售: {n['drop_time']}  关键词: {n['keywords']}")
        print(f"      证据: {n['evidence']}")
    if not apply_flag:
        print("-" * 66)
        print("  确认无误后,原命令追加 --apply 应用「开售时间更新」"
              "(写入前自动备份 targets.json.bak;新活动不自动写入)。")
        return 0
    if not updates:
        print("  没有可应用的更新(新活动不自动写入)。")
        return 0
    bak = apply_refresh(r["path"], r["targets"], updates)
    print(f"✅ 已应用 {len(updates)} 条开售时间更新;备份: {bak}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="发现当前热门玩具(只读)")
    ap.add_argument("--channel", default="到店自取",
                    help="到店自取/麦乐送/得来速,或口语「送到家」")
    ap.add_argument("--store", default=None, help="storeCode,默认 1450523")
    ap.add_argument("--city", default="上海市", help="外送地址匹配城市")
    ap.add_argument("--address-id", default=None)
    ap.add_argument("--be-code", default=None)
    ap.add_argument("--when", default=None, help="菜单时间口径,如 2026-10-12 12:30")
    ap.add_argument("--no-deep", action="store_true", help="不拉套餐 detail(更快)")
    ap.add_argument("--watch", type=int, default=None, metavar="SEC",
                    help="每 SEC 秒盯一次目标上架")
    ap.add_argument("--watch-all", action="store_true",
                    help="配合 --watch:全量玩具关键词模式,首轮建基线,"
                         "只盯基线外新出现的玩具项(含不在 targets.json 的新周边)")
    ap.add_argument("--max-rounds", type=int, default=40)
    ap.add_argument("--refresh-targets", action="store_true",
                    help="换期提案:活动日历 vs targets.json(只读)")
    ap.add_argument("--apply", action="store_true",
                    help="配合 --refresh-targets:应用开售时间更新(自动备份)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.refresh_targets:
        sys.exit(cmd_refresh_targets(apply_flag=args.apply))
    if args.watch_all and not args.watch:
        ap.error("--watch-all 需配合 --watch SEC")
    if args.watch:
        sys.exit(watch(args.watch, args.max_rounds, all_keywords=args.watch_all,
                       channel_hint=args.channel, store=args.store, city=args.city,
                       address_id=args.address_id, be_code=args.be_code, when=args.when))
    try:
        d = discover(args.channel, args.store, args.city, args.address_id,
                     args.be_code, args.when, deep=not args.no_deep)
    except RuntimeError as e:
        print(f"[受阻] {e}")
        reason = explain_error(e, args.channel)
        if reason:
            print(f"  转译: {reason}")
        sys.exit(2)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(render(d))


if __name__ == "__main__":
    main()
