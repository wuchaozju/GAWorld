# 城市与地图

城市把地图、环境与居民放在同一个数据包中。你可以创建真实地点对应的城市，也可以用描述或草图构建虚构城市。

## 功能与准备

本章用于创建仿真的空间环境和初始人口，并把城市选为后续运行或新世界的基础。准备一个真实地名，或一段虚构城市描述；离线创建可用于先检查工作区和数据流程。

## 创建城市

在控制台打开 **城市**，进入新建城市界面，填写地名并设置居民规模。真实地点会查询地理位置和 OpenStreetMap 数据，同时生成程序化地图与环境配置。

在工作区中也可以执行：

```bash
python -m gaworld.city create "绍兴柯桥" --size 200
```

创建完成后，城市包保存在 `data/cities/<slug>/`。打开城市详情，检查地图范围、居民与环境信息。

## 选择地图来源

| 方式 | 适合的情况 | 输入 |
| --- | --- | --- |
| 真实城市 | 研究具体地点的空间与通勤 | 地名与居民规模 |
| 离线程序化城市 | 本地演示、测试与复现 | 地名、规模与 `--offline` |
| 虚构城市 | 研究自定义环境 | 城市描述或草图，以及可用模型 |

创建离线城市：

```bash
python -m gaworld.city create "柳溪村" --offline --scale tiny --size 100
```

使用描述创建虚构城市：

```bash
python -m gaworld.city create "翡翠屿" \
  --description "热带火山岛上的小城，靠渔业和潜水旅游为生，北边是火山，港口在西南角"
```

离线程序化城市按地名确定性生成；虚构城市则通过模型将描述或草图转成地图设计。

## 选择当前城市

在城市面板中选择要使用的城市，或在工作区中执行：

```bash
python -m gaworld.city use 绍兴柯桥
```

随后回到仿真页面，确认当前城市与居民列表，再设置运行时长。

## 将城市用于世界

在控制台 **管理世界** 中选择一座已有居民的城市，新建自己的世界。世界保存居民副本；在该世界中修改居民与运行配置，可以围绕同一座城市组织不同实验。

居民编辑和导入步骤见 [居民与 Agent Studio](residents.md)。

```{figure} _static/screenshots/city.png
:alt: GAWorld 城市创建与列表界面
:figclass: guide-shot
:target: _static/screenshots/city.png

城市页面示例。上方输入地名或城市描述，设置规模与人口；下方选择已有城市。 点击图片查看完整尺寸。
```

## 城市数据与运行结果

`data/cities/<slug>/` 保存城市输入。选择城市后，运行结果使用对应城市的输出目录，例如 `output/cities/<slug>/`。多人部署中，控制台按当前世界管理运行数据。

查找结果时，先确认当前世界与城市，再从运行日志或分析页面定位本次运行。

## 环境状态与事件

环境系统随仿真时间推进天气和环境事件，并生成居民感知所需的上下文。`EnvironmentSystem` 提供日开始、时间推进、事件查询和运行状态导入导出接口，详见 [环境系统 API](api/env.md)。

## 接入自定义环境机制

通过插件订阅 `perception.compose` 或 `env.events.compose`，为感知和事件流贡献内容。新增行为机制通过插件装配，操作见 [编写插件](plugins.md)。

## 完成后检查

创建后在城市列表打开详情，核对居民人数、地图和环境。切换城市后回到仿真页面确认居民列表；需要独立修改居民和配置时，再以该城市创建世界。

## 代码结构与执行流程

### 模块分工

```{container} code-map

| 源码位置 | 职责 |
| --- | --- |
| [site/dashboard/city.js](https://github.com/wuchaozju/GAWorld/blob/main/site/dashboard/city.js) | 城市页面：提交创建参数、展示列表和详情、切换城市。 |
| [gaworld/apps/city\_api.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/apps/city_api.py) | 城市接口：连接页面与创建、人口补充、查询和切换操作。 |
| [gaworld/city/create.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/city/create.py) | create_city() 编排地理定位、地图、环境与城市包生成。 |
| [gaworld/city/imagine.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/city/imagine.py) | 将描述或草图转换为虚构城市设计。 |
| [gaworld/city/bundle.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/city/bundle.py) | 定义 CityBundle，管理城市目录、清单和查找。 |
| [gaworld/city/config.py](https://github.com/wuchaozju/GAWorld/blob/main/gaworld/city/config.py) | apply_city() 将城市地图、环境、居民和输出路径写入运行配置。 |

```

### 执行流程

```text
城市页面 / python -m gaworld.city
  → create_city() → 地图与环境生成 → CityBundle
选择城市 → apply_city() → 仿真读取该城市的数据
```

真实地点的创建流程调用 `geocode.py` 和 `osm.py` 获取位置与地图，同时写入程序化地图；虚构城市通过 `imagine.py` 生成设计。`bundle.py` 管理城市包，`config.py` 在运行前将包内输入接入仿真。

### 城市包结构

```text
data/cities/<slug>/
├── city.json          城市清单
├── citymap.md         程序化地图描述
├── map.geojson        获取成功的真实地图
├── environment.json   城市环境配置
├── agents.csv         居民初始状态
└── profiles.md        居民档案
```

创建地图后生成或补充人口，居民文件供后续初始化使用。

### 从哪里修改

修改创建流程查看 `create.py`，调整真实地图查询查看 `geocode.py`、`osm.py`，调整程序化地图查看 `procedural.py`。界面上的创建选项对应 `city.js` 与 `city_api.py`。
