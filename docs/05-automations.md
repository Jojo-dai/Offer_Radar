# 05 · 定时任务配置（可直接粘贴）

> **推荐：只建 1 个「总调度」任务** —— `FREQ=HOURLY;INTERVAL=2`，prompt 内部按阈值分派 P0–P5：
> 有 pending 采集请求立即执行（P0）、白天数据超 8 小时就采（P1）、夜间超 14 小时强制补采（P1b）。
> 原因：本机定时器依赖客户端在线，实测每天只落地 1–2 次，8:00 / 18:00 整点几乎从未成功
> （见 [11-guardrails.md](11-guardrails.md) 第二节）。
>
> 下面三段是**旧的三任务方案**，保留供已部署者对照与兼容；**新部署不要再建三个**。

> 复刻时把 `<APPLICATION_ID>` 换成你自己的 `wbapp_...`，把 `<SHARE_LINK>` 换成你自己的应用链接即可。
>
> - 旧任务 1：采集（早）`FREQ=DAILY;BYHOUR=8;BYMINUTE=0`
> - 旧任务 2：采集（晚）`FREQ=DAILY;BYHOUR=18;BYMINUTE=0`
> - 旧任务 3：检查点 `FREQ=HOURLY;INTERVAL=1`
> - **新推荐：总调度** `FREQ=HOURLY;INTERVAL=2`（单个任务，替代上面三个）

## 2026-11-09 夜间手动补采实测（429 的杀伤粒度是"整词"）

补跑一轮，两侧都走通，顺带把 429 的真实影响量清楚了。

| 环节 | 实测 |
|---|---|
| 猎聘 | 3 词 × 2 页，每页均 42 张卡片，全部提取成功（SAP BPC / SAP 顾问 / SAP 项目经理） |
| 领英 | 4 词 × 5 页：SAP S/4HANA Finance 50 条、BPC Consultant 50 条、Business Planning and Consolidation 50 条；**Comprehensive Budget Management 在第 1 页 start=0 就 429，冷却 63s 重试仍 429，该词整段 0 条** |
| 落库 | 候选 402 条（猎聘 252 / 领英 150）→ 地点收窄保留 222（外地跳过 180）→ 重复跳过 108 → 新增 114（猎聘 54 / 领英 60） |
| 打分 | 114 条全部打分，均分 60.5，≥70 共 43 条（SAP FICO / CO / SCM 顾问、Adidas FP&A Senior Manager 等） |
| 库容 | 1 150 → 1 264 条，待确认 1 191 条 |

结论与待办：429 一旦落在某个词的**首页**，冷却重试也救不回来，损失的是整个词（约 50 条），而不是几页。所以「失败词冷却 5–10 分钟后排队重采」应该做，优先级高于再调页间隔——页间隔已经在 3–5 秒抖动、词间隔 4–6 秒，再拉长只是让人更早被限流，救不回已丢的整词。

查重规则依旧一字未动：全状态、永久、不设时间窗。

## 2026-11-06 领英采集重构（永久解决"领英抓不到"）

11-06 两轮采集（09:13 补跑、18:09 定时）都只进了猎聘、领英 0 条。原因不是关键词，而是**门禁判据错了**：旧规则先看"出口 IP 地理判定是否为 CN"，是 CN 就直接整段放弃领英；当天出口是上海电信 IP，于是两条腿全断，而实际上 jobs-guest 接口当时可用。

| 项目 | 旧 | 新 |
|---|---|---|
| 门禁判据 | 出口 IP 不是 CN 且 linkedin.com 返回 200 | **接口实测**：jobs-guest 返回 ≥1 条卡片就放行；302→linkedin.cn / 429 / 451 / 0 条才跳过 |
| 采集方式 | browse.exe 开浏览器 → 提取（90 条 / 5 分 26 秒） | `job-apply-agent/scripts/collect-linkedin-guest.py` 直连 HTTP（200 条 / 2 分 40 秒） |
| 每词页数 | 3 页（30 条） | **5 页（50 条）**，实测 start=40 仍有结果 |
| 每轮词数 | 3 个 | **4 个**（单轮上限 90 → 200 条） |
| 词池轮换周期 | 3 词/轮 → 5 轮 2.5 天 | 4 词/轮 → 4 轮 2 天 |

> 查重规则仍然一个字未动：全状态、永久、不设时间窗。本次只改"怎么抓"和"什么时候允许抓"，不改"抓回来怎么判重"。
>
> 配套脚本：`job-apply-agent/scripts/collect-linkedin-guest.py`（采集，退出码 2 = 接口不可用）、`job-apply-agent/scripts/check-network.sh`（自检，同一口径）。两者都以接口返回为准，IP 只做提示信息打印。

## 2026-11-05 关键词重估（v2）

用户反馈「岗位池里没有新的、不一样的岗位进来」，排查结论是**关键词偏科 + 前端只展示高分前 200 条**，不是采集坏了。本次调整只动两处，**查重规则一字未改**：

