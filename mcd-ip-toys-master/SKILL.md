---
name: mcd-ip-toys-master
description: 麦当劳热门玩具与周边「情报+抢购+收藏」Skill。四个功能:1) 发现现在/未来的热门玩具与联名周边(活动日历+门店菜单+套餐玩具轮次+积分商城四路情报,含开售时间);2) 情报变化监测(intel_diff 快照比对:新联名/开售时间变化/上架下架,已配每天10:40自动刷新);3) 下单抢购(品牌点单话术渠道分流「到店自取/麦乐送」+ 预热确认卡/令牌确认两段式;乐园餐玩具直接下单,加价购周边先下满足条件的餐品单);4) 我的玩具库(本地长期收藏买过的玩具,像博物馆藏品一样记录;下单自动收藏+首装口述录入)。本期目标:PEACEMINUSONE 联名复古棒球帽(任意消费加39.9元)、开心乐园餐海绵宝宝×航海王系列玩具、10月15日徽章第二弹、10月22日限定丝巾。当用户说「我要买麦当劳周边」「有什么新玩具」「到店还是麦乐送」「看看我的玩具库」时使用本 skill。触发词:我要买麦当劳周边、买周边、麦当劳周边、抢玩具、麦当劳玩具、棒球帽、乐园餐玩具、开心乐园餐、联名、限定、开售、抢单、PEACEMINUSONE、GD同款、麦乐送、到店还是麦乐送、玩具新品、情报变化、上新、玩具库、我的玩具、藏品、收藏。
---

# 麦当劳 IP 玩具/周边抢购 · mcd-ip-toys-master

基于 mcd-what-to-eat-today 的下单逻辑(mcd_client/channel/order_builder 逐字拷贝,
全部实测铁律继承),面向「限时周边/玩具」场景扩展为四个功能:
**发现**(现在/未来有什么)→ **变化监测**(每天自动盯情报)→ **下单**(品牌话术
渠道分流 + 两段式抢购)→ **玩具库**(本地长期收藏买过的玩具)。
信息更新优先于下单顺畅:先让用户知道现在有什么、未来有什么,再把单下顺;
买过的玩具像博物馆藏品一样在本地默默长期保存。

## 〇、本期情报(assets/targets.json,2026-10-11 01:20 真机实测)

| 目标 | 机制 | MCP 可直接下单? |
|---|---|---|
| 联名复古棒球帽(麦当劳 X PEACEMINUSONE) | 任意餐品消费 **加39.9元** 即可得 | ❌ 菜单/券四路均无该 SKU,加价购在 APP 下单页/到店 |
| 开心乐园餐玩具(**海绵宝宝×航海王系列**) | 玩具是乐园餐套餐内**选择轮次**(detail 第5轮,code 521991),下单即得 | ✅ 到店 ¥23.5-25,三变体(汉堡/鱼排堡/麦乐鸡) |
| 「我就喜欢」限定丝巾(第三弹) | 任意餐品消费加 39.9 元;**10月22日 10:45 开售** | ❌ 同棒球帽 |

换期只改 `assets/targets.json`(aliases/menu_keywords/drop_time),脚本零改动。

## 一、功能1:发现热门玩具(只读)

```bash
python3 scripts/toys.py                        # 到店自取 + 默认门店 1450523
python3 scripts/toys.py --channel 麦乐送       # 外送菜单(自动取地址→可送门店)
python3 scripts/toys.py --when "2026-10-12 12:30"   # 钉死菜单时间口径
python3 scripts/toys.py --watch 30             # 每30秒盯目标上架,出现即响铃(只读)
python3 scripts/toys.py --watch 30 --watch-all # 全量模式:盯基线外新出现的玩具项(含不在 targets.json 的新周边)
python3 scripts/toys.py --refresh-targets      # 换期提案:活动日历 vs targets.json(只读)
python3 scripts/toys.py --refresh-targets --apply  # 应用开售时间更新(自动备份 .bak)
python3 scripts/toys.py --json                 # 机器可读(给 Agent 链用)
```

