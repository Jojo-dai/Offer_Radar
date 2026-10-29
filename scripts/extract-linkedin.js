// 领英职位卡片提取器（配合 jobs-guest 公开搜索接口使用）
// 用法：browse.exe chain <<< '[["goto","https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=AI%20Product%20Manager&location=Shanghai%2C%20China&f_TPR=r604800&start=0"],["wait","li"],["eval","scripts/extract-linkedin.js"]]'
// 返回：JSON 数组字符串 [{title, company, location, link, salary, posted}, ...]
(() => {
  const out = [];
  document.querySelectorAll('li').forEach(li => {
    const a = li.querySelector('a.base-card__full-link') || li.querySelector('a[href*="/jobs/view/"]');
    const t = li.querySelector('.base-search-card__title') || li.querySelector('h3');
    const c = li.querySelector('.base-search-card__subtitle') || li.querySelector('h4');
    const l = li.querySelector('.job-search-card__location');
    const s = li.querySelector('.job-search-card__salary-info');
    const d = li.querySelector('time');
    const title = t ? t.textContent.trim().replace(/\s+/g, ' ') : '';
    const link = a ? (a.href || '').split('?')[0] : '';
    if (!title || !link || link.indexOf('/jobs/view/') < 0) return;
    // 统一成 https://www.linkedin.com/jobs/view/<id>，与库内历史数据同构，便于链接去重
    const m = link.match(/(\d{6,})\/?$/);
    out.push({
      title: title,
      company: c ? c.textContent.trim().replace(/\s+/g, ' ') : '',
      location: l ? l.textContent.trim().replace(/\s+/g, ' ') : '',
      link: m ? 'https://www.linkedin.com/jobs/view/' + m[1] : link,
      salary: s ? s.textContent.trim().replace(/\s+/g, ' ') : '',
      posted: d ? (d.getAttribute('datetime') || '') : ''
    });
  });
  return JSON.stringify(out);
})()