| 项目 | 旧 | 新 |
|---|---|---|
| 中文词池 | 15 词，猎聘固定只用前 3 个（全面预算/BPC/SAP BPC），不翻页 | 15 词按游标轮换（含 SAP 顾问、SAP 项目经理、SAP 实施顾问、财务数字化、EPM 预算等），每词 2 页 |
| 英文词池 | 含裸词 `Project Manager`，轮到即涌入大量无关岗 | 换成 `SAP Project Manager`、`SAP Senior Consultant`、`SAP Consultant`、`SAP S/4HANA Finance`、`BPC Consultant`、`FP&A Manager` 等限定词；泛词自动加 `SAP ` 前缀 |
| 查重 | 全状态、永久 | **完全不变**（见下方红线） |

> 这些 SAP 字眼同时作为**相关性首选标记**：打分时岗位标题/摘要命中 SAP BPC、SAP Project Manager、SAP Senior Consultant 等，视为强相关证据；但**不作为硬过滤**——不命中不等于丢弃，避免又回到"筛得太严"的老问题。

>
> 任务 1 与任务 2 的 prompt **完全相同**（内容与时间无关），只是 RRULE 不同。

---

## 任务 1 / 任务 2 · 定时采集 + 打分

**RRULE**：`FREQ=DAILY;BYHOUR=8;BYMINUTE=0`（早） / `FREQ=DAILY;BYHOUR=18;BYMINUTE=0`（晚）

```text
这是「投递助手」的定时自动采集+打分任务（工作区 <WORKSPACE>）。目标：① 用无头浏览器采集猎聘在招岗位；② 用脚本直连领英 jobs-guest 公开接口采集领英（LinkedIn）搜索结果（不依赖登录态与浏览器）；③ 全部与云数据库全量去重后入库；④ 对新入库岗位按 JEV 方法论自动打分；⑤ 把本轮运行登记到 agent_tasks 表；最后给用户发简短汇总。全程只读网页，绝不点击投递、发消息或修改任何设置。

【状态口径（全局统一，必须遵守）】
- 已完成：status='done'，note=统计摘要（如：猎聘入库N1条/领英入库N2条/重复M个/打分K条）。
- 已失败：status='failed'，note 必须以「失败原因：」开头 + 一句话原因（≤40字）。不罗列细节。
- 已合并：status='merged'，note 以「已合并：」开头 + 一句话说明。
- 进行中：status='processing'，note='定时采集运行中'。超过 2 小时仍 processing 视为卡死，会被每小时看门狗切断标失败。

【第0步：读取画像】用 mcp__genie-baas__workbuddy_cloudservice_db_exec_sql（applicationId=<APPLICATION_ID>，mode=read）执行：SELECT id, owner_id, owner_name, keywords, keywords_en, competitiveness, target_profile FROM profiles WHERE is_active=true AND confirmed=true ORDER BY created_at DESC LIMIT 1。
- 若无结果：给用户发一句话提醒「请先完成投递助手①简历分析与确认画像，之后采集任务才会自动运行」，附链接 <SHARE_LINK> ，结束（不登记记录）。
- 若有结果：记下 owner_id、owner_name、keywords、keywords_en、competitiveness、target_profile（含 cities_en），第3.5步复用。

【第0.4步：防重复补跑守卫】1. mode=write 清理僵尸：UPDATE agent_tasks SET status='failed', note='失败原因：运行超时无响应，已自动切断', processed_at=now() WHERE status='processing' AND requested_at < now() - interval '2 hours'。2. mode=read 检查：SELECT id, requested_at FROM agent_tasks WHERE type='collect_scheduled' AND status='processing' AND requested_at > now() - interval '90 minutes' ORDER BY requested_at DESC LIMIT 1 —— 有结果说明另一轮在跑，本轮直接结束（不采集、不写库、不发消息）。

【第0.5步：登记运行记录】mode=write 执行：INSERT INTO agent_tasks (owner_id, owner_name, type, status, note) VALUES ('<owner_id>', '<owner_name>', 'collect_scheduled', 'processing', '定时采集运行中')。再 mode=read：SELECT id FROM agent_tasks WHERE owner_id='<owner_id>' AND type='collect_scheduled' AND status='processing' ORDER BY requested_at DESC LIMIT 1，记下 run_id。

【第1步：猎聘无头采集】**关键词按游标轮换（2026-11-05 新增，防止固定 3 词吃干第一页）**：读 profiles.keywords（中文）全量得词池（当前 15 个：SAP BPC / SAP 顾问 / SAP 项目经理 / SAP 实施顾问 / 全面预算 / 合并报表 / 业财一体化 / 财务数字化 / EPM 预算 / AI 产品经理 / 企业级 AI / 大模型应用 / 数字化转型 / 解决方案架构师 / 数据产品经理）；读游标 `.workbuddy/tmp/liepin-kw-cursor.txt`（无则 0），从游标起循环取 3 个，用完写回 `(游标+3) % 池长`——15 个词约 5 轮（2.5 天）全部轮到一次。
每个关键词取 2 页：`https://www.liepin.com/zhaopin/?key=<URL编码关键词>&currentPage=<1|2>`（翻页参数以站点实测为准：若第 2 页结果与第 1 页完全重复，则该词只算 1 页，并在汇总注明「翻页无效」）。每个关键词依次（间隔 sleep 30-60 秒）：
用 /c/Users/<USER>/.workbuddy/skills/gstack/browse/dist/browse.exe：1) goto 该 URL（含 Server failed 则重试一次）；2) sleep 5；3) 执行 js 提取（单行 JSON.stringify）：遍历 document.querySelectorAll('a[data-nick=job-detail-job-info]')，取 title=第一个 div[title] 的 title 属性；link=a.href 去掉 ? 后参数；salary=a 内 span 文本匹配 /^\d/ 且含 k 或 万 的第一个；location=以 区/县/市 结尾的第一个 span 文本；tags=含「年以下|年以上|本科|硕士|大专|博士」的 span 文本拼接；company=a.closest('li') 内 [class*=companyName] 或 [data-nick*=company] 的文本；4) 写入 .workbuddy/tmp/liepin-<关键词slug>.json。0 条则记录后继续。