换期半自动边界:**--apply 只应用既有目标的 drop_time 更新**(同一目标多段日历取
最后一段;没有 drop_time 字段的目标如 cap 不误更新——同活动族的新一弹是另一回事);
**日历新活动只提案不写入**(新目标需人工定 id/aliases/menu_keywords)。一条文案可
同时命中多个目标(实测「丝巾搭配棒球帽」同时挂 cap+scarf),提案会逐个判。

四路情报源(全只读):

1. **campaign-calendar**(markdown)——联名活动/开售时间的第一来源;解析出活动块并抽取「N月N日HH:MM开售」
2. **query-meals**——菜单玩具 SKU / 开心乐园餐;**code 是渠道相关的,输出必带渠道+门店**
3. **query-meal-detail**(deep)——提取套餐内「玩具轮次」与可选款式
4. **mall-points-products**——积分商城周边扫描

排序:命中 targets.json 本期目标 > 活动日历 > 菜单命中。查不到如实说查不到,
不带 --watch 不轮询。**菜单随时段变**(铁律:深夜拉到的是次日早餐菜单,10:30 档仍是早餐、11:00 起正餐),
默认时间梯 `now+5min → 次日11:30 → 次日07:00`,输出里注明实际用了哪档。

**watch 双模式**:`--watch SEC` 默认只盯**本期目标**关键词上架;`--watch-all` 为全量
玩具关键词模式——首轮把在售玩具关键词菜单项记为基线(基线占第 1 轮,有效盯守
轮数 = max-rounds-1),只对**基线外新出现**的玩具项响铃,补「不在 targets.json 的
新周边」盲区。响铃时本期目标直接给 dialog 抢购命令;非本期目标引导先看四路情报、
再人工入库(--refresh-targets 提案),不代客扩 targets。

### 情报变化监测(daily diff;信息更新自动化的核心)

「现在/未来有什么」每次跑 toys.py 都是实时,但**变化**要两次观测做差:

```bash
python3 scripts/intel_diff.py            # 跑一次观测 → 与上次快照 diff → 落新快照
python3 scripts/intel_diff.py --json     # 机器可读(Agent/定时任务用)
python3 scripts/intel_diff.py --reset    # 丢弃旧快照重建基线
```

- 报三类变化:**🆕 新增**(新联名/新上架)、**🔁 变化**(开售时间/价格/玩具轮次款式)、
  **👋 消失**(下架/活动结束);首次运行建基线
- 诚实规则:某路情报源本次拉取失败时,该路旧条目**原样结转**,不误报消失
- 快照 `scripts/.intel-snapshot.json`(已 gitignore;落点限定 scripts/ 内,拒绝路径穿越)
- 已配 ZCode 持久定时任务:**每天 10:40** 自动跑一次并报告变化(麦当劳开售惯例 10:45,
  正好多留 5 分钟);2026-10-11 迁库独立建仓后已在新工作区重建该任务
  (automation-a09a2fb7);若当天是任一目标 drop_time 开售日,任务会一并提醒复核;
  换设备/重装/迁库后需重建该任务
- 已知边界:活动日历里**同名活动跨日期段合并为一个键**(如 PEACEMINUSONE 三段),
  开售时间取最后一段;该活动的任何变化仍能检出,但按日粒度会丢

## 二、功能2:快速下单抢购(两段式,写操作有门禁)

```bash
# 第1步 预热(可提前跑;只读+试算,零写操作)→ 输出确认卡 + 8位确认令牌
python3 scripts/quick_order.py --target happymeal
python3 scripts/quick_order.py --target happymeal --variant 麦乐鸡   # 指定乐园餐变体
python3 scripts/quick_order.py --target happymeal --toy 海绵宝宝     # 多款式期指定玩具
python3 scripts/quick_order.py --target cap --code 511781            # 棒球帽:下满足「任意餐品消费」的单

# 第2步 抢购(回贴令牌 = 对确认卡的逐单确认)→ create-order
python3 scripts/quick_order.py --target happymeal --confirm <令牌>

# 下单后回查(只读;不输出 deliveryInfo/payId)
python3 scripts/quick_order.py --query-order <orderId>
```

