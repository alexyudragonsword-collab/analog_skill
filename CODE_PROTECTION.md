# 代码保护评估报告 — 冻结包中隐藏原始 Python 源码

> 目标(用户提出):**exe 运行后,在任何安装目录和临时目录中都找不到 vendored
> 与自研的原始 Python 代码。**
>
> 结论先行:**"找不到可恢复的 Python 源码" 可以做到;"任何目录里找不到任何
> 相关文件" 做不到** —— ngspice 需要读的非 Python 仿真资产必须以明文落盘。
> 本文只做评估,不改代码。

---

## 1. 威胁模型与"可恢复"的定义

"保护"必须先定攻击者能力,否则无从谈起:

| 档位 | 攻击者手段 | 能否防住 |
|---|---|---|
| A 小白 | 直接翻安装目录 / 工作区,找 `.py` 打开看 | ✅ 可防 |
| B 一般 | `pyinstxtractor` 解包 + `decompyle3` 反编译 `.pyc` | ⚠️ 只有原生编译能防,`.pyc` 防不住 |
| C 逆向 | 反汇编原生二进制、动态调试、dump 内存 | ❌ 无法根本防住(业界通例) |

**本报告把目标定在"挡住 A、B" —— 即磁盘上不留任何可反编译回 Python 的产物。**
C 档(有决心的逆向工程)对任何编译型语言都无法根治,原生编译只是把成本从
"几分钟反编译"提高到"读汇编逆算法"。这是能达到的实际天花板,需向用户如实声明。

---

## 2. 本工程当前的暴露面(实测)

代码分两类,打包待遇完全不同:

### 2a. 自研 `app/`(约 9,100 LOC)
- **PyInstaller 构建**:进 `PYZ` 归档,形态是 **`.pyc` 字节码**。
  `pyinstxtractor` 解包 → 反编译器还原出带变量名、逻辑的近似源码 → **B 档即破**。
- **Nuitka 构建**:编译为 **C → 原生机器码**,磁盘无 `.py`/`.pyc`。✅ 挡住 A、B。

### 2b. skill 树(vendored + 自研混在其中,实测规模)

| 树 | .py 文件 | Python LOC |
|---|---|---|
| `ngspice/assets` | 26 | 1,986 |
| `gmoverid/assets` | 6 | 2,480 |
| `circuit-skills` | 92 | 11,079 |
| `transistor-models/assets` | 0 | 0(纯模型,非 Python) |
| **合计** | **124** | **≈ 15,545** |

这些 `simulate_*.py` / `plot_*.py` / `design_gmoverid.py` / `*_common.py`:
- 由 `app.spec` 的 `collect_tree(...)` 以 **明文 `.py`** 打进 `_internal/skill/`;
- `app/paths.py::init_runtime()` 首次启动 `shutil.copytree` **复制到用户工作区**
  `~/.local/share/Analog Studio/workspace/<version>/`,再 `sys.path.insert` 注入;
- 三个加载层 `app/core/{examples,circuits,sizing}.py` 通过动态 import 按模块名导入。

> **关键:因为是"运行时 sys.path 注入源码",Nuitka/PyInstaller 的静态分析都
> 看不到这些模块,只能把它们当数据文件原样打包。所以无论哪种构建,skill 的
> 原始 Python 在安装目录 (`_internal/skill/`) 和工作区里都是明文可读的。**

### 2c. 非 Python 仿真资产(293 个文件)
`.tmpl` / `.lib` / `.pm` / `.cir` / `.osdi` / `.spice` / SKY130 PDK zip —— ngspice
在仿真时**直接从文件系统读取**它们。这些**无法隐藏**:进程运行期间必须存在于
磁盘上的真实路径(`wrdata`/`.include`/`pre_osdi` 都是文件路径)。它们不是"代码",
且大多是公开资产(SKY130 PDK Apache-2、PTM 模型 ASU 学术、AnalogGym BSD-3)。

---

## 3. 各方案能达到什么(为什么只有一条真路)

