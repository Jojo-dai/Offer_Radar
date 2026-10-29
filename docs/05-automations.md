# 05 · 三个定时任务（可直接粘贴）

> 下面三段 prompt 是**生产在用**的原文。复刻时把 `<APPLICATION_ID>` 换成你自己的 `wbapp_...`，把 `<SHARE_LINK>` 换成你自己的应用链接即可。
>
> - 任务 1：采集（早）`FREQ=DAILY;BYHOUR=8;BYMINUTE=0`
> - 任务 2：采集（晚）`FREQ=DAILY;BYHOUR=18;BYMINUTE=0`
> - 任务 3：检查点 `FREQ=HOURLY;INTERVAL=1`
>
> 任务 1 与任务 2 的 prompt **完全相同**（内容与时间无关），只是 RRULE 不同。

---

## 任务 1 / 任务 2 · 定时采集 + 打分

**RRULE**：`FREQ=DAILY;BYHOUR=8;BYMINUTE=0`（早） / `FREQ=DAILY;BYHOUR=18;BYMINUTE=0`（晚）

```text
这是「投递助手」的定时自动采集+打分任务（工作区 <WORKSPACE>）。目标：① 用无头浏览器采集猎聘在招岗位；② 用 WorkBuddy 浏览器控制在用户已登录的真实 Edge 里低频采集领英（LinkedIn）搜索结果；③ 全部与云数据库全量去重后入库；④ 对新入库岗位按 JEV 方法论自动打分；⑤ 把本轮运行登记到 agent_tasks 表；最后给用户发简短汇总。全程只读网页，绝不点击投递、发消息或修改任何设置。

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

【第1步：猎聘无头采集】取最多 3 个中文关键词构造 URL：https://www.liepin.com/zhaopin/?key=<URL编码关键词>。每个关键词依次（间隔 sleep 30-60 秒）：
用 /c/Users/<USER>/.workbuddy/skills/gstack/browse/dist/browse.exe：1) goto 该 URL（含 Server failed 则重试一次）；2) sleep 5；3) 执行 js 提取（单行 JSON.stringify）：遍历 document.querySelectorAll('a[data-nick=job-detail-job-info]')，取 title=第一个 div[title] 的 title 属性；link=a.href 去掉 ? 后参数；salary=a 内 span 文本匹配 /^\d/ 且含 k 或 万 的第一个；location=以 区/县/市 结尾的第一个 span 文本；tags=含「年以下|年以上|本科|硕士|大专|博士」的 span 文本拼接；company=a.closest('li') 内 [class*=companyName] 或 [data-nick*=company] 的文本；4) 写入 .workbuddy/tmp/liepin-<关键词slug>.json。0 条则记录后继续。

【第2步：领英采集（条件执行）】mcp__browser__browsers_list：无 Edge 扩展浏览器则跳过并注明「领英未采集：Edge 未连接」。有则做关键词选择：读 keywords_en 全量列表，去掉含括号注释的词（如「RAG (Retrieval-Augmented Generation)」截取括号前部分使用）后得到有效词池。再读游标文件 .workbuddy/tmp/linkedin-kw-cursor.txt（不存在则视为 0），从游标位置起取 3 个（循环轮换），**避免每轮都只用前 3 个词导致其余词永远采不到**；用完把 (游标+3)%池子长度 写回游标文件。若游标轮到连续两轮都 0 入库的词，跳过换下一词。地点取 target_profile.cities_en 第一个，不含「China」则追加「, China」（%2C%20China），缺省 Shanghai%2C%20China。每个关键词：
1) tabs_new 打开 https://www.linkedin.com/jobs/search/?keywords=<编码关键词>&location=<地点>&f_TPR=r604800，等 6 秒（f_TPR=r604800 = 近一周。2026-10-29 实测：上海 AI Product Manager 近一周有 159 个结果，而近 3 天（r259200）大幅缩水导致每轮入库个位数；重复问题交给第3步全状态查重兜底，不怕窗口宽）；
2) tab_screenshot + tab_url 检查：若重定向到 linkedin.cn 或出现 451/登录页/验证码/认证墙 → 领英整体放弃（不重试、不点击），原因记「领英重定向到 linkedin.cn：Edge 未走全局代理」；若页面出现 429 / 「Too Many Requests」/ 空白风控页 → 立即放弃领英（**绝不重试、绝不换关键词再试**），原因记「领英限流429」；有 cookie/广告遮罩可点 × 关闭。注意：跳转到 cn.linkedin.com（中国区子域）不算失败，按该页实际 DOM 解析即可；
3) 滚动加载 + 分段读卡片（领英为懒加载，首屏只渲染 6-8 张，不滚动等于白采。2026-10-29 实测：职位列表在**内层窗格**里，直接 cua_scroll 滚窗口无效，必须先把鼠标指针移进列表区域再滚）：
   a. 先用 cua_execute 执行 move（x=屏宽×0.34 附近、y=500，即左侧职位卡片区域中心），同一次调用里再执行 scroll（x/y 同坐标，scroll_y=1500）。cua_execute 若 provider 超时：等 5 秒后仍执行一次 dom_cua_get_visible_dom（动作可能已落地），然后继续下一屏，不整体放弃；
   b. 每屏滚动后等 4-6 秒随机（滚动后先出现骨架屏，必须等渲染完再读），再 dom_cua_get_visible_dom 一次；重复 5 屏（共 5 次）；
   c. 每次读取的卡片按 link 去重累积（LinkedIn 虚拟化列表，滚动后旧卡片会从 DOM 消失，必须分次累积，不能只读最后一次）；若某屏读完没有新增 link，把滚动坐标 y 改 400（列表更靠上位置）重试一次；
   d. 字段：title、company、location、link（href 含 /jobs/view/，去掉 ? 后参数）、salary（空则「面议」）；累积上限 40 条；
   e. 不点「分页/加载更多按钮」，只做自然向下滚动；滚动到位后不再回滚、不点任何卡片（滚动可能让右侧自动展开第一个职位详情，无妨，只读左侧列表）。
4) 写入 .workbuddy/tmp/linkedin-<关键词slug>.json（platform='领英'）；
5) 卡片缺链接时用「岗位名+公司名」精确搜索一次补齐 /jobs/view/<id>；仍找不到则在 jd_summary 标注。间隔 sleep 30-60 秒。只读，绝不点职位卡、绝不 Easy Apply。

【第3步：写入岗位池——全状态查重（本步是本任务最关键的约束，必须严格执行）】
3.1 先取全量存量（不限状态）：mode=read 执行
SELECT id, company, position, source_url, salary, location, status, match_score FROM jobs WHERE owner_id='<owner_id>' ORDER BY id LIMIT 2000
【查重范围：全状态】必须把返回的全部记录都放进比对集合，涵盖 待确认 / 待投递 / 已查看 / 已投递 / 面试中 / 不合适 / 已拒绝 等所有状态。绝不能只比对 status='待确认' 的记录——已投递或已拒绝的岗位同样算「已存在」，不得再次作为新岗位写入。
3.2 规范化函数（用于生成岗位键）：把公司名、岗位名分别处理——转小写 → 删除「招聘/诚聘/急招/热招/岗位名称/职位名称/岗位/职位」等字样 → 删除所有空格（含全角空格）与标点符号（全角括号、英文括号、方括号、斜杠、反斜杠、连字符、下划线、顿号、逗号、句点、冒号、分号、加号、星号、引号等）。得到 norm(company)+'|'+norm(position) 即岗位键。
3.3 逐条判定（对猎聘 + 领英的每一个采集结果）：
  a) 岗位键命中存量集合 或 命中本轮已入库集合 → 判定为重复，直接跳过，不写入、不改状态、不打分，重复计数 M+1。即使链接不同、平台不同、薪资不同也必须跳过。
  b) 链接兜底：source_url 去掉 ? 与 # 及其后内容后与存量完全相同 → 也判定重复跳过。
  c) 仅当岗位键与链接都未命中时，才 INSERT INTO jobs (owner_id, owner_name, company, position, jd_summary, salary, location, source_url, platform, status) VALUES ('<owner_id>', '<owner_name>', '<company>', '<position>', '<tags 或「自动采集：详情见职位链接」>', '<salary 或「面议」>', '<location>', '<link>', '<猎聘/领英>', '待确认')；写入后立刻把该岗位键加入本轮已入库集合。单轮总入库上限 120 条。
  d) 存量中有同一岗位但字段缺失（库中无链接而新采集有链接；或库中 salary/location 为空）→ 不新增，改为 UPDATE jobs SET source_url=COALESCE(source_url,'<新链接>'), salary=CASE WHEN salary IS NULL OR salary='' THEN '<新薪资>' ELSE salary END, location=CASE WHEN location IS NULL OR location='' THEN '<新地点>' ELSE location END, updated_at=now() WHERE id=<存量id>。补齐字段可以，但绝不改变原 status、绝不重新打分为待确认。
3.4 入库后自检（必须执行）：mode=read 执行
SELECT company, position, count(*) AS cnt FROM jobs WHERE owner_id='<owner_id>' GROUP BY company, position HAVING count(*)>1 ORDER BY cnt DESC
若返回结果，按「状态优先级 已投递>面试中>已查看>待投递>待确认>不合适 → 匹配度更高 → 有链接 → id 更小」保留一条，其余同组记录先 UPDATE job_events SET job_id=<保留id> WHERE job_id=<被删id>，再 DELETE FROM jobs WHERE id=<被删id>，并在汇总里说明清理了几条。

【第3.5步：JEV 自动打分】仅对本轮新入库且 status='待确认' 的岗位逐条打分：
- 方法论：核心技能与岗位要求匹配 35%；行业/业务领域 15%；职级与经验年限 20%；薪资与地点可行性 15%；与目标岗位方向的发展契合度 15%。只依据画像中真实存在的证据，禁止虚构脑补；证据不足按保守中间分计；硬性冲突（城市/职级/行业完全不符）直接 <50。
- 依据 position/jd_summary/salary/location 对照画像，给出 0-100 与 match_reason（≤30字：得分主依据+最大缺口）。
- mode=write：UPDATE jobs SET match_score=<0-100>, match_reason='<原因>', updated_at=now() WHERE id=<job_id>。存量老岗位一律不重新打分。

【第4步：收尾登记+汇总】清理 .workbuddy/tmp/ 临时 JSON，然后 mode=write：两部分都完全失败（0 入库）→ UPDATE agent_tasks SET status='failed', note='失败原因：<≤40字>', processed_at=now() WHERE id='<run_id>'；否则 → UPDATE agent_tasks SET status='done', note='猎聘入库N1条/领英入库N2条/重复M个/清理重复C条/打分K条', processed_at=now() WHERE id='<run_id>'（领英因代理跳过时在 note 末尾注明「失败原因：领英跳过——Edge未走代理」）。补跑（比计划晚 30 分钟以上）在 note 末尾加「（补跑）」。汇总消息包含：运行时间、猎聘新入库 N1、领英新入库 N2（跳过则注明原因）、因已存在而跳过 M 个（注明其中分别有多少是已投递/已拒绝岗位）、自检清理 C 条、已打分 K 条（列出最高分前 3：公司+岗位+分数），附链接 <SHARE_LINK> 并提示去「③ 投递清单 · 最新岗位清单」查看。
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

【第3步：猎聘无头采集】取最多 3 个中文关键词（keywords）构造 URL：https://www.liepin.com/zhaopin/?key=<URL编码后的关键词>。对每个关键词依次执行（不同搜索之间 sleep 30-60 秒随机间隔）：
用命令 /c/Users/<USER>/.workbuddy/skills/gstack/browse/dist/browse.exe：
1. goto 该 URL（若输出含 Server failed 则再执行一次 goto 重试）
2. sleep 5
3. 执行 js 提取（单行 JSON.stringify）：遍历 document.querySelectorAll('a[data-nick=job-detail-job-info]')，每条取：title = 第一个 div[title] 的 title 属性；link = a.href 去掉 ? 后参数；salary = a 内 span 文本中匹配 /^\d/ 且含 k 或 万 的第一个；location = a.textContent 匹配 /【([^】]+)】/ 的第一段（如「苏州-常熟」，旧版按「区/县/市」结尾匹配会漏掉「xx-xx」格式）；tags = 匹配含「年以下|年以上|本科|硕士|大专|博士」的 span 文本拼接；company = a.closest('div.jobDetailBox')（注意：2026-10 实测卡片没有 li 容器，closest('li') 返回 null）内 [class*=companyNam] 元素的文本。实测避坑：browse 守护进程崩溃后会在 <WORKSPACE>/.gstack/terminal-agent-pid.lock 留下 0 字节残留锁，导致后续所有启动报「Server failed to start」——重试前先删除该锁文件；若环境变量含失效的 HTTP(S)_PROXY，browse 启动时也会失败，需先 unset。
4. 把 JSON 写入 .workbuddy/tmp/liepin-<关键词slug>.json。若猎聘整体失败（goto 连续异常/验证码），记下失败原因，继续第4步。

【第4步：领英采集（条件执行）】调用 mcp__browser__browsers_list：
- 若没有 Edge 扩展浏览器（name=Microsoft Edge, type=extension）：跳过领英部分，记下原因「领英未采集：Edge 未连接」。
- 若有：先做关键词选择：读 keywords_en 全量，去掉括号注释（取括号前部分）得有效词池；读游标 .workbuddy/tmp/linkedin-kw-cursor.txt（无则 0），从游标起循环取 3 个，用完写回 (游标+3)%池长（轮换，避免每轮只用同 3 个词）。构造地点参数：取 target_profile.cities_en 第一个，若不含「China」则在末尾追加「, China」（%2C%20China）；缺省 Shanghai%2C%20China。对每个关键词：
  1. tabs_new 打开 https://www.linkedin.com/jobs/search/?keywords=<URL编码关键词>&location=<地点>&f_TPR=r604800 ，等 6 秒（近一周。2026-10-29 实测上海 AI Product Manager 近一周 159 个结果，近 3 天口径会让每轮入库只剩个位数；重复由第5步全状态查重兜底）；
  2. tab_screenshot + tab_url 检查：若 tab_url 被重定向到 linkedin.cn、或页面出现 451/登录页/验证码/认证墙 → 领英整体放弃（不重试、不点击），记下原因「领英重定向到 linkedin.cn：Edge 未走全局代理」；有 cookie/广告遮罩可点 × 关闭；
  3. 滚动加载 + 分段读卡片（首屏只渲染 6-8 张，必须滚动；职位列表在内层窗格，必须先把鼠标 move 进列表区域再 scroll，直接滚窗口无效）：
     a. cua_execute：先 move（x=屏宽×0.34 附近，y=500）再 scroll（同坐标，scroll_y=1500）；超时则等 5 秒读一次 DOM 再继续；重复 5 屏，每屏后等 4-6 秒随机（骨架屏渲染完）再 dom_cua_get_visible_dom；
     b. 按 link 去重累积（虚拟化列表会移除旧卡片，不能只读最后一次）；某屏无新增 link 时把滚动 y 坐标改 400 重试一次；
     c. 字段：title、company、location、link（href 含 /jobs/view/，去掉 ? 后参数）、salary（为空填「面议」）；累积上限 40 条；
     d. 不点分页/加载更多按钮，只做自然向下滚动，不点击任何职位卡；
  4. 写入 .workbuddy/tmp/linkedin-<关键词slug>.json（platform='领英'）。
每个关键词之间 sleep 30-60 秒。全程只读领英页面，绝不点击职位卡、绝不点击 Easy Apply。

【第5步：写入岗位池——全状态查重（本步是最关键约束，必须严格执行）】
5.1 先取全量存量（不限状态）：mode=read 执行
SELECT id, company, position, source_url, salary, location, status, match_score FROM jobs WHERE owner_id='<owner_id>' ORDER BY id LIMIT 2000
【查重范围：全状态】返回的全部记录都进入比对集合，涵盖 待确认 / 待投递 / 已查看 / 已投递 / 面试中 / 不合适 / 已拒绝 等所有状态。绝不能只比对 status='待确认'——已投递或已拒绝的岗位同样算「已存在」，不得再次作为新岗位写入。
5.2 规范化函数：公司名、岗位名分别 转小写 → 删除「招聘/诚聘/急招/热招/岗位名称/职位名称/岗位/职位」等字样 → 删除所有空格（含全角空格）与标点（全角括号、英文括号、方括号、斜杠、反斜杠、连字符、下划线、顿号、逗号、句点、冒号、分号、加号、星号、引号等）。得到 norm(company)+'|'+norm(position) 即岗位键。
5.3 逐条判定（猎聘 + 领英的每一条）：
  a) 岗位键命中存量集合 或 命中本轮已入库集合 → 重复，直接跳过（不写入、不改状态、不打分），M+1。即使链接不同、平台不同、薪资不同也必须跳过。
  b) 链接兜底：source_url 去掉 ? 与 # 及其后内容后与存量完全相同 → 也跳过。
  c) 仅当两者都未命中才 INSERT INTO jobs (owner_id, owner_name, company, position, jd_summary, salary, location, source_url, platform, status) VALUES ('<owner_id>', '<owner_name>', '<company>', '<title>', '<tags 或「自动采集：详情见职位链接」>', '<salary 或「面议」>', '<location>', '<link>', '<猎聘/领英>', '待确认')；写入后把岗位键加入本轮集合。单轮上限 120 条。
  d) 存量同岗位但字段缺失（无链接/薪资空/地点空）→ 不新增，改为 UPDATE jobs SET source_url=COALESCE(source_url,'<新链接>'), salary=CASE WHEN salary IS NULL OR salary='' THEN '<新薪资>' ELSE salary END, location=CASE WHEN location IS NULL OR location='' THEN '<新地点>' ELSE location END, updated_at=now() WHERE id=<存量id>；绝不改原 status、绝不重置为待确认。
5.4 入库后自检（必须执行）：mode=read 执行
SELECT company, position, count(*) AS cnt FROM jobs WHERE owner_id='<owner_id>' GROUP BY company, position HAVING count(*)>1 ORDER BY cnt DESC
若有结果，按「已投递>面试中>已查看>待投递>待确认>不合适 → 匹配度更高 → 有链接 → id 更小」保留一条，其余先 UPDATE job_events SET job_id=<保留id> WHERE job_id=<被删id>，再 DELETE FROM jobs WHERE id=<被删id>，并在汇总里说明清理几条。

【第6步：JEV 自动打分】仅对本轮新入库且 status='待确认' 的岗位逐条打分：
- 方法论：核心技能匹配 35%；行业 15%；职级经验 20%；薪资地点 15%；发展契合 15%。只依据画像中真实存在的证据打分，禁止脑补；证据不足按保守中间分；硬性冲突直接 <50。
- 得出 0-100 总分和 match_reason（≤30字：主依据+最大缺口），用 mode=write 逐条 UPDATE jobs SET match_score=<分>, match_reason='<原因>', updated_at=now() WHERE id=<job_id>。存量老岗位不重新打分。

【第7步：收尾登记+通知】清理 .workbuddy/tmp/ 下本轮临时 JSON，然后登记结果（mode=write，逐条执行）：
- 若猎聘与领英两部分均未成功（全部失败/跳过且 0 入库）：UPDATE agent_tasks SET status='failed', note='失败原因：<一句话，≤40字>', processed_at=now() WHERE id='<task_id>'，并给用户发失败说明（若涉及领英，提醒用户开启全局代理后重新点「⚡ 通知 Agent 立即采集」）。
- 否则：UPDATE agent_tasks SET status='done', note='猎聘入库N1条/领英入库N2条/重复M个/清理重复C条/打分K条'（领英跳过时末尾注明「失败原因：领英跳过——Edge未走代理」）, processed_at=now() WHERE id='<task_id>'。
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
22:00–06:00  深夜休眠，不触发任何任务
```

