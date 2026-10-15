/* Browser checks for documentation widgets. Provider requests are mocked.
 * GAWORLD_DOCS_BUILD points to a strict Sphinx build; Playwright is optional
 * tooling, selected through GAWORLD_PLAYWRIGHT_MODULE and GAWORLD_BROWSER.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.GAWORLD_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(process.env.GAWORLD_DOCS_BUILD || 'site/home/docs');
const output = process.env.GAWORLD_WIDGET_SCREENSHOTS;
const origin = 'https://s2014628.github.io';
const prefix = '/gaworld-bench/world/docs/';
const mime = {'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.woff2':'font/woff2'};
const fixture = `
const root = document.getElementById('mapmyvisitors').parentElement;
const link = document.createElement('a'); link.id = 'mapmyvisitors-widget';
link.href = 'https://mapmyvisitors.com/';
link.innerHTML = '<div class="mapmyvisitors-visitors">Test fixture: 4 visits</div><div style="height:110px;background:#2d78ad;color:white">Map fixture</div>';
root.appendChild(link);`;

(async () => {
  const browser = await chromium.launch(process.env.GAWORLD_BROWSER ? {executablePath:process.env.GAWORLD_BROWSER} : {});
  let checks = 0;
  async function context({width=1440,theme='light',reduced='no-preference',mode='success'}={}) {
    const ctx = await browser.newContext({viewport:{width,height:1000},colorScheme:theme,reducedMotion:reduced});
    let calls = 0;
    await ctx.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname === 'mapmyvisitors.com') {
        calls++;
        assert.equal(url.pathname, '/map.js');
        assert.equal(url.searchParams.get('d'), 'Qv8NcKeQND1Rw6TTxjM9dacMMD10_yGRj76gBrTDnd4');
        if (mode === 'error') return route.abort();
        return route.fulfill({contentType:'text/javascript',body:mode === 'timeout' ? '' : fixture});
      }
      const local = url.pathname.startsWith(prefix) ? url.pathname.slice(prefix.length) : url.pathname.replace(/^\/+/, '');
      const file = path.join(root, local || 'index.html');
      if (file.startsWith(root + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile())
        return route.fulfill({contentType:mime[path.extname(file)] || 'application/octet-stream',body:fs.readFileSync(file)});
      return route.abort();
    });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    return {ctx,page,errors,calls:()=>calls};
  }

  for (const width of [1440,768,390]) for (const theme of ['light','dark']) {
    const {ctx,page,errors,calls} = await context({width,theme});
    await page.goto(origin+prefix+'index.html');
    if (width < 1072) await page.locator('.nav-overlay-icon').click();
    await page.waitForFunction(()=>document.querySelector('[data-brand-reveal]')?.dataset.started === 'true');
    const boxBefore = await page.locator('[data-brand-reveal]').boundingBox();
    if (width===1440 && theme==='light') {
      const motion = await page.evaluate(()=>{
        const scene = document.querySelector('.brand-reveal-scene');
        const animations = scene.getAnimations({subtree:true});
        const sample = time => {
          animations.forEach(a=>{a.pause();a.currentTime=time;});
          return {path:getComputedStyle(scene.querySelector('[data-brand-spine]')).d,
            ink:parseFloat(getComputedStyle(scene.querySelector('mask path')).strokeWidth)};
        };
        const early = sample(600), forming = sample(1700), settled = sample(2900);
        animations.forEach(a=>{a.currentTime=0;a.play();});
        return {early,forming,settled,nodes:scene.querySelectorAll('[data-brand-node]').length};
      });
      assert.equal(motion.nodes,8,'the opening must remain legible at sidebar size');
      assert.notEqual(motion.early.path,motion.forming.path,'connections must morph continuously');
      assert.notEqual(motion.forming.path,motion.settled.path);
      assert.equal(motion.early.ink,0);
      assert.equal(motion.settled.ink,45,'the final mask must reveal the complete original glyph');
    }
    if (output && width===1440 && theme==='light') {
      fs.mkdirSync(output,{recursive:true});
      for (const time of [650,1500,2100,2750]) {
        await page.evaluate(time=>document.querySelector('.brand-reveal-scene').getAnimations({subtree:true}).forEach(a=>{a.pause();a.currentTime=time;}),time);
        await page.locator('[data-brand-reveal]').screenshot({path:path.join(output,`logo-${time}.png`)});
      }
      await page.evaluate(()=>document.querySelector('.brand-reveal-scene').getAnimations({subtree:true}).forEach(a=>a.play()));
    }
    await page.waitForFunction(()=>document.querySelector('[data-brand-reveal]')?.dataset.finished === 'true');
    const boxAfter = await page.locator('[data-brand-reveal]').boundingBox();
    assert.equal(boxBefore.width,boxAfter.width); assert.equal(boxBefore.height,boxAfter.height);
    assert.equal(await page.locator('.brand-reveal-scene').count(),0);
    await page.locator('.visitor-widget').scrollIntoViewIfNeeded();
    assert.equal(await page.locator('.visitor-widget-status').isHidden(),true);
    assert.equal(calls(),1);
    assert.equal(await page.locator('#mapmyvisitors-widget').getAttribute('target'),'_blank');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.addScriptTag({content:fs.readFileSync(path.join(root,'_static/visitors.js'),'utf8')});
    assert.equal(calls(),1,'loader must be idempotent');
    await page.goto(origin+prefix+'prompts/index.html');
    assert.equal(await page.locator('[data-brand-reveal]').count(),0);
    await page.goto(origin+prefix+'index.html');
    assert.equal(await page.locator('.brand-reveal-scene').count(),0,'returning to the homepage must not replay');
    assert.deepEqual(errors,[]);
    await ctx.close(); checks++;
  }
  for (const url of ['http://localhost/index.html','https://gaworld.zczltfe.chatgpt.site/index.html',origin+'/index.html','http://s2014628.github.io'+prefix+'index.html']) {
    const {ctx,page,calls} = await context(); await page.goto(url);
    assert.equal(calls(),0); assert(await page.locator('.visitor-widget').isHidden());
    await ctx.close(); checks++;
  }
  for (const mode of ['error','timeout']) {
    const {ctx,page} = await context({mode});
    await page.addInitScript(()=>{const native=setTimeout;window.setTimeout=(fn,ms,...args)=>native(fn,ms===20000?50:ms,...args);});
    await page.goto(origin+prefix+'index.html');
    await page.waitForFunction(()=>document.querySelector('.visitor-widget-status')?.textContent.includes('暂时无法'));
    assert(await page.locator('.visitor-widget-map').isHidden());
    assert(await page.locator('article h1').isVisible());
    await ctx.close(); checks++;
  }
  const {ctx,page} = await context({reduced:'reduce'});
  await page.goto(origin+prefix+'index.html');
  assert.equal(await page.locator('.brand-reveal-scene').count(),0);
  assert(await page.locator('.sidebar-logo').isVisible());
  await ctx.close();
  for (const scenario of ['unsupported','reduce-during-play']) {
    const {ctx,page,errors} = await context();
    if (scenario==='unsupported') await page.addInitScript(()=>{
      const supports=CSS.supports.bind(CSS);
      CSS.supports=(property,...args)=>property==='d'?false:supports(property,...args);
    });
    await page.goto(origin+prefix+'index.html');
    if (scenario==='reduce-during-play') {
      await page.waitForFunction(()=>document.querySelector('[data-brand-reveal]')?.dataset.started === 'true');
      await page.emulateMedia({reducedMotion:'reduce'});
      await page.waitForFunction(()=>document.querySelector('[data-brand-reveal]')?.dataset.finished === 'true');
    }
    assert.equal(await page.locator('.brand-reveal-scene').count(),0);
    assert(await page.locator('.sidebar-logo').isVisible());
    assert.deepEqual(errors,[]);
    await ctx.close(); checks++;
  }
  await browser.close();
  console.log(`PASS ${checks+1} widget cases: host restriction, counter loading/failure, repeat prevention, stable geometry, mobile, dark theme, and reduced motion.`);
})().catch(error=>{console.error(error);process.exit(1);});
