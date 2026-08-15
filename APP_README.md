# Analog Studio — PySide6 桌面应用(v1.4)

基于本仓库三个 skill(ngspice 教学案例 / gm/ID 设计 / PTM 模型)的统一桌面工作台。
Skill 目录(`ngspice/`、`gmoverid/`、`transistor-models/`)保持原样未修改;应用代码全部在 `app/`。

## 功能(六个标签页)

| 标签页 | 功能 |
|---|---|
| **gm/ID Designer** | 40 个模型可选:20 个 PTM 体硅(180/130/90/65nm、45/32/22nm 的 HP/LP,nmos+pmos)+ 20 个 **PTM-MG FinFET**(7/10/14/16/20nm 的 HP/LSTP,经 OSDI 加载 BSIM-CMG,以 **NFIN** 为尺寸变量、真实器件电容);设 W(或 NFIN)/L/Vds 构建 `GmIdTable` 查找表(首次跑 ngspice 仿真并缓存,之后秒开);三种 sizing 模式(按 gm/ID + Id/W/gm 约束、fT ≥ 目标、gm·ro ≥ 目标);Tools 面板提供任意 gm/ID 的单量快速查询与 5 项物理自检(self-check);工程单位结果表格 + 2×2 原生设计图,工作点红点标记,支持缩放/平移。参数变化会自动使旧表失效,防止误用 |
| **ngspice Examples** | 9 个教学案例一键运行;常用参数直显,VDD/扫描范围/频率/时序/温度等归入可折叠 Advanced 分组(通过临时 monkey-patch 实现,不改 skill 文件);结果 PNG 支持滚轮缩放、拖拽、另存 |
| **Curve Browser** | 按模型/L/W 生成并浏览特性图:IV 特性、gm/ID 四象限、栅电容;会话内缓存,可强制重新生成 |
| **Comparison** | 对比图:同一模型多沟长对比(如 L=180/360/1000nm)、跨节点对比(多选同极性模型)、跨节点栅电容对比 |
| **Circuits** | 五个块级电路(circuit-skills 技能集):StrongArm 比较器(波形/probit 噪声/ramp/四类扫描/五项自检)、LDO(全表征/auto-design/补偿扫描/理论对照)、自举开关、五管 OTA、两级 Miller 运放(含 PZ 极零表);选中电路即显示按 DUT 网表绘制的**电路原理图**(schemdraw 预渲染,`tools/gen_schematics.py`),运行后常驻缩略图栏首位;参数可编辑,指标报告可复制 |
| **Sizing** | 基于 vendored **AnalogGym**(ICCAD'24,BSD-3)开源子集的尺寸自动优化:**20 个 SKY130 电路**(15 个文献级三级 Miller 运放 + Basic LDO + 4 个 LDO 变体,均经 ngspice-42 逐一验证;上游 Qu_LEC/Tan_CLIA 两个缺陷电路未注册;20 张原理图均按网表逐器件 schemdraw 重绘——`tools/gen_sizing_schematics.py`,带器件完整性自检,替换上游低清截图并为 Alfio/全部 LDO 补图);另含 1 个 **自建**(非 vendored,`studio_circuits/`)单级 PMOS 输入电流镜(对称)OTA——复用 AnalogGym 的 `.subckt gnda vdda vinn vinp vout` 契约与共享测试台,自动获得完整 9 指标(增益/GBW/相位裕度/PSRR±/CMRR/功耗/失调/温漂),单内部基准电流自偏置、全尺寸区间稳健收敛(默认 ~42dB/0.37MHz/PM 90°/0.42mW);变量/边界与指标目标均可编辑,支持**硬约束**(违约代价 ×10);内置 Sobol+Powell 与 **Differential evolution**(大预算全局搜索)优化器,源码运行装有 optuna 时可选 **Optuna TPE**;**并行评估**(默认 min(4, CPU 核),4 核实测 ~3.5× 加速,skill 电路自动串行);日志实时进度、可取消;完成后显示收敛曲线 + 最优指标表(逐项 ✓/✗),可导出最优 `.PARAM`;SKY130 PDK 首次使用时自动解压到工作区(~109MB);另接入 6 个 **circuit-skills PTM 条目**(5T OTA/两级运放/LDO 秒级评估;StrongArm 比较器完整 probit 档 ~2 分钟/次 + **快速 τ 代理档** ~1 秒/次、优化后自动对最优点补跑完整 probit 验证;自举开关 Ron 标量指标 ~0.5 秒/次),变量与 Circuits 页同源,最优尺寸可回填复跑表征;**运行管理**:每次优化自动存 JSON,Runs… 可加载/多次运行收敛对比/最优点热启动(Use best as init);**波形对比(Waves…,27 电路全可用)**:把默认与最优尺寸各补跑一次表征并叠画对比图,面板按电路族——运放:增益/相位 Bode + PSRR± + Vout-温度;LDO:最大/最小负载环路增益/相位 + PSRR + 线性调整率;5T OTA/两级运放:Bode;skill LDO:环路 + PSRR + Zout;比较器:锁存/输出瞬态(标 τ);自举开关:Ron-Vin(skill 秒级,运放/LDO ~10-20 秒);**器件变更总结**:报告自动含 "device changes vs default" 按器件分组的前后对照(27 电路全适用);**设计导入(Import ▾)**:.PARAM 尺寸文件回填变量表 init 列(与 Export 对偶);或导入**自定义 SKY130 运放设计**(AnalogGym 5-pin 契约 `.subckt <name> gnda vdda vinn vinp vout` + .PARAM 变量文件)注册为新电路——存工作区跨会话持久、导入即真实评估验证、自动获得全套能力(指标/并行/Waves/变更总结/AI);**网表查看(Netlist…)**:弹窗显示 DUT 网表、变量文件(按当前表格值渲染)与渲染后测试台,skill 电路显示其模板,导入电路可在此移除;**AI 辅助(可选,自备 LLM API,OpenAI 兼容/Anthropic 双协议)**:LLM-guided 闭环优化算法(LLM 提议尺寸、ngspice 逐点实测回喂,坏回复自动回退 Sobol)、AI advise 开跑前边界/预算建议、AI explain 结果解读(英文) |

菜单栏 Help 提供中英双语图文用户手册(F1)与 About。**FinFET(7–20nm)** 通过
ngspice 的 OSDI 接口运行时加载随包携带的 `bsimcmg.osdi`(主流预编译 ngspice 不含
BSIM-CMG level 72,但 ngspice ≥ 38 普遍支持 OSDI);若用户的 ngspice 不支持 OSDI
或当前平台无对应 `.osdi`,FinFET 条目自动置灰。详见手册。

所有仿真任务经过单一后台线程串行执行(避免 gm/ID sweep 的 scratch 文件冲突),
skill 代码的 print 进度实时转发到底部日志面板。

## 运行(源码方式)

```bash
pip install -r requirements.txt          # 运行依赖
pip install -r requirements-dev.txt      # 开发/打包才需要
# 系统需安装 ngspice: apt install ngspice / brew install ngspice
python -m app.main
```

无显示环境下冒烟测试:`QT_QPA_PLATFORM=offscreen python -m app.main --smoke`

测试与 lint:

```bash
python -m pytest app/tests/ -v     # 仿真类测试需要 ngspice,缺失时自动 skip
python -m ruff check .             # 规则集见 ruff.toml
```

push/PR 会触发 `.github/workflows/test.yml`:一个 `lint` job + 在
**Ubuntu / Windows / macOS** 三平台上跑的测试矩阵。详见
[`CONTRIBUTING.md`](./CONTRIBUTING.md)。

## ngspice 检测

按以下顺序自动检测,状态栏常驻指示器显示结果(可点击打开设置):

1. 设置对话框中用户指定的路径(会 prepend 到 PATH,skill 代码自动生效)
2. 冻结版:exe 旁的 `ngspice/Spice64/bin/`(Windows 便携安装)
3. 系统 PATH(`ngspice_con` 优先于 `ngspice`)

未找到时显示横幅提示并禁用运行按钮;已缓存的 gm/ID 表仍可加载。

## 打包

CI(`.github/workflows/build-windows.yml`)每次 push 产出 **5 个包**,
两条技术路线各有取舍:

| Job | 平台 | 工具 | 产物 | 说明 |
|---|---|---|---|---|
| `pyinstaller` | Windows | PyInstaller | `AnalogStudio-windows-pyinstaller.zip` | onedir;`app/` 以可反编译的字节码分发 |
| `linux` | Linux | PyInstaller | `AnalogStudio-linux-pyinstaller.tar.gz` | 同上 |
| `nuitka` | Windows | Nuitka standalone | `AnalogStudio-windows-nuitka.zip` | `app/` 编译为原生机器码 |
| `linux-nuitka` | Linux | Nuitka standalone | `AnalogStudio-linux-nuitka.tar.gz` | 同上;CI 会**校验 dist 里没有任何 `app/` 的 `.py`/`.pyc` 泄漏**,有则构建失败 |
| `nuitka-onefile` | Windows | Nuitka `--onefile` | `AnalogStudio.exe` | 单文件自解压;skill 资产以 `skill_assets.zip` 随包,首启解压到工作区 |

三种构建的取舍见 [`CODE_PROTECTION.md`](./CODE_PROTECTION.md)
(保护了什么、没保护什么);onefile 更好分发,但每次启动都要把整个载荷
自解压到临时目录,冷启动明显慢于 standalone。

本地手工打包(PyInstaller 与 Nuitka 均**不支持交叉编译**,要在目标平台上跑):

```bash
pyinstaller app.spec                      # -> dist/AnalogStudio/(onedir)

python -m nuitka --standalone --enable-plugin=pyside6 \
    --include-package=app --output-dir=build-nuitka app/main.py
```

Nuitka 的完整命令行(资产打包、图标、DLL 收集等)以 workflow 里的为准 ——
那是唯一经过验证的一份,不要凭记忆重写。

不论哪种构建:

- skill 资产树(.py/.tmpl/.lib)随包分发,首次启动同步到用户可写 workspace
  (Linux `~/.local/share/AnalogStudio/`,Windows `%APPDATA%/AnalogStudio/`),
  logs/plots/cache 都写在那里,安装目录保持只读
- 用户自己的数据(保存的运行记录、导入的电路)写在 workspace **之外**的
  用户数据区,升级不会被清掉(见 `paths.user_data_dir()`)
- **ngspice 不打包**:Windows 用户从 [ngspice.sourceforge.io](https://ngspice.sourceforge.io)
  下载 zip,把 `Spice64/` 解压到 exe 同级目录(或在设置里指定路径)即可

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
│   ├── model_registry.py    # 注入 PTM bulk 全节点到 MODEL_INFO(20 模型)
│   ├── validate_service.py  # 封装 validate_gmoverid 的 5 项物理自检
│   ├── examples.py          # 9 案例注册表 + monkey-patch 运行器
│   ├── circuits.py          # circuit-skills 五电路的运行编排 + 导入隔离
│   ├── finfet_sim.py        # FinFET(BSIM-CMG/OSDI)仿真
│   ├── finfet_table.py      # FinFET 的 GmIdTable 等价物(以 NFIN 为尺寸变量)
│   ├── llm_client.py        # LLM 双协议客户端(OpenAI 兼容 / Anthropic)
│   ├── llm_sizing.py        # LLM 引导的闭环优化 + 结果解读 + 开跑前建议
│   ├── render_lock.py       # 进程级 matplotlib 渲染锁(GUI/worker 互斥)
│   ├── browser_service.py   # 特性图/对比图编排(复刻 run_gmoverid/run_multinode 逻辑)
│   └── sizing/              # Sizing 标签页内核(按职责分层,层间单向依赖)
│       ├── spec.py          #   纯数据:电路/指标/变量 dataclass + 数值解析
│       ├── registry.py      #   内置电路注册表 SIZING + 各自的指标目标
│       ├── assets.py        #   电路设计文件定位 + .PARAM → 变量表
│       ├── evaluation.py    #   渲染测试台 → 跑 ngspice → 指标/波形
│       ├── user_circuits.py #   导入用户自带网表并注册
│       ├── scoring.py       #   指标 dict → 单一 cost
│       ├── report.py        #   SizingRun 记录 + 报告/器件变更文本
│       ├── optimizer.py     #   预算内的 evaluate→score→提议循环(4 种算法)
│       ├── runs.py          #   运行记录的 JSON 存取(用户数据区)
│       └── plots.py         #   收敛曲线 / 波形对比渲染(仅 GUI 线程)
├── ui/                      # main_window + 六个 tab + settings/manual 对话框
│   ├── job_mixin.py         #   六个 tab 共用的任务提交/取消/失败展示协议
│   └── widgets/             # png_viewer / mpl_canvas / log_panel / op_result_view
└── tests/                   # pytest(见 CONTRIBUTING.md)
```

> `render_lock.py` 之外的其余 `core/` 模块与 `resources/`(图标、手册、
> 预渲染原理图)未逐一列出。开发流程(测试、lint、原理图重生成、CI、发版)
> 见 [`CONTRIBUTING.md`](./CONTRIBUTING.md)。
