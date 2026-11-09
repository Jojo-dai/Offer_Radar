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

## 二、每轮采集收尾自检（执行 Agent 必做，任何一项不过都要在 note 里写明）

1. **入库数**：本轮入库 > 0，或「重复 M 个」有具体数字可查（0 入库且 0 重复 = 异常，必须写失败原因）。
2. **领英没有静默跳过**：note 里领英要么有入库数，要么有「领英跳过：<原因>」；脚本输出里 RETRY-ENQUEUE / RETRY-PICK 出现说明队列在工作，属正常。
3. **游标推进**：`liepin-kw-cursor.txt` 和 `linkedin-kw-cursor.txt` 本轮已更新（读取 → 取词 → 写回）。
4. **登记收尾**：agent_tasks 已置 done/failed，不留 processing。
5. **打分完成**：新入库岗位全部有 match_score，或 note 注明为什么没打。

## 三、改动纪律（防止"修复"本身变成新事故）

- **查重规则是红线**：全状态、永久、不设时间窗。任何采集优化（改词、改页数、改脚本）都不得触碰 `dedupe.py` 的比对逻辑。
- **打分只改 score_jobs.py**：不允许在采集轮里临时写打分脚本——历史上同一个 bug 复发 3 次就是因为规则一路漂移。
- **前端禁裸 limit 查全表**：jobs 表的任何全量读取必须走 `fetchAllJobs()`（键集分页）或 `dump-existing.py`，云库单次 1000 行上限永远存在。
- **脚本改动必须实测**：改完至少跑一次 `--pages 1` 级别的真实调用，看 GATE/KW/ALL DONE 输出正常再收工。
