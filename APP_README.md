# Analog Studio — PySide6 桌面应用

基于本仓库三个 skill(ngspice 教学案例 / gm/ID 设计 / PTM 模型)的统一桌面工作台。
Skill 目录(`ngspice/`、`gmoverid/`、`transistor-models/`)保持原样未修改;应用代码全部在 `app/`。

## 功能

| 标签页 | 功能 |
|---|---|
| **gm/ID Designer** | 选择模型(nmos180/pmos180/nmos45hp/pmos45hp/nmos22hp/pmos22hp)、W/L/Vds,构建 `GmIdTable` 查找表(首次跑 ngspice 仿真并缓存,之后秒开);三种 sizing 模式(按 gm/ID + Id/W/gm 约束、fT ≥ 目标、gm·ro ≥ 目标);工程单位结果表格 + 2×2 原生设计图(fT、Id/W、gm·ro、Vgs&Vov vs gm/ID),工作点在图上以红点标记,支持缩放/平移 |
| **ngspice Examples** | 9 个教学案例一键运行,关键参数(R/C、W/L、Vgs 列表、Iref 等)可在表单里调整(通过临时 monkey-patch 实现,不改 skill 文件);结果 PNG 支持滚轮缩放、拖拽、另存 |
| **Curve Browser** | 按模型/L/W 生成并浏览特性图:IV 特性、gm/ID 四象限、栅电容;会话内缓存,可强制重新生成 |

所有仿真任务经过单一后台线程串行执行(避免 gm/ID sweep 的 scratch 文件冲突),
skill 代码的 print 进度实时转发到底部日志面板。

## 运行(源码方式)

```bash
pip install -r requirements.txt
# 系统需安装 ngspice: apt install ngspice / brew install ngspice
python -m app.main
```

无显示环境下冒烟测试:`QT_QPA_PLATFORM=offscreen python -m app.main --smoke`

测试:`python -m pytest app/tests/ -v`(examples 集成测试需要 ngspice)

## ngspice 检测

按以下顺序自动检测,状态栏常驻指示器显示结果(可点击打开设置):

1. 设置对话框中用户指定的路径(会 prepend 到 PATH,skill 代码自动生效)
2. 冻结版:exe 旁的 `ngspice/Spice64/bin/`(Windows 便携安装)
3. 系统 PATH(`ngspice_con` 优先于 `ngspice`)

未找到时显示横幅提示并禁用运行按钮;已缓存的 gm/ID 表仍可加载。

## 打包(PyInstaller)

```bash
pyinstaller app.spec        # 输出 dist/AnalogStudio/(onedir 模式)
```

- 两个 skill 资产树(.py/.tmpl/.lib)打包在 `_internal/skill/` 下
- 首次启动时同步到用户可写 workspace(Linux `~/.local/share/Analog Studio/`,
  Windows `%APPDATA%/Analog Studio/`),logs/plots/cache 都写在那里,安装目录保持只读
- **ngspice 不打包**:Windows 用户从 [ngspice.sourceforge.io](https://ngspice.sourceforge.io)
  下载 zip,把 `Spice64/` 解压到 exe 同级目录(或在设置里指定路径)即可

Windows 打包:在 Windows 机器上执行同样的 `pyinstaller app.spec`
(PyInstaller 不支持交叉打包)。

### 路径含空格的兼容性说明

netlist 模板中的路径占位符已加引号以支持含空格的路径(Windows 用户目录常见):
`.include "{model_path}"`(双引号)、`wrdata '{path}'`(单引号——经实测
ngspice 42 的 wrdata 只剥离单引号,双引号会被当作文件名的一部分)。
这是对 skill 模板文件的唯一修改。

## 代码结构

```
app/
├── main.py                  # 入口(python -m app.main)
├── paths.py                 # sys.path 注入 + 冻结模式 workspace 同步
├── core/
│   ├── worker.py            # SimWorker 单线程任务队列 + stdout 捕获
│   ├── ngspice_locator.py   # ngspice 三级检测(不会 sys.exit)
│   ├── gmid_service.py      # GmIdTable 适配(私有数组访问集中在此)
│   ├── examples.py          # 9 案例注册表 + monkey-patch 运行器
│   └── browser_service.py   # 特性图编排(复刻 run_gmoverid/run_multinode 逻辑)
├── ui/                      # main_window + 三个 tab + settings 对话框
│   └── widgets/             # png_viewer / mpl_canvas / log_panel / op_result_view
└── tests/                   # pytest(worker 单测 + examples 集成测试)
```
