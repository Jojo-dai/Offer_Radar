# 11 · 防再犯清单（每一条都来自真实事故）

> 原则：**问题修一次，防线留永久。** 每个历史故障都必须对应一个"结构上不可能复发"的机制，
> 而不是"下次注意"。本表同时是每轮采集的验收清单——执行 Agent 收尾时逐条核对。

## 一、事故 → 防线对照表

| # | 历史事故 | 根因 | 现在的防线 | 防线怎么验证 |
|---|---|---|---|---|
| 1 | 11-07~11-09 停更 3 天 | 纯钟点调度「22–06 不跑」+ 电脑睡眠 60 小时 | 调度 P1 条款：库里最新岗位超 14 小时立即补采，深夜也跑，不看钟点 | 应用顶部「最近入库」超 14h 仍未自愈 → 查自动化是否 PAUSED |
| 2 | 池过千后查重崩溃（DATABASE_RESULT_EXCEED_MAX_ROWS） | 云库单次查询上限 1000 行，`SELECT ... LIMIT 2000` 直接报错 | `scripts/dump-existing.py` 按 id 键集分页（每页 900），采集轮禁止手写 LIMIT 2000 | 脚本存在且 `python scripts/dump-existing.py` 能导出全量 |
| 3 | 猎聘 75 条整批判 26 分沉底 | HR 硬冲突正则吃掉「招聘」标题前缀 | `scripts/score_jobs.py` 固化：打分前剥前缀 + HR 正则收窄；采集轮禁止临时改打分脚本 | 打分只调 score_jobs.py，`.workbuddy/tmp` 里不再出现 scoreN.py |
| 4 | 领英整天 0 条 | 门禁看「出口 IP 是否 CN」误杀 | 门禁改为接口实测（GATE PASS = 返回 ≥1 张卡片）；调度铁律 2 明文禁止按 IP 跳过 | 自动化 prompt 里铁律 2 存在；check-network.sh 同口径 |
| 5 | 领英固定前 3 词吃干第一页 | 关键词不轮换、不翻页 | 游标轮换（`.workbuddy/tmp/*-kw-cursor.txt`）+ 每词 5 页 | 两个游标文件存在且每轮推进 |
| 6 | 领英泛词涌入无关岗（79 条均分 51） | 词池含裸 `Project Manager` | 泛词护栏：无 SAP/BPC/AI 等限定前缀的泛词自动拼 `SAP + 原词` | 词池全为限定词；config.example.json genericKeywordGuard |
| 7 | 429 按整词丢（每词 ~50 条全损） | 限流粒度是词级，冷却重试救不回首页即 429 的词 | ① 脚本内置 45-75s 冷却重试；② **失败词重采队列**（2026-11-10 新增）：被限流中断的词写入 `<out>/linkedin-retry-queue.json`，下轮自动补采（冷却 30 分钟，每轮最多补 1 个）；③ 门禁整体跳过时本轮词全部入队，接口恢复后自动补采 | `python scripts/collect-linkedin-guest.py` 输出含 RETRY-ENQUEUE / RETRY-PICK 行为生效 |
| 8 | 前端假性停更（558 条里只见 18 条新的；看板数字停在 500） | 前端多处 `limit(500)/limit(1000)` 硬截断 | 统一 `fetchAllJobs()`：按 id 键集分页取全量（每页 900），岗位池/清单/看板/去重/打分按钮全量 | 前端代码禁新增裸 `limit()` 查 jobs 全表；看板「岗位总数」与库一致 |
| 9 | agent_tasks 留 processing 僵尸 | 采集中断/超时无人收尾 | 每小时看门狗：超 2 小时的 processing 记录自动置 failed；调度铁律 4 禁止留僵尸 | `SELECT count(*) FROM agent_tasks WHERE status='processing' AND requested_at < now()-interval '2 hours'` = 0 |
| 10 | browse.exe 启动失败 | 残留锁文件 + 失效代理环境变量 | `br.sh` 统一封装：先清 `terminal-agent-pid.lock`、unset 代理再启动，失败自动重试 4 次 | 猎聘采集走 collect_liepin3.sh（内含 br.sh） |
| 11 | 自动化被暂停无人知晓 | 手动暂停后遗忘 | 每次排查先查自动化状态；本表 #1 的验证方法兜底 | automation 状态 = ACTIVE |
| 13 | **点过「不投了 / 已投递」的岗位又出现在岗位池** | 三条路径：①「一键去重」按公司+岗位**跨状态**合并，`bestFirst` 把「不合适」排在最低优先级（STATUS_RANK=5），同组还剩一条待确认时就把"不投"记录删掉、留下待确认那条；② 同一个应用开在两个标签页/设备，A 里点过标记，B 里列表从不重载（旧代码只在动作后或重开页面时刷新）；③ `skipJob` 不校验更新是否命中，写库失败时界面照样刷新，岗位原地不动 | ① 一键去重改为**只在状态完全相同的组内合并**（key = 公司+岗位+状态），跨状态一律不动；② 新增列表新鲜度守卫：窗口获得焦点 / 从后台标签切回，自动重载当前页签（8 秒去抖）；③ `skipJob` 校验 `data.length`，未命中直接提示「状态未写入」；④ 岗位池渲染前后各兜一次状态白名单，非「待确认」永远进不去；⑤ `loadPool`/`loadConfirm` 不再静默吞异常，取数失败会写明"下方可能不是最新" | ① 池子里出现任何 `status <> '待确认'` 的卡片；② `SELECT j.status, count(*) FROM job_events e JOIN jobs j ON j.id=e.job_id WHERE e.event_type IN ('放弃投递','已投递','授权投递') AND j.status='待确认' GROUP BY 1` 必须为空；③ 点「不投了」应立刻 toast「✕ 已移入不投的岗位」 |
| 14 | 池子超过 2000 条后「智能导入」直接失败 | 导入查重用了 `limit(2000)` 硬截断，云库单次查询上限 1000 行，超限即报错 | 两条导入路径统一改走 `fetchAllJobs(cols)` 键集分页 | 导入任意内容不再报 `DATABASE_RESULT_EXCEED_MAX_ROWS`；查重集合覆盖全部历史状态（含已投递/不投），旧岗位不会因重新导入而复活 |
| 15 | 前端改完发布后整页按钮全失效 | 把 `bindListFilters()` 的调用放在 `const LIST` 声明之前（TDZ），语法合法、`node --check` 与 `new Function()` 都过，但浏览器加载即抛 ReferenceError，脚本中断 | 新增 `scripts/smoke-frontend.js`：用 Proxy 伪造 DOM/云 SDK 真正执行一遍内联脚本，任何顶层异常都让退出码为 1；发布前必须跑 | `node scripts/smoke-frontend.js ../job-agent/index.html app/index.html` 退出码 = 0 |
| 12 | 11-12 白天整日无采集、手动请求卡 pending 48 分钟 | 定时任务依赖客户端在线，实际每天只落地 1–2 次，8/18 点整点采集几乎从未成功；漏掉的触发不会回溯 | ① 调度阈值化：白天距上次入库 >8 小时即采（P1），不再等整点；夜间 >14 小时仍强制补采（P1b）；② **前端自动补采**：打开应用发现数据 >8 小时陈旧，自动写 collect_now（90 分钟去抖 + 已有 pending 不重复）；③ 调度铁律 8 明确自动补采请求按 P0 执行；④ pending 不允许跨轮滞留超 2 小时 | 打开应用看新鲜度条：>8 小时应出现「已自动排入补采队列」提示；`agent_tasks` 中不应出现 pending 超过 2 小时 |

