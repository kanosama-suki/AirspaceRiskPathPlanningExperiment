# 参数来源审计记录

本条目为只读来源审计记录。核查对象为 `lib/03_场景/config.json`、`lib/03_场景/README.md`、`lib/02_公式提取/公式提取.md` 和 `plan.md` 的 §3.3、§4、§6。未修改上述输入文件，也未把审计判断写回配置。

## 六项危险项

| 编号 | 危险项 | 结论 | 依据与影响 |
|---|---|---|---|
| D1 | `P_LOC` 与公式提取的 `P_f` 是否为同一概率 | FAIL：来源语义未闭合 | `P_LOC` 只在 `config.json` 出现；`公式提取.md` §一公式(9)定义 `P_f`。不能把一个概率字段静默替代另一个，风险参数链被阻断。 |
| D2 | `alpha/ALPHA`、`beta/BETA` 及组合缓存字段的映射 | TODO：符号可对照，键语义未最终确认 | `公式提取.md` §一和 §二使用无下标 `alpha`、`beta`，配置另有 `SQRT_ALPHA_BETA`；映射错误会影响致死率和能量分支。 |
| D3 | `T_1` 与运动学阶段时间的映射 | TODO：单位和公式对应未确认 | `config.json` 有 `supplementary.T_1`；`公式提取.md` §3.2.2描述 `t1`、`t2`，但没有声明 `T_1`对应哪个阶段时间。 |
| D4 | `ETA` 的同名异义 | FAIL：必须拆分语义 | `公式提取.md` §4.1中的 `eta`是降落伞展开成功率；`plan.md` §4中的 RRT* `eta`是重连半径上限。当前没有独立的 RRT* 来源键。 |
| D5 | 坐标、分辨率、`R` 索引及建筑格语义 | PASS：数据契约明确，实施仍需验证 | `README.md` §2.1、§3、§6明确 `building_mask`、`R` 的形状、`[i,j,h_idx]`索引和建筑格 NaN；`GRID_SIZE`与`coords.resolution`的重复关系仍需人工确认。 |
| D6 | 风险小时制、归一化风险代价与综合代价尺度 | TODO：时间单位明确，距离项尺度未闭合 | `README.md` §2.2和 `plan.md` §3.3支持小时制与 `t_hour`；`distance_cost`的完整来源和综合代价单位尚未由公式提取文件闭合。 |

## 缺失项分类

| 项目 | 分类 | 结论 | 依据与后续边界 |
|---|---|---|---|
| 公共邻域规则 | DESIGN | 属于公共搜索设计，不是场景 config 参数 | `plan.md` §4、§6要求公共邻域；应由 `core/grid.py`固定并测试。 |
| `R` 形状、索引顺序、建筑格 NaN 语义 | DESIGN | 属于 README 数据契约 | `README.md` §2.1、§3、§6已有契约，需校验，不应猜造 config 键。 |
| `P_s` 范围和窗口语义 | DESIGN | 由现有遮蔽参数和 README 协议派生 | `README.md` §2.8描述覆盖率、窗口和无高度维语义。 |
| 采样时间预算、迭代预算和 seed 集合 | DESIGN | 应放在实验配置，不应塞入场景配置 | `plan.md` §5、§6要求实验矩阵、预算和种子；边界应由 `experiments/configs/`定义。 |
| `P_f` 与 `P_LOC` 的对应键/语义 | MISSING | 风险概率来源没有闭合映射 | `公式提取.md`定义 `P_f`，`config.json`只出现 `P_LOC`；需要人工确认是否同义或分别建模。 |
| RiskA* 启发式系数与风险裁剪下界 | MISSING | 规划书要求但没有当前 config 来源键 | `plan.md` §4、§6要求记录这些算法参数，不能直接把描述当作来源键。 |
| RRT* 重连半径系数与半径上限 | MISSING | 规划书要求但没有独立来源键 | `plan.md` §4、§6要求 `gamma`、`eta`；不能复用风险模型 `supplementary.ETA`。 |
| `distance_cost` 的完整来源和尺度 | MISSING | 综合代价实现口径未闭合 | `plan.md` §3.3要求公共评估器使用它，但 `公式提取.md`未给出完整路径代价定义。 |
| `P_f` 映射表行 | OMITTED（已修正） | 原参数映射曾漏列公式提取定义的 `P_f` | 已在 `report/parameter_sources.md`新增单独行，仍保留与 `P_LOC`关系待核对。 |
| `building_mask`、`pop_density`、`building_footprint` 数据键 | OMITTED（审计记录） | 原表按建筑语义概括，未逐一列出 city.npz 键 | `README.md` §2.1列出三个数据键；它们不是 config 键，但需在数据验证记录中逐项引用。 |

## M1 阻断结论

能否进 M1：不能。阻断项为：`P_LOC` 与 `P_f` 的关系未确认；`alpha/ALPHA`、`beta/BETA`及组合缓存字段映射未确认；`T_1` 的单位和阶段时间对应未确认；公共评估器的 `distance_cost` 尺度和综合代价单位未闭合。`ETA` 同名异义、RiskA* 参数、RRT* 参数及采样预算属于后续算法或实验阶段阻断项，不应在 M1 中静默代用。
