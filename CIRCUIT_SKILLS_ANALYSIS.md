# analog-circuit-skills 分析报告 + Analog Studio GUI 集成评估

> 分析对象:[Arcadia-1/analog-circuit-skills](https://github.com/Arcadia-1/analog-circuit-skills)
> 存档位置:本仓库 `circuit-skills/`(vendor 时点:2026-07-09,单一提交 cf1066e;已去 .git,
> 并清理了 2 份误提交的 `b3v3_1check.log`,其余原样保留)
> 评估结论:**可集成进 Analog Studio,与现有架构高度契合;总量 ≈1200–1500 行,量级与 FinFET 工作流相当。**

---

## 一、总体定位

面向 **AI agent + 工程师**的模拟电路仿真"技能库"——每个电路是一个自包含 skill,
覆盖"拓扑 → netlist 生成 → ngspice 仿真 → 指标提取 → 出图"的完整闭环。
是 gmoverid-skill(单器件 gm/ID 表征)的同作者续作,把范围升级到**块级电路**。

- 规模:**~11,000 行 Python**(92 个 .py)+ 27 个 netlist 模板 + 5 份 PTM 模型库
- 依赖:ngspice(PATH)+ numpy/matplotlib/scipy;纯 CLI,无 GUI,无打包
- 许可:MIT(PTM 模型另有学术使用限制,见本仓库 NOTICE)

## 二、五个电路 skill 明细

| Skill | 工艺/电源 | Python LOC | 覆盖内容 | 成熟度 |
|---|---|---|---|---|
| **comparator** | 45nm HP / 1.0V | 5188(39 脚本) | StrongArm 动态比较器:内部节点波形、probit 输入噪声提取(trnoise×1000 周期)、ramp 传输曲线、多维扫描(输入幅度/共模/尾管宽/latch 宽)、τ=C/gm 验证、FOM 报告 | ★★★★★ |
| **LDO** | 180nm / 1.8V | 3846(23 脚本) | 低压差稳压器:DC 调整率/AC 环路增益与相位裕度/PSRR/负载瞬态/输出噪声 + **auto-design(给 spec 出尺寸)** + Ccomp/Rcomp/Cout 补偿扫描 + 理论-仿真交叉验证 | ★★★★☆ |
| **bootstrap_switch** | 180nm(文档称 45/22 可选) | 754 | 自举采样开关:栅压自举波形(VGATE≈VIN+VDD)、导通电阻平坦度 | ★★★ |
| **two_stage_opamp** | 180nm / 1.8V | 740 | Miller 两级运放:工作点、增益/相位、**PZ 极零分析**、开环/闭环噪声、稳定性比值报告 | ★★★ |
| **five_transistor_ota** | 180nm / 1.8V | 551 | 五管 OTA:DC 传输、AC 开环、噪声(教学基线) | ★★☆ |

## 三、架构与约定(与 gmoverid-skill 同源)

```
run_*.py   (入口;均有 main() + __main__ 守卫,可 import 调用;master 用 ThreadPoolExecutor 并行多仿真)
  → simulate_*.py (str.format 渲染 .cir.tmpl → 调 ngspice → parse_wrdata 解析两列文本 → numpy)
  → plot_*.py     (matplotlib Agg 出 PNG,恒 plt.close)
共享层:
  ngspice_common.py   (每 skill 一份副本:ngspice 定位/运行/解析/模板渲染)
  <circuit>_common.py (电路参数=模块级全局(晶体管尺寸/偏置/时钟/噪声配置)、DUT 渲染)
```

关键约定(CLAUDE.md 成文):输出目录与 skill 包分离(comparator→`.work_comparator/`、
bootstrap→`.work_bootstrap/`、其余→`WORK/`),**全部支持 `ANALOG_WORK_DIR` 环境变量重定向**;
路径恒用正斜杠;比较图最多 3 个纵向子图。

## 四、工程亮点

1. **Agent eval 框架**(`comparator/evals/evals.json`):用自然语言 prompt + 可断言的期望
   (如"sigma_n 在 200–600µV 内"、"生成 3 张 PNG")评测 AI agent 能否正确调用 skill——
   "skill 即 agent 能力单元 + 可回归评测"的范式。
2. **LDO 自动设计**(`run_auto_design.py`):给定 VOUT/VIN/ILOAD,自动算反馈分压、按负载
   线性缩放 pass 管、按 fz=0.4·GBW 定 Ccomp,再跑验证仿真出指标;SKILL.md 附完整 7 步
   初始 sizing 公式与 spec 优化指南(441 行,近乎一份 LDO 设计手册)。
3. **理论-仿真交叉验证**:LDO 环路极点/零点/PSRR/Zout 公式 vs AC 仿真;比较器 τ=C/gm
   经 latch 管宽扫描验证(gm∝W 且 C∝W → τ 近似不变;加大输入对管只加 C → τ 变大)。
4. **probit 噪声提取**:trnoise 注入 + 固定 Vin 跑 1000 周期 + 数 P(HIGH) →
   σ = Vin/Φ⁻¹(P),再算 FOM1=E·σ²、FOM2=FOM1·Tcmp——动态比较器噪声表征的硬核方法。
5. LDO 附真实设计参考网表(`c018bcd_gen2_v1d6.scs.txt`,Spectre 导出)作 sizing 对照。

## 五、不足

- **无自动化测试、无 CI**:仅 comparator 有 agent-eval(需人工跑);仓库无 `.github/`。
- 成熟度不均:comparator/LDO 深,OTA/opamp 偏基线,bootstrap 只有波形+Ron。
- 卫生问题:2 份误提交的 `b3v3_1check.log`(vendor 时已清)、PTM 模型多份重复打包。
- 参数入口是模块级全局,改尺寸需编辑源码(仅 LDO auto-design 有 CLI)。
- 单一提交,无演进历史。
- `bootstrap_switch` 硬编码 `~/.claude/skills/ngspice/assets` 作为外部依赖路径(见下)。

---

## 六、Analog Studio GUI 集成评估

### 结论

**可行,且与现有架构高度契合。** 五个 skill 与 app 已封装的 ngspice examples 完全同构
(run→simulate→plot + 模板 netlist),集成即"第五个标签页",三件既有资产直接复用:

- `app/core/examples.py` 的 **ParamSpec + monkey-patch + render-closure** 模式(参数表单、
  Advanced 折叠、worker 仿真 / GUI 线程画图的切分);
- `JobTabMixin + SimWorker` 串行任务框架(日志转发、按钮状态、错误行);
- `PngViewer`(缩放/拖拽/另存)。

### 经代码核实的集成关键事实

| 事实 | 出处 | 对集成的意义 |
|---|---|---|
| 全部 5 个 skill 的 work 目录读 `ANALOG_WORK_DIR`(import 时求值) | 各 `ngspice_common.py` / `bootstrap_common.py` | 冻结包中 skill 树保持只读;GUI 启动时(import 前)设 env 指向工作区即可。**比 gmoverid 的 `__file__` 相对写入更友好** |
| 模块名冲突面仅 `ngspice_common.py`(4 份 + gmoverid 1 份),其余 92 个模块名唯一 | 全库 basename 统计 | 串行 worker 下,每任务前 sys.path 交换 + 从 sys.modules 清 `ngspice_common` 即完成隔离 |
| 所有 run_*.py 有 `main()` + `__main__` 守卫 | 各 skill 抽查 | 可 import 后编程调用,无 import 副作用炸弹 |
| master `main()` 在进程内画图 + 内部 ThreadPoolExecutor | run_ldo/run_ota/run_opamp/run_tran_strongarm_comp | **不能**在 SimWorker 线程直接调 main()(违反本 app "matplotlib 仅 GUI 线程"策略);须仿 browser_service:worker 跑 simulate_*(其内部并行是 ngspice 子进程,无害),render 闭包在 GUI 线程调 plot_* |
| 参数面 = `*_common.py` 模块级全局(OTA:VDD/VCM/VBIAS/W_*/L_*/M_*;comparator:W dict/FCLK/NOISE_*;LDO:尺寸+补偿网络) | 各 common 文件 | 与 examples.py 的 ParamSpec monkey-patch 完全适配 |
| bootstrap_switch 硬编码 `Path.home()/.claude/skills/ngspice/assets`(borrow ngspice_common + ptm 模型) | bootstrap_common.py:30-53 | 适配时:app 的 NGSPICE_ASSETS 已在 sys.path(init_runtime),`from ngspice_common import ...` 可解析;import 后 patch `bootstrap_common.MODEL_PATH` 指向工作区模型。**已核实 gmoverid 版 ngspice_common 具备其需要的全部 7 个函数**(含 parse_print_table),兼容风险低 |

### 集成方案

新增 **"Circuits" 标签页**(左:电路下拉 + 分析类型 + 参数表单(基础/Advanced 折叠)+ 运行按钮;
右:PngViewer + 指标文本区)+ `app/core/circuits.py` 注册表:

```
CIRCUITS = {
  'ldo':        CircuitSpec(scripts_dir, params=[...], analyses={dc, ac, psrr, tran, noise, auto_design}),
  'comparator': CircuitSpec(..., analyses={wave, noise, ramp, sweeps…}),
  'ota5t':      CircuitSpec(..., analyses={dc, ac, noise}),
  'opamp2':     CircuitSpec(..., analyses={dc, ac, pz, noise}),
  'bootstrap':  CircuitSpec(..., analyses={wave, ron}),
}
```

适配器职责(每电路 ~80–150 行):sys.path 交换 + `ngspice_common` 隔离、参数 monkey-patch、
调 simulate_* 收集结果、返回 GUI 线程 render 闭包(调 plot_*)、收集 work 目录 PNG 与指标文本。
打包:五个 skill 树按现有 `skill/` 同样方式进 app.spec datas + Nuitka 数据目录 + 工作区 sync
(纯 .py/.tmpl/.lib,与 gmoverid 树同性质);`ANALOG_WORK_DIR` 由 `app/paths.py` 在 init_runtime 设定。

### 分期与工作量(总计 ≈1200–1500 新 LOC,量级 ≈ FinFET 工作流)

| 阶段 | 内容 | 占比 |
|---|---|---|
| **P1(核心)** | 5 电路"完整表征"跑通 + 基础参数编辑 + 出图/指标;LDO auto-design 向导(--vout/--vin/--iload 已是 CLI 参数,最易) | ~2/3 |
| **P2** | comparator 各扫描(幅度/共模/尾管/latch 宽)、LDO 补偿扫描(Ccomp/Rcomp/Cout)、理论验证脚本入 Tools | ~1/4 |
| **P3(可选)** | comparator evals.json 跑批回归、两级运放 PZ 结果表格化 | 余量 |

### 风险表

| 风险 | 等级 | 处置 |
|---|---|---|
| bootstrap 硬编码 `~/.claude/skills` 路径 | 低 | import 后 patch MODEL_PATH;ngspice_common 由 app sys.path 提供(API 已核实全兼容) |
| comparator 噪声仿真 1000 周期耗时(~10s+,扫描类更久) | 中 | GUI 进度提示 + 复用 worker 的排队/取消;首版对扫描类给出耗时预估文案 |
| 各 skill 的 `ngspice_common` 差异(4 个副本非完全一致) | 中 | 隔离方案本就按"每任务用自己那份"设计;不合并、不改 skill 源(沿用 gmoverid 集成原则) |
| 多份 ptm180.lib 重复 | 低 | 原样打包不合并(遵守"不改 skill"原则,体积代价 ~几百 KB) |

---

*本文档由 Claude Code 生成(vendor + 分析 + 评估:2026-07-09)。实施集成前请以本评估的
"分期与工作量"为准立项;P1 完成即可在 GUI 中运行全部五个电路的标准表征。*
