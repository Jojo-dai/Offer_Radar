《领英岗位采集书签》安装与使用说明
========================================

一、安装书签（一次性，约 1 分钟）

1. 打开你的 Edge 浏览器，按 Ctrl+Shift+O 打开收藏夹管理（或点击收藏夹图标）；
2. 点「添加收藏夹」（或右键收藏栏 → 新建收藏夹项）；
3. 名称填：采集领英岗位
4. 网址（URL）栏填入下面这一整行（从 javascript: 开始到结尾，完整复制，不要有换行）：

javascript:(function(){var cards=[].slice.call(document.querySelectorAll('div.job-search-card, li div.base-card, div.base-card'));var seen={},out=[];for(var i=0;i<cards.length;i++){var c=cards[i];var a=c.querySelector('a.base-card__full-link')||c.querySelector('a[href*="/jobs/view/"]')||(c.tagName==='A'?c:null);if(!a)continue;var href=(a.href||'').split('?')[0];if(seen[href])continue;seen[href]=1;var t=c.querySelector('.base-search-card__title, h3');var comp=c.querySelector('.base-search-card__subtitle')||c.querySelector('h4');var compA=comp&&comp.querySelector('a');var loc=c.querySelector('.job-search-card__location')||c.querySelector('span[class*="location"]');var sal=c.querySelector('.job-search-card__salary')||c.querySelector('span[class*="salary"]');var tm=c.querySelector('time');out.push({platform:'领英',title:(t?t.textContent:'').replace(/\s+/g,' ').trim(),company:(compA||comp?((compA||comp).textContent):'').replace(/\s+/g,' ').trim(),location:(loc?loc.textContent:'').replace(/\s+/g,' ').trim(),salary:(sal?sal.textContent:'').replace(/\s+/g,' ').trim(),tags:(tm&&tm.getAttribute('datetime'))||'',link:href});}if(!out.length){alert('未抓到岗位卡片。请确认你在领英的职位搜索结果页（网址含 /jobs/search/）且列表已加载。');return;}var json=JSON.stringify(out);var done=function(n){alert('✅ 已采集 '+n+' 个领英岗位并复制到剪贴板，回到投递助手「② 岗位池 → 一键采集导入」粘贴即可。');};if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(json).then(function(){done(out.length);},function(){fallback();});}else{fallback();}function fallback(){var ta=document.createElement('textarea');ta.value=json;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done(out.length);}catch(e){alert('复制失败，请截图联系开发者。');}ta.remove();}})()

二、使用（每次采集 3 步，约 30 秒）

1. 在 Edge（保持领英登录）打开领英职位搜索结果页。
   推荐入口：投递助手「① 简历画像」已确认画像下方的「🔗 领英搜索」链接
   （注意：搜中国区职位，地点必须带 China，如 Shanghai, China，否则代理出口 IP 会定位到外国同名地名）；
2. 点击收藏栏上的「采集领英岗位」书签 → 弹窗提示采集数量（一页通常 25 个）；
3. 回到投递助手「② 岗位池 → 📥 一键采集导入」，Ctrl+V 粘贴 → 点「批量导入去重」。
   系统自动识别平台为「领英」，与猎聘数据并行去重，互不冲突。

三、说明与注意

- 领英反自动化是所有招聘平台里最严格的，请保持「人工触发、低频」使用：
  建议每天最多采集 2-3 页，不要连续快速翻页点击；
- 采集的岗位自动带「领英」平台标签，在确认清单中显示为「岗位来源：领英」；
- 授权投递后系统会自动打开领英职位页，Easy Apply 的岗位点起来很快；
- 领英开场白是英文版（自动生成），发送前可以自己顺一眼语感；
- 若页面改版抓不到卡片（弹窗提示 0 个），把情况告诉我，我会更新选择器。