【第2步：领英采集（直连 jobs-guest 公开接口，2026-11-06 重构）】**唯一主路径**：用脚本 `job-apply-agent/scripts/collect-linkedin-guest.py` 直连领英访客接口，不开浏览器、不依赖登录态。实测 200 条约 2 分 40 秒（旧 browse.exe 通道 90 条约 5 分半）。
- 门禁**不再看出口 IP**：脚本内置探针，先请求一次接口，返回 ≥1 条卡片即放行；302→linkedin.cn / 429 / 451 / 0 条才跳过。跑之前也可单独执行 `bash job-apply-agent/scripts/check-network.sh` 自检（同样是接口实测口径）。
- 调用：`python job-apply-agent/scripts/collect-linkedin-guest.py --keywords "<词1>,<词2>,<词3>,<词4>" --pages 5 --out .workbuddy/tmp`，退出码 2 = 接口不可用，此时跳过领英并在 note 写明原因，不要重试、不要改走直连。
- 每关键词 **5 页**（start=0/10/20/30/40，每页 10 条，实测第 5 页仍有结果）；某页不足 10 条自动停该词的翻页；页间隔 3-5 秒抖动、词间隔 4-6 秒，脚本已内置。
- **429 自适应**：某页返回 429 时脚本先冷却 45-75 秒再重试一次，仍 429 才放弃该关键词（继续跑后面的词）。实测一轮 20 页约在第 16-17 页开始被限流，冷却重试能把剩余页捞回来；不要让 Agent 在 429 后手工狂重试。
- **每轮取 4 个关键词**（旧口径 3 个）：单轮上限 200 条，是旧口径（3×3×10=90）的 2.2 倍。
- **失败词自动补采（2026-11-10 新增，防 429 丢词）**：脚本会把"被限流中断"的词写入 `.workbuddy/tmp/linkedin-retry-queue.json`，下轮运行自动补采冷却满 30 分钟的失败词（每轮最多补 1 个，总词数 ≤5）；门禁整体跳过时本轮词也全部入队，接口恢复后自动补采。看到 `RETRY-PICK`（补采上轮失败词）或 `RETRY-ENQUEUE`（本轮失败词已入队）属正常，无需人工处理；失败词被顺延时输出 `RETRY-DEFER`。
关键词选择：读 keywords_en 全量，去掉括号注释（取括号前部分）得有效词池（当前 15 个：SAP BPC / SAP Project Manager / SAP Senior Consultant / SAP Consultant / SAP S/4HANA Finance / BPC Consultant / Comprehensive Budget Management / Business Planning and Consolidation / AI Product Manager / Enterprise AI Solutions / Digital Transformation / Large Language Model(LLM) / RAG / Multi-Agent Systems / FP&A Manager）；读游标 `.workbuddy/tmp/linkedin-kw-cursor.txt`（无则 0），从游标起循环取 4 个，用完写回 (游标+4) % 池长——15 词约 4 轮（2 天）全部轮到一次。
**泛词护栏**：取到的词若不含 SAP / BPC / AI / LLM / Digital 等限定前缀且属于 Project Manager、Consultant、Product Manager 这类泛词，自动拼成「SAP + 原词」再搜；带限定词的保持原样。地点取 target_profile.cities_en 第一个，不含「China」则追加「, China」，缺省 Shanghai, China（脚本 --location 参数）。
**回退方式（仅当脚本因解析结构变化返回 0 条、且接口本身 200 可用时）**：mcp__browser__browsers_list 取 Edge 扩展浏览器，tabs_new 打开 https://www.linkedin.com/jobs/search/?keywords=<编码关键词>&location=<地点>&f_TPR=r604800，等 6 秒；页面若重定向到 linkedin.cn 或出现 451/登录页/验证码则放弃；429 立即放弃。滚动：把鼠标 move 到列表区域（x≈屏宽×0.34，y=500）再 scroll，滚 5 屏、每屏等 4-6 秒再 dom_cua_get_visible_dom、按 link 去重累积（上限 40 条）。此路径只做兜底，不要每轮都走。
采集结果由脚本写入 .workbuddy/tmp/li-page-<slug>-<start>.json（platform='领英'；脚本输出已按 3.x 步所需的 title/company/location/link 字段对齐）。
5) 卡片缺链接时用「岗位名+公司名」精确搜索一次补齐 /jobs/view/<id>；仍找不到则在 jd_summary 标注。间隔 sleep 30-60 秒。只读，绝不点职位卡、绝不 Easy Apply。

