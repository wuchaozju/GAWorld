# 居家模式并入室内模式（2026-10-26）

状态：已实现。
代码：`gaworld/world/home_environment.py`（家的分区与「活动 → 房间」映射）、
`gaworld/apps/visualizer.py`（轨迹里的 `home_room` / `household`）、
`site/dashboard/home-layout.js`（家的房间 → 平面图）、`site/dashboard/indoor-view.js`（画自己的家 + 家卡片）、
`site/dashboard/app.js`（视图跟着居民走）、`site/dashboard/home.js`（家卡片）。
测试：`tests/test_home_environment.py`、`tests/test_simulation_visualizer.py`、
`tests/test_dashboard_home.py`（含 `site/dashboard/home-layout.test.js`、`site/dashboard/home.test.js`）。

---

## 1. 为什么

仿真工作台（控制台）里，「居家模式」是右边一栏独立面板，讲的是每位居民的**家**：
户型、家具、整体气质、每次在家的房间与当时的氛围。同一屏上还有「室内模式」——
地图右上角一个按钮切过去的等距平面图，画的是某栋楼（住宅/公寓/咖啡馆……）的**通用布局**。

两件事因此对不上：

* **家有两套数据。** 居家环境插件给每个居民生成自己的家（房间、面积、家具）；
  室内渲染器画的是「按地点用途共用」的模板。居民家里到底有几间房、摆了什么，两边说的不一样。
* **在家时看不到家。** 居民在家、在卧室睡觉、在厨房做饭，地图还停在城市视图；
  想看室内得手动点按钮，而点开画的是一栋公共住宅楼，不是他的家。

## 2. 做了什么

### 2.1 家真的分了区，而且人真的在不同的房间

`gaworld/world/home_environment.py`：

* 房间模板新增**餐厅**（`dining_room`：餐桌、餐椅、碗柜、餐边柜），吃饭有地方了；
  收入档位决定有没有餐厅（最低档没有餐厅，吃饭就在客厅）。
* 每个房间的活动表补全：卧室（睡觉、午休、换衣服…）、客厅（看电视、刷手机、接待客人…）、
  餐厅（吃早饭/午饭/晚饭、家庭聚餐…）、厨房（做饭、做早餐、洗碗…）、书房（加班、上网课、写作业…）、
  卫生间、阳台。
* **`pick_room_for_activity` 从「精确匹配」升级成三段**：
  1. 房间自己的活动表精确命中；
  2. 关键词规则（做饭 → 厨房、吃 → 餐厅、睡 → 卧室、学习/加班 → 书房、洗澡 → 卫生间、浇花 → 阳台…）；
  3. 时间兜底（深夜 → 卧室、清晨 → 厨房、其余 → 客厅）。
  家没有那个房间时，退到最接近的一间（没有餐厅 → 客厅吃饭）。

规则按优先级排，所以「做饭」不会被「饭」字带去餐厅，「晚饭后陪孩子写作业」也不会被当成做饭。

### 2.2 轨迹里写清「此刻在家哪个房间」

`gaworld/apps/visualizer.py` 的 `build_agent_step_payload` 多两个字段：

* `home_room`：`{key, name, activity}`——在家时才有，房间来自居家环境插件，不在前端重新推导
  （前后端不会走样，和 `tests/test_rooms.py` 里的做法一致）。
* `household`：家庭插件的户 id——同住的人共用一套户型，室内视图只画这一家人，不画整栋楼。

### 2.3 室内模式画居民自己的家

`site/dashboard/home-layout.js` 新模块：把 `/api/home/<id>` 的户型编译成渲染器认得的平面图树——
房间按网格排开（房间数决定几行几列），家具按名字匹配成像素渲染器画的种类
（床 → bed/睡、灶台 → stove/做饭、餐桌 → table/吃饭、马桶 → toilet…），
匹配不上的（地毯、抱枕、窗帘）不画。每个房间还带上渲染器认识的房间类型（living/bedroom/kitchen/dining…）。