### 渠道分流对话(品牌点单话术;到店自取 / 麦乐送)

quick_order 的 `--channel` 默认「到店自取」静默生效——用户从没被问过
「到店拿还是麦乐送」。`dialog.py` 用**品牌点单话术**(「喜欢您来♥️」迎宾、
编号选项、一轮只问一件事,纪律全部继承父 skill flow.py 的 S0-S4)把渠道
问清楚,再把参数交给 quick_order 出确认卡:

```bash
python3 scripts/dialog.py --target happymeal                          # T0F 启动分流
python3 scripts/dialog.py --target happymeal --reply 买玩具           # 买玩具→问渠道
python3 scripts/dialog.py --target happymeal --reply 买玩具 --reply 1 --reply 1      # 门店→取餐方式
python3 scripts/dialog.py --target happymeal --reply 买玩具 --reply 1 --reply 1 --reply 2  # →出确认卡
python3 scripts/dialog.py --target happymeal --reply 2                # 看看我的玩具库
# 出卡后追加 --confirm <令牌> 重跑同一条命令,即两段式第二段下单
```

分流规则(全部有离线测试 T14-T17 把守):
- **渠道必问**(T1),不替用户默认;得来速/团餐不进选项(链路未实测,见 U5)
- **到店系**:默认门店 1450523 确认/换一家(`--keyword` 搜店)→ 堂食/外带;
  取餐方式在 quick_order 下单前对照本单 takeWayList 校验(铁律5,不在表里拒绝)
- **外送系**:🔴 先确认地址才查可送门店(父 skill S3A 纪律,分页每页3个)
  → 复诵「送到哪、谁家送」(确认/换店/换地址)→ 放置点写进 remark;
  可送门店全打烊时如实报每家开门时间,给「约开门后送」(预约单)出路
- 对话全程**零写操作**;create-order 仍只在 quick_order 两段式第二段(单一写路径)
- 编号只在当轮有效;选项 ≤4;话术超移动端 16 字预算直接抛错(render_mobile 纪律)
- **门店一律显示店名,不甩裸编码**:对话问题行只放短店名(16 字预算放不下「店名(编码)」),
  编码进 facts;日志/确认卡用「店名(编码)」。映射表 `toys.KNOWN_STORES`
  (来源:父 skill 画像实测,nearby/delivery 检索不返回默认店名,只能静态映射);
  换默认店时同步改映射表

### 确认令牌机制(硬门禁)

令牌 = sha256(门店+渠道+商品结构+应付分) 前 8 位。第二段重跑时全链路重验,
**价格或商品任何变化都会令牌失配、拒绝下单**——防止拿旧确认卡买新价格。
无令牌或令牌错 = 零写操作(测试 T9 系列守门)。

### 继承的实测铁律(全部来自父 skill 真机验证)

1. create-order 即时单**不传 reservationDate**(预约传了 600054;`--reserve` 才走预约)
2. `roundList` 的 round 是**字符串**;照读结构 rounds 写会 500
3. productCode 渠道相关:60006 ≠ 售罄,是编码不属于该渠道(explain_error 转译)
4. beCode 只能来自 delivery-query-stores;外送还必传 addressId
5. takeWayCode 只能取试算返回的 takeWayList(默认取第一项,--take-way 覆盖)
6. create-order 不扣款;不付款订单自动关闭。MCP 无支付工具。
   🔴 实测(2026-10-11):自动关闭极快——16:56:40 创建的单,用户在 APP 进了付款页
   但未完成付款,16:58 即「已取消」,实付 0。**下单后必须一口气在 APP 付完**,
   不要停在付款页;抢购话术里要提醒用户这一点。

