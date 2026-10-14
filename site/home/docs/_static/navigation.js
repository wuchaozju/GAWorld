'use strict';
// Preserve the previous landing-page chapter links after the guide became multi-page.
if (location.pathname.endsWith('/docs/') || location.pathname.endsWith('/docs/index.html')) {
  const pages = {'quick-start':'index.html','overview':'index.html','population':'cities.html','runtime':'simulation.html','research':'features.html#research','extension':'api.html','operations':'models.html','development':'development.html'};
  const target = pages[location.hash.slice(1)];
  if (target) location.replace(target);
}
document.addEventListener('DOMContentLoaded', () => {
  for (const el of document.querySelectorAll('.toc-title')) el.textContent = '本页内容';
  const back = document.querySelector('.back-to-top span');
  if (back) back.textContent = '回到顶部';
});
