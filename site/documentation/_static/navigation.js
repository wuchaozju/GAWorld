'use strict';
// Compatibility for existing chapter links from the project homepage.
if (location.pathname.endsWith('/docs/') || location.pathname.endsWith('/docs/index.html')) {
  const pages = {'quick-start':'quickstart.html','overview':'index.html','population':'residents.html','runtime':'simulation.html','research':'research.html','extension':'plugins.html','operations':'models.html','development':'development.html'};
  const target = pages[location.hash.slice(1)];
  if (target) location.replace(target);
}
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') document.querySelector('.doc-tools')?.removeAttribute('open');
});

// Segment Chinese phrases into words that match the Jieba search index.
if (typeof Intl.Segmenter === 'function') {
  const segmenter = new Intl.Segmenter('zh-CN', { granularity: 'word' });
  window.splitQuery = query => Array.from(segmenter.segment(query), item => item.isWordLike ? item.segment : '').filter(Boolean);
}