> 刷新只发生在「数据刚被写过」之后（+40 分钟给任务留执行时间），不做盲轮询。

### 单任务总调度（推荐形态）

生产环境已把上面 **5 个定时任务合并为 1 个**「总调度」任务（`FREQ=HOURLY;INTERVAL=2`，每 2 小时触发一次），由 prompt 内的时间分派逻辑决定当前时段做什么：

| 小时（北京时间） | 执行 |
|---|---|
| 8 / 18 | 采集 + 打分（任务 1 / 任务 2 流程） |
| 10 / 20 | 反馈同步（原 9:30 / 19:30 因整点调度顺延，给补跑留更多余地） |
| 7–21 点其余小时 | 看门狗 + 消费手动请求（任务 3 流程） |
| 22–06 | 深夜休眠，直接结束 |

> 每 2 小时触发是任务量与任务栏记录噪音的折中：真正抓网站的始终只有每天 8:00 / 18:00 两轮，其余触发只是几条 SQL 的轻检查。用户点「⚡立即采集」后最迟 2 小时内被消费；滞留超过 2 小时的请求会被看门狗优先处理并在 note 注明。

复刻时建议同样合并为单任务：任务列表干净（左侧菜单只占一项）、时段逻辑集中在一份 prompt 里、改流程只改 `docs/05-automations.md` 一个文件。若你的调度器支持分钟级多时段（如 cron），也可以保持 8:00/9:30/18:00/19:30 的原始时间。
