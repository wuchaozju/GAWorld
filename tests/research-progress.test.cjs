/* Actual study UI with mocked jobs; never starts a simulation. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.GAWORLD_PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const origin = 'http://gaworld.test';
const mime = {'.html':'text/html', '.js':'text/javascript', '.css':'text/css', '.svg':'image/svg+xml', '.png':'image/png'};
const study = {
  id:'progress-test', title:'Long-running study', stage:'running', live:true,
  active_job_id:'run-test', created_at:'2026-10-15T08:17:54Z',
  protocol:{sample:{}, validity:{seeds:[123,456]}, sim_days:365, conditions:[], hypotheses:[]},
  preflight:{ok:true}, runs:[],
};

(async () => {
  const browser = await chromium.launch(process.env.GAWORLD_BROWSER ? {executablePath:process.env.GAWORLD_BROWSER} : {});
  let checks = 0;
  try {
    for (const width of [1440,390]) {
      const context = await browser.newContext({viewport:{width,height:1000}});
      const errors = [], writes = [];
      let progress = 0;
      await context.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        if (request.method() !== 'GET') writes.push(request.method() + ' ' + url.pathname);
        if (url.pathname.startsWith('/api/')) {
          let data = {};
          if (url.pathname === '/api/research/context') data = {providers:[], plans:[], studies:[study]};
          if (url.pathname === '/api/research/studies/progress-test') data = study;
          if (url.pathname === '/api/research/jobs/run-test') data = {status:'running',progress,message:'Seed 123: 0/4 worlds'};
          return route.fulfill({json:data});
        }
        const file = path.resolve(root, '.' + url.pathname);
        if (file.startsWith(root + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) {
          return route.fulfill({contentType:mime[path.extname(file)] || 'application/octet-stream',body:fs.readFileSync(file)});
        }
        return route.abort();
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      for (const [value,label] of [[0,'0%'],[0.0004424657534246575,'0.04%'],[0.000001,'<0.01%'],[0.125,'12.5%'],[0.999999,'>99.99%'],[1,'100%']]) {
        progress = value;
        await page.goto(origin + '/site/dashboard/research.html');
        await page.locator('[data-id="progress-test"]').click();
        await page.waitForFunction(expected => document.getElementById('rwStudyProgress')?.textContent.endsWith(' ' + expected),label);
        const labelBox = await page.locator('#rwStudyProgress').boundingBox();
        assert(labelBox && labelBox.width > 0);
        if (process.env.GAWORLD_PROGRESS_SCREENSHOTS && value === 0.0004424657534246575) {
          fs.mkdirSync(process.env.GAWORLD_PROGRESS_SCREENSHOTS,{recursive:true});
          await page.locator('#rwStudy').screenshot({path:path.join(process.env.GAWORLD_PROGRESS_SCREENSHOTS,`research-progress-${width}.png`)});
        }
        checks++;
      }
      assert.deepEqual(errors,[]);
      assert.deepEqual(writes,[], 'opening a running study must not restart it');
      await context.close();
    }
    console.log(`${checks} progress display checks passed (desktop/mobile); no write requests.`);
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
