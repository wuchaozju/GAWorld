/* A social graph resolves into the existing wordmark, once per tab. */
(() => {
  const host = document.querySelector('[data-brand-reveal]');
  if (!host || host.dataset.started) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  // Unsupported browsers retain the original, fully accessible SVG logo.
  if (reduced.matches || !Element.prototype.animate ||
      !CSS.supports('d', 'path("M0 0 C0 0 1 1 1 1")')) return;
  const storageKey = 'gaworld-docs-brand-seen-v2';
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
  const defs = make('defs', {}, svg);
  const mask = make('mask', {id:'brand-reveal-ink', maskUnits:'userSpaceOnUse', x:160, y:0, width:160, height:160}, defs);
  const graph = make('g', {fill:'none', stroke:'#fff', 'stroke-linecap':'round', 'stroke-linejoin':'round'}, svg);

  // Eight residents share one continuous trajectory. The same connections
  // become the letter's spine; no sampled particles or replacement glyph fade.
  const residents = [[278,46],[237,29],[194,53],[212,86],[200,125],[247,130],[285,103],[262,76]];
  const anchors = [[272,59],[245,45],[208,65],[208,101],[239,117],[272,108],[272,90],[245,90]];
  const curves = [
    [268,49,257,45,245,45], [228,44,214,52,208,65],
    [203,75,203,91,208,101], [214,112,225,117,239,117],
    [251,117,264,114,272,108], [272,102,272,96,272,90],
    [263,90,254,90,245,90]
  ];
  const straight = (a,b) => [a[0]+(b[0]-a[0])/3,a[1]+(b[1]-a[1])/3,
    a[0]+2*(b[0]-a[0])/3,a[1]+2*(b[1]-a[1])/3,...b];
  const path = (start,segments) => `M${start.join(' ')} ` + segments.map(c=>`C${c.join(' ')}`).join(' ');
  const initialPath = path(residents[0],residents.slice(1).map((point,i)=>straight(residents[i],point)));
  const finalPath = path(anchors[0],curves);
  const ink = make('path', {d:finalPath, fill:'none', stroke:'white', 'stroke-width':0, 'stroke-linecap':'round', 'stroke-linejoin':'round'}, mask);
  const letter = make('text', {x:240, y:124, 'text-anchor':'middle', 'font-family':'Arial,sans-serif', 'font-size':120, 'font-weight':700, fill:'white', mask:'url(#brand-reveal-ink)'}, svg);
  letter.textContent = 'G';
  const spine = make('path', {d:initialPath, 'stroke-width':1.65, 'data-brand-spine':''}, graph);
  const nodes = make('g', {}, svg);

  const animations = [];
  let complete = false;
  let timer;
  const finish = () => {
    if (complete) return;
    complete = true;
    clearTimeout(timer);
    animations.forEach(animation => animation.cancel());
    svg.remove();
    reduced.removeEventListener('change',finish);
    window.removeEventListener('pagehide',finish);
    host.dataset.finished = 'true';
  };
  const play = (element,frames,options) => {
    const animation = element.animate(frames,{fill:'both',...options});
    animations.push(animation);
    return animation;
  };
  const settle = {duration:1500,delay:850,easing:'cubic-bezier(.65,0,.2,1)'};
  const morph = (element,from,to) => play(element,[{d:`path("${from}")`},{d:`path("${to}")`}],settle);
  const start = () => {
    if (host.dataset.started) return;
    if (reduced.matches) { finish(); return; }
    host.dataset.started = 'true';
    try { sessionStorage.setItem(storageKey,'1'); } catch (_) { /* One play per load. */ }

    morph(spine,initialPath,finalPath);
    play(spine,[{opacity:0},{opacity:.65,offset:.16},{opacity:.8,offset:.72},{opacity:0}],{duration:2450});
    const ties = [[0,7],[1,3],[1,7],[2,4],[3,7],[3,5],[5,7]];
    ties.forEach(([a,b],i) => {
      const from = path(residents[a],[straight(residents[a],residents[b])]);
      const to = path(anchors[a],[straight(anchors[a],anchors[b])]);
      const tie = make('path',{d:from,'stroke-width':1},graph);
      morph(tie,from,to);
      play(tie,[{opacity:0},{opacity:.38,offset:.25},{opacity:.38,offset:.55},{opacity:0}],{duration:1900,delay:i*30});
    });
    residents.forEach(([x,y],i) => {
      const node = make('g',{'data-brand-node':''},nodes);
      const hub = i===3 || i===7;
      if (hub) {
        const ring = make('circle',{cx:0,cy:0,r:8,fill:'none',stroke:'#b8cfff','stroke-width':1},node);
        play(ring,[{opacity:0},{opacity:.65,offset:.3},{opacity:0}],{duration:1700,delay:120});
      }
      const dot = make('circle',{cx:0,cy:0,r:hub?4:3.2,fill:'#fff'},node);
      const [tx,ty] = anchors[i];
      play(node,[{transform:`translate(${x}px,${y}px)`},{transform:`translate(${tx}px,${ty}px)`}],settle);
      play(dot,[{opacity:0,transform:'scale(.65)'},{opacity:1,transform:'scale(1)',offset:.17},
        {opacity:1,transform:'scale(1)',offset:.71},{opacity:0,transform:'scale(.3)'}],{duration:2370,delay:i*18});
    });
    // Two quiet exchanges make the opening a social graph, before it resolves.
    [[1,3,330],[7,5,570]].forEach(([a,b,delay]) => {
      const signal = make('circle',{cx:0,cy:0,r:1.7,fill:'#dce8ff'},nodes);
      play(signal,[{transform:`translate(${residents[a][0]}px,${residents[a][1]}px)`,opacity:0},
        {opacity:1,offset:.2},{opacity:1,offset:.8},
        {transform:`translate(${residents[b][0]}px,${residents[b][1]}px)`,opacity:0}],{duration:530,delay,easing:'ease-in-out'});
    });
    // Ink grows outwards from the shared spine, clipped to the original Arial G.
    // Its exact outline stays visible when the overlay is removed.
    play(ink,[{strokeWidth:0},{strokeWidth:45}],{duration:850,delay:1900,easing:'cubic-bezier(.32,0,.2,1)'});
    play(svg,[{opacity:1},{opacity:0}],{duration:160,delay:3100}).finished.then(finish,finish);
    reduced.addEventListener('change',finish);
    window.addEventListener('pagehide',finish,{once:true});
    timer = setTimeout(finish,3600);
  };
  // Mobile drawers wait until the logo is actually on screen.
  const visibility = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) { visibility.disconnect(); start(); }
  },{threshold:.6});
  visibility.observe(host);
})();
