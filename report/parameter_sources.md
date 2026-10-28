| 参数名 | 来源文件 | 键路径 | 单位 | 使用模块 | 备注 |
|---|---|---|---|---|---|
| 配置读取约定 | 03_场景/config.json | _说明 | - | io/config.py | 配置来源及读取约定文本。 |
| P_LOC（概率字段） | 03_场景/config.json | table1.P_LOC | - | TODO: 待确认模块 | 公式提取未定义 P_LOC 的准确语义；它与公式提取定义的 P_f 是否相关待人工核对。 |
| P_f（撞击致死率） | 02_公式提取/公式提取.md | TODO: 待确认键路径 | - | risk/risk_matrix.py | 公式提取定义 P_f；config.json 中没有同名键。它与 table1.P_LOC 的关系待人工核对。 |
| G（重力加速度） | 03_场景/config.json；02_公式提取/公式提取.md | table1.G | m/s² | risk/risk_matrix.py | 风险模型机体运动参数。 |
| alpha/ALPHA（风险能量参数） | 03_场景/config.json；02_公式提取/公式提取.md | table1.ALPHA | J | risk/risk_matrix.py | 公式提取使用无下标 alpha；配置键与公式符号的映射待人工核对。 |
| beta/BETA（能量阈值） | 03_场景/config.json；02_公式提取/公式提取.md | table1.BETA | J | risk/risk_matrix.py | 公式提取使用无下标 beta；配置键与公式符号的映射待人工核对。 |
| 机体质量 | 03_场景/config.json；02_公式提取/公式提取.md | table1.MASS | kg | risk/risk_matrix.py | 风险模型及机体运动计算参数。 |
| 巡航速度 | 03_场景/config.json；plan.md §3.3 | table1.V_CRUISE | m/s | core/metrics.py；experiments/run.py | 公共路径风险评估的速度输入。 |
| table1 说明 | 03_场景/config.json | table1.note | - | io/config.py | 说明文本，不是数值参数。 |
| 场景平面尺寸 | 03_场景/config.json；03_场景/README.md §3 | table2.SCENE_SIZE | m | core/grid.py；io/scene.py | 平面尺寸参数。 |
| 数据栅格尺寸 | 03_场景/config.json；03_场景/README.md §3 | table2.GRID_SIZE | m | core/grid.py；risk/risk_matrix.py；io/scene.py | 与 coords.resolution 都描述空间分辨率，二者关系待人工核对。 |
| 平面栅格维度 | 03_场景/config.json；03_场景/README.md §2.1 | table2.N_I；table2.N_J | 格 | core/grid.py；risk/verify.py | 用于平面数组及边界维度。 |
| 高度下限与上限 | 03_场景/config.json；03_场景/README.md §3 | table2.H_LOW；table2.H_HIGH | m | core/grid.py；core/collision.py；algorithms/*.py | 场景高度边界。 |
| 高度层数 | 03_场景/config.json；03_场景/README.md §2.1 | table2.N_H | 层 | core/grid.py；risk/verify.py | 用于风险矩阵和建筑体素的高度维度。 |
| 搜索步长 | 03_场景/config.json；03_场景/README.md §3 | table2.STEP | m | core/grid.py；algorithms/*.py | 算法搜索节点间距。 |
| 转角上限 | 03_场景/config.json；03_场景/README.md §3；plan.md §3.3、§4 | table2.THETA_MAX | rad | core/grid.py；core/collision.py；algorithms/*.py | README 将其定义为水平航向变化约束。 |
| 综合代价权重 | 03_场景/config.json；plan.md §3.3 | table2.ALPHA1；table2.ALPHA2 | - | core/metrics.py；algorithms/rc_astar.py；algorithms/rrt_star.py；experiments/run.py | 与 table1.ALPHA 属于不同参数语义；distance_cost 的具体归一化口径待人工核对。 |
| 起点与终点坐标 | 03_场景/config.json；03_场景/README.md §3 | table2.START1；table2.GOAL1；table2.START2；table2.GOAL2 | m | io/scene.py；experiments/run.py；algorithms/*.py | 坐标按世界坐标解释。 |
| table2 任务参数说明 | 03_场景/config.json | table2.note_start2；table2.note | - | io/config.py | 说明文本；不在此复述其中的数值。 |
| 空气密度 | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.RHO | kg/m³ | risk/risk_matrix.py | 风险模型运动学参数。 |
| 高度参数 H_P | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.H_P | m | risk/risk_matrix.py | 与坠落运动和影响面积计算相关；精确物理定义按公式源核对。 |
| 半径参数 | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.R_P；supplementary.R_U | m | risk/risk_matrix.py | 风险影响面积几何参数。 |
| 阻力系数 | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.C_D_U；supplementary.C_D_P | - | risk/risk_matrix.py | 无量纲阻力系数。 |
| 参考面积 | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.S_U；supplementary.S_P | m² | risk/risk_matrix.py | 机体与降落伞运动模型参数。 |
| 时间参数 T_1 | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.T_1 | TODO: 待人工核对单位 | risk/risk_matrix.py | 公式提取涉及阶段时间符号；T_1 与公式符号的对应及单位待人工核对。 |
| 降落伞展开成功率 | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.ETA | - | risk/risk_matrix.py | 公式提取将 eta 描述为降落伞展开成功率；与 RRT* 半径上限 eta 区分。 |
| 遮蔽系数缩放与覆盖率参考 | 03_场景/config.json；03_场景/README.md §2.8 | supplementary.P_S_SCALE；supplementary.P_S_C_REF | - | risk/risk_matrix.py；risk/verify.py | 遮蔽系数范围由缩放与覆盖率参考定义；config 中没有独立的范围键。 |
| 遮蔽系数窗口宽度 | 03_场景/config.json；03_场景/README.md §2.8 | supplementary.P_S_WINDOW | 格 | risk/risk_matrix.py；risk/verify.py | 窗口在地面栅格上计算，P_s 无高度维。 |
| 伤亡面积参考量 | 03_场景/config.json；03_场景/README.md §2.6 | supplementary.A_CAS_REF | m² | risk/risk_matrix.py；risk/verify.py | README 将其作为量级锚点。 |
| alpha 与 beta 的组合字段 | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.SQRT_ALPHA_BETA | - | risk/risk_matrix.py | 字段名不能区分乘积或比值；公式提取中的根式为 alpha/beta 关系，精确映射待人工核对。 |
| 半径组合字段 | 03_场景/config.json；02_公式提取/公式提取.md | supplementary.R_PLUS_R_U | m | risk/risk_matrix.py | 配置同时存在组成半径键；此字段与组成项的关系待人工核对。 |
| 风险补充参数来源说明 | 03_场景/config.json | supplementary.source | - | io/config.py | 来源说明文本。 |
| 遮蔽系数说明 | 03_场景/config.json；03_场景/README.md §2.8 | supplementary.P_s_note | - | risk/risk_matrix.py；risk/verify.py | 描述覆盖率窗口和边界处理的数据契约。 |
| 伤亡面积说明 | 03_场景/config.json；03_场景/README.md §2.6 | supplementary.A_CAS_note | - | risk/risk_matrix.py；risk/verify.py | 描述参考量的用途。 |
| 城市生成随机种子 | 03_场景/config.json；03_场景/README.md §1 | citygen.RANDOM_SEED | - | TODO: 待确认模块 | 场景生成用途；规划书未指定城市生成器的目标模块。 |
| 清空半径 | 03_场景/config.json | citygen.CLEAR_RADIUS | m | TODO: 待确认模块 | 场景生成参数；规划书未指定城市生成器的目标模块。 |
| 建筑尺寸范围 | 03_场景/config.json | citygen.BUILDING_SIZE_RANGE | m | TODO: 待确认模块 | 场景生成参数；规划书未指定城市生成器的目标模块。 |
| 噪声分辨率 | 03_场景/config.json | citygen.NOISE_RES | TODO: 待人工核对单位 | TODO: 待确认模块 | 配置与 README 未说明该分辨率采用的长度或采样计数单位。 |
| 人口密度上限 | 03_场景/config.json；03_场景/README.md §2.1 | citygen.POP_MAX | 人/m² | TODO: 待确认模块 | README 定义 pop_density 输出单位；场景生成器的目标模块未在规划书中指定。 |
| 建筑密度调节因子 | 03_场景/config.json | citygen.BUILDING_DENSITY_FACTOR | - | TODO: 待确认模块 | 场景生成参数；规划书未指定城市生成器的目标模块。 |
| 道路与边界调节因子 | 03_场景/config.json | citygen.ROAD_BOOST；citygen.BOUNDARY_BOOST | - | TODO: 待确认模块 | 场景生成参数；规划书未指定城市生成器的目标模块。 |
| 主干道数量 | 03_场景/config.json | citygen.AVENUE_COUNT | 条 | TODO: 待确认模块 | 场景生成参数；规划书未指定城市生成器的目标模块。 |
| 主干道宽度 | 03_场景/config.json | citygen.AVENUE_WIDTH | m | TODO: 待确认模块 | 场景生成参数；规划书未指定城市生成器的目标模块。 |
| 区域类型权重 | 03_场景/config.json | citygen.REGION_PARAMS.commercial.weight；citygen.REGION_PARAMS.residential.weight；citygen.REGION_PARAMS.industrial.weight；citygen.REGION_PARAMS.suburban.weight；citygen.REGION_PARAMS.park.weight；citygen.REGION_PARAMS.plaza.weight | - | TODO: 待确认模块 | 区域生成权重；规划书未指定城市生成器的目标模块。 |
| 区域覆盖率范围 | 03_场景/config.json | citygen.REGION_PARAMS.commercial.coverage；citygen.REGION_PARAMS.residential.coverage；citygen.REGION_PARAMS.industrial.coverage；citygen.REGION_PARAMS.suburban.coverage；citygen.REGION_PARAMS.park.coverage；citygen.REGION_PARAMS.plaza.coverage | - | TODO: 待确认模块 | 区域覆盖率为比例；规划书未指定城市生成器的目标模块。 |
| 区域建筑高度范围 | 03_场景/config.json | citygen.REGION_PARAMS.commercial.height；citygen.REGION_PARAMS.residential.height；citygen.REGION_PARAMS.industrial.height；citygen.REGION_PARAMS.suburban.height；citygen.REGION_PARAMS.park.height；citygen.REGION_PARAMS.plaza.height | m | TODO: 待确认模块 | 建筑高度用于场景体素化；规划书未指定城市生成器的目标模块。 |
| 区域人口密度 | 03_场景/config.json；03_场景/README.md §2.1 | citygen.REGION_PARAMS.commercial.density；citygen.REGION_PARAMS.residential.density；citygen.REGION_PARAMS.industrial.density；citygen.REGION_PARAMS.suburban.density；citygen.REGION_PARAMS.park.density；citygen.REGION_PARAMS.plaza.density | TODO: 待人工核对单位 | TODO: 待确认模块 | 需确认这些生成参数如何映射到 README 定义的 pop_density；规划书未指定城市生成器的目标模块。 |
| 城市生成说明 | 03_场景/config.json | citygen.note | - | TODO: 待确认模块 | 说明文本；生成器目标模块未在规划书中指定。 |
| 数组索引顺序 | 03_场景/config.json；03_场景/README.md §2.1、§3 | coords.axes_order | - | core/grid.py；io/scene.py；risk/verify.py | R 与建筑数据的索引顺序契约。 |
| 坐标映射约定 | 03_场景/config.json；03_场景/README.md §3 | coords.convention | - | core/grid.py；io/scene.py | 索引到世界坐标的映射说明。 |
| 世界坐标原点 | 03_场景/config.json；03_场景/README.md §3 | coords.origin | m | core/grid.py；io/scene.py | 坐标变换输入。 |
| 坐标分辨率 | 03_场景/config.json；03_场景/README.md §3 | coords.resolution | m | core/grid.py；io/scene.py；risk/risk_matrix.py | 与 table2.GRID_SIZE 都描述空间分辨率，二者关系待人工核对。 |
| 路径解析说明 | 03_场景/config.json | paths.NOTE | - | io/scene.py | 配置写明路径基准；与当前配置所在目录的相对关系待人工核对。 |
| 场景目录名 | 03_场景/config.json；03_场景/README.md §1 | paths.scene_A；paths.scene_B | - | io/scene.py；experiments/run.py | 场景标识符。 |
| 城市数据路径模板 | 03_场景/config.json | paths.city_npz | - | io/scene.py | 与 scenes.A.file、scenes.B.file 存在路径描述重叠，实际解析优先级待人工核对。 |
| 风险切片目录模板 | 03_场景/config.json；03_场景/README.md §1 | paths.slices_dir | - | io/scene.py；risk/verify.py | 校验参考数据路径。 |
| 场景切换说明 | 03_场景/config.json | paths.pattern | - | io/scene.py；experiments/run.py | 路径模板说明文本。 |
| 场景名称 | 03_场景/config.json；03_场景/README.md §1 | scenes.A.name；scenes.B.name | - | io/scene.py；experiments/run.py | 结果元数据与场景标识。 |
| 场景数据文件路径 | 03_场景/config.json | scenes.A.file；scenes.B.file | - | io/scene.py；experiments/run.py | 与 paths.city_npz 的路径描述重叠，实际解析优先级待人工核对。 |
| 场景数据来源 | 03_场景/config.json；03_场景/README.md §2.1 | scenes.A.provenance；scenes.B.provenance | - | io/scene.py；report/data_validation.md | 场景来源元数据。 |
| 场景 A 中心纬度 | 03_场景/config.json | scenes.A.window_center_lat | 十进制度 | io/scene.py；report/data_validation.md | 地理坐标元数据。 |
| 场景 A 中心经度 | 03_场景/config.json | scenes.A.window_center_lon | 十进制度 | io/scene.py；report/data_validation.md | 地理坐标元数据。 |
| 场景建筑数量统计 | 03_场景/config.json；03_场景/README.md §4 | scenes.A.n_buildings；scenes.B.n_buildings | 个 | io/scene.py；risk/verify.py；report/data_validation.md | 场景统计元数据。 |
| 地面建筑覆盖比例 | 03_场景/config.json；03_场景/README.md §4 | scenes.A.building_ratio；scenes.B.building_ratio | - | io/scene.py；risk/verify.py；report/data_validation.md | 比例统计，不是建筑碰撞数据本身。 |
| 建筑体素占比 | 03_场景/config.json；03_场景/README.md §4 | scenes.A.voxel_ratio；scenes.B.voxel_ratio | - | io/scene.py；risk/verify.py；report/data_validation.md | 体素统计元数据。 |
| 场景 B 生成器说明 | 03_场景/config.json | scenes.B.generator | - | TODO: 待确认模块 | 配置为生成器说明文本；规划书未指定对应目标模块。 |
| 场景 B 随机种子 | 03_场景/config.json | scenes.B.seed | - | TODO: 待确认模块 | 场景元数据；与 citygen.RANDOM_SEED 的关系待人工核对。 |
| 统一邻域规则 | plan.md §4、§6 | TODO: 待确认键路径 | - | core/grid.py；algorithms/*.py | 规划书要求公共邻域生成；config.json 中没有对应键。 |
| 风险率 R 的单位 | 03_场景/README.md §2.2；plan.md §3.3 | TODO: 待确认键路径 | h^-1 | risk/risk_matrix.py；core/metrics.py | README 将 R 定义为每飞行小时风险；风险单位应与小时制评估一致。 |
| 建筑格语义与 R 中的表示 | 03_场景/README.md §2.1、§6；plan.md §3.3 | TODO: 待确认键路径 | - | io/scene.py；core/collision.py；risk/risk_matrix.py | README 规定碰撞使用 building_mask，建筑体素在 R 中为 NaN；该语义不是 config.json 参数键。 |
| R 形状 | 03_场景/README.md §2.1、§6；plan.md §3.1 | table2.N_I；table2.N_J；table2.N_H | 格 | risk/risk_matrix.py；risk/verify.py；io/scene.py | 由配置维度键与 README 数据契约共同确定；config.json 没有独立的 R.shape 键。 |
| R 索引顺序 | 03_场景/README.md §2.1、§3、§6 | coords.axes_order | - | core/grid.py；risk/risk_matrix.py；risk/verify.py | README 定义的数组索引契约。 |
| R_norm | 派生：03_场景/README.md §2.7；plan.md §3.3 | 不来自 config | h^-1 | core/metrics.py；risk/verify.py | 场景风险统计派生量；summary.json 中有校验参考值，但不是配置键。 |
| t_hour | 派生：plan.md §3.3 | 不来自 config | h | core/metrics.py | 路径段距离和巡航速度派生的飞行时间。 |
| 归一化风险代价 | 派生：plan.md §3.3；02_公式提取/公式提取.md | 不来自 config | h | core/metrics.py | 使用 R_seg、R_norm 与 t_hour；公式提取文件未列出路径评价公式，来源口径待人工核对。 |
| 综合代价 | 派生：plan.md §3.3 | 不来自 config | TODO: 待人工核对单位 | core/metrics.py；experiments/run.py | 使用 table2 权重与 distance_cost、归一化风险代价；distance_cost 的具体尺度及组合单位待人工核对。 |
| RiskA* 启发式系数 | plan.md §4、§6 | TODO: 待确认键路径 | - | algorithms/risk_astar.py | 规划书要求记录的算法参数；config.json 中没有对应键。 |
| RiskA* 风险裁剪下界 | plan.md §4、§6 | TODO: 待确认键路径 | - | algorithms/risk_astar.py | 规划书要求的数值稳定/裁剪参数；config.json 中没有对应键。 |
| RRT* 重连半径系数 | plan.md §4、§6 | TODO: 待确认键路径 | TODO: 待人工核对单位 | algorithms/rrt_star.py | 规划书要求按自由空间估计；config.json 中没有对应键。 |
| RRT* 半径上限参数 eta | plan.md §4、§6 | TODO: 待确认键路径 | m | algorithms/rrt_star.py | 与 supplementary.ETA（降落伞展开成功率）同名但语义不同；缺少单独配置键，待人工核对。 |
| 采样算法时间预算 | plan.md §3.2、§5、§6 | TODO: 待确认键路径 | s | experiments/run.py；algorithms/rrt_star.py；algorithms/informed_rrt_star.py | 规划书要求统一截止时间；config.json 中没有实验预算键。 |
| 采样算法迭代预算 | plan.md §3.2、§5、§6 | TODO: 待确认键路径 | 次 | experiments/run.py；algorithms/rrt_star.py；algorithms/informed_rrt_star.py | 规划书要求记录统一最大迭代预算；config.json 中没有实验预算键。 |
| 随机算法种子策略 | plan.md §5、§6 | TODO: 待确认键路径 | - | experiments/run.py | 规划书要求可复现的采样运行；config.json 中没有算法实验 seed 集合键。 |

### 1. 缺失项

- 搜索邻域规则没有对应的 config.json 键；来源为 plan.md 的算法实现要求。
- 规划书要求的采样算法时间预算、最大迭代预算和实验随机种子策略没有对应的 config.json 键。
- 规划书涉及的 RiskA* 启发式系数、风险裁剪下界，以及 RRT* 重连半径系数和半径上限没有对应的 config.json 键。
- 建筑格在 R 中的 NaN 语义、R 的显式 shape 键不存在于 config.json；README 提供了数据契约，shape 可由维度参数对应。
- config.json 没有单独的 P_s 范围键；范围语义见 P_S_SCALE、P_S_C_REF 及 README 的遮蔽系数契约。
- config.json 没有路径评价公式的独立参数键；plan.md 给出派生量口径，02_公式提取/公式提取.md 未包含完整的路径代价公式。

### 2. 待人工核对

- P_LOC 的准确语义以及是否对应任务要求中的失效概率；对应表格行的使用模块标为 TODO。
- table1.ALPHA、table1.BETA 与公式提取中的 alpha、beta 符号映射；公式提取未提供下标 j。
- supplementary.T_1 与运动学阶段时间符号的映射和单位。
- supplementary.SQRT_ALPHA_BETA 的字段名与公式根式含义是否一致。
- supplementary.R_PLUS_R_U 与 supplementary.R_P、supplementary.R_U 的关系。
- supplementary.ETA 与规划书 RRT* 半径公式中 eta 的同名异义，以及缺少独立配置键的问题。
- table2.GRID_SIZE 与 coords.resolution 的关系；paths.city_npz 与 scenes.A.file、scenes.B.file 的路径优先级；paths.NOTE 所述路径基准与当前目录结构的对应关系。
- citygen.NOISE_RES 的单位；citygen.REGION_PARAMS 各 density 字段与 pop_density 单位及生成映射；所有 citygen 字段的目标模块尚未由规划书指定。
- scenes.B.seed 与 citygen.RANDOM_SEED 的关系。
- distance_cost 的精确公式、归一化尺度，以及综合代价的单位一致性。
- 表中标注 TODO 的单位和模块项：supplementary.T_1、citygen.NOISE_RES、citygen.REGION_PARAMS.*.density、RiskA* 重连半径系数、综合代价；以及 P_LOC、citygen 各生成参数、场景 B 生成器/种子等使用模块。

### 3. 派生量公式

- R_norm = min(r_mean, r_median)；实现模块：core/metrics.py；不来自 config。
- t_hour = d / (V_CRUISE × 3600)；实现模块：core/metrics.py；不来自 config。
- 归一化风险代价 = (R_seg / R_norm) × t_hour；实现模块：core/metrics.py；不来自 config。
- 综合代价 = ALPHA1 × distance_cost + ALPHA2 × normalized_risk_cost；实现模块：core/metrics.py；不来自 config。

### 4. A/B/C 分层核验

| 层级 | 核验项 | 结论 | 依据与说明 |
|---|---|---|---|
| A：来源与键路径 | `config.json` 的实际叶子键是否全部出现在映射表 | PASS | 已按 `config.json` 实际层级核对；数组键按完整路径保留，未把值当作来源。 |
| A：来源与键路径 | `P_LOC` 的来源是否仅指向配置文件 | PASS | `P_LOC` 仅在 `03_场景/config.json` 出现；`02_公式提取/公式提取.md` 未定义该字段。 |
| A：来源与键路径 | 公式提取定义的 `P_f` 是否单列且不伪造 config 键 | PASS | `02_公式提取/公式提取.md` 公式(9)定义 `P_f`；表中使用 `TODO: 待确认键路径`，不把它写成 config 键。 |
| A：来源与键路径 | `alpha/ALPHA`、`beta/BETA` 的键映射 | TODO | 公式提取使用无下标 `alpha`、`beta`，配置使用大写键；符号对应尚需人工确认。 |
| A：来源与键路径 | 派生量是否与 config 键分离 | PASS | `R_norm`、`t_hour`、归一化风险代价和综合代价均标记为“不来自 config”。 |
| B：单位与数据契约 | 场景尺寸、栅格分辨率、高度范围、层数、起终点单位 | PASS | `03_场景/README.md` §3 明确世界坐标和空间分辨率；表中分别标为 `m` 或离散计数。 |
| B：单位与数据契约 | 搜索步长和水平转角单位 | PASS | README §3 将步长定义为长度，将 `THETA_MAX` 定义为水平航向变化；表中转角标为 `rad`。 |
| B：单位与数据契约 | 邻域规则来源 | TODO | plan.md §4、§6要求公共26邻域，但 `config.json` 没有邻域键；应作为设计契约单独核对。 |
| B：单位与数据契约 | `P_s` 的连续覆盖率、窗口和无高度维语义 | PASS | README §2.8给出覆盖率窗口、边界处理和 `P_s` 无高度维；表中由 `P_S_SCALE`、`P_S_C_REF`、`P_S_WINDOW`承载。 |
| B：单位与数据契约 | `R` 的形状、索引顺序、建筑格 NaN 和碰撞语义 | PASS | README §2.1、§3、§6明确 `R` 的三维形状、`[i,j,h_idx]` 顺序、建筑格为 NaN，碰撞使用 `building_mask`。 |
| B：单位与数据契约 | 风险率与小时制 | PASS | README §2.2给出每飞行小时风险单位；plan.md §3.3明确 `t_hour` 使用小时制。 |
| B：单位与数据契约 | `T_1` 与公式阶段时间的单位和映射 | TODO | 配置存在 `supplementary.T_1`，公式提取描述阶段时间符号，但未建立两者直接映射。 |
| C：模块与执行准备 | 公共网格、碰撞和评估模块的目标边界 | PASS | plan.md §3、§6将坐标、碰撞、邻域和指标集中到 `core`，风险矩阵集中到 `risk`。 |
| C：模块与执行准备 | RiskA* 参数、RRT* 重连参数的来源 | FAIL | plan.md §4、§6要求这些参数，但 `config.json`没有对应键，不能形成可追溯来源。 |
| C：模块与执行准备 | 采样预算和算法种子的位置 | TODO | plan.md要求统一时间/迭代预算和种子；它们应进入实验配置，但当前未见对应配置文件或键。 |
| C：模块与执行准备 | 综合代价的 `distance_cost` 尺度和单位 | TODO | plan.md §3.3给出组合关系，但 `02_公式提取/公式提取.md`未给出完整路径代价尺度；需要人工确认后才能验证实现。 |
| C：模块与执行准备 | 是否满足 M1 风险矩阵验证前置条件 | FAIL | 风险参数语义、阶段时间映射和评估单位仍有未决项；见“危险项”和 M1 阻断结论。 |

### 5. 六项危险项逐项结论

| 编号 | 危险项 | 结论 | 依据与影响 |
|---|---|---|---|
| D1 | `P_LOC` 与公式提取的 `P_f` 是否为同一概率 | FAIL：来源语义未闭合 | `P_LOC`仅在 `03_场景/config.json`出现；`02_公式提取/公式提取.md` §一公式(9)定义的是 `P_f`。两者关系未知，不能把一个替代另一个。阻断风险参数链核验。 |
| D2 | `alpha/ALPHA`、`beta/BETA` 及组合缓存字段的映射 | TODO：符号可对照，键语义未最终确认 | 公式提取 §一和 §二使用无下标 `alpha`、`beta`；配置另有 `SQRT_ALPHA_BETA`。若映射或缓存语义错位，会影响致死率和能量分支。 |
| D3 | `T_1` 与运动学阶段时间的映射 | TODO：单位和公式对应未确认 | 配置有 `supplementary.T_1`；公式提取 §3.2.2描述 `t1`、`t2` 和分阶段运动，但未声明 `T_1`对应哪个时间。风险矩阵中间量无法仅凭当前来源复核。 |
| D4 | `ETA` 的同名异义 | FAIL：必须拆分语义 | 公式提取 §4.1将 `eta`作为降落伞展开成功率；plan.md §4将 RRT* 公式中的 `eta`作为重连半径上限。当前仅有 `supplementary.ETA`，不能让两个模块共享同一来源。阻断算法参数审计，虽不单独阻断 M1。 |
| D5 | 坐标、分辨率、`R` 索引及建筑格语义 | PASS：数据契约明确，实施仍需验证 | README §2.1、§3、§6明确 `building_mask`、`R` 形状、`[i,j,h_idx]` 索引和建筑格 NaN；`table2.GRID_SIZE`与`coords.resolution`的重复关系仍需人工确认。 |
| D6 | 风险小时制、归一化风险代价与综合代价尺度 | TODO：风险时间单位已明确，距离项尺度未闭合 | plan.md §3.3明确 `t_hour`和归一化风险代价，README §2.2明确风险率单位；但 `distance_cost` 的完整来源和综合代价单位尚未在公式提取中闭合，不能据此验收公共评估器。 |

### 6. 缺失项分类

| 项目 | 分类 | 结论 | 依据与后续边界 |
|---|---|---|---|
| 公共26邻域规则 | DESIGN | 不属于场景 config 参数 | plan.md §4、§6把邻域作为公共搜索设计；应由 `core/grid.py`固定并测试，不应从缺失的场景键猜值。 |
| `R` 形状、索引顺序、建筑格 NaN 语义 | DESIGN | 属于 README 数据契约 | README §2.1、§3、§6已给出契约；不需要另造 config 键，但必须在 M1 校验。 |
| `P_s` 范围与窗口语义 | DESIGN | 由现有遮蔽参数和 README 协议派生 | README §2.8已给出连续覆盖率、窗口和无高度维语义；没有独立范围键不是缺漏。 |
| 采样时间预算、迭代预算和算法 seed 集合 | DESIGN | 应放在实验配置而非场景配置 | plan.md §5、§6要求实验矩阵和预算；其来源边界应由 `experiments/configs/`定义。 |
| `P_f` 与 `P_LOC` 的对应键/语义 | MISSING | 风险概率来源没有闭合映射 | 公式提取定义 `P_f`，配置只出现 `P_LOC`；需要人工确认是否同义或分别建模。 |
| RiskA* 启发式系数与风险裁剪下界 | MISSING | 规划书要求但当前 config 没有来源键 | plan.md §4、§6要求记录这些算法参数；不能把规划书中的描述直接当作 config 来源。 |
| RRT* 重连半径系数与半径上限 | MISSING | 规划书要求但当前 config 没有独立来源键 | plan.md §4、§6要求 `gamma`、`eta`；`supplementary.ETA`已有风险模型语义，不能复用。 |
| `distance_cost` 的完整来源和尺度 | MISSING | 综合代价实现所需口径未闭合 | plan.md §3.3要求公共评估器使用它，公式提取文件没有完整路径代价定义。 |
| `P_f` 表格行 | OMITTED（已修正） | 原映射表曾遗漏公式提取定义的 `P_f` | 已在当前表中新增单独行，仍保留与 `P_LOC`关系待核对。 |
| `building_mask`、`pop_density`、`building_footprint` 的数据键行 | OMITTED（审计记录） | 当前表以建筑语义概括，未逐一列出 city.npz 数据键 | README §2.1给出三个数据键；它们不是 config 键，但应在数据验证记录中逐项引用。 |

### 7. M1 阻断结论

能否进 M1：不能。当前阻断项为：`P_LOC` 与公式提取 `P_f` 的关系未确认；`alpha/ALPHA`、`beta/BETA` 及组合缓存字段的映射未确认；`T_1` 的单位和阶段时间对应未确认；公共评估器的 `distance_cost` 尺度和综合代价单位未闭合。`ETA` 同名异义、RiskA* 参数、RRT* 参数及采样预算属于后续算法/实验阶段阻断项，不应在 M1 中静默代用。