| 方案 | 原理 | 挡住档位 | 判定 |
|---|---|---|---|
| 临时解压→退出删除 | 启动解压 skill 到 temp,`atexit` 删 | 无 | ❌ 运行期文件在磁盘(可复制 / `/proc` dump / 崩溃残留),"临时目录找不到"在运行时已不成立 |
| 加密 PYZ / 混淆 `.pyc` | AES 包裹字节码 | A | ❌ PyInstaller 6.x 已删 `--key`,且密钥在二进制里;解密后照样反编译 |
| `.pyc` 替代 `.py` | 只发字节码 | A | ❌ 字节码 = 可反编译,B 档即破 |
| **Nuitka / Cython 原生编译** | Python → C/机器码 或 `.so`/`.pyd` | A、B | ✅ **唯一真答案**:磁盘无 Python,反编译只得汇编 |

**唯一能让磁盘不留可恢复 Python 的路子:把所有要隐藏的 Python(app/ + 全部
skill 模块)都原生编译进二进制。** 非 Python 仿真资产则无法隐藏(§2c)。

---

## 4. 真正做到"无可恢复 Python" 的改造清单

### 4a. 自研 app/ → ✅ 已实现(2026-07-16)
- 以 **Nuitka standalone** 为受保护发布构建。Windows Nuitka job 已有;新增
  **Linux Nuitka job**(`build-windows.yml` 的 `linux-nuitka`),产出
  `AnalogStudio-linux-nuitka.tar.gz` 并接进 release。
- 两个 Nuitka 命令都加了 **`--include-package=app`**,强制 app/ **每个**子模块
  编译进原生二进制(不只从 `main.py` 静态跟随到的)。
- Linux Nuitka job 内置**源码泄漏门禁**:打包后 `find` dist 里任何 `app/**.py`
  或 `.pyc`,发现即 `exit 1` fail 构建 —— 把"无 app 源码"变成 CI 可断言的约束。
- **沙箱实测(2026-07-16,Nuitka 2.8.10 / Python 3.11 / Linux x86-64)**:
  - `AnalogStudio.bin` 138 MB,dist 414 MB;
  - **dist 内 app/ 的 `.py` 数量 = 0**(app/ 全部编成机器码);
  - 补齐 skill 资产 + auditwheel `*.libs`(numpy/scipy/pillow)后
    `--smoke`(offscreen 构造整窗 + 导入 scipy/matplotlib/numpy)**退出 0**。
  - 注:Nuitka 的 traceback 仍会显示 `app/paths.py` 之类的**文件名/行号**
    (编译时嵌入,用于可读回溯),但磁盘上并无对应 `.py`,不可反编译。
- 弃用 PyInstaller 产物作为"受保护"对外分发(它的 PYZ 是 `.pyc`,B 档可破);
  PyInstaller 包保留但仅作兼容变体,不宣称保护。
- 净效果:app/ 的 ~9,100 LOC 变原生码,Windows + Linux 两平台均有受保护包。✅

> **skill 的 124 个 Python 模块本步仍是明文**(§4b 未做)——本步只保护自研
> `app/`;要连 vendored/skill 一起隐藏需推进 §4b(circuit-skills 92 文件的
> 重名/相对导入梳理是主要工作量)。

### 4b. skill 的 124 个 Python 模块 → 核心改造(工作量主体)
现状"复制到工作区 + sys.path 注入源码"必须改成"编译进二进制 + import 编译模块"。
需要动的点(按依赖顺序):

1. **加载层去源码化**(`app/core/examples.py` / `circuits.py` / `sizing.py`,
   以及 `gmid_service.py` / `finfet_sim.py` / `model_registry.py`):
   - 现在的 monkey-patch 机制(examples.py 改 skill 模块的模块级全局跑参数)
     依赖"模块是可写源码对象"—— 对编译后的扩展模块,模块级全局仍可 setattr,
     大部分可保留;但任何依赖 `__file__` 相对定位资产的代码要改为经
     `paths.*` 显式定位(§4c)。
   - `sys.path.insert(工作区)` + 动态 `import_module(名)` → 改为对**已编译进
     二进制的包**做常规 import(Nuitka `--include-package=<pkg>` 或
     Cython 产出的 `.so` 随 datas 打包并加进 sys.path)。
   - `circuit-skills` 的 4 份重名 `ngspice_common.py` 冲突隔离(现在靠 sys.path
     交换)在编译进二进制后需改为**唯一化包名**(重命名或包内相对导入),否则
     编译期就撞名。**这一条最费事**(92 文件、11k LOC 的重名/相对导入梳理)。
