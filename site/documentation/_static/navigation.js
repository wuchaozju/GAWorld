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

// Keep figure enlargement inside the guide and restore the reader's place.
function setupFigureViewer() {
  const figures = document.querySelectorAll('figure.guide-shot, figure.guide-diagram, figure.annotated-shot');
  if (!figures.length || typeof HTMLDialogElement === 'undefined') return;
  const dialog = document.createElement('dialog');
  dialog.className = 'figure-viewer';
  dialog.setAttribute('aria-labelledby', 'figure-viewer-title');
  dialog.innerHTML = `<div class="figure-viewer-bar">
    <h2 id="figure-viewer-title">图片预览</h2>
    <button type="button" class="figure-viewer-close" autofocus>← 返回文档</button>
    </div><div class="figure-viewer-tools" aria-label="图片缩放">
    <button type="button" data-zoom="out" aria-label="缩小图片">−</button>
    <button type="button" data-zoom="fit">适应窗口</button>
    <button type="button" data-zoom="in" aria-label="放大图片">＋</button>
    <span class="figure-viewer-help">Esc 返回</span></div>
    <div class="figure-viewer-canvas"><img alt=""></div>`;
  document.body.append(dialog);
  const picture = dialog.querySelector('img');
  const canvas = dialog.querySelector('.figure-viewer-canvas');
  const close = dialog.querySelector('.figure-viewer-close');
  let opener, zoom = 1, previousOverflow = '', previousScroll = { x: 0, y: 0 };
  function sizeImage() {
    if (!dialog.open || !picture.naturalWidth) return;
    const fit = Math.min((canvas.clientWidth - 32) / picture.naturalWidth,
      (canvas.clientHeight - 32) / picture.naturalHeight, 1);
    picture.style.width = `${Math.max(1, Math.round(picture.naturalWidth * fit * zoom))}px`;
    picture.style.height = `${Math.max(1, Math.round(picture.naturalHeight * fit * zoom))}px`;
    dialog.querySelector('[data-zoom="out"]').disabled = zoom <= 1;
    dialog.querySelector('[data-zoom="in"]').disabled = zoom >= 6;
  }
  picture.addEventListener('load', sizeImage);
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener('close', () => {
    document.body.style.overflow = previousOverflow;
    opener?.focus({ preventScroll: true });
    window.scrollTo({ left: previousScroll.x, top: previousScroll.y, behavior: 'instant' });
  });
  dialog.querySelectorAll('[data-zoom]').forEach(button => button.addEventListener('click', () => {
    zoom = button.dataset.zoom === 'fit' ? 1 : Math.min(6, Math.max(1, zoom * (button.dataset.zoom === 'in' ? 1.5 : 1 / 1.5)));
    sizeImage();
    if (zoom === 1) canvas.scrollTo(0, 0);
  }));
  window.addEventListener('resize', sizeImage);
  figures.forEach(figure => {
    const img = figure.querySelector('img');
    if (!img) return;
    let link = img.closest('a');
    if (!link) {
      link = document.createElement('a');
      link.href = img.src;
      img.replaceWith(link);
      link.append(img);
    }
    link.setAttribute('aria-haspopup', 'dialog');
    link.setAttribute('aria-label', `放大查看：${img.alt || '文档插图'}`);
    link.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      opener = link;
      zoom = window.innerWidth < 640 ? 2 : 1.5;
      previousOverflow = document.body.style.overflow;
      previousScroll = { x: window.scrollX, y: window.scrollY };
      picture.alt = img.alt;
      picture.src = link.href;
      document.body.style.overflow = 'hidden';
      dialog.showModal();
      sizeImage();
      canvas.scrollTo(0, 0);
    });
  });
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setupFigureViewer);
else setupFigureViewer();
