from pathlib import Path
from shutil import copyfile

here = Path(__file__).parent
source = (here / 'city-lab-v3.1.html').read_text()
styles = (here / 'design-options.css').read_text()
variants = [
    ('forest', '01', '城市实验室', '暖纸色与橙色，像一本正在更新的城市观察手册。', ['大胆', '编辑感', '城市特色'], ['#242820', '#ef7041', '#f4f0e7']),
    ('swiss', '02', '瑞士排版', '黑白与信号红，强网格和大数字，让信息本身成为视觉焦点。', ['克制', '高对比', '信息秩序'], ['#171b18', '#bc312b', '#f7f7f5']),
    ('blueprint', '03', '蓝图科技', '海军蓝与冰蓝线框，把城市呈现为一张可阅读的研究蓝图。', ['专业', '工程感', '精密'], ['#132d47', '#246bb4', '#8ae0ed']),
    ('human', '04', '温暖人文', '砂岩与鼠尾草绿，衬线标题和柔和曲线，把人的日常放在前面。', ['亲近', '柔和', '人文气质'], ['#8f512f', '#a8b396', '#f5eee4']),
    ('future', '05', '未来观测', '石墨黑与荧光绿，数据、节点和运行状态像仪器上的实时读数。', ['前沿', '沉浸', '观测仪器'], ['#101613', '#c7f565', '#ff9c65']),
]
buttons = ''.join(f'<button class="theme-button option-{key}" data-theme="{key}" aria-pressed="{str(key == "forest").lower()}"><i class="swatch"></i>{title}</button>' for key, number, title, description, tags, colors in variants)
start = source.index('    <button class="theme-button"')
end = source.index('\n  </div>', start)
source = source[:start] + '    ' + buttons + source[end:]
source = source.replace('</style>', styles + '\n</style>', 1)
source = source.replace('GAWorld · 城市实验室 · 大胆版预览', 'GAWorld · 五种视觉方案').replace('CITY LAB · V3', 'DESIGN STUDIES · V4')
source = source.replace('<a class="compare-link" href="/files/previous-preview.html#dashboard" target="_blank" rel="noopener">对比上一版 ↗</a>', '<button class="overview-button" id="overviewButton">全部方案</button>')
cards = []
for key, number, title, description, tags, colors in variants:
    palette = ''.join(f'<span class="color-dot" style="background:{color}"></span>' for color in colors)
    labels = ''.join(f'<span>{tag}</span>' for tag in tags)
    cards.append(f'<button class="design-option option-{key}" data-option="{key}" aria-label="查看{title}方案"><div class="option-image"><img src="/files/option-{key}.jpg" alt="{title}控制台设计示意" loading="lazy"></div><div class="option-copy"><h2 class="option-title"><span class="option-number">{number}</span>{title}<span class="go">↗</span></h2><p>{description}</p><div class="option-tags">{palette}{labels}</div></div></button>')
    image = here / f'option-{key}.jpg'
    if not image.exists():
        copyfile(here.parent / 'state/dashboard-bold.jpg', image)
gallery = '<section class="comparison" id="comparisonView" hidden><header class="comparison-header"><div><p class="comparison-kicker">GAWORLD / DESIGN STUDIES / 01 — 05</p><h1>选择 GAWorld 的视觉方向</h1><p>点击方案查看完整界面，再切换首页、研究工作台和手机布局。</p></div><div class="comparison-note">同一城市 · 同一组数据<br>五种不同的视觉表达</div></header><div class="option-grid">' + ''.join(cards) + '<aside class="comparison-guide"><div class="guide-mark">↗</div><h2>先选气质，再打磨细节。</h2><p>可以选一套完整方向，也可以组合：例如蓝图科技的地图，配上瑞士排版的信息层次。</p><p class="guide-facts">5 种方案 / 3 个页面 / 桌面与手机</p></aside></div><footer class="comparison-footer"><span>所有居民、地图与数据均为设计示例</span><a class="comparison-link" href="/files/previous-preview.html#dashboard" target="_blank" rel="noopener">查看最初的克制版 ↗</a></footer></section>'
source = source.replace('<div class="app bold" id="app"', gallery + '\n<div class="app bold" id="app"', 1)
script = '''
function showOverview(){document.getElementById('comparisonView').hidden=false;app.hidden=true;document.getElementById('deviceButton').hidden=true;history.replaceState(null,'','#gallery');document.querySelectorAll('.theme-button').forEach(el=>el.setAttribute('aria-pressed','false'));}
function openOption(key){document.getElementById('comparisonView').hidden=true;app.hidden=false;document.getElementById('deviceButton').hidden=false;app.dataset.theme=key;document.querySelectorAll('.theme-button').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.theme===key)));showView('dashboard');history.replaceState(null,'','#dashboard');record('design-'+key,key);}
document.querySelectorAll('[data-option]').forEach(el=>el.addEventListener('click',()=>openOption(el.dataset.option)));
document.querySelectorAll('.theme-button').forEach(el=>el.addEventListener('click',()=>{document.getElementById('comparisonView').hidden=true;app.hidden=false;document.getElementById('deviceButton').hidden=false;if(location.hash==='#gallery'){showView('dashboard');history.replaceState(null,'','#dashboard');}}));
document.getElementById('overviewButton').addEventListener('click',showOverview);
if(!location.hash||location.hash==='#gallery')showOverview();
'''
source = source.replace('</script>', script + '\n</script>', 1)
(here / 'visual-directions-v4.1.html').write_text(source)