2. **打包配置**:
   - Nuitka:对每个 skill 包加 `--include-package` / `--include-module`;若走
     Cython,先 `cythonize` 出各平台 `.so`/`.pyd` 再随包打。
   - `app.spec` 的 `collect_tree(skill/**.py)` 删掉(不再发源码),但 §2c 的
     **非 Python 资产仍要 `collect_tree` 保留**(ngspice 要读)。
3. **工作区同步收敛**:`paths.py::_sync_tree` 只再同步**非 Python 资产**
   到可写工作区(ngspice 写 `wrdata` 也需要可写目录);Python 不再落工作区。

### 4c. 非 Python 资产:无法隐藏,只能规整
- `.tmpl`/`.lib`/`.pm`/`.cir`/`.osdi`/PDK 仍以明文随包 + 同步到工作区(ngspice
  读)。可做的仅是:放只读安装目录、运行时按需解压、命名混淆 —— 但**运行期
  必然可见**,不构成保护。如实告知用户:**电路网表/模型/PDK 无法防提取**。

### 4d. 许可义务(编译不免除)
- 隐藏/编译 vendored 代码**不解除许可要求**:AnalogGym **BSD-3 需保留署名与
  许可全文**,PTM 模型 **ASU 学术用途**,circuit-skills / ngspice 各自条款。
- `NOTICE` / `LICENSE` / 各树的 LICENSE 文本**仍须随包携带**(编译代码可以,
  但通知文件要留);否则是许可违规,与技术手段无关。

---

## 5. 工作量与风险

| 项 | 估计 | 风险 |
|---|---|---|
| app/ 改走 Nuitka 发布 | 小(已有 job) | 低 |
| skill 加载层去源码化 | 中(3 个加载层 + 3 个服务) | 中:monkey-patch 语义在编译模块上要逐个验证 |
| circuit-skills 重名/相对导入梳理 | **大**(92 文件、11k LOC) | **高**:4 份 `ngspice_common` 唯一化易引入回归 |
| 打包/同步配置改造 | 中 | 中:漏包某模块 → 运行时 ImportError,需冒烟全覆盖 |
| 非 Python 资产 | 无法隐藏 | — |
| 全回归(80 pytest + 六标签冒烟 + 冻结包出图) | 中 | 每步都要跑,防编译破坏动态导入 |

**建议路径**:先做 **§4a(app/ Nuitka)** 拿到"自研代码已保护"的确定收益;再对
**1–2 个 skill 模块**(如 `simulate_gmoverid`)做 Nuitka 编译 + 改加载层的
**可行性 spike**,验证整条链路(编译 → import → ngspice 仍跑通 → 出图),
**通过后再决定是否全量**推进 circuit-skills 的大改。

---

## 6. 一页纸总结

- **能做到**:app/ + 全部 skill Python 走 Nuitka/Cython 原生编译 → 磁盘上
  **没有可反编译回 Python 的产物**(挡住 A、B 档攻击者)。
- **做不到**:① 防住有决心的二进制逆向(C 档,任何编译语言皆然);
  ② 隐藏 ngspice 必须读盘的网表/模型/PDK(293 个非 Python 资产,运行期必然可见)。
- **主要成本**:把"运行时 sys.path 注入源码"的 skill 加载机制改成"编译模块
  import",其中 circuit-skills 的 92 文件 / 4 份重名模块梳理是工作量与风险主体。
- **别忘了**:编译不免除 BSD-3/ASU 等**许可署名义务**,通知文件仍须随包。