【第3步：写入岗位池——全状态查重（本步是本任务最关键的约束，必须严格执行）】
3.0 地点收窄（先做）：只保留 location 含「上海 / Shanghai / 远程 / Remote / 全国」之一的候选，外地一律跳过并计入「外地跳过」数。2026-10-29 实测猎聘 111 条去重后仅 24 条在上海。
3.1 先取全量存量（不限状态）：执行
python job-apply-agent/scripts/dump-existing.py
【查重取数：必须分页】存量岗位**只能**通过该脚本导出（id 键集分页，每页 900），禁止手写 `SELECT ... LIMIT 2000`。
> **云库单次查询上限 1000 行**（`DATABASE_RESULT_EXCEED_MAX_ROWS`）。岗位池 2026-11-09 已达 1150 条，一次拉全量会直接报错、整轮采集中断在查重这一步。脚本按 id 键集分页（每页 900），池子涨到几万条也稳。

【查重范围：全状态】必须把返回的全部记录都放进比对集合，涵盖 待确认 / 待投递 / 已查看 / 已投递 / 面试中 / 不合适 / 已拒绝 等所有状态。绝不能只比对 status='待确认' 的记录——已投递或已拒绝的岗位同样算「已存在」，不得再次作为新岗位写入。**此条为最高优先级硬约束（用户 2026-11-05 再次确认）：任何关键词、翻页或流程优化都不得放宽，也不得改成"仅比对近 N 天"。**
3.2 规范化函数（用于生成岗位键）：把公司名、岗位名分别处理——转小写 → 删除「招聘/诚聘/急招/热招/岗位名称/职位名称/岗位/职位」等字样 → 删除所有空格（含全角空格）与标点符号（全角括号、英文括号、方括号、斜杠、反斜杠、连字符、下划线、顿号、逗号、句点、冒号、分号、加号、星号、引号等）。得到 norm(company)+'|'+norm(position) 即岗位键。
3.3 逐条判定（对猎聘 + 领英的每一个采集结果）：
  a) 岗位键命中存量集合 或 命中本轮已入库集合 → 判定为重复，直接跳过，不写入、不改状态、不打分，重复计数 M+1。即使链接不同、平台不同、薪资不同也必须跳过。
  b) 链接兜底：source_url 去掉 ? 与 # 及其后内容后与存量完全相同 → 也判定重复跳过。
  c) 仅当岗位键与链接都未命中时，才 INSERT INTO jobs (owner_id, owner_name, company, position, jd_summary, salary, location, source_url, platform, status) VALUES ('<owner_id>', '<owner_name>', '<company>', '<position>', '<tags 或「自动采集：详情见职位链接」>', '<salary 或「面议」>', '<location>', '<link>', '<猎聘/领英>', '待确认')；写入后立刻把该岗位键加入本轮已入库集合。单轮总入库上限 200 条。
  d) 存量中有同一岗位但字段缺失（库中无链接而新采集有链接；或库中 salary/location 为空）→ 不新增，改为 UPDATE jobs SET source_url=COALESCE(source_url,'<新链接>'), salary=CASE WHEN salary IS NULL OR salary='' THEN '<新薪资>' ELSE salary END, location=CASE WHEN location IS NULL OR location='' THEN '<新地点>' ELSE location END, updated_at=now() WHERE id=<存量id>。补齐字段可以，但绝不改变原 status、绝不重新打分为待确认。
3.4 入库后自检（必须执行）：mode=read 执行
SELECT company, position, count(*) AS cnt FROM jobs WHERE owner_id='<owner_id>' GROUP BY company, position HAVING count(*)>1 ORDER BY cnt DESC
若返回结果，按「状态优先级 已投递>面试中>已查看>待投递>待确认>不合适 → 匹配度更高 → 有链接 → id 更小」保留一条，其余同组记录先 UPDATE job_events SET job_id=<保留id> WHERE job_id=<被删id>，再 DELETE FROM jobs WHERE id=<被删id>，并在汇总里说明清理了几条。

【第3.5步：JEV 自动打分】仅对本轮新入库且 status='待确认' 的岗位逐条打分。

