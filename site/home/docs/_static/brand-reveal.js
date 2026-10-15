/* A single social-network-to-G introduction on the documentation homepage. */
(() => {
  const host = document.querySelector('[data-brand-reveal]');
  if (!host || host.dataset.started) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  if (reduced.matches || !Element.prototype.animate) return;
  const storageKey = 'gaworld-docs-brand-seen';
  try { if (sessionStorage.getItem(storageKey)) return; } catch (_) { /* Private browsing. */ }

  const ns = 'http://www.w3.org/2000/svg';
  const make = (tag, attrs, parent) => {
    const element = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
    parent.appendChild(element);
    return element;
  };
  const svg = make('svg', {viewBox:'0 0 480 281.08', 'aria-hidden':'true', class:'brand-reveal-scene'}, host);
  make('rect', {x:160, y:0, width:160, height:160, rx:35, fill:'#000088'}, svg);
  const network = make('g', {}, svg);
  const particles = make('g', {}, svg);
  const letter = make('text', {x:240, y:124, 'text-anchor':'middle', 'font-family':'Arial,sans-serif', 'font-size':120, 'font-weight':700, fill:'white', opacity:0}, svg);
  letter.textContent = 'G';

  // Spatially separated residents exchange signals before forming the glyph.
  const residents = [[190,40],[226,30],[268,35],[294,57],[179,79],[213,65],
    [250,67],[282,91],[196,115],[231,101],[262,122],[289,131]];
  const ties = [[0,1],[1,2],[2,3],[0,4],[0,5],[1,5],[2,6],[3,7],
    [4,5],[4,8],[5,6],[5,9],[6,7],[6,9],[7,10],[7,11],[8,9],[9,10],[10,11]];
  const animations = [];
  let complete = false;
  let timer;
  const finish = () => {
    if (complete) return;
    complete = true;
    clearTimeout(timer);
    animations.forEach(animation => animation.cancel());
    svg.remove();
    reduced.removeEventListener('change', finish);
    window.removeEventListener('pagehide', finish);
    host.dataset.finished = 'true';
  };
  const play = (element, frames, options) => {
    const animation = element.animate(frames, {fill:'both', ...options});
    animations.push(animation);
    return animation;
  };
  const start = () => {
    if (host.dataset.started) return;
    host.dataset.started = 'true';
    try { sessionStorage.setItem(storageKey, '1'); } catch (_) { /* One play per load. */ }
    ties.forEach(([from,to], index) => {
      const [x1,y1] = residents[from], [x2,y2] = residents[to];
      const line = make('line', {x1,y1,x2,y2,stroke:'#a8c9ff','stroke-width':1.6}, network);
      play(line, [{opacity:0},{opacity:.5,offset:.3},{opacity:.8,offset:.65},{opacity:0}],
        {duration:1450,delay:index*24,easing:'ease-in-out'});
    });
    // Sample the same Arial bold G used by the existing SVG logo.
    const canvas = document.createElement('canvas');
    canvas.width = 160; canvas.height = 160;
    const ctx = canvas.getContext('2d');
    if (!ctx) { finish(); return; }
    ctx.font = '700 120px Arial'; ctx.textAlign = 'center';
    ctx.fillText('G',80,124);
    const pixels = ctx.getImageData(0,0,160,160).data;
    const targets = [];
    for (let y=32;y<132;y+=7) for (let x=34;x<130;x+=7) {
      if (pixels[(y*160+x)*4+3] > 180) targets.push([x+160,y]);
    }
    targets.forEach(([x,y], index) => {
      const [sx,sy] = residents[index % residents.length];
      const circle = make('circle', {cx:0,cy:0,r:2.7,fill:'white'}, particles);
      const dx = ((index % 3)-1)*2.8, dy = ((index % 5)-2)*1.8;
      play(circle, [
        {transform:`translate(${sx}px,${sy}px)`,opacity:0},
        {transform:`translate(${sx+dx}px,${sy+dy}px)`,opacity:.9,offset:.16},
        {transform:`translate(${sx-dy}px,${sy+dx}px)`,opacity:.9,offset:.4},
        {transform:`translate(${x}px,${y}px)`,opacity:1,offset:.82},
        {transform:`translate(${x}px,${y}px)`,opacity:0}
      ], {duration:2350,delay:(index%12)*28,easing:'cubic-bezier(.4,0,.2,1)'});
    });
    play(letter,[{opacity:0},{opacity:1}],{duration:600,delay:2150,easing:'ease-out'});
    play(svg,[{opacity:1},{opacity:0}],{duration:200,delay:2850}).finished.then(finish,finish);
    reduced.addEventListener('change',finish);
    window.addEventListener('pagehide',finish,{once:true});
    timer = setTimeout(finish,3400);
  };
  // A mobile drawer starts off-screen; play when the logo is first visible.
  const visibility = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) { visibility.disconnect(); start(); }
  }, {threshold:.6});
  visibility.observe(host);
})();