## 二、调度可靠性的真相（必须知道）

本机自动化**不是可靠的定时器**：它依赖 WorkBuddy 客户端在运行、电脑不休眠。实测 11-10 至 11-12 三天，每天只成功采集 1–2 次，且集中在深夜（P1 补采救场），设计的 8:00 / 18:00 整点采集基本没落地过。

所以设计上不再把"准时"当作前提，而是**任何一次触发都尽量干活**：

- 触发稀疏 → P1 阈值化后，每次触发只要数据超 8 小时就采，不会空手而归；
- 完全不触发（关机/休眠）→ 前端自动补采 + 重开后 P1b 兜底；
- 用户想立刻要新岗位 → 应用里「⚡ 通知 Agent 立即采集」按钮，或直接在对话里说一声。

判断有没有问题，只看一个指标：**应用顶部「最近入库」**。超过 8 小时就该出现自动补采提示，超过 24 小时标黄即视为异常。

## 二、每轮采集收尾自检（执行 Agent 必做，任何一项不过都要在 note 里写明）

1. **入库数**：本轮入库 > 0，或「重复 M 个」有具体数字可查（0 入库且 0 重复 = 异常，必须写失败原因）。
2. **领英没有静默跳过**：note 里领英要么有入库数，要么有「领英跳过：<原因>」；脚本输出里 RETRY-ENQUEUE / RETRY-PICK 出现说明队列在工作，属正常。
3. **游标推进**：`liepin-kw-cursor.txt` 和 `linkedin-kw-cursor.txt` 本轮已更新（读取 → 取词 → 写回）。
4. **登记收尾**：agent_tasks 已置 done/failed，不留 processing。
5. **打分完成**：新入库岗位全部有 match_score，或 note 注明为什么没打。
6. **状态一致性**（2026-11-12 新增）：跑一次等价于前端「🩺 数据自检」的三条 SQL，任何一条非空都要写进 note：
   - 重复：`SELECT company, position, count(*) FROM jobs WHERE owner_id='<uid>' GROUP BY 1,2 HAVING count(*)>1`
   - 标记丢失：`SELECT j.id FROM job_events e JOIN jobs j ON j.id=e.job_id WHERE e.event_type IN ('放弃投递','已投递','授权投递') AND j.status='待确认'`
   - 异常状态：`SELECT DISTINCT status FROM jobs WHERE status NOT IN ('待确认','待投递','已投递','已查看','已回复','面试邀请','不合适','已拒绝')`