> **唯一权威打分器：`python job-apply-agent/scripts/score_jobs.py`**（2026-11-09 固化）。
> 以前每轮都在 `.workbuddy/tmp/scoreN.py` 里临时改一份，规则一路漂移，同一个 bug 反复出现。
> 现在脚本即口径：新增/调整规则只改这个文件，采集轮一律调用它，不允许再手写一次性打分脚本。
>
> 本次修掉的 bug：猎聘卡片标题带「招聘」前缀（如「招聘数据产品经理」），被 HR 硬冲突正则
> `招聘|hrbp|...` 命中，整批猎聘岗位一律判 26 分沉底——11-09 那轮 45 条、历史累计 75 条中招。
> 修复：打分前先剥前缀，HR 只匹配 `招聘(专员|经理|主管|顾问|助理|总监)|hrbp|人力资源|recruiter`。
> 采集收尾时顺手跑 `--where "position LIKE '招聘%'" --fix-prefix` 可清掉存量标题前缀。

- 方法论：核心技能与岗位要求匹配 35%；行业/业务领域 15%；职级与经验年限 20%；薪资与地点可行性 15%；与目标岗位方向的发展契合度 15%。只依据画像中真实存在的证据，禁止虚构脑补；证据不足按保守中间分计；硬性冲突（城市/职级/行业完全不符）直接 <50。
- 依据 position/jd_summary/salary/location 对照画像，给出 0-100 与 match_reason（≤30字：得分主依据+最大缺口）。
- **关键词加权（2026-11-05，修正"打分过严"）**：岗位标题或 JD 摘要命中 SAP BPC / SAP Project Manager / SAP Senior Consultant / SAP Consultant / BPC Consultant / 全面预算 / 合并报表 / 业财一体化 / 财务数字化 之一，核心技能维度按「强相关」计（不低于 70），总分相应上调；未命中的按原规则评估，**不因未命中而扣分**（命中即加分，不命中不减分）。
- mode=write：UPDATE jobs SET match_score=<0-100>, match_reason='<原因>', updated_at=now() WHERE id=<job_id>。存量老岗位一律不重新打分。

【第4步：收尾登记+汇总】收尾前先做**轮末自检**（docs/11-guardrails.md 第二节，逐条核对）：① 本轮入库>0 或重复数有值；② 领英未静默跳过；③ 两个关键词游标文件已推进；④ 打分完成或注明原因；⑤ 状态一致性三条 SQL（重复 / 标记丢失 / 异常状态值）全为空，非空则照实写进 note 并用前端「🩺 数据自检」修复。任何一项不过，在 note 里写明，不许静默略过。然后清理 .workbuddy/tmp/ 临时 JSON，然后 mode=write：两部分都完全失败（0 入库）→ UPDATE agent_tasks SET status='failed', note='失败原因：<≤40字>', processed_at=now() WHERE id='<run_id>'；否则 → UPDATE agent_tasks SET status='done', note='猎聘入库N1条/领英入库N2条/重复M个/清理重复C条/打分K条', processed_at=now() WHERE id='<run_id>'（领英跳过时在 note 末尾注明「领英跳过：<脚本给出的原因>」）。补跑（比计划晚 30 分钟以上）在 note 末尾加「（补跑）」。汇总消息包含：运行时间、猎聘新入库 N1、领英新入库 N2（跳过则注明原因）、因已存在而跳过 M 个（注明其中分别有多少是已投递/已拒绝岗位）、自检清理 C 条、已打分 K 条（列出最高分前 3：公司+岗位+分数），附链接 <SHARE_LINK> 并提示去「③ 投递清单 · 最新岗位清单」查看。
【注意】猎聘 goto 连续失败或遇验证码/异常页，该部分说明后结束（重试不超过 2 次），继续领英。不访问职位详情页，不做登录、点击投递等操作。
```

**为什么这段 prompt 要写得这么"啰嗦"**：它同时承担了三件事——流程定义、状态口径、以及**唯一能防重复的查重规则**。任务由 LLM 执行，任何含糊表述都会在每天两轮的累积里变成系统性偏差（历史上"同一岗位重复 5 条"就是这么来的）。

---

## 任务 3 · 每小时检查点（看门狗 + 消费手动请求）

**RRULE**：`FREQ=HOURLY;INTERVAL=1`

```text
这是「投递助手」的手动采集请求检查点任务（工作区 <WORKSPACE>）。它每小时被触发一次，承担两个职责：A) 看门狗——切断卡死的采集运行；B) 消费用户在应用里点「⚡ 通知 Agent 立即采集」产生的手动请求。绝大多数运行应是空跑——没有超时记录且无请求时必须静默结束，不发任何消息、不做任何写操作。

【第0步：看门狗——切断超时运行（每次必执行）】用 mcp__genie-baas__workbuddy_cloudservice_db_exec_sql（applicationId=<APPLICATION_ID>，mode=write）执行：
UPDATE agent_tasks SET status='failed', note='失败原因：运行超时无响应，已自动切断', processed_at=now() WHERE status='processing' AND requested_at < now() - interval '2 hours'
（对 collect_scheduled 和 collect_now 一视同仁；正常采集一轮约 20-60 分钟，超过 2 小时无收尾即视为卡死。）

