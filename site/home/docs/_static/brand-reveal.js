/* A social graph resolves into the existing wordmark, once per tab. */
(() => {
  const host = document.querySelector('[data-brand-reveal]');
  if (!host || host.dataset.started) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  // Unsupported browsers retain the original, fully accessible SVG logo.
  if (reduced.matches || !Element.prototype.animate ||
      !CSS.supports('d', 'path("M0 0 C0 0 1 1 1 1")')) return;
  const storageKey = 'gaworld-docs-brand-seen-v3';
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
  const connection = (a,b,bend=8) => {
    const c = straight(a,b), length = Math.hypot(b[0]-a[0],b[1]-a[1]);
    const dx = -(b[1]-a[1])/length*bend, dy = (b[0]-a[0])/length*bend;
    return [c[0]+dx,c[1]+dy,c[2]+dx,c[3]+dy,...b];
  };
  const path = (start,segments) => `M${start.join(' ')} ` + segments.map(c=>`C${c.join(' ')}`).join(' ');
  // A continuous spline gives the graph a common flow before the glyph forms.
  const initialCurves = residents.slice(1).map((b,i)=>{
    const a=residents[i], before=residents[Math.max(0,i-1)], after=residents[Math.min(residents.length-1,i+2)];
    return [a[0]+(b[0]-before[0])*.18,a[1]+(b[1]-before[1])*.18,
      b[0]-(after[0]-a[0])*.18,b[1]-(after[1]-a[1])*.18,...b];
  });
  const initialPath = path(residents[0],initialCurves);
  const finalPath = path(anchors[0],curves);
  const ink = make('path', {d:finalPath, fill:'none', stroke:'white', 'stroke-width':0, 'stroke-linecap':'round', 'stroke-linejoin':'round'}, mask);
  const letter = make('text', {x:240, y:124, 'text-anchor':'middle', 'font-family':'Arial,sans-serif', 'font-size':120, 'font-weight':700, fill:'white', mask:'url(#brand-reveal-ink)'}, svg);
  letter.textContent = 'G';
  const spine = make('path', {d:initialPath, 'stroke-width':2.15, 'data-brand-spine':''}, graph);
  // Two fine companion contours gather into the same spine, retaining depth
  // while the social connections resolve into a single mark.
  const contours = [-1,1].map(side=>{
    const offset = initialCurves.map(c=>c.map((n,i)=>n+(i%2?side*4:side*2)));
    const from = path([residents[0][0]+side*2,residents[0][1]+side*4],offset);
    return {from,element:make('path',{d:from,'stroke-width':.9,stroke:'#b9ccff'},graph)};
  });
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
  const settle = {duration:2800,delay:1800,easing:'cubic-bezier(.45,0,.18,1)'};
  const morph = (element,from,to) => play(element,[{d:`path("${from}")`},{d:`path("${to}")`}],settle);
  const start = () => {
    if (host.dataset.started) return;
    if (reduced.matches) { finish(); return; }
    host.dataset.started = 'true';
    try { sessionStorage.setItem(storageKey,'1'); } catch (_) { /* One play per load. */ }

    morph(spine,initialPath,finalPath);
    play(spine,[{opacity:0},{opacity:.65,offset:.12},{opacity:.8,offset:.86},{opacity:0}],{duration:5250});
    contours.forEach(({element,from},i)=>{
      morph(element,from,finalPath);
      play(element,[{opacity:0},{opacity:.34,offset:.2},{opacity:.34,offset:.67},{opacity:0}],{duration:4700,delay:i*90});
    });
    const ties = [[0,7],[1,3],[1,7],[2,4],[3,7],[3,5],[5,7]];
    ties.forEach(([a,b],i) => {
      const from = path(residents[a],[connection(residents[a],residents[b])]);
      const to = path(anchors[a],[straight(anchors[a],anchors[b])]);
      const tie = make('path',{d:from,'stroke-width':1.25},graph);
      morph(tie,from,to);
      play(tie,[{opacity:0},{opacity:.38,offset:.25},{opacity:.38,offset:.55},{opacity:0}],{duration:4000,delay:i*30});
    });
    residents.forEach(([x,y],i) => {
      const node = make('g',{'data-brand-node':''},nodes);
      const hub = i===3 || i===7;
      if (hub) {
        const ring = make('circle',{cx:0,cy:0,r:8,fill:'none',stroke:'#b8cfff','stroke-width':1},node);
        play(ring,[{opacity:0},{opacity:.5,offset:.22},{opacity:.5,offset:.6},{opacity:0}],{duration:3600,delay:150});
      }
      const dot = make('circle',{cx:0,cy:0,r:hub?4:3.2,fill:'#fff'},node);
      const [tx,ty] = anchors[i];
      play(node,[{transform:`translate(${x}px,${y}px)`},{transform:`translate(${tx}px,${ty}px)`}],settle);
      play(dot,[{opacity:0},{opacity:1,offset:.12},{opacity:1,offset:.8},{opacity:0}],{duration:5100,delay:i*18});
    });
    // Two quiet exchanges make the opening a social graph, before it resolves.
    [[1,3,450],[5,7,1000]].forEach(([a,b,delay]) => {
      const signal = make('circle',{cx:0,cy:0,r:1.7,fill:'#dce8ff'},nodes);
      const [x,y] = residents[a], c = connection(residents[a],residents[b]);
      const frames = Array.from({length:25},(_,i)=>{
        const t=i/24, u=1-t;
        const px=u*u*u*x+3*u*u*t*c[0]+3*u*t*t*c[2]+t*t*t*c[4];
        const py=u*u*u*y+3*u*u*t*c[1]+3*u*t*t*c[3]+t*t*t*c[5];
        return {transform:`translate(${px}px,${py}px)`,opacity:Math.min(1,t*5,(1-t)*5),offset:t};
      });
      play(signal,frames,{duration:800,delay,easing:'ease-in-out'});
    });
    // Ink grows outwards from the shared spine, clipped to the original Arial G.
    // Its exact outline stays visible when the overlay is removed.
    play(ink,[{strokeWidth:0},{strokeWidth:2,offset:.15},{strokeWidth:17,offset:.7},{strokeWidth:45}],{duration:1500,delay:4100,easing:'cubic-bezier(.45,0,.3,1)'});
    play(svg,[{opacity:1},{opacity:0}],{duration:250,delay:6250}).finished.then(finish,finish);
    reduced.addEventListener('change',finish);
    window.addEventListener('pagehide',finish,{once:true});
    timer = setTimeout(finish,7000);
  };
  // Mobile drawers wait until the logo is actually on screen.
  const visibility = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting)) { visibility.disconnect(); start(); }
  },{threshold:.6});
  visibility.observe(host);
})();
