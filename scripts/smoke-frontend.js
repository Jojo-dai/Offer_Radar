#!/usr/bin/env node
/**
 * 前端冒烟测试（2026-11-12 新增）
 *
 * 为什么需要它：`node --check` 只查语法，查不出运行期引用错误。
 * 本项目出现过一次真实事故——把 `bindListFilters(...)` 的调用放在
 * `const LIST` 声明之前，语法完全合法，但浏览器一加载就抛
 * `ReferenceError: Cannot access 'LIST' before initialization`，
 * 整个脚本中断、页面所有按钮失效，而发布流程看不出任何异常。
 *
 * 本脚本用 Proxy 伪造 document/window/localStorage/云 SDK，把 index.html
 * 里的内联脚本真正执行一遍，任何顶层异常（TDZ、未定义变量的立即调用、
 * 事件绑定到不存在的元素后立刻取属性等）都会被捕获。
 *
 * 用法：
 *   node scripts/smoke-frontend.js ../job-agent/index.html app/index.html
 *   全部通过 → 退出码 0；任一失败 → 退出码 1
 */

const fs = require('fs');
const path = require('path');

function makeProxy() {
  const fn = function () { return proxy; };
  const proxy = new Proxy(fn, {
    get(t, k) {
      if (k === 'then') return undefined;          // 不能被当成 thenable，否则 await 会挂住
      if (k === Symbol.toPrimitive) return () => '';
      if (k === 'toString') return () => '';
      if (k === 'length') return 0;
      return proxy;
    },
    set() { return true; },
    apply() { return proxy; },
    has() { return true; }
  });
  return proxy;
}

function installStubs() {
  const el = makeProxy();
  const origin = 'https://job-apply-agent-36841.app.workbuddy.host';

  global.document = new Proxy({}, {
    get(t, k) {
      if (k === 'querySelector') return () => el;
      if (k === 'querySelectorAll') return () => [];
      if (k === 'addEventListener') return () => {};
      if (k === 'hidden') return false;
      if (k === 'body') return el;
      if (k === 'createElement') return () => el;
      if (k === 'baseURI') return origin + '/';
      return el;
    }
  });
  global.location = { href: origin + '/?sharecode=TEST', origin, search: '?sharecode=TEST', host: origin.replace('https://', ''), protocol: 'https:' };
  global.window = new Proxy({}, {
    get(t, k) {
      if (k === 'addEventListener') return () => {};
      if (k === 'location') return global.location;
      return el;
    },
    set() { return true; }
  });
  global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  global.navigator = { userAgent: 'smoke-test' };
  global.WorkBuddyCloud = { createWorkBuddyCloud: () => makeProxy() };
  global.fetch = () => Promise.resolve(el);
  global.confirm = () => false;
  global.alert = () => {};
  global.setTimeout = () => 0;
  global.setInterval = () => 0;
  global.clearTimeout = () => {};
  global.clearInterval = () => {};
}

function runOne(file) {
  const html = fs.readFileSync(file, 'utf8');
  const scripts = [...html.matchAll(/<script(?![^>]*src=)[^>]*>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  if (!scripts.length) return { ok: false, msg: '没有找到内联脚本' };
  const code = scripts.join('\n;\n');
  try {
    new Function(code)();
    return { ok: true };
  } catch (e) {
    return { ok: false, msg: e.constructor.name + ': ' + e.message, stack: (e.stack || '').split('\n').slice(1, 4).join('\n') };
  }
}

installStubs();
process.on('unhandledRejection', e => {
  console.log('  ✗ 未处理的 Promise 拒绝：' + (e && e.message));
  process.exit(1);
});

const files = process.argv.slice(2);
if (!files.length) {
  console.log('用法：node scripts/smoke-frontend.js <index.html> [更多 index.html]');
  process.exit(1);
}

let failed = 0;
for (const f of files) {
  const target = path.resolve(f);
  if (!fs.existsSync(target)) { console.log('  ✗ 文件不存在：' + f); failed++; continue; }
  const r = runOne(target);
  if (r.ok) {
    console.log('  ✓ ' + f + ' 顶层脚本执行无异常');
  } else {
    failed++;
    console.log('  ✗ ' + f + ' → ' + r.msg);
    if (r.stack) console.log(r.stack.split('\n').map(l => '      ' + l).join('\n'));
  }
}
console.log(failed ? `\n冒烟测试失败：${failed} 个文件有问题，禁止发布` : '\n冒烟测试全部通过');
process.exit(failed ? 1 : 0);
