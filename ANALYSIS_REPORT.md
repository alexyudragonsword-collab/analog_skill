# gmoverid-skill 仓库分析报告

来源仓库：https://github.com/Arcadia-1/gmoverid-skill
分析日期：2026-07-05

## 仓库概览

**gmoverid-skill**（Arcadia-1）不是一个常规软件应用，而是一套 **Claude Code Skills 包**——面向"用 AI Agent 做模拟电路设计与仿真"的场景。仓库开发周期约 2026-03-08 至 2026-05-25，20 次提交，6.5MB，License 声明 MIT（但仓库中**并无实际 LICENSE 文件**，只有 README 上的徽章）。

结构上是三个独立但可组合的 skill，每个都遵循 Claude Code skill 的标准格式（`SKILL.md` + `assets/` + `references/`）：

| Skill | 定位 | 内容 |
|---|---|---|
| **ngspice** | 入门 | 9 个标准 SPICE 教学案例（DC/AC/瞬态/噪声），~1900 行 Python |
| **gmoverid** | 进阶 | gm/ID 表征仿真 + 晶体管尺寸设计 API，~2500 行 Python |
| **transistor-models** | 模型库 | ASU PTM 模型全集（体硅 65-180nm，HP/LP 22-45nm，FinFET 7-20nm） |

## 技术实现分析

**架构模式统一**：每个仿真案例都拆成 `simulate_*.py`（跑 ngspice + 解析数据）→ `plot_*.py`（matplotlib 绘图）→ `run_*.py`（编排入口）三段式，命名规范一致（`dc_`/`ac_`/`tran_`/`noise_` 前缀），路径全部用 `Path(__file__).resolve().parent` 自动解析，避免了硬编码路径的常见坑。

**核心亮点 —— `design_gmoverid.py` 的 `GmIdTable` 类**：
- 实现了模拟集成电路设计中经典的 **gm/ID 方法学**（区别于传统的长沟道方程近似，在先进工艺节点下更准确）
- 用 JSON 做仿真结果缓存（按 model/W/L/Vds 做文件名 hash），首次调用触发 ngspice 仿真，之后 ~0.05s 从缓存读取
- gds 通过对同一 Vgs 扫描做**有限差分**（vds 和 vds+50mV 两次扫描相减）获取，而非稀疏 Vds 扫描插值，这个设计注释里说明是为了消除插值扭结（kink）——说明作者对仿真数据质量有较深考虑
- 提供 `lookup()`/`size()`/`size_from_ft()`/`size_from_gmro()` 等直觉化 API，配合详细的设计示例（45nm HP 共源放大器，从指标推导到 W/L 尺寸的完整手算+验证流程）

**自验证机制**：`validate_gmoverid.py` 有 5 项数值自检（弱反型极限、单调性、沟长调制、fT 峰值位置、Vds 敏感度），另外 SKILL.md 里专门写了给 LLM 看图做物理判读的 checklist（每个象限图的预期趋势/红旗信号）——这是比较少见的"面向 Agent 消费者"的自文档化设计。

## 亮点

1. **面向 Agent 而非人类的文档设计**：README 明确写"如果你是 Agent，跳过图片直接看 Installation"，SKILL.md 里有"不要修改 skill 文件"的告诫、"生成图表存到用户项目目录而非 `.claude/`"等约束，体现了对 Claude Code skill 生态使用方式的深刻理解。
2. **单元与坐标系约定详尽**：例如强制要求 axis label 用 ASCII+LaTeX、避免 `µ` 符号在某些字体下无法渲染、gm/ID 折返曲线的 `_fall_mask` 处理等，都是实战踩坑后沉淀的经验。
3. **中英文双语 README**，中文用户友好。

## 潜在问题

1. **LICENSE 缺失**：README 声明 MIT license 但仓库根目录没有 LICENSE 文件，实际可能存在版权风险（尤其模型文件本身来自 ASU PTM，有学术引用要求，不能直接按 MIT 分发）。
2. **依赖外部系统程序 ngspice**：仓库本身不能独立运行，需要用户系统预装 ngspice，安装说明较复杂（有专门的 Windows 章节和中国大陆 pip 镜像 fallback）。
3. **无自动化测试/CI**：`validate_gmoverid.py` 是运行时自检脚本而非 pytest 单元测试，仓库没有 GitHub Actions 或测试框架，代码正确性依赖运行者手动执行验证脚本。
4. **代码里较多硬编经验参数**（如 fT 范围、gm·ro 典型值等经验判据）散落在 SKILL.md 文档中而非配置文件，扩展新工艺节点需要同时改 3 处（`.lib` 复制、`MODEL_INFO` 字典、`NODE_CFG`），文档里虽有说明但容易遗漏一处。

## 总结

这是一个专业度较高、针对模拟IC设计教学/预研场景打造的 **Claude Code Skill 扩展包**，核心价值在于把 gm/ID 设计方法学工程化并适配给 AI Agent 使用。代码质量整体不错（模块化、路径处理健壮、有自验证机制），主要短板是许可证文件缺失和缺乏自动化测试。适合需要在没有真实 PDK 的情况下用 Agent 做模拟电路仿真教学或早期方案探索的场景。
