<div align="center">

# 🧸 麦门玩具大师 · 限时周边情报站

**「帽子什么时候开售？乐园餐现在是什么玩具？」**

一句问出去，回来的是**四路情报交叉验证的答案**——现在有什么、未来有什么、
和上次比起了什么变化；想买，它用品牌点单话术带你两段式下单；
买过的玩具，它像博物馆藏品一样替你长期收藏。

<br>

[![MCP](https://img.shields.io/badge/MCD--MCP-35%20tools-DA291C.svg)](MCP_INTEGRATION.md)
[![Deps](https://img.shields.io/badge/Dependencies-zero-success.svg)](mcd-ip-toys-master/SKILL.md)
[![Tests](https://img.shields.io/badge/tests-151%20offline-brightgreen.svg)](#%EF%B8%8F-免-token-直接体验)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**零第三方依赖** · **纯 Python 标准库** · **clone 下来即可运行**

> 💛 如果这个思路对你有用，点个 **⭐ Star** 支持一下！本作品正在参加
> 「麦当劳程序员节创意开发大赛」，**Star 数决定排名** 🙏

</div>

---

## 🧭 30 秒看懂

```text
你：麦当劳现在有什么玩具？

玩具大师：喜欢您来♥️ 玩具上新啦！
      🎯 开心乐园餐·海绵宝宝×航海王系列玩具
         到店 ¥23.5 起,玩具是套餐第 5 轮自选,下单即得
      📅 「我就喜欢」限定丝巾(第三弹)
         任意消费加 39.9 元,10月22日 10:45 开售
      ⚠️ 联名棒球帽:任意消费加 39.9 元——官方接口查不到该加价购 SKU,
         如实告诉你,不瞎猜、不下无法交付的单
```

**信息更新是这个 Skill 的第一优先级**：先让你知道「现在有什么、未来有什么」，
变化交给每天 10:40 的自动巡检盯着（麦当劳开售惯例 10:45，正好提前 5 分钟）；
下单只是水到渠成的最后一步。

---

## 🎯 四个功能

| # | 功能 | 一句话 | 入口 |
|---|---|---|---|
| 1 | **发现** | 活动日历 + 门店菜单 + 套餐玩具轮次 + 积分商城**四路交叉**，附开售时间 | `python3 scripts/toys.py` |
| 2 | **变化监测** | 快照 diff:🆕新联名 / 🔁开售时间变动 / 👋下架,每天 10:40 自动盯 | `python3 scripts/intel_diff.py` |
| 3 | **下单** | 品牌点单话术渠道分流(到店/麦乐送) + **两段式令牌确认** | `python3 scripts/dialog.py` |
| 4 | **玩具库** | 买过的玩具像博物馆藏品一样本地长期收藏,下单自动入藏 | `python3 scripts/collection.py list` |

watch 双模式盯上架:`--watch 30` 盯本期目标;`--watch-all` 全量玩具关键词,
首轮建基线,只对**新出现**的玩具响铃——连不在预设目标里的新周边也能抓到。

---

## ✅ 它说的每一句话,哪些是真的?

| 你看到的 | 是真的吗 | 一句话解释 |
|---|---|---|
| 「10月22日 10:45 开售」 | ✅ 真 | 活动日历原文抽取,带证据行输出 |
| 「乐园餐 ¥23.5,玩具第 5 轮」 | ✅ 真 | `query-meal-detail` 实测,玩具轮次 code 521991 |
| 「棒球帽官方接口查不到 SKU」 | ✅ 如实 | 菜单+券四路实测均无;**查不到就说查不到,不编** |
| 「每天 10:40 自动巡检」 | ✅ 真 | 定时任务实跑;快照落本地,拉取失败的路**结转不误报** |
| 下单确认卡的价格 | ✅ 官方核价 | `calculate-price` 试算返回,非估算 |
| 「下单后请立刻在 APP 付完」 | ✅ 实测教训 | 未付款订单**约 2 分钟自动取消**(真机踩过) |

**两条诚实红线**:某路情报源拉取失败,旧条目原样结转,绝不误报「消失」;
MCP 查不到的商品(加价购周边)如实告知入口在 APP/到店,不下无法交付的单。

---

## 🚀 三步开吃

### 第 1 步 · 一键安装技能(免 Token,约 30 秒)

**方式 A · 对话式(推荐)**——把下面这段话原样发给你的 Agent(WorkBuddy / Claude Code / Cursor / ZCode 等均可):

```text
帮我安装这个技能:https://github.com/lanceagi/mcd-ip-toys-master
把仓库里 mcd-ip-toys-master 文件夹整个复制到你的用户级技能目录,
确认 mcd-ip-toys-master/SKILL.md 存在,装完提醒我重开一轮会话
```

**方式 B · 命令行**:

```bash
git clone https://github.com/lanceagi/mcd-ip-toys-master.git
# 把技能目录复制进你所用 Agent 的技能目录(任选其一):
cp -r mcd-ip-toys-master/mcd-ip-toys-master ~/.workbuddy/skills/    # WorkBuddy
cp -r mcd-ip-toys-master/mcd-ip-toys-master ~/.agents/skills/      # 通用 agents 目录
cp -r mcd-ip-toys-master/mcd-ip-toys-master ~/.claude/skills/      # Claude Code
```

> 🔧 **为什么装进哪个 Agent 都行**:技能不依赖宿主的 MCP 连接器——
> 脚本自带纯标准库直连客户端(Bearer Token 走 `https://mcp.mcd.cn`),
> 宿主只需要能执行 `python3` 和读取 SKILL.md。
> 装完可立即验证(免 Token):`bash mcd-ip-toys-master/run_all_tests.sh` 应全绿。

### 第 2 步 · 申请并配置 MCP Token(免费,1 分钟)

访问 <https://open.mcd.cn/mcp> → 手机号登录 → 右上角「控制台」→ 点「激活」→ 一键复制,然后:

```bash
export MCD_MCP_TOKEN=<你刚复制的Token>    # 或存入 ~/.mcd_token(权限600)
```

想在 MCP 客户端里挂载,见 [`mcp-config.example.json`](mcp-config.example.json);
也可以一直当命令行工具用——纯标准库,无需安装任何依赖。

### 第 3 步 · 问一句

在技能目录下运行(`cd mcd-ip-toys-master`;已装进 Agent 的话直接对它说「麦当劳现在有什么玩具」):

```bash
python3 scripts/toys.py                     # 现在有什么玩具(四路情报)
python3 scripts/toys.py --refresh-targets   # 换期提案:开售时间变化一屏看清
python3 scripts/dialog.py --target happymeal   # 买玩具(渠道它会问,不替你默认)
```

### 🛡️ 免 Token 直接体验

不申请 Token 也能玩:**`bash run_all_tests.sh` 是完全离线的**——
结构自检 38 项 + 流程测试 113 项,全部用假 API 驱动,零网络、零凭证、
clone 即跑,60 秒看完整个 Skill 的行为契约(含两段式令牌门禁的反例测试)。

---

## 👥 谁需要它

| 你是 | 你会问 |
|---|---|
| 麦门收藏党 | 「这期联名什么时候开售?别让我错过」 |
| 乐园餐家长 | 「这周的玩具是什么?去哪家店有?」 |
| 抢购型选手 | 「开售那一刻帮我下好单,我直接去付」 |
| 联名周边粉 | 「帽子/丝巾/徽章,上新和补货盯着点」 |

---

## 🔬 给爱看细节的同学

### 两段式令牌:防「拿旧确认卡买新价格」

第 1 步预热只读+试算,输出确认卡和 8 位令牌 = `sha256(门店+渠道+商品结构+应付分)` 前 8 位。
第 2 步回贴令牌才真正 create-order,**全链路重验:价格或商品任何变化令牌即失配、拒绝下单**。
无令牌 = 零写操作(测试 T9 系列守门);对话层全程零写操作,写路径只有这一个。

### 继承自真机实测的铁律(全部踩过坑)

1. create-order 即时单不传 `reservationDate`(传了报 600054)
2. `roundList` 的 round 是**字符串**,照读结构写会 500
3. 商品 code **渠道相关**:同一商品到店/外送编码不同,换店必须重查菜单
4. beCode 只能来自 delivery-query-stores,外送必传 addressId
5. takeWayCode 只能取试算返回的 takeWayList(铁律5,不在表里拒绝)
6. create-order 不扣款、MCP 无支付工具——**付款永远在你的麦当劳 APP 里完成**;
   未付款约 2 分钟自动取消(2026-10-11 真机实测)

### 信息自动化:快照 diff + 每日巡检

「现在有什么」每次跑都是实时,但「**变化**」要两次观测做差:
`intel_diff.py` 报三类变化(新增/变化/消失),配定时任务每天 10:40 自动盯
(开售日还会提醒复核加价购周边是否上了架)。已知边界照样诚实:
同名活动跨日期段合并为一个键,按日粒度会丢——写在文档里,不藏着。

### 真实运行记录(2026-10-11)

- 全链路下单实测:四轮分流 → 确认卡 → 令牌 → 成单(orderId 已脱敏)
  → APP 可发起付款 → 未付款按预期自动取消,零成本收尾
- 玩具库真机闭环:口述建档 2 件 + 下单自动入藏 + 取消单对账清理

### 常用命令

```bash
python3 scripts/toys.py --watch 30 --watch-all   # 开售日盯新周边(全量模式)
python3 scripts/intel_diff.py                    # 情报变化(与上次快照做差)
python3 scripts/quick_order.py --target happymeal            # 第1步:出确认卡
python3 scripts/quick_order.py --target happymeal --confirm <令牌>   # 第2步:下单
python3 scripts/collection.py list               # 我的玩具库
bash run_all_tests.sh                            # 离线全量测试(免 Token)
```

---

## 📋 参赛材料

| 要求 | 文件 |
|---|---|
| 项目介绍 / 安装 / 使用示例 / 目标用户 | 本 README |
| 参赛声明(官方原文未改动) | [CONTEST_DECLARATION.md](CONTEST_DECLARATION.md) |
| MCP 接入说明(Server / Tool / 调用流程 / 业务价值) | [MCP_INTEGRATION.md](MCP_INTEGRATION.md) |
| 脱敏 MCP 配置示例(仅环境变量占位符) | [mcp-config.example.json](mcp-config.example.json) |
| 源代码 | [`mcd-ip-toys-master/`](mcd-ip-toys-master/) |
| WorkBuddy 开发上下文 | workbuddy.md(未提交;仅在真实使用 WorkBuddy 后补) |

### 合规说明

- `CONTEST_DECLARATION.md` 为官方原文,文件名与内容均未改动
- 仓库不含任何真实 Token、密钥、账号凭证或他人个人信息;
  配置仅环境变量占位符;运行时快照(`.intel-snapshot.json`)已 gitignore
- **唯一写操作是 create-order,且必须两段式令牌确认**;禁止批量、
  禁止代客确认、禁止自动支付;券类写操作(`auto-bind-coupons`)不调用
- 隐私红线:不输出 contactName/phone/payId/deliveryInfo
- 不贬损品牌、不与其他品牌对比;输出以麦当劳官方渠道实时结果为准

---

## 📄 License

[MIT](LICENSE) · 本项目为「麦当劳程序员节创意开发大赛」参赛作品,
由参赛者独立开发,**非麦当劳官方产品**。
