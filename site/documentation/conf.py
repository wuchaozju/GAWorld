project = 'GAWorld'
author = 'GAWorld contributors'
language = 'zh_CN'
extensions = ['myst_parser', 'sphinx_copybutton']
source_suffix = {'.md': 'markdown'}
master_doc = 'index'
exclude_patterns = ['README.md']
html_theme = 'furo'
html_title = 'GAWorld 文档'
html_static_path = ['_static']
templates_path = ['_templates']
html_css_files = ['gaworld.css']
html_js_files = ['navigation.js']
html_favicon = '_static/favicon.svg'
html_copy_source = False
html_show_sourcelink = False
html_show_copyright = False
html_show_sphinx = False
html_theme_options = {
 'light_css_variables': {'color-brand-primary': '#245bdb', 'color-brand-content': '#245bdb', 'color-sidebar-background': '#f6f8fc'},
 'dark_css_variables': {'color-brand-primary': '#9bbcff', 'color-brand-content': '#9bbcff', 'color-sidebar-background': '#171b22'},
 'sidebar_hide_name': False,
 'navigation_with_keys': True,
}
html_sidebars = {'**': ['sidebar/brand.html', 'sidebar/search.html', 'sidebar/scroll-start.html', 'sidebar/navigation.html', 'sidebar/links.html', 'sidebar/scroll-end.html']}
myst_heading_anchors = 3
myst_enable_extensions = ['colon_fence']
copybutton_prompt_text = ''
html_search_language = 'zh'


def page_metadata(app, pagename, templatename, context, doctree):
    from html import escape
    descriptions = {
        'index': '安装 GAWorld，配置模型，运行第一次城市仿真并查看结果。',
        'models': '配置 GAWorld 模型服务、个人 API Key、默认模型和日程模型。',
        'cities': '在 GAWorld 中创建城市、选择地图、编辑居民并切换城市。',
        'simulation': '设置 GAWorld 仿真时长与步长，查看运行日志、轨迹和输出文件。',
        'features': '了解 GAWorld 的居民、记忆、社交、经济、技能、工作与实验功能。',
        'cli': '使用 GAWorld 命令行创建工作区、运行仿真、访谈居民和管理城市。',
        'api': '使用 GAWorld HTTP API、OpenAPI 描述和 Python 客户端。',
        'development': '准备 GAWorld 开发环境、定位代码、运行测试和提交修改。',
    }
    context['metatags'] = context.get('metatags', '') + '<meta name="description" content="' + escape(descriptions.get(pagename, '查阅 GAWorld 使用与开发文档。'), quote=True) + '">'


def setup(app):
    app.connect('html-page-context', page_metadata)