`site/dashboard/indoor-view.js`：选中居民在家且有户型时，用这张平面图替代建筑模板；
标题写「XXX 的家 · 餐厅」，副标题写「7 个房间 · 2 人在家」；居民按轨迹里的 `home_room`
落在对应的房间，按活动坐在对应的家具上（床、餐桌、灶台、沙发）。
`site/simviz/phaser-app.js` 的渲染器多接一个 `tree` 参数：有自定义平面图就用它。

### 2.4 视图跟着居民走

`site/dashboard/app.js`：`state.sceneMode` 默认 `auto`——选中的居民在家就切室内模式，不在家就回城市地图；
手点「城市地图 / 室内模式」压住自动切换，换一位居民又重新跟随。

### 2.5 居家模式面板并进室内模式

控制台右边那一栏不再有「居家模式」。它的内容变成室内模式里平面图右边的一张「家」卡片
（`site/dashboard/home.js`）：户型（房间数、总面积、档次）、此刻在哪个房间做什么、
家的整体气质、此刻氛围、每个房间的家具与常做的事、居家活动记录。

顺带修了两个一直存在的 bug：面板的翻译函数 `t` 从未定义（渲染必然抛 ReferenceError），
以及接口返回的载荷里根本没有 `has_home` 字段（面板永远显示「没有居家记录」）。

## 3. 设计取舍（引用前必读）

* **家是「每个居民一份」。** 居家环境插件按 agent id 生成户型，同住的家庭成员各有一份设计；
  室内视图画的是选中居民那一份，同住的人按自己的活动坐在里面。
* **餐厅不是每家都有。** 收入最低档没有餐厅，吃饭在客厅（厨房里）。
* **房间归位靠关键词，不靠模型。** 活动词表是固定的（做饭、吃、睡、洗…），
  规则表在后端；模型只决定「做什么」，不决定「在哪个房间」。
* **不改仿真行为。** 房间只是居民在家时的**位置**，不改变谁碰到谁、不改变容量计算；
  `local_physical.rooms`（真正的房间级偶遇）仍然默认关。
* **家是运行时数据。** 户型来自 `/api/home/<id>`，前端编译成平面图；
  建筑模板（住宅/公寓/咖啡馆…）仍由 `spatial_tree` / `spatial-tree.js` 提供，两者互不影响。
* **深色主题。** 家卡片原来自己刷浅色面（`rgba(245,244,232,...)`），深色模式下白字看不见；
  现在走 `--surface-alt` / `--line-soft` 两个 token（两套主题都给值）。

## 4. 配置

无新开关。居家环境插件默认开（`home.enabled`），关掉就没有家可画；
`home.llm_enrich` 打开后家具名会被润色，平面图按关键词匹配，画不出来的东西就不画。

## 5. 怎么在浏览器里看到它（不跑仿真）

不用等一次完整运行就能看见这个画面：

1. **看服务端的输出根目录**。控制台的接口读的是**当前城市**的目录，不是默认的 `output/`：
   `world_paths.effective_config()["output_root"]`（例如 `output/cities/伦敦`）。
   家设计放 `<输出根>/home/agent_<id>.json`，户型来自 `home_environment.design_home(agent, seed)`。
2. **写一份轨迹**。`<输出根>/visualization/simulation_trace.json` 里给帧的居民加上
   `home_room: {key, name, activity}` 与 `household`，轨迹顶层还要有 `map.nodes`（住宅节点）。
3. **别忘了 `latest_frame.json`**。页面把「实时帧」接在轨迹帧后面（`index` 更大的优先），
   只改轨迹不改它，页面照样显示上一次运行的那一帧。
4. 起服务 `python3 generative_city_sim.py dashboard --port 8799`，打开
   `/site/dashboard/index.html`，在人物下拉里选一位居民——他/她在家，页面就自动切到室内模式。

> 渲染器的 Phaser 替身在 `tests/indoor-pixel.test.js` 里；它必须实现渲染器链式调用的每个
> Text 方法（`setOrigin` / `setDepth` / `setStroke` …），少一个就会在 `draw()` 里抛错。