【第0.5步：检查请求队列】用 mode=read 执行：SELECT id, owner_id, owner_name, requested_at FROM agent_tasks WHERE type='collect_now' AND status='pending' ORDER BY requested_at ASC LIMIT 1。
- 若无结果：直接结束，不给用户发任何消息，不做任何写操作。
- 若有结果：记下 task_id、owner_id、owner_name，继续。

【第1步：锁定请求】用 mode=write 执行两条 UPDATE（逐条执行）：
1. UPDATE agent_tasks SET status='processing', processed_at=now() WHERE id='<task_id>'
2. UPDATE agent_tasks SET status='merged', note='已合并：与同一时段正在进行的采集合并执行', processed_at=now() WHERE type='collect_now' AND status='pending' AND id<>'<task_id>'

【第2步：读取画像】用 mode=read 执行：SELECT id, owner_id, owner_name, keywords, keywords_en, competitiveness, target_profile FROM profiles WHERE owner_id='<owner_id>' AND is_active=true AND confirmed=true ORDER BY created_at DESC LIMIT 1。
- 若无结果：UPDATE agent_tasks SET status='failed', note='失败原因：画像未确认，请先在应用①完成简历分析并确认画像', processed_at=now() WHERE id='<task_id>'，然后给用户发一条消息「手动采集未能执行：请先在应用①完成简历分析并确认画像」，附链接 <SHARE_LINK> ，结束。

【第3步：猎聘无头采集】**关键词按游标轮换**：读 profiles.keywords（中文）全量得词池；读游标 `.workbuddy/tmp/liepin-kw-cursor.txt`（无则 0），从游标起循环取 3 个，用完写回 `(游标+3) % 池长`。每个关键词取 2 页：`https://www.liepin.com/zhaopin/?key=<URL编码后的关键词>&currentPage=<1|2>`（第 2 页与第 1 页完全重复则只算 1 页并注明）。对每个关键词依次执行（不同搜索之间 sleep 30-60 秒随机间隔）：
用命令 /c/Users/<USER>/.workbuddy/skills/gstack/browse/dist/browse.exe：
1. goto 该 URL（若输出含 Server failed 则再执行一次 goto 重试）
2. sleep 5
3. 执行 js 提取（单行 JSON.stringify）：遍历 document.querySelectorAll('a[data-nick=job-detail-job-info]')，每条取：title = 第一个 div[title] 的 title 属性；link = a.href 去掉 ? 后参数；salary = a 内 span 文本中匹配 /^\d/ 且含 k 或 万 的第一个；location = a.textContent 匹配 /【([^】]+)】/ 的第一段（如「苏州-常熟」，旧版按「区/县/市」结尾匹配会漏掉「xx-xx」格式）；tags = 匹配含「年以下|年以上|本科|硕士|大专|博士」的 span 文本拼接；company = a.closest('div.jobDetailBox')（注意：2026-10 实测卡片没有 li 容器，closest('li') 返回 null）内 [class*=companyNam] 元素的文本。实测避坑：browse 守护进程崩溃后会在 <WORKSPACE>/.gstack/terminal-agent-pid.lock 留下 0 字节残留锁，导致后续所有启动报「Server failed to start」——重试前先删除该锁文件；若环境变量含失效的 HTTP(S)_PROXY，browse 启动时也会失败，需先 unset。
4. 把 JSON 写入 .workbuddy/tmp/liepin-<关键词slug>.json。若猎聘整体失败（goto 连续异常/验证码），记下失败原因，继续第4步。

【第4步：领英采集（直连 jobs-guest 接口，2026-11-06 重构）】用 `python job-apply-agent/scripts/collect-linkedin-guest.py --keywords "<4 个词>" --pages 5 --out .workbuddy/tmp` 一次跑完 4 词 × 5 页（约 200 条，2-3 分钟）。
- 门禁以脚本输出为准：`GATE PASS` 才继续；`GATE FAIL` / `SKIP linkedin: <原因>`（退出码 2）→ 跳过领英，note 记「领英跳过：<原因>」，不重试、不改走直连。
- 关键词：读 keywords_en，从游标 `.workbuddy/tmp/linkedin-kw-cursor.txt` 起取 4 个循环，写完回写 (游标+4)%池长。泛词（无 SAP/BPC/AI/LLM/Digital 限定）自动拼「SAP + 原词」。
- 脚本产出 .workbuddy/tmp/li-page-<slug>-<start>.json，字段已对齐 title/company/location/link，直接进入第 5 步查重。
- 仅在接口 200 可用但解析出 0 条（疑似页面改版）时，才回退 Edge 浏览器路径：mcp__browser__browsers_list 取 Edge → tabs_new 打开 https://www.linkedin.com/jobs/search/?keywords=<编码关键词>&location=<地点>&f_TPR=r604800 → 等 6 秒 → 列表内层窗格滚动 5 屏（每屏 4-6 秒）→ dom_cua_get_visible_dom 按 link 去重累积（上限 40 条）。重定向 linkedin.cn / 429 / 451 立即放弃。
直连接口路径的节流已内置在脚本里（页间隔 3 秒、词间隔 4 秒），不需要额外 sleep；只有回退到 Edge 浏览器路径时才需要词间 30-60 秒。全程只读，绝不点击职位卡、绝不点击 Easy Apply。**失败词重采队列已内置在脚本里**（RETRY-PICK / RETRY-ENQUEUE / RETRY-DEFER 输出属正常现象，详见任务 2 第 4 步说明），不需要也不允许手工管理队列文件。
【地点收窄】写库前只保留上海/远程/全国（location 含「上海 / Shanghai / 远程 / Remote / 全国」之一）；外地岗位一律跳过并在汇总里报数。2026-10-29 实测猎聘单轮 111 条去重后仅 24 条在上海，不加这层过滤会持续稀释清单。

