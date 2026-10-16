/* Load the owner's counter only on the registered public documentation site. */
(() => {
  const widget = document.querySelector('.visitor-widget');
  if (!widget || widget.dataset.started) return;
  if (location.protocol !== 'https:' || location.hostname !== 's2014628.github.io' ||
      !location.pathname.startsWith('/gaworld-bench/world/docs/')) return;

  const embed = document.getElementById('visitor-widget-embed');
  const source = embed?.content.querySelector('script#mapmyvisitors');
  if (!source) return;

  const url = new URL(source.src);
  if (url.origin !== 'https://mapmyvisitors.com' || url.pathname !== '/map.js' ||
      !url.searchParams.get('d')) return;

  const map = widget.querySelector('.visitor-widget-map');
  const status = widget.querySelector('.visitor-widget-status');
  widget.dataset.started = 'true';
  widget.hidden = false;

  let timeout;
  const observer = new MutationObserver(() => {
    const counter = map.querySelector('.mapmyvisitors-visitors');
    if (!counter?.textContent.trim() || map.querySelector('.mapmyvisitors-loading')) return;
    clearTimeout(timeout);
    observer.disconnect();
    status.hidden = true;
    const link = map.querySelector('a#mapmyvisitors-widget');
    if (link) {
      link.setAttribute('aria-label', '查看访客地图与详细统计');
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
    }
  });
  const fail = () => {
    clearTimeout(timeout);
    observer.disconnect();
    map.hidden = true;
    status.hidden = false;
    status.textContent = '访问统计暂时无法加载。';
  };
  observer.observe(map, {childList: true, subtree: true, characterData: true});
  timeout = setTimeout(fail, 20000);
  const script = document.createElement('script');
  script.id = source.id;
  script.type = 'text/javascript';
  script.src = url.href;
  script.async = true;
  script.onerror = fail;
  map.appendChild(script);
})();
