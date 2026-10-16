"""Generate static Sphinx Python-domain reference from the GAWorld source AST.

Usage: python generate_api.py /path/to/GAWorld
No GAWorld modules are imported or executed.
"""
import ast
from pathlib import Path
import re
import sys
from sphinx.ext.napoleon.docstring import NumpyDocstring
from sphinx.ext.napoleon import Config

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(__file__).resolve().parent / 'api'
OUT.mkdir(exist_ok=True)
PAGES = {
 'agent': ('居民数据', '居民数据视图、属性访问与字典转换。', [('gaworld.core.agent', None)]),
 'skills': ('技能接口', '技能数据结构、注册、提示词选择与经验提炼。', [('gaworld.skills.schemas', None), ('gaworld.skills.registry', None), ('gaworld.skills.prompt_helpers', None), ('gaworld.skills.consolidation', None)]),
 'env': ('环境系统', '环境状态、事件查询与远程环境访问。', [('gaworld.env.system', ['EnvironmentSystem', 'RemoteEnvironmentClient'])]),
 'kernel': ('仿真内核', '运行上下文、仿真时钟、事件总线与动作控制器。', [('gaworld.kernel.context', None), ('gaworld.kernel.clock', None), ('gaworld.kernel.bus', None), ('gaworld.kernel.controller', None)]),
 'storage': ('记录与记忆', '结构化事件记录、记忆与运行状态访问。', [('gaworld.kernel.recorder', None), ('gaworld.memory.store', ['load_agent_memory','save_agent_memory','load_agent_schedule','save_agent_schedule','load_agent_actions','save_agent_actions','load_sim_state','save_sim_state','known_agent_ids'])]),
 'config': ('配置与模型', '运行配置构建、覆盖合并、模型路由与提供商。', [('gaworld.settings', ['build_config']), ('gaworld.settings.defaults', ['build_default_config']), ('gaworld.settings.overrides', ['deep_update','load_env_override','apply_runtime_overrides']), ('gaworld.llm.providers', ['LLMRouter','build_provider','probe_provider','available_providers','resolve_provider','call_llm'])]),
 'registry': ('插件注册', '插件定义、注册、依赖装配与生命周期。', [('gaworld.kernel.registry', None)]),
 'client': ('HTTP 客户端', 'HTTP 客户端、操作调用、后台任务与错误类型。', [('gaworld.client', None)]),
}

def signature(n, method=False):
 args=ast.arguments(posonlyargs=list(n.args.posonlyargs), args=list(n.args.args), vararg=n.args.vararg, kwonlyargs=list(n.args.kwonlyargs), kw_defaults=list(n.args.kw_defaults), kwarg=n.args.kwarg, defaults=list(n.args.defaults))
 if method:
  if args.posonlyargs and args.posonlyargs[0].arg in ('self','cls'):args.posonlyargs.pop(0)
  elif args.args and args.args[0].arg in ('self','cls'):args.args.pop(0)
 ret=' -> '+ast.unparse(n.returns) if n.returns else ''
 return '('+ast.unparse(args)+')'+ret

def prose(n):
 s=ast.get_docstring(n) or ''
 if not s:return ''
 return '```{eval-rst}\n'+str(NumpyDocstring(s, config=Config(napoleon_use_ivar=True)))+'\n```'

def source(module,n,file):
 rel=file.relative_to(ROOT).as_posix()
 return f'{{gaworld-source}}`https://github.com/wuchaozju/GAWorld/blob/main/{rel}#L{n.lineno}`'

for slug,(title,intro,modules) in PAGES.items():
 parts=[f'# {title}',intro,'接口签名与说明由当前仓库源代码生成。']
 for module,names in modules:
  file=ROOT/(module.replace('.','/')+'.py')
  if not file.exists():file=ROOT/module.replace('.','/')/'__init__.py'
  tree=ast.parse(file.read_text())
  parts += ['## '+module, ':::{py:currentmodule} '+module+'\n:::']
  for n in tree.body:
   if not isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) or n.name.startswith('_') or (names and n.name not in names):continue
   full=n.name
   if isinstance(n,ast.ClassDef):
    init=next((m for m in n.body if isinstance(m,ast.FunctionDef) and m.name=='__init__'),None)
    sig=signature(init,True).split(' -> ')[0] if init else ''
    parts += [f':::'+'{py:class} '+full+sig, prose(n),source(module,n,file),':::']
    for m in n.body:
     if isinstance(m,ast.AnnAssign) and isinstance(m.target,ast.Name) and not m.target.id.startswith('_'):
      parts += [':::{py:attribute} '+full+'.'+m.target.id+'\n:type: '+ast.unparse(m.annotation)+'\n:::']
     if not isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef)) or m.name.startswith('_'):continue
     prop=any(isinstance(d,ast.Name) and d.id=='property' for d in m.decorator_list)
     kind='property' if prop else 'method'
     sig='' if prop else signature(m,True)
     directive=':::{py:'+kind+'} '+full+'.'+m.name+sig
     if any(isinstance(d,ast.Name) and d.id=='classmethod' for d in m.decorator_list):directive+='\n:classmethod:'
     if prop and m.returns:directive+='\n:type: '+ast.unparse(m.returns)
     parts += [directive,prose(m),source(module,m,file),':::']
   else:parts += [':::{py:function} '+full+signature(n),'',prose(n),source(module,n,file),':::']
 if slug=='client':
  parts += ['## HTTP 接口描述', '运行 Dashboard 后，可读取完整 OpenAPI 文档：','```bash\ncurl http://127.0.0.1:8766/api/openapi.json\n```','文档包含操作名、路径、参数、请求体、响应与访问要求。客户端的 `operations()` 列出操作，`call()` 通过 `operationId` 调用。', '独立的 Twin、Agent Relay 和 External Environment 服务接口见仓库的 [完整 API 参考](https://github.com/wuchaozju/GAWorld/blob/main/docs/API_REFERENCE.md)。']
 (OUT/(slug+'.md')).write_text('\n\n'.join(p for p in parts if p)+'\n')
(OUT/'index.md').write_text('''# API 参考

本节按模块列出 GAWorld 的 Python 类型与方法。接口签名与说明从仓库源代码生成；HTTP 接口通过 Dashboard 的 OpenAPI 文档查询。

```{toctree}
:maxdepth: 2

agent
skills
env
kernel
storage
config
registry
client
```

```{note}
调用依赖运行状态的接口前，先初始化工作区并确认当前配置。HTTP 客户端的使用步骤见 [Python 与 HTTP 接口](../integration.md)。
```
''')
print('Generated',len(PAGES),'API modules')
