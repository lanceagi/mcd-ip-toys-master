#!/usr/bin/env python3
"""移动端一屏渲染器。(拷贝自 mcd-what-to-eat-today,逐字未改;升级时重新拷贝)

## 为什么单独一个模块
2026-10-10 首次真人走查:确认卡在手机上要左右滑动,用户读不完。
根因是 `order_builder.render_card()` —— 那是 66 字符定宽的**日志渲染器**,
按桌面终端设计,被原样搬到了 375pt 的手机上。它没有「视口」这个概念。

## 硬预算(来自 docs/23-点单流程重设计v2.md 第五节)
| 指标 | 阈值 |
|---|---|
| 单行折合汉字数 | ≤ 16 |
| 一条消息总行数 | ≤ 13 |
| 选项个数 | 1 ~ 4 |
| 单选项折合汉字数 | ≤ 16 |

## 关键纪律
**超预算抛 AssertionError,不静默截断。**
静默截断会让人以为信息就这么点 —— 这个项目最吃过亏的一类 bug 就是
「渲染器悄悄扔掉了字段,对话里看起来一切正常」。

用法:
    print(turn("今天店里吃,还是送到家?",
               facts=["11 天没见了"],
               options=["堂食", "外带", "送到家", "得来速"]))
"""
import re
import unicodedata

MAX_WIDTH = 16.0   # 单行折合汉字数
MAX_LINES = 13     # 一条消息总行数
MAX_OPTIONS = 4
HINT = "回数字就行"


def width(text: str) -> float:
    """折合汉字宽度。汉字/全角 = 1.0,半角 = 0.5。"""
    w = 0.0
    for ch in text:
        w += 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.5
    return w


def check(lines, options=None, soft=0):
    """超预算直接抛错。soft = 前 N 行豁免宽度检查(仍计入总行数)。

    豁免的用途:地址、单位名这类**中文长串会自然折行**的内容。
    横向滚动是空格对齐和长 ASCII 串造成的,不是长中文造成的。
    """
    bad = []
    for i, ln in enumerate(lines, 1):
        if i <= soft:
            continue
        if width(ln) > MAX_WIDTH:
            bad.append(f"第{i}行 {width(ln):.1f}>{MAX_WIDTH:.0f}: {ln}")
    if len(lines) + len(options or []) + (1 if options else 0) > MAX_LINES:
        bad.append(f"总行数 {len(lines)}+{len(options or [])}>{MAX_LINES}")
    for i, o in enumerate(options or [], 1):
        t = f"{i} {o}"
        if width(t) > MAX_WIDTH:
            bad.append(f"选项{i} {width(t):.1f}>{MAX_WIDTH:.0f}: {t}")
    if options is not None and len(options) > MAX_OPTIONS:
        bad.append(f"选项数 {len(options)}>{MAX_OPTIONS}")
    return bad


def assert_budget(lines, options=None, soft=0):
    bad = check(lines, options, soft)
    if bad:
        raise AssertionError("移动端预算超限:\n  " + "\n  ".join(bad))
    return True


def turn(question: str, facts=None, options=None, hint=None, tail=None, soft=0, pre=None):
    """组装一轮对话。

    question : 店员那一句(≤2 句)
    facts    : 事实陈述,每条一行(只陈述,不预测)
    options  : ≤4 个选项,按序编号
    tail     : 结尾补充行(如报价)
    soft     : 前 N 行豁免宽度检查(给地址这类长中文串)
    pre      : 前置块(迎宾语)。空行分隔,同样过预算检查
    """
    # 🔴 facts 里允许传条件项(为 None 时不渲染)。不过滤的话,
    #    条件不成立时会往对话里塞一个 None 行,width() 直接崩。
    pre = [f for f in (pre or []) if f]
    facts = [f for f in (facts or []) if f]
    options = list(options or []) if options is not None else None
    head, body = [], []
    if pre:
        head.extend(pre)
        head.append("")          # 空行分隔,不算宽度
    if question:
        head.append(question)
    head.extend(facts)
    if tail:
        body.append(tail)
    if options:
        body.extend(f"{i} {o}" for i, o in enumerate(options, 1))
        body.append(hint or HINT)
    lines = head + body
    assert_budget(head, None, soft)          # 头部逐行查
    assert_budget(body, options, 0)          # 尾部整体查
    if len(lines) > MAX_LINES:
        raise AssertionError(f"总行数 {len(lines)}>{MAX_LINES}")
    return "\n".join(lines)


def pre_block(lines):
    """把前置块转成 soft 豁免的宽度参数:前 N 行都豁免。"""
    return sum(1 for x in lines if x) + 1


# ---------------------------------------------------------------- 商品名缩写
_PAREN = re.compile(r"[（(][^）)]*[）)]")
# 🔴 「套餐」不在噪音表里 —— 它承载形态信息(中套餐/四件套)。
#    删掉它会把「鳕鱼堡中套」压成悬空的「鳕鱼堡中」。
_NOISE = ("经典", "风味", "麦金卡", "免配", "免打包", "服务费",
          "单人餐", "中餐", "三件套", "四件套", "精选", "超值")
_TAIL = ("中套", "大套", "中套餐", "四件套", "三件套", "五件套", "双人餐",
         "单人餐", "中杯", "大杯", "中薯", "大薯", "双层")


def short_name(name: str, limit: float = MAX_WIDTH) -> str:
    """把商品名压到预算内。

    「双层深海鳕鱼堡中套餐（麦金卡免配）」→「双层深海鳕鱼堡中套」8 字
    「经典安格斯单人餐（麦金卡免配）」→「安格斯」3 字
    规则:去括号 → 去修饰词 → 压缩形态词(中套餐→中套) → 仍超长则保留尾部形态词截断
    """
    s = _PAREN.sub("", name).strip()
    for n in _NOISE:
        s = s.replace(n, "")
    s = re.sub(r"中套餐$", "中套", s)
    s = re.sub(r"套餐$", "套", s)
    s = re.sub(r"\s+", "", s)
    if width(s) <= limit:
        return s
    m = None
    for tail in _TAIL:
        if s.endswith(tail) and width(s) > limit:
            m = re.escape(tail)
            break
    if m:
        tail = re.search(m + "$", s).group(0)
        keep = int(limit - width(tail)) - 1
        head = s[:s.index(tail)]
        return head[:max(keep, 1)] + tail
    return s[:int(limit)]


# ---------------------------------------------------------------- 金额
def money(v):
    """分 → 「¥41.5」。已是元就原样返回。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f"¥{f:.1f}" if abs(f - round(f)) > 1e-9 else f"¥{round(f)}"


def price_line(original, final, discount=None):
    """价格行。优惠为 0 时不写优惠,避免「优惠 -¥0.0」这种噪音。"""
    o, f = money(original), money(final)
    if o and f and o != f:
        return f"原价 {o} → {f}"
    return f"实付 {f}" if f else (f"实付 {o}" if o else "")
