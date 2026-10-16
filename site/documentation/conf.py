project = 'GAWorld'
author = 'GAWorld contributors'
copyright = '2026, GAWorld contributors'
release = '0.2.1'
language = 'zh_CN'
extensions = ['myst_parser', 'sphinx_copybutton']
source_suffix = {'.md': 'markdown'}
master_doc = 'index'
exclude_patterns = ['README.md']
html_theme = 'furo'
html_title = 'GAWorld 文档'
html_static_path = ['_static']
templates_path = ['_templates']
html_css_files = ['gaworld.css', 'prompts.css']
html_js_files = ['navigation.js', 'visitors.js', 'brand-reveal.js']
html_favicon = '_static/favicon.svg'
html_logo = '_static/logo.svg'
html_copy_source = True
html_show_sourcelink = True
html_theme_options = {
    'light_css_variables': {
        'font-stack': 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        'color-brand-primary': 'rgb(0, 0, 136)',
        'color-brand-content': 'rgb(0, 0, 136)',
        'color-brand-visited': 'rgb(72, 38, 131)',
    },
    'dark_css_variables': {
        'color-brand-primary': '#b0b0e8',
        'color-brand-content': '#c4c4f0',
        'color-brand-visited': '#d4a8ff',
    },
    'source_repository': 'https://github.com/wuchaozju/GAWorld/',
    'source_branch': 'main',
    'source_directory': 'site/documentation/',
    'navigation_with_keys': True,
}
myst_heading_anchors = 3
myst_enable_extensions = ['colon_fence']
copybutton_prompt_text = ''
html_search_language = 'zh'
# The loader restricts tracking to the registered public documentation site.
html_context = {'visitor_widget_enabled': True}


def page_metadata(app, pagename, templatename, context, doctree):
    from html import escape
    title = str(context.get('title', 'GAWorld'))
    context['metatags'] = context.get('metatags', '') + '<meta name="description" content="' + escape('GAWorld 文档：' + title + '。使用步骤、配置示例与接口参考。', quote=True) + '">'


def fix_chinese_stemmer(app, exception):
    # Sphinx 9.1.0 embeds the English stemmer for Chinese but exports a
    # nonexistent ChineseStemmer. Keep its Jieba index and correct the export.
    from pathlib import Path
    if exception is None and app.builder.format == 'html':
        path = Path(app.outdir) / '_static' / 'language_data.js'
        source = path.read_text()
        path.write_text(source.replace('window.Stemmer = ChineseStemmer;', 'window.Stemmer = EnglishStemmer;'))


def source_role(name, rawtext, text, lineno, inliner, options=None, content=None):
    from docutils import nodes
    return [nodes.reference(rawtext, '[源代码]', refuri=text, classes=['viewcode-link', 'gaworld-source'])], []


def align_source_links(app, doctree, docname):
    from docutils import nodes
    from sphinx import addnodes
    for link in list(doctree.findall(nodes.reference)):
        if 'gaworld-source' not in link.get('classes', []):
            continue
        parent = link.parent
        desc = parent
        while desc is not None and not isinstance(desc, addnodes.desc):
            desc = desc.parent
        if desc is None:
            continue
        signature = next(desc.findall(addnodes.desc_signature))
        parent.remove(link)
        if not parent.children:
            parent.parent.remove(parent)
        signature += link


def setup(app):
    app.connect('html-page-context', page_metadata)
    app.connect('build-finished', fix_chinese_stemmer)
    app.add_role('gaworld-source', source_role)
    app.connect('doctree-resolved', align_source_links)