### 抢购节奏建议

- 开售前(如丝巾 10/22 10:45):`toys.py --watch 30` 盯上架;或先跑第1步预热拿到确认卡
- 开售瞬间:跑第1步(重验拿新令牌)→ 第2步确认 → 打开麦当劳 APP 付款
- MCP 链路全程无扣款,最终支付永远在用户手里的 APP 完成

## 三、功能4:我的玩具库(本地长期收藏)

启动分流的第一问就是它:「买玩具,还是看看您的玩具库?」。

```bash
python3 scripts/collection.py list                     # 藏品清单(默认)
python3 scripts/collection.py add --toy 海绵宝宝×航海王系列玩具 --series 海绵宝宝×航海王
python3 scripts/collection.py add-many 海绵宝宝系列、大盘鸡公仔、小丸子玩偶
python3 scripts/collection.py remove 3                 # 按入藏编号移除
python3 scripts/collection.py edit 1 --date 2024-05-01 --note "2024年5月首批"  # 补日期/备注/系列
python3 scripts/collection.py reconcile                # 对账:订单来源藏品逐条回查状态(只读)
python3 scripts/collection.py reconcile --prune        # 移除已取消订单的藏品(查询失败的不瞎删)
python3 scripts/collection.py stats                    # 件数/系列数
```

- **存储**:`assets/collection.json`,**随仓库保存**(长期资产,不 gitignore);
  入藏编号 #1 起只增不减、不重排(博物馆式 accession number)
- **两个来源**:① 下单自动收藏——quick_order 两段式下单成功且套餐含玩具轮次,
  默默 append(source=order,带订单号;🔴 收藏失败绝不阻断下单);未付款取消的
  订单也会留痕,用 `remove` 清理,宁多记不漏记 ② 首装口述录入——订单历史拿不到
  玩具维度(冷启动边界),空库时对话进入访谈轮:用户口述、一次多件(、分隔)、
  「先这些」收尾,录入长期记录
- 对话路径:`dialog.py` T0F 选「看看我的玩具库」→ TM 藏品清单/空库邀请 →
  TI 口述录入 → 回看清单(T20-T22 系列测试把守)


## 四、安全边界(硬规则)

- **create-order 是唯一写操作**,必须两段式令牌确认;禁止批量、禁止代客确认、禁止自动支付
- `auto-bind-coupons` 等写操作本 skill 不调用
- 隐私红线同父 skill:不输出 contactName/phone/payId/deliveryInfo;
  支付链接默认不回显(--show-pay-link 显式开启,仅本人)
- 棒球帽/丝巾类加价购周边:**如实告知 MCP 无 SKU**,不下无法交付的单;
  本 skill 只负责把满足加价购条件的餐品单下好,加价动作在 APP/到店完成

## 五、文件结构

```
mcd-ip-toys-master/
├── SKILL.md
├── PLAN.md                          # 本 skill 独立开发计划(现状/待开发/已定决策)
├── run_all_tests.sh                  # 一键测试(离线;--full 含在线只读)
├── assets/
│   └── targets.json                  # 本期目标情报(换期只改这里)
└── scripts/
    ├── mcd_client.py                 # 拷贝自父 skill(+SSRF 加固:https白名单/私网阻断/禁重定向)
    ├── channel.py                    # 拷贝自父 skill,逐字未改
    ├── order_builder.py              # 拷贝自父 skill,逐字未改(被 import 复用组装规则)
    ├── render_mobile.py              # 拷贝自父 skill,逐字未改(移动端一屏渲染器,超预算抛错)
    ├── toys.py                       # ★ 功能1:四路情报发现 + 时间梯 + watch
    ├── intel_diff.py                 # ★ 功能1.5:情报快照与差异(新增/变化/消失,喂每日定时刷新)
    ├── quick_order.py                # ★ 功能2:两段式抢购下单 + 令牌门禁 + 铁律5取餐方式校验
    ├── dialog.py                     # ★ 启动分流+渠道分流(买玩具/看玩具库→到店自取/麦乐送,零写操作)
    ├── collection.py                 # ★ 功能4:我的玩具库(藏品增/列/移除,下单自动收藏钩子)
    ├── selftest.py                   # 结构自检(离线 38 项;--full 含在线 3 项)
    └── test_toys.py                  # 离线测试 113 项(假 API,fixture 取自真机探针+channel合同;T25 系列把守 watch 双模式)
```

