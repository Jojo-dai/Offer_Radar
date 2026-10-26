# 10 · 采集通道适配：换一个 Agent 环境怎么跑

> 本文档回答一个问题：**不用 WorkBuddy 的 Agent（Claude Code / Codex / 自建脚本）下载本项目后，猎聘、领英两条采集通道如何保持不间断。**

## 0. 核心设计：三层互备，不押注单一通道

每条岗位来源都设计了**三条实现路径**，自动程度递减、环境依赖递减：

| 层级 | 谁来干 | 依赖 | 断了会怎样 |
|---|---|---|---|
| L1 自动采集 | Agent 定时任务（浏览器自动化） | 平台的浏览器控制能力 + 定时调度 | 降级到 L2/L3，岗位池不更新但系统不死 |
| L2 半自动 | Agent 按需驱动用户真实浏览器 | 用户本机浏览器 + 扩展/CDP | 降级到 L3 |
| L3 手动兜底 | 用户点书签 → 复制 JSON → 粘贴导入 | **只有浏览器**，任何环境可用 | 永远可用（这是不间断的最终保证） |

**「不间断」不是靠某条通道永不故障，而是靠降级链：L1 挂了走 L2，L2 挂了走 L3，L3 永远在。**

## 1. 三种环境的通道适配表

### 猎聘（本机直连即可，无需代理）

| 环境 | L1 自动 | L2 半自动 | L3 手动 |
|---|---|---|---|
| WorkBuddy | ✅ 定时任务 + MCP browser 无头采集（现行为） | ✅ 对话触发 | ✅ [书签](collect/liepin-bookmarklet.md) |
| Claude Code / Codex | ⚠️ 需替代定时器（见 §2）+ Playwright/Puppeteer 无头脚本 | ✅ agent 执行 Playwright 脚本 | ✅ 同左 |
| 纯人工 | — | — | ✅ 书签 + 手动粘贴 |

**其他 Agent 的猎聘采集要点**（与 WorkBuddy 版 prompt 等价）：

```bash
# Playwright 无头采集（本机直连，不碰代理）
npx playwright install chromium
node collect_liepin.js   # 打开搜索结果页 → 解析 .job-card 节点 → 输出 JSON
```

- 解析目标：`title / salary / company / location / tags / link` 六字段（与书签脚本一致）
- 入库前**必须**走同一套查重：岗位键 `norm(company)|norm(position)`，全状态比对
- 频率纪律不变：关键词间 sleep 30-60 秒，单日单来源不超过 2 轮

### 领英（门禁不因环境而变）

| 环境 | L1 自动 | L2 半自动 | L3 手动 |
|---|---|---|---|
| WorkBuddy | ✅ 定时任务 + 用户真实 Edge + 代理门禁（现行为） | ✅ 对话触发 | ✅ [书签](collect/linkedin-bookmarklet.md) |
| Claude Code / Codex | ⚠️ Playwright 接管用户真实浏览器 profile + 系统代理 | ✅ 同左 | ✅ 同左 |
| 纯人工 | — | — | ✅ 书签 |

**其他 Agent 的领英采集要点**：

1. **先过门禁再谈采集**：`bash scripts/check-network.sh` 两条硬断言（出口 loc≠CN + LinkedIn 返回 200）不过，领英整段跳过——**任何环境都不允许直连降级**
2. **必须用用户真实浏览器 profile**（Playwright `launchPersistentContext` 指向用户 Chrome/Edge 的 user-data-dir，或 CDP 接管已打开的浏览器），因为领英登录态和风控都在真实指纹上；新建无头指纹容易触发验证
3. 只读搜索结果页，绝不点击 Easy Apply（与 WorkBuddy 版纪律一致）
4. 无条件满足 → 只保留猎聘一个来源，并明确告知用户

## 2. 定时调度替代方案

WorkBuddy 的三个定时任务在别的环境里等价替换为：

| 环境 | 方案 | 说明 |
|---|---|---|
| Linux/macOS 服务器 | `cron` | `0 0,10 * * *`（UTC 对应北京时间 08:00/18:00）+ 每小时看门狗 |
| Windows 本机 | 任务计划程序 | 同上三条，`schtasks /create` 即可 |
| 任何 Agent CLI | 系统级 cron 触发 agent 无头执行 | 把 `docs/05-automations.md` 的 prompt 逻辑改写成脚本 |

**不建议 GitHub Actions 做领英采集**：出口是海外数据中心 IP，触发风控概率高；做猎聘也浪费额度。

## 3. 健康与降级规则（所有环境通用）

1. 每次采集运行后写 `agent_tasks`（status=done/failed + 失败原因 ≤40 字）——表结构不变，这是看门狗的数据源
2. 同一来源**连续失败 2 次**：自动跳过该来源 + 在岗位池页面顶部告知用户「自动采集异常，今日请用书签兜底」
3. `agent_tasks` 里连续 24 小时无成功记录：下一次运行时先自检（网络脚本 / 选择器失效判断），再决定走 L3 提示
4. 书签抓不到卡片（网站改版）：文档末尾留了「把情况告诉维护者更新选择器」的出口

## 4. 不变的东西（换任何环境都不许改）

- 四张表结构 + `owner_id` 语义 + RLS/身份注入（见 `docs/09-portability-auth.md`）
- 查重口径：全状态比对、岗位键归一化、重复即跳过
- 打分规格（`docs/07-matching-jev.md`）与「绝不代投」底线
- 频率上限与随机间隔（反爬合规）