【第5步：写入岗位池——全状态查重（本步是最关键约束，必须严格执行）】
5.1 先取全量存量（不限状态）：执行
python job-apply-agent/scripts/dump-existing.py
（禁止手写 `SELECT ... LIMIT 2000`：云库单次上限 1000 行，会直接报错）
【查重范围：全状态】返回的全部记录都进入比对集合，涵盖 待确认 / 待投递 / 已查看 / 已投递 / 面试中 / 不合适 / 已拒绝 等所有状态。绝不能只比对 status='待确认'——已投递或已拒绝的岗位同样算「已存在」，不得再次作为新岗位写入。
5.2 规范化函数：公司名、岗位名分别 转小写 → 删除「招聘/诚聘/急招/热招/岗位名称/职位名称/岗位/职位」等字样 → 删除所有空格（含全角空格）与标点（全角括号、英文括号、方括号、斜杠、反斜杠、连字符、下划线、顿号、逗号、句点、冒号、分号、加号、星号、引号等）。得到 norm(company)+'|'+norm(position) 即岗位键。
5.3 逐条判定（猎聘 + 领英的每一条）：
  a) 岗位键命中存量集合 或 命中本轮已入库集合 → 重复，直接跳过（不写入、不改状态、不打分），M+1。即使链接不同、平台不同、薪资不同也必须跳过。
  b) 链接兜底：source_url 去掉 ? 与 # 及其后内容后与存量完全相同 → 也跳过。
  c) 仅当两者都未命中才 INSERT INTO jobs (owner_id, owner_name, company, position, jd_summary, salary, location, source_url, platform, status) VALUES ('<owner_id>', '<owner_name>', '<company>', '<title>', '<tags 或「自动采集：详情见职位链接」>', '<salary 或「面议」>', '<location>', '<link>', '<猎聘/领英>', '待确认')；写入后把岗位键加入本轮集合。单轮上限 200 条。
  d) 存量同岗位但字段缺失（无链接/薪资空/地点空）→ 不新增，改为 UPDATE jobs SET source_url=COALESCE(source_url,'<新链接>'), salary=CASE WHEN salary IS NULL OR salary='' THEN '<新薪资>' ELSE salary END, location=CASE WHEN location IS NULL OR location='' THEN '<新地点>' ELSE location END, updated_at=now() WHERE id=<存量id>；绝不改原 status、绝不重置为待确认。
5.4 入库后自检（必须执行）：mode=read 执行
SELECT company, position, count(*) AS cnt FROM jobs WHERE owner_id='<owner_id>' GROUP BY company, position HAVING count(*)>1 ORDER BY cnt DESC
若有结果，按「已投递>面试中>已查看>待投递>待确认>不合适 → 匹配度更高 → 有链接 → id 更小」保留一条，其余先 UPDATE job_events SET job_id=<保留id> WHERE job_id=<被删id>，再 DELETE FROM jobs WHERE id=<被删id>，并在汇总里说明清理几条。

【第6步：JEV 自动打分】仅对本轮新入库且 status='待确认' 的岗位逐条打分：
- 方法论：核心技能匹配 35%；行业 15%；职级经验 20%；薪资地点 15%；发展契合 15%。只依据画像中真实存在的证据打分，禁止脑补；证据不足按保守中间分；硬性冲突直接 <50。
- 得出 0-100 总分和 match_reason（≤30字：主依据+最大缺口），用 mode=write 逐条 UPDATE jobs SET match_score=<分>, match_reason='<原因>', updated_at=now() WHERE id=<job_id>。存量老岗位不重新打分。