## 六、常用命令

```bash
python3 scripts/toys.py                          # 发现热门玩具
python3 scripts/toys.py --channel 麦乐送 --deep  # 外送菜单
python3 scripts/toys.py --watch 30 --max-rounds 60
python3 scripts/toys.py --watch 30 --watch-all        # 全量模式盯新周边
python3 scripts/intel_diff.py                    # 情报变化监测(与上次快照做差)
python3 scripts/dialog.py --target happymeal     # 启动分流:买玩具 / 看看我的玩具库
python3 scripts/collection.py list               # 我的玩具库藏品清单
python3 scripts/quick_order.py --target happymeal
python3 scripts/quick_order.py --target happymeal --confirm <令牌>
python3 scripts/selftest.py                      # 离线自检
bash run_all_tests.sh                            # 离线全量
bash run_all_tests.sh --full                     # 含真实 MCP 在线(只读)
```

## 七、未实现/待验证清单

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| U1 | 到店单 takeWayCode 默认取 takeWayList[0] | ⚠️ 待实测 | 真实试算返回 `堂食(eat-in)/外带(take-in-store)`,code 是**字符串**;默认取 eat-in,真实 create-order 待验证,--take-way 可覆盖 |
| U2 | create-order 真实提交 | ✅ 全链路测试通过 | 2026-10-11 用户实测:dialog 分流→确认卡→令牌→成单(orderId 已脱敏)→APP 可见且可发起付款;未付款按预期自动取消(≈2 分钟),零成本收尾 |
| U3 | 棒球帽/丝巾加价购 SKU | ❌ MCP 无此数据 | 2026-10-11 实测菜单+券四路均无;开售后重跑 toys.py 复核 |
| U4 | 乐园餐玩具多款式选择 | ✅ 逻辑就绪(--toy) | 本期单款式(随机玩具),多款式期生效 |
| U5 | 得来速/团餐渠道抢购 | ⚠️ 未实测 | 渠道参数已支持,链路未真机跑;dialog 分流选项因此不含得来速/团餐 |
| U6 | dialog 语音口播(speech) | ❌ 未接入 | 父 skill flow.py 的 Turn 有 speech 字段;本 skill 无语音链路,只出文字话术 |
| U7 | dialog 出卡后的麦乐送真实下单 | 🔴 待实测 | 外送 create-order(含 addressId/beCode/remark)从未真机提交,首次使用按两段式走 |
| U8 | 玩具库从订单历史回填 | ❌ 未做 | 订单接口拿不到玩具维度(冷启动边界);现路径=口述录入+下单自动收藏 |

## 八、与父 skill 的关系

- 下单执行逻辑(mcd_client/channel/order_builder)**逐字拷贝**,不做双源维护;
  父 skill 修复实测坑后,重新拷贝这三个文件即可(升级点只在 SSRF 加固一行)
- render_mobile.py(移动端渲染器)同为逐字拷贝;dialog.py 的话术纪律
  (渠道必问/先地址后门店/编号不跨轮/≤4选项)移植自父 skill flow.py 的 S0-S4,
  但**不拷贝 flow.py 本体**——玩具单没有点餐/定制/场景推荐那些状态
- 本 skill 不依赖父 skill 的 profile.json(玩具单不做口味签名定制,签名传空)
- 两 skill 可并存,各自独立触发
