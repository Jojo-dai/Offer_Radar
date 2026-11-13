#!/usr/bin/env node
/**
 * 「已决岗位不再回池」逻辑回归测试（2026-11-13）
 *
 * 为什么单独测：这是用户反复踩到的坑——点过「不投 / 授权投递」的岗位，
 * 下一轮采集后又在岗位池里出现。冒烟测试只验证顶层脚本能跑，
 * 验证不了「哪条该显示、哪条该隐藏」。
 *
 * 做法：从 index.html 源码里抽出 normTxt / dupKey / urlKeyOf / decidedIndex
 * 四个函数真执行（不是复制一份逻辑，改了实现这里就会跟着变），再断言场景。
 * 抽不到函数说明实现被改名/挪走 → 直接失败，避免测试悄悄失效。
 *
 * 用法：node scripts/test-decisions.js ../job-agent/index.html
 */
const fs = require('fs');

const file = process.argv[2] || '../job-agent/index.html';
const src = fs.readFileSync(file, 'utf8');

/** 从源码里按花括号配平抽出一个函数定义 */
function extract(name) {
  const start = src.indexOf('function ' + name + '(');
  if (start < 0) throw new Error('抽不到函数 ' + name + '（实现被改名或删除？）');
  let i = src.indexOf('{', start), depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') {
      depth--;
      if (depth === 0) return src.slice(start, j + 1);
    }
  }
  throw new Error('函数 ' + name + ' 括号不配平');
}

/** 抽一行常量定义（如 const CITY_TAIL = /.../;），丢了同样视为实现变更 */
function extractLine(prefix) {
  const line = src.split('\n').map(l => l.trim()).find(l => l.startsWith(prefix));
  if (!line) throw new Error('抽不到常量 ' + prefix + '（实现被改名或删除？）');
  return line;
}

const code = [extractLine('const CITY_TAIL'),
  ...['normTxt', 'dupKey', 'urlKeyOf', 'looseKey', 'decidedIndex'].map(extract)].join('\n');
const api = new Function(code + '\nreturn { normTxt, dupKey, urlKeyOf, looseKey, decidedIndex };')();

let pass = 0, fail = 0;
function ok(cond, label) {
  if (cond) { pass++; console.log('  ✓ ' + label); }
  else { fail++; console.log('  ✗ ' + label); }
}

const J = (id, company, position, status, url) =>
  ({ id, company, position, status, source_url: url || null });

console.log('用例：已决岗位的同名副本不得进池');

// 1. 同一岗位：一条「不合适」，一条后来采集回来的「待确认」→ 待确认副本必须被抑制
const s1 = [J(1, 'Deloitte', 'SAP Consultant', '不合适'), J(2, 'Deloitte', 'SAP Consultant', '待确认')];
ok(api.decidedIndex(s1).has(s1[1]) === true, '已点「不投」的岗位，新采副本被隐藏');

// 2. 已授权投递的同理
const s2 = [J(3, '联合利华', 'FP&A Manager', '待投递'), J(4, '联合利华', 'FP&A Manager', '待确认')];
ok(api.decidedIndex(s2).has(s2[1]) === true, '已「授权投递」的岗位，新采副本被隐藏');

// 3. 已投递同理
const s3 = [J(5, 'Visa', 'Finance Manager', '已投递'), J(6, 'Visa', 'Finance Manager', '待确认')];
ok(api.decidedIndex(s3).has(s3[1]) === true, '已「投递」的岗位，新采副本被隐藏');

// 4. 同链接但标题写法不同（编号/后缀差异，归一化键撞不上）→ 靠 URL 拦
const s4 = [J(7, '佛吉亚', 'FP&A Supervisor', '不合适', 'https://x.com/job/123?ref=a'),
            J(8, '佛吉亚', 'FP&A Supervisor (MJ003311)', '待确认', 'https://x.com/job/123/')];
ok(api.decidedIndex(s4).has(s4[1]) === true, '标题编号差异 + 同链接，仍被隐藏');

// 5. 没有任何决定的岗位必须正常显示（不能误伤）
const s5 = [J(9, '巴斯夫', '财务分析经理', '不合适'), J(10, '西门子', 'SAP 顾问', '待确认')];
ok(api.decidedIndex(s5).has(s5[1]) === false, '无关岗位不受影响，正常进池');

// 6. 撤销决定后（状态回到待确认），该岗位应重新可见
const s6 = [J(11, '罗氏', 'Finance IT', '待确认')];
ok(api.decidedIndex(s6).has(s6[0]) === false, '撤销「不投」后岗位回到池子');

// 7. 大小写 / 空格 / 全角括号差异，属同一岗位
const s7 = [J(12, 'PepsiCo', 'Commercial Control Manager', '不合适'),
            J(13, 'pepsico ', 'commercial control manager（上海）', '待确认')];
ok(api.decidedIndex(s7).has(s7[1]) === true, '大小写/空格差异仍判为同一岗位');

// 8. URL 判据必须忽略查询串与末尾斜杠
ok(api.urlKeyOf('https://A.com/j/1/?x=2#top') === api.urlKeyOf('https://a.com/j/1'), 'URL 归一化忽略参数/锚点/尾斜杠');

// 9. 空链接不得互相误判为同一岗位
const s9 = [J(14, '甲公司', '岗位A', '不合适', null), J(15, '乙公司', '岗位B', '待确认', '')];
ok(api.decidedIndex(s9).has(s9[1]) === false, '空链接不会互相误判');

console.log('\n通过 ' + pass + ' / ' + (pass + fail));
process.exit(fail ? 1 : 0);