## 三、改动纪律（防止"修复"本身变成新事故）

- **查重规则是红线**：全状态、永久、不设时间窗。任何采集优化（改词、改页数、改脚本）都不得触碰 `dedupe.py` 的比对逻辑。
- **打分只改 score_jobs.py**：不允许在采集轮里临时写打分脚本——历史上同一个 bug 复发 3 次就是因为规则一路漂移。
- **前端禁裸 limit 查全表**：jobs 表的任何全量读取必须走 `fetchAllJobs()`（键集分页）或 `dump-existing.py`，云库单次 1000 行上限永远存在。
- **脚本改动必须实测**：改完至少跑一次 `--pages 1` 级别的真实调用，看 GATE/KW/ALL DONE 输出正常再收工。
- **状态是用户资产，只能由用户意图改变**：任何批量/清理/去重逻辑都不得跨状态合并记录，也不得把"非待确认"的记录改回待确认（唯一例外是用户手点「↩ 移回待确认」）。合并逻辑的 key 必须包含 `status`。
- **列表只显示白名单状态**：岗位池只允许「待确认」，最新岗位清单只允许「待确认」，已确认投递只允许「待投递」。新增任何列表都要显式过滤，禁止"全量渲染再靠角标区分"。
- **写状态必须校验命中行数**：`update(...).eq('id',id).select()` 之后必须检查 `data.length`，为 0 就明确报错，不允许"静默刷新界面"。
- **异常不许静默**：列表加载的 `catch` 里必须给出可见提示，不能让旧 DOM 冒充当前数据。
- **列表必须分页 + 白名单**（2026-11-12）：任何岗位列表每页 ≤30 条并带筛选（平台/匹配度/新鲜度），禁止一次性渲染上千张卡片；列表只显示白名单状态。
- **前端改动必须过冒烟测试**（2026-11-12）：发布前跑 `node scripts/smoke-frontend.js ../job-agent/index.html app/index.html`，退出码必须为 0。
  `node --check` / `new Function(code)` 只验语法，查不出运行期引用错误。真实事故：把 `bindListFilters(...)` 写在 `const LIST` 之前，语法合法但浏览器一加载就抛
  `ReferenceError: Cannot access 'LIST' before initialization`，整段脚本中断、全站按钮失效，而发布流程毫无异常提示。