【第7步：收尾登记+通知】清理 .workbuddy/tmp/ 下本轮临时 JSON，然后登记结果（mode=write，逐条执行）：
- 若猎聘与领英两部分均未成功（全部失败/跳过且 0 入库）：UPDATE agent_tasks SET status='failed', note='失败原因：<一句话，≤40字>', processed_at=now() WHERE id='<task_id>'，并给用户发失败说明（若涉及领英，把脚本给出的失败原因原样告诉用户）。
- 否则：UPDATE agent_tasks SET status='done', note='猎聘入库N1条/领英入库N2条/重复M个/清理重复C条/打分K条'（领英跳过时末尾注明「领英跳过：<脚本给出的原因>」）, processed_at=now() WHERE id='<task_id>'。
最后给用户发简短汇总：执行时间、猎聘 N1 条/领英 N2 条入库（跳过注明原因）、因已存在跳过 M 个（注明其中分别有多少是已投递/已拒绝岗位）、自检清理 C 条、已打分 K 条（附最高分前3：公司+岗位+分数），附链接 <SHARE_LINK> 并提示到「③ 投递清单 → 最新岗位清单」查看倒排结果。

【注意】不要访问职位详情页；不要登录、点击投递或修改任何设置；猎聘连续失败或遇验证码时该部分记下原因后放弃（重试不超过 2 次），继续领英部分。
```

---

## 另外两个反馈同步任务（可选但推荐）

| 名称 | RRULE | 职责 |
|---|---|---|
| 投递反馈自动跟踪（早） | `FREQ=DAILY;BYHOUR=9;BYMINUTE=30` | 读平台投递状态 → 写 `job_events` → 更新 `jobs.status` |
| 投递反馈自动跟踪（晚） | `FREQ=DAILY;BYHOUR=19;BYMINUTE=30` | 同上 |

它们不改岗位池，只更新状态，因此不受查重规则影响。若你的环境无法稳定访问平台后台，可以不建这两个任务，改为在应用里手动点「📮 我已手动投递」和手动改状态。

---

## 时间线总览

```
08:00  采集 + 打分（猎聘 + 领英）
08:40  看板刷新
10:00  投递反馈同步
10:40  看板刷新
18:00  采集 + 打分
18:40  看板刷新
20:00  投递反馈同步
20:40  看板刷新
每小时  看门狗 + 消费手动采集请求（07:00–21:00 之间的整点）
22:00–06:00  深夜休眠（无积压时不跑；有积压则按 P1 补采）
```

> 刷新只发生在「数据刚被写过」之后（+40 分钟给任务留执行时间），不做盲轮询。

### 单任务总调度（推荐形态）

生产环境已把上面 **5 个定时任务合并为 1 个**「总调度」任务（`FREQ=HOURLY;INTERVAL=2`，每 2 小时触发一次），由 prompt 内的时间分派逻辑决定当前时段做什么：

分派的前提是**先算积压、再看钟点**（2026-11-09 改）。每次触发先读三项状态，再按下表命中即执行：

- A = 手动请求积压：`SELECT count(*) FROM agent_tasks WHERE type='collect_now' AND status='pending'`
- B = 库里最新岗位时间：`SELECT max(created_at) FROM jobs`
- C = 最近一次成功采集时间：`SELECT max(processed_at) FROM agent_tasks WHERE type IN ('collect_scheduled','collect_now') AND status='done'`

| 优先级 | 条件 | 执行 |
|---|---|---|
| P0 | A ≥ 1 且 (现在 − C) > 90 分钟 | 采集 + 打分（消费手动请求） |
| P1 | **B 距现在 > 14 小时** | 采集 + 打分，note 加「（补采：距上次入库 N 小时）」。**不看钟点，深夜也跑** |
| P2 | h = 8 / 18 | 采集 + 打分 |
| P3 | h = 10 / 20 | 反馈同步 |
| P4 | h = 7–21 其余 | 看门狗 + 消费手动请求 |
| P5 | h = 22、23、0–6 且 A=0、B 在 14 小时内 | 直接结束 |

> P1 是「自愈」条款，也是本次改造的核心。旧规则是「22–06 一律不跑」的纯钟点分派，结果是：电脑睡眠 60 小时（11-07 09:50 → 11-09 22:13）后，22:14 那次唤醒正好落进休眠时段，什么都没做；次日 08:xx 又因为调度漂移没落上 h=8，于是连续三天零新增。改成积压驱动后，任何一次触发只要发现库里的最新岗位超过 14 小时，就立刻补采，不管几点——睡眠断档最多多存在 2 小时（一个调度间隔），而不是三天。

> 每 2 小时触发是任务量与任务栏记录噪音的折中：正常日子里真正抓网站的仍然只有 8:00 / 18:00 两轮，其余触发只是几条 SQL 的轻检查，无积压就空跑退出。用户点「⚡立即采集」后最迟 2 小时内被消费（P0），不再受休眠时段限制。

复刻时建议同样合并为单任务：任务列表干净（左侧菜单只占一项）、时段逻辑集中在一份 prompt 里、改流程只改 `docs/05-automations.md` 一个文件。若你的调度器支持分钟级多时段（如 cron），也可以保持 8:00/9:30/18:00/19:30 的原始时间。
