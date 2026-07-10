# 三个模拟电路自动化仓库对比分析

> AnalogCoder(AAAI'25)· Analogagent(自称 KDD'26)· AnalogGym(ICCAD'24)
>
> 分析日期:2026-07-10。三库均克隆自 GitHub(浅克隆),在本仓库的开发环境
> (Linux x86-64,ngspice-42)做了**离线实证**——所有可复现性结论都来自实跑,
> 不是转述 README。仓库本体**未** vendor 进本仓库(许可与体积考虑,见各节),
> 仅存档本分析。文末附基于 AnalogGym 的 **Analog Studio "sizing 优化"功能集成评估**。

## 目录

1. [AnalogCoder](#1-analogcoder)
2. [Analogagent](#2-analogagent)
3. [AnalogGym](#3-analoggym)
4. [三仓库谱系与横向对比](#4-三仓库谱系与横向对比)
5. [对 Analog Studio 的可复用性总结](#5-对-analog-studio-的可复用性总结)
6. [基于 AnalogGym 的 "sizing 优化" 功能集成评估](#6-基于-analoggym-的-sizing-优化功能集成评估)
7. [附:实证记录](#7-附实证记录)

---

## 1. AnalogCoder

**仓库**:`laiyao1/AnalogCoder` · **论文**:AnalogCoder: Analog Circuit Design via
Training-Free Code Generation,**AAAI 2025 Oral(Top 5%)**,arXiv 2405.14918。
作者:Yao Lai(HKU)、Sungyoung Lee / Souradip Poddar / David Z. Pan(UT Austin)、
Guojin Chen(CUHK)等。**无 LICENSE 文件**(默认保留所有权利)。

### 1.1 定位

第一个**免训练(training-free)的 LLM 模拟电路设计智能体**:把"设计电路拓扑"表述为
**PySpice 代码生成**——LLM 先写器件级设计方案(CoT),再产出可运行的 PySpice 代码;
代码经 ngspice 仿真、自动检查(工作点 + 功能测试台),错误以自然语言反馈迭代修复;
成功设计归档为可复用子电路("技能库")供复杂系统组合。头条结果:24 个基准任务,
GPT-4o 版解出 20 个、Claude-3.5 版解出 22 个。

### 1.2 规模与形态

64 个 `.py` 共 **4035 行**,主体是单文件 `gpt_run.py`(**1368 行**,整个智能体)。
资产:`problem_set.tsv`(24 任务)、`prompt_template*.md`、`problem_check/`
(12 类功能测试台)、`subcircuit_lib/p1..p15_lib.py`(SubCircuitFactory 技能库)、
`sample_design/p1..p24.py`(24 个金样参考解)+ `test_all_sample_design.py` 环境自检、
`lib_info.tsv`(库电路实测增益/相位/偏置)。

### 1.3 基准(24 任务)

Easy(1–8):共源(阻性负载)、三级共源、共漏、共栅、cascode、NMOS/CMOS 反相器、恒流源。
Medium(9–13):Miller 两级运放、二极管负载共源、五管差分运放、cascode 电流镜、
双阻性负载差分运放。Hard(14–24):两级差分运放、telescopic cascode 运放,以及 9 个
系统级任务(RC 移相/文氏桥振荡器、积分/微分/加法/减法器、施密特、**VCO、PLL**)。
任务提示只有一句:`Design [TASK]. Input node: [INPUT]. Output node: [OUTPUT].`。

### 1.4 架构

生成 → 仿真 → 检查 → 反馈闭环(全在 `gpt_run.py`):

- **提示词**:worked example(两级放大器 CoT+代码)+ 8 条领域规则
  (MOSFET 参数顺序、bulk 接 source、偏置考虑 V_TH、不放 AC 源、IO 节点名必须出现、
  不用子电路、标称尺寸、Vdd=5V)。
- **LLM 接入**:OpenAI SDK 统一客户端(GPT 直连、DeepSeek 兼容端点、开源模型走
  Ollama)。README 中 Claude/Gemini 成绩系外部运行,脚本无 Anthropic SDK。
- **自动定偏置**:先 DC 扫描找到令 Vout≈2.5V 的输入偏置再回写代码。
- **工作点/拓扑校验器 `check_netlist()`**(~190 行):逐管检查 V_DS/V_GS 与 V_TH 的
  区域有效性、栅源短接、漏极钉死、差分对偏置不等;叠加任务特定结构规则
  (共栅 Vin 必须进 source、Miller 电容必须桥接一级输出↔Vout 等),产出可读修复建议。
- **功能测试台 `problem_check/`**:拼接到生成电路后子进程运行,`sys.exit(0/2)` 判定。
  Amplifier:全管 I_D>10µA + 100Hz AC 增益;Opamp:**共模 vs 差模增益**
  (Vinn 相位翻 180° 双跑);CurrentMirror:负载扫描恒流 + 镜像跟随;
  Oscillator:瞬态 + FIR + `find_peaks` 判持续振荡。
- **子电路技能库**:复杂任务先用 `retrieval_prompt.md` 让 LLM 挑选归档模块,
  再注入规格表/使用注意/调用代码片段。消融显示该机制是 Hard 任务的关键
  (GPT-4o 去掉 tool 从 20 题掉到 15 题)。

### 1.5 实证(本环境)

- `pip install pyspice` 后直跑金样 → 24/24 全挂:PySpice 需要 **libngspice 共享库**
  (非 ngspice 可执行文件),`apt install libngspice0` 解决其一;
- 仍全挂:**ngspice-42 把提示 "Using SPARSE 1.3 as Direct Linear Solver" 打到
  stderr**,PySpice 1.5 视任何 stderr 为致命错误——给其 stderr 分类加一行白名单后
  **24/24 金样全部通过**;
- 功能测试台抽查:p1+Amplifier ✓(增益 5.0,合 lib_info 的 13.98dB);
  p11+Opamp 首跑失败——第二次 AC 是**退化单点扫描**(start=stop、1 点),
  ngspice-42 返回空;改两点扫描后 ✓(差模 5×10⁹、共模 2×10⁻⁹)。

**结论**:仿真/检查层完全不依赖 LLM、离线可复现,但对 ngspice 版本敏感。

### 1.6 亮点与不足

亮点:PySpice 表述借用 LLM 的 Python 先验(消融证实直接生成 SPICE 明显更差);
领域化校验器把"仿真跑通但电路不对"变成可反馈文字;测量配方简洁实用;金样+自检复现门槛低。
不足:**无 LICENSE**;level-1 理想模型(kp=100µ、vto=0.5、Vdd=5V)、通/不通二值判定,
无指标优化;单文件、无测试无 CI、消融提示词文件缺失;校验规则硬编码到 24 题。

---

## 2. Analogagent

**仓库**:`TheWind-upBird/Analogagent` · 自称 **KDD 2026(AI4Science Track)Oral**
"AnalogAgent: Self-Improving Analog Circuit Design Automation with LLM Agents"。
README 给出的 arXiv 号 `2603.23910` 格式可疑、无法核实。单 commit(2026-06-08),
**MIT 许可**(版权人 Jiageng Wang),作者/单位未署名。README 自我声明是 **MVP**。

### 2.1 定位与架构

在 AnalogCoder 骨架上加四层(共 ~3880 行,主体 `main_run.py` 1658 行):

| 组件 | 内容 |
|---|---|
| 多智能体(`agents.py`) | CodeGenerator(写/修代码)+ DesignOptimizer(跑仿真并**多模态**反思——波形 PNG base64 喂回 LLM) |
| 自进化记忆(`curator.py`,419 行) | 失败后 LLM 反思提炼 JSON 规则,去重/冲突检查后持久化 `playbook.json`,跨任务注入 |
| 可视化调试(`visual_debugger.py`) | 按电路类型的期望波形字典 + LLM 看图诊断 |
| 参数优化(`auto_optimizer.py`) | 功能通过后用 **Optuna** 对 W/L/R 做 20 轮贝叶斯优化(目标从 stdout 抓 dB/增益数字) |

LLM 接入:OpenAI SDK(默认模型串 `"gpt-5"`)或本地 vLLM(OpenAI 兼容端点);
`google.generativeai` import 了但**从未接线**。

### 2.2 派生性(定量实证)

- `problem_set.tsv` 前 24 题与 AnalogCoder **一字不差**,新增 25–30:运放比较器、
  无源低/高/带通/带阻滤波器、**Gilbert 混频器**(测试台要求 FFT 出 |LO−RF| 与 LO+RF
  两个混频积);新题带内嵌 Testbench/Expected 文字规格。
- `problem_check/` 12 个测试台:**10 个与 AnalogCoder 逐字节相同**,Oscillator
  相似度 0.99,仅 Inverter 重写。
- OP 校验器/DC 定偏置/exit(0|2) 约定均沿用。
- **全库无任何对 AnalogCoder 的引用或致谢**——学术规范上是显著问题;工程上意味着
  其基准与检查器的质量上限即 AnalogCoder。

### 2.3 完成度问题(逐项实证)

1. `main_run.py:939` 使用 `import_template` —— 全库 **0 处定义**,`--ngspice` 路径
   一开即 NameError;
2. 同路径要读 `prompt_template_ngspice.md` —— **文件缺失**;
3. `curator.py` 核心规则教 LLM `from opamp import Opamp`,Integrator/Comparator
   测试台也依赖该子电路 —— **`opamp.py` 缺失**,这些任务照原样跑不通。

另:无 requirements(scipy 是数个测试台的硬依赖但安装说明缺失)、无测试无 CI、
无金样设计(不可像 AnalogCoder 那样离线自证)、死代码若干(tmux 管理、`--retrieval`)。

### 2.4 有价值的部分

超出 AnalogCoder 的两点:**功能通过后继续 Optuna 调参**(从"能不能用"往"好不好"
迈了半步)与 **playbook 规则沉淀机制**(`playbook.json` 里的 PySpice 最佳实践本身
可作静态 lint 提示)。6 个新任务的测量配方(FFT 混频判定等)可借鉴。

---

## 3. AnalogGym

**仓库**:`CODA-Team/AnalogGym` · **论文**:AnalogGym: An Open and Practical Testing
Suite for Analog Circuit Synthesis,**ICCAD 2024**,arXiv 2409.08534。作者:复旦
(Zhaori Bi、Keren Zhu、Fan Yang、Xuan Zeng 等)/东南/贵大/电子科大。
**BSD-3 许可**(可自由复用,保留版权声明即可)。

### 3.1 定位

**非 LLM 项目**——模拟电路 **sizing/优化算法基准套件**:给定成熟拓扑 + 设计变量 +
完整表征测试台 + FoM 定义,让优化算法(BO/RL/进化)调尺寸。谱系上游是
Li & Carusone 的 ICCAD'23 SKY130 LDO RL 工作(RL 示例改编自它并署名)。

### 3.2 内容(30 拓扑 5 类,两类完全开源)

| 类别 | 数量 | 工艺/仿真器 | 可复现 |
|---|---|---|---|
| **运放(Miller 多级)** | 21 组设计变量,**17 个 ngspice 网表**(NMCF/DFCFC/AFFC/TCFC/PFC/CFCC 等,以文献命名,另附 TSMC22 Spectre 版) | **SKY130 + ngspice** | ✅ |
| **LDO** | ~5 个(basic/simple/1/2/folded_cascode) | **SKY130 + ngspice** | ✅ |
| 电压基准(带隙/亚阈值) | 4 | 保密 PDK + HSPICE | ❌ 仅参考网表 |
| 传感前端(PTAT/温度传感) | ~10 | TSMC + Spectre | ❌ |
| PLL / 电荷泵 | 2 | Cadence OCEAN / SMIC 0.13µm + HSPICE | ❌ |

SKY130 PDK 随库携带(`sky130_pdk.zip` 17.7MB,解压 ~109MB,含 ngspice corner 全套)。
README 特别警告**必须用 ngspice-42/43**(conda 的 41 在温度/电流 DC 扫描上有 bug)。

### 3.3 测试台设计(工程上最值得学)

`TB_Amplifier_ACDC.cir` **一台全测**:DUT 按固定 5 脚契约
`gnda vdda vinn vinp vout` 实例化四次,同时测差模/共模(CMRR)、PSRR+、PSRR−、
DC/温漂(TC)/功耗/失调;`.meas` 直接产出 dcgain / GBW / 相位 / TC / power / Vos。
文件组织四层解耦——**网表 ⊥ 设计变量(.PARAM 文件)⊥ PDK corner ⊥ 测试台**,
换电路只改 3 行 include。配套 `perf_extraction_amp.py`:解析日志 + 从瞬态数据推导
SR/settling + 由 L·W·M 求面积、缺项给惩罚默认值;其 `TB_Amplifier_ACDC.__call__(x)`
是标准的 24 维黑盒目标函数(写参数 → 跑 ngspice → 解析 → 标量 FoM),可直接接任何
优化器。FoM 定义(归一化乘积 + `max(1,·)` 惩罚)与逐电路 target/baseline 规格表齐备。
LDO 侧 `TB_LDO_ACDC/Tran.cir` 覆盖轻/重载(5mA/55mA)环路增益+PM、LNR/LR、PSRR、
dropout、瞬态过冲,输出 wrdata 文件由 `perf_extraction_LDO.py` 解析。
RL 侧提供完整 Gymnasium 环境(13 个 AMP env + LDO env)+ RGCN-DDPG 基线。

### 3.4 实证(本环境 ngspice-42,零补丁开箱即跑 ✅)

- **AMP**(HoiLee_AFFC 三级,默认尺寸):`ngspice -b TB_Amplifier_ACDC.cir` 一次通过,
  **DC 增益 90.1dB、GBW 838kHz、PSRR+ −39dB / PSRR− −71dB、CMRR −39dB、
  功耗 424µW、Vos −16µV、TC 20ppm/°C**(GBW 处相位仅 8°——默认尺寸本就是给
  优化器的起点,欠稳定属预期)。单次评估耗时:**ACDC 3.3s + Tran 0.7s ≈ 4s**。
- **LDO**:`TB_LDO_ACDC.cir` 一次通过,输出全套 wrdata(轻/重载 GBW+PM、LNR、
  LR/功耗/Vos、PSRR),环路相位裕度 94°/96°。

三个仓库中**唯一不打任何补丁即可在本环境全速跑**的一个。

### 3.5 不足

仓库卫生一般:87MB 中大头是重复提交的 PDK zip(两份)、torch wheel(两份)、
`__pycache__`、RL 权重 zip;单 squash commit;无测试、无功能 CI;5 类中 3 类绑定
商业仿真器/保密 PDK;设计变量文件(21)多于 ngspice 网表(17);电压基准"网表"
嵌在 Markdown 里。

---

## 4. 三仓库谱系与横向对比

```
EDA 优化谱系                          LLM 智能体谱系
─────────────                        ──────────────
sky130_ldo_rl (ICCAD'23)             AnalogCoder (AAAI'25, 无 LICENSE)
      │ 改编 + 署名                        │ 基准/测试台/校验器整体沿用,未署名
      ▼                                   ▼
AnalogGym (ICCAD'24, BSD-3)          Analogagent (自称 KDD'26, MIT, MVP)
          互不引用,零共享代码
```

| | AnalogCoder | Analogagent | AnalogGym |
|---|---|---|---|
| 性质 | LLM 拓扑发明 + 通/不通判定 | 其智能体化扩展 + Optuna 调参 | sizing 优化基准(无 LLM) |
| 物理真实度 | level-1 理想模型,5V | 同左 | **SKY130 BSIM,1.8V** |
| 电路表示 | PySpice 代码 | PySpice 代码 | SPICE 网表 + .PARAM |
| 仿真接口 | PySpice→libngspice | 同左 | **ngspice 子进程**(与本 app 同构) |
| 许可 | **无 LICENSE** | MIT | **BSD-3** |
| 离线可跑(实测) | ✅ 需 2 处 ngspice-42 补丁 | 部分(缺 opamp.py 等) | ✅ **零补丁** |
| 工程质量 | 论文代码 | MVP,缺关键文件 | 数据齐全,仓库卫生一般 |

## 5. 对 Analog Studio 的可复用性总结

- **AnalogCoder**:借鉴思想(PySpice 表述、OP linter、测量配方),**不搬代码**
  (无 LICENSE);不 vendor。
- **Analogagent**:playbook 规则集与 FFT 混频判定配方可参考(MIT),但完成度低、
  质量上限即 AnalogCoder;不 vendor。
- **AnalogGym**:**复用价值最高**——BSD-3、ngspice 原生(与本 app 的子进程 +
  wrdata 解析技术栈完全同构)、17 个文献级 SKY130 运放 + 5 个 LDO + 一台全测的
  表征测试台 + 现成 FoM/目标函数模式,可直接支撑一个 "sizing 优化" 新功能。
  集成评估见下一节。

---

## 6. 基于 AnalogGym 的 "sizing 优化"功能集成评估

> 评估结论先行:**可行,且与现有架构高度契合**;建议按 P1→P2 分期,总量级
> ≈ 1000–1400 新 LOC(与 FinFET / Circuits 两次工作流相当)。以下为方案框架,
> 未写实现代码。

### 6.1 功能定义

新增 **Sizing 标签页**(或 Circuits 标签页内的新分析类型,推荐前者):
选一个 AnalogGym 运放/LDO 拓扑 → 表格编辑设计变量(W/L/M/电容/偏置,含边界)→
选目标与约束(FoM 或单指标 + 硬约束,如 PM≥60°)→ 选算法与评估预算 → 运行;
右侧实时显示**收敛曲线**(最优 FoM vs 评估次数)+ 当前最优的**指标表**
(dcgain/GBW/PM/CMRR/PSRR/功耗/Vos/TC/面积),完成后可导出最优 `.PARAM` 文件。

### 6.2 素材与落点(全部经实测验证)

| 素材 | 来源(BSD-3) | 用法 |
|---|---|---|
| 17 个 AMP 子电路 + 5 个 LDO | `AnalogGym/Amplifier/spice_netlist/`、`Low Dropout Regulator/spice_netlist/` | vendor 为 `analoggym/` 目录(仅开源子集,~几百 KB) |
| 设计变量 .PARAM 文件 | `design_variables/` | 解析为变量表(名称/默认值/类型),GUI 表格的初值 |
| 表征测试台 | `amp_spice_testbench/*.cir`、`ldo_spice_testbench/*.cir` | 原样使用;include 路径按工作区渲染 |
| 指标提取 | `perf_extraction_amp.py` / `perf_extraction_LDO.py` | 参考其解析逻辑在 `app/core` 重写(约 200 行;原脚本 cwd 相关、`os.system` 风格,不宜直接 import) |
| FoM/规格 | README 公式 + `ckt_graphs.py` 的 target/baseline 字典 | 内置默认目标,GUI 可改 |
| SKY130 PDK | `PDK/sky130_pdk.zip`(17.7MB,解压 109MB) | **vendor zip、首启解压到工作区**(复用现有 `_sync_tree` 原子落盘模式);tt corner 的 include 图很宽,不做裁剪 |
| 原理图 PNG | `Amplifier/schematic/` | 电路选择时展示(复用 Circuits 页的 schematic 显示模式) |

### 6.3 架构方案(复用现有资产)

- **`app/core/sizing.py`**(新,~400 行):
  - `SIZING_CIRCUITS` 注册表:每项声明网表文件、变量文件、测试台、指标 schema、
    默认 FoM 目标(照 `CircuitSpec` 的既有模式);
  - `evaluate(circuit, params) -> dict`:渲染 .PARAM → 组装测试台(改 3 行 include
    指向工作区)→ `ngspice -o log -b`(沿用 skill 的子进程模式与路径引号修复)→
    解析 `.meas`/wrdata → 指标 dict + FoM;
  - `optimize(circuit, bounds, budget, algo, progress_cb, cancel_flag)`:
    **P1 用 `scipy.optimize.differential_evolution`(零新依赖,scipy 已随包)**,
    P2 可选 Optuna(pypi 可得,仅 ~1MB 纯 Python,打包无痛)。
- **线程模型**:整个优化循环作为一个 SimWorker 任务(串行队列不变);每次评估后经
  `progress_cb` 把 `(eval_no, best_fom, best_metrics)` 转发到日志面板与收敛曲线;
  取消 = 在两次评估之间检查 flag(现有 worker 的取消协议直接适用)。
  matplotlib 收敛图沿用 render-closure 模式(worker 出数据、GUI 线程画图)。
- **GUI**:`app/ui/sizing_tab.py`(~350 行):左侧电路下拉 + 变量表格
  (QTableWidget,名称/下界/初值/上界)+ 目标/预算/算法 + Run/Cancel;
  右侧 PngViewer(原理图 + 收敛曲线)+ 指标表(复用 `OpResultView` 风格)。
- **打包**:`analoggym/` 子集 + PDK zip 进 `app.spec` datas 与 Nuitka
  `--include-data-*`;首启解压到工作区(只读安装目录不写)。
- **合规**:根目录 NOTICE 追加 AnalogGym 的 BSD-3 版权声明与 ICCAD'24 引用。

### 6.4 预算与耗时(实测推算)

单次全评估 ≈ **4s**(ACDC 3.3s + Tran 0.7s;若目标不含 SR/settling 可只跑 ACDC ≈ 3.3s)。
差分进化 popsize=8、24 维、20 代 ≈ 160 次评估 ≈ **11 分钟**;快速模式(50 次)≈ 3.5 分钟。
GUI 需明确显示预计耗时与进度,默认预算取 100–200 次。

### 6.5 分期与工作量

- **P1(核心,~2/3)**:2 个代表电路(1 AMP + 1 LDO)端到端——评估函数 + 差分进化 +
  收敛曲线 + 指标表 + 导出 .PARAM;PDK 落盘与打包;测试(评估函数返回完整 schema、
  一次 20-eval 微型优化 FoM 单调不降)。
- **P2**:全部 17+5 电路注册;约束模式(PM/功耗硬约束 + 罚函数);Optuna 可选算法;
  手册 zh/en 新章节。
- **P3(可选)**:把 FoM/优化框架回接到现有 circuit-skills 五电路(PTM 工艺)——
  评估函数换成 Circuits 页已有的 simulate 路径即可,框架无需改动。

### 6.6 风险表

| 风险 | 等级 | 缓解 |
|---|---|---|
| PDK 体积(zip 17.7MB / 解压 109MB) | 中 | vendor zip、首启解压;安装包增幅可接受,文档注明磁盘占用 |
| 优化时长(百次评估十分钟级) | 中 | 预算/快速模式 + 实时收敛曲线 + 可取消;默认只跑 ACDC |
| 用户 ngspice 版本 < 42 | 低 | locator 已能读版本,Sizing 页对 <42 给横幅警告(README 明确 41 有 DC 扫描 bug) |
| `.meas` 在个别 ngspice 构建差异 | 低 | 解析层对缺项给惩罚默认值(照 perf_extraction 的做法),不崩 |
| BSD-3 合规 | 低 | NOTICE + 文件头保留版权声明即可 |
| Windows 路径含空格 | 低 | 沿用既有 include/wrdata 引号修复经验 |

---

## 7. 附:实证记录

环境:Linux x86-64,ngspice-42(发行版 apt),Python 3.11。

- **AnalogCoder**:`pip install pyspice`(1.5)+ `apt install libngspice0`;
  给 `PySpice/Spice/NgSpice/Shared.py` 的 stderr 分类加一行白名单
  (放行 ngspice≥42 的 "Using … Direct Linear Solver" 提示)后,
  `sample_design/test_all_sample_design.py` **24/24 通过**。
  功能测试台:p1+Amplifier ✓;p11+Opamp 需把第二次 AC 从退化单点扫描改为两点后 ✓。
- **Analogagent**:`diff -r problem_check/`(vs AnalogCoder)→ 10/12 逐字节相同、
  Oscillator 相似度 0.99、Inverter 重写;`problem_set.tsv` 前 24 题一字不差;
  `import_template` 全库 0 定义、`prompt_template_ngspice.md` 与 `opamp.py` 缺失
  均经 grep/ls 验证。
- **AnalogGym**:解压 `sky130_pdk.zip` 到 `Amplifier/mosfet_model/` 后,
  `ngspice -o log.txt -b TB_Amplifier_ACDC.cir` 退出码 0,`.meas` 输出:
  `dcgain=90.08dB, GBW=838.4kHz, dcpsrp=-39.2dB, dcpsrn=-71.4dB, cmrrdc=-39.0dB,
  power=423.5µW, vos25=-16.3µV, tc=20.3ppm`;`TB_Amplifier_Tran.cir` 0.7s 通过。
  LDO:`TB_LDO_ACDC.cir` 退出码 0,输出 7 个 wrdata 文件,`phase_margin1/2 = 94.0°/95.5°`。
  单次评估计时:ACDC 3.3s、Tran 0.7s。
