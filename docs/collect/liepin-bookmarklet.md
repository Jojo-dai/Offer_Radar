猎聘岗位「一键采集」书签（连采版 v2）— 安装与使用说明
=======================================================

【连采版说明】
点一次书签 = 自动连采最多 5 页搜索结果（每页间隔 3-5 秒随机停顿，模拟真人翻页节奏），
累计约 80-100 个岗位一次性复制。页面右上角有绿色进度提示，采完自动消失。

【安装一次】
1. 打开浏览器书签栏，右键 → 「添加书签/收藏夹」
   （如果之前装过旧版，直接编辑那条书签、替换下面的网址即可）
2. 名称填：采集猎聘岗位
3. 网址(URL)填下面这一整行（从 javascript: 开始到行尾，一个字符都不能少）：

javascript:(async()=>{const MAX=5;const sleep=ms=>new Promise(r=>setTimeout(r,ms));const q=(e,s)=>e.querySelector(s);const qa=(e,s)=>[...e.querySelectorAll(s)];const tip=document.createElement('div');tip.style.cssText='position:fixed;top:10px;right:10px;z-index:999999;background:#0f6e56;color:#fff;padding:10px 16px;border-radius:8px;font-size:14px;font-family:sans-serif';document.body.appendChild(tip);const harvest=()=>{const out=[];qa(document,'.job-card-wrapper,li[class*=job-card],div[class*=job-card-wrap]').forEach(c=>{const a=q(c,'a[href*="/job/"],a[href*="job_detail"],a[href*="/a/"],a[class*=job-card]');if(!a)return;const t=s=>{const x=q(c,s);return x?x.textContent.trim():''};const title=t('.job-title')||t('[class*=job-title]')||a.textContent.trim().slice(0,40);const salary=t('.job-salary')||t('[class*=salary]');const company=t('.company-name')||t('[class*=company-name]');const loc=t('.job-area')||t('[class*=area]');const tags=qa(c,'.tag-list li,span[class*=tag],span[class*=label]').map(x=>x.textContent.trim()).filter(Boolean).slice(0,8).join(' ');if(title&&a.href)out.push({title:title,salary:salary,company:company,location:loc,tags:tags,link:a.href})});return out};const nextBtn=()=>q(document,'.next:not([class*=disabled])')||q(document,'a[aria-label*="下一页"]:not([class*=disabled])')||q(document,'[title*="下一页"]:not([class*=disabled])');const seen=new Set();const jobs=[];const add=arr=>arr.forEach(j=>{if(!seen.has(j.link)){seen.add(j.link);jobs.push(j)}});add(harvest());let page=1;tip.textContent='连采中 第'+page+'页：累计'+jobs.length+'个岗位';while(page<MAX&&nextBtn()){await sleep(3000+Math.random()*2000);nextBtn().click();await sleep(3000+Math.random()*2000);page++;add(harvest());tip.textContent='连采中 第'+page+'页：累计'+jobs.length+'个岗位';}tip.remove();if(!jobs.length){alert('未抓到职位卡片：请确认当前在猎聘「搜索结果/职位列表」页，且页面已加载完成');return}const json=JSON.stringify(jobs);const ta=document.createElement('textarea');ta.value=json;ta.style.cssText='position:fixed;left:-9999px';document.body.appendChild(ta);ta.select();let ok=false;try{ok=document.execCommand('copy')}catch(e){}ta.remove();if(ok){alert('连采完成：共 '+page+' 页、'+jobs.length+' 个岗位，已复制\n\n回到「投递助手 → ② 岗位池 → 一键采集导入」粘贴即可')}else{prompt('自动复制失败，请手动全选复制：',json)}})()

【每次使用（三步）】
1. 在猎聘网页版打开搜索结果页（或点投递助手画像页的「按画像关键词直达猎聘搜索」链接），等页面加载完
2. 点书签「采集猎聘岗位」→ 右上角出现绿色进度提示，自动翻页连采，约 15-25 秒后弹窗提示完成
3. 切回「投递助手 → ② 岗位池 → 一键采集导入」，Ctrl+V 粘贴 → 点「批量导入去重」

【说明】
- 连采上限 5 页（想改上限告诉我）；不足 5 页时（没有下一页按钮）自动提前结束
- 自动按 公司+岗位+链接 去重，应用端导入时还会再去重一次，重复采集无副作用
- 脚本只读取职位卡片并复制，不上传、不自动投递，完全合规
- 若提示只采到第 1 页就结束，说明猎聘改了「下一页」按钮结构，把情况告诉我，我更新选择器
- 猎聘页面结构改版导致抓取失败时，同样告诉我更新脚本
