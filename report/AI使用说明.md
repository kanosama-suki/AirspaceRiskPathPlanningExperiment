# AI 使用说明

## 本次 M1 验收工作（2026-10-29）

- **Agent / 模型：** Codex，GPT-6 系列模型。
- **参与环节：** 阅读项目规则和校验实现；核对现有 A/B 全量校验 JSON 与场景 README；修改 `src/risk/verify_r.py` 的已知差异接受条件；更新 `report/assumptions.md`、M1 验收记录和项目状态。
- **人工提供的任务约束：** 不改风险公式、不碰算法、不修改输入文件；B 的 `1.1447%` 中位数差异只按基准精度限制接受，不能写成计算通过；未显式接受时保留严格失败行为。
- **人工核查：** 本地代码读取 `experiments/validation/validation_A.json`、`experiments/validation/validation_B.json`、A/B `summary.json` 和 README；确认 shape、NaN/finite 计数、窗口/探针工程容差状态及 B summary mismatch 键。桶边界和计数未出现在 summary 中，因此没有补造分桶或声称复算通过。
- **采用的 AI 输出：** `verify_r.py` 的显式 `--accept-known-diff` 开关与窄条件判断；assumptions 中的 M1 接受口径；`report/m1_acceptance.md` 中基于本地校验结果的验收记录。
- **拒绝/保留事项：** 未将 B 的 `r_median` / `r_norm` 从 MISMATCH 改成 PASS；未放宽 README 的 1% 统计容差；未改公式、场景输入或生成全量 R 数据文件。
- **验证：** 本地 full 校验在不带接受开关时返回 `1`；带 `--accept-known-diff` 时返回 `0` 并保留 B summary MISMATCH。`python -m pytest -q` 为 `10 passed`，模块编译检查通过。
- **截图索引：** 本次文本任务未采集交互截图，无截图文件可列。
- **验证原则：** 最终统计和验收状态以本地 Python 程序及其全量校验 JSON 为依据；AI 未代替实验运行或生成风险数据。

## 本次实验产物目录整理（2026-10-29）

- **参与环节：** 按项目目录约定归位场景采集记录、检查脚本日志、机器可读校验结果和人工诊断说明；调整相关脚本的默认输出目录；更新 `structure.md` 和现有路径引用。
- **人工提供的任务约束：** `experiments/raw/` 保存真实运行记录和场景采集结果；`experiments/validation/` 保存检查脚本输出；`report/` 保存人工整理的说明和结论；只读输入资料保持不变。
- **采用的 AI 输出：** 检查脚本默认目录调整、既有产物归档和结构索引更新。场景采集记录 `inspect_A/B.txt` 仍留在 `experiments/raw/`；校验日志及 JSON 位于 `experiments/validation/`；诊断和验收说明位于 `report/`。
- **验证：** `python -m pytest -q` 为 `10 passed`；`python -m compileall -q src tests` 成功；五个采集/校验脚本的 `--help` 均正常；只读输入目录的 Git diff 无输出。
- **变更范围：** 未改写场景数组、论文、公式或任务书；调整了 P_s 校验器，使其只写验证日志，不自动追加人工维护的 assumptions 文档。

## 本次 M2 公共层接入真实 R（2026-10-29）

- **Agent / 模型：** Codex，GPT-6 系列模型。
- **参与环节：** 按中文实施计划实现只读场景加载器、统一规划请求/结果接口、真实 R 切片指标测试和 A/B 直线数据流冒烟；扩展 metrics 以复用场景精确 `R_norm` 并输出未归一化风险积分。
- **人工提供的任务约束：** 不写五算法、不修改风险公式和场景输入、不把穿建筑路线记作有效结果；只做真实数据流与接口冒烟。
- **采用的 AI 输出：** `src/io/scene.py` 从 config 相对路径加载城市数组并生成 R 或读取显式缓存；`src/core/types.py` 定义 `PlanRequest`、`PathResult`、`PlannerBase` 和空注册表；`src/experiments/smoke_dataline.py` 依次处理 A/B 各两组任务；`tests/test_scene_metrics.py` 对真实 R 小切片做手算比对。
- **实际验证：** `python -m pytest tests/ -q` 为 `18 passed`。A/B 的 shape 和 NaN/finite 数与契约一致。四条直线均穿越建筑并命中 NaN，转角检查无违规；因此日志保留长度和飞行时间，风险积分与综合代价如实记为 INVALID，没有将 NaN 当成零风险。
- **结果位置：** `experiments/raw/smoke_dataline_A.txt`、`experiments/raw/smoke_dataline_B.txt`；中文计划位于 `docs/superpowers/plans/2026-10-29-m2-public-layer.md`。
- **变更边界：** 未修改 `src/risk/risk_matrix.py`、`src/algorithms/`、论文、公式、场景和任务书。冒烟结果只验证数据流，不用于算法排名或性能结论。

## 本次标准 A* 实现与冒烟（2026-10-29）

- **Agent / 模型：** Codex，GPT-6 系列模型。
- **参与环节：** 按项目规范撰写中文实施计划；实现标准 A*，复用公共网格、坐标、碰撞与转角检查；补充玩具地图测试；在 A/B 两个真实场景分别加载 R 并运行任务 1；同步更新阶段状态和文件结构索引。
- **人工提供的任务约束：** 只实现标准 A*；优先级 `f=g+h` 只含几何长度；不实现另外四种算法、不修改风险公式/公共层公式、不做排名、不更改只读场景资料。
- **采用的 AI 输出：** `src/algorithms/astar.py`、算法包导出与注册、`tests/test_astar.py`；A/B 冒烟原始日志和对应的 M3 状态记录。
- **实际验证：** 定向测试 `7 passed`；全套 `python -m pytest tests/ -q` 为 `25 passed`；`python -m compileall -q src tests` 和 `git diff --check` 通过。A/B 任务 1 均 success：A 路径长 `1432.7849 m`，B 路径长 `1445.9973 m`。运行时间与展开节点数仅记录本次冒烟事实，不作为算法性能结论。
- **结果位置：** `experiments/raw/smoke_astar_A.txt`、`experiments/raw/smoke_astar_B.txt`；实施计划位于 `docs/superpowers/plans/2026-10-29-astar.md`。
- **变更边界：** 未修改 `src/risk/risk_matrix.py`、`src/core/` 的公共公式、`src/algorithms/` 中其他算法（尚未实现）、输入论文/公式/场景/任务书。真实冒烟只确认 A* 可在 A/B 任务 1 上运行，不构成路径优劣或综合代价结论。

## 本次 RiskA* 实现与冒烟（2026-10-29）

- **Agent / 模型：** Codex，GPT-6 系列模型。
- **参与环节：** 阅读 Primatesta 2019 的 RiskA* 式 (8)–(11) 与 Algorithm 2；按中文计划实现纯风险积分搜索、低风险平局、LOS 后优化和 metadata；编写玩具地图手算测试；在 A/B 真实 R 上运行任务 1 并复查最终路径的碰撞和转角。
- **人工提供的任务约束：** 只实现 RiskA* 原版；不使用综合代价的 α 权重；不实现 RC-A*、RRT*、Informed RRT*；不改公共层、风险公式或输入数据。
- **采用的 AI 输出：** `src/algorithms/risk_astar.py`、算法包注册、`tests/test_risk_astar.py`；保留优化前/后路径与纯风险积分的 A/B raw 冒烟日志。
- **实际验证：** 定向 RiskA* 测试为 `10 passed`，全套 `python -m pytest tests/ -q` 为 `35 passed`。A/B 任务 1 最新复核均 success。A：展开 `830112` 次，用时 `293.135410 s`，LOS 前后为 140→47 点，纯风险积分 `978.097827247→749.978994437`。B：展开 `705376` 次，用时 `191.566500 s`，LOS 前后为 168→91 点，积分 `451.227813406→362.723166052`。两条最终路径的公共节点碰撞、边碰撞和转角违规数均为 0。A 初次运行与三次优化重试的 timeout 均保留在同一原始日志，最终实现成功。编译检查、`git diff --check` 和只读目录 diff 均通过。
- **参数假设：** 配置没有 RiskA* `eps` 键，实现暂用 float64 机器 epsilon；A/B 全图最小 `R/R_norm` 高于该值，当前数据不受影响。该假设和未来风险见 `report/assumptions.md`。
- **结果位置：** `experiments/raw/smoke_risk_astar_A.txt`、`experiments/raw/smoke_risk_astar_B.txt`；中文计划在 `docs/superpowers/plans/2026-10-29-risk-astar.md`。
- **变更边界：** 未修改 `src/core/`、`src/risk/risk_matrix.py`、A* 公式、场景/论文/公式/任务书；不计算综合代价或排名。LOS 替换还要求新连接处满足公共转角约束，且 1 m 采样与离散端点两种风险代价都不增加。真实冒烟只核验搜索与优化路径有效，不构成算法性能结论。

## 本次 RC-A* 与 RRT* 实现（2026-10-29）

- **Agent / 模型：** Codex，GPT-6 系列模型；RRT* 子任务由并行子代理完成，主代理复核并合并公共注册表。
- **参与环节：** 按用户给出的论文 A 与 Karaman-Frazzoli 2011 约束实现 RC-A*、标准 RRT*，增加中文计划、手算玩具测试、真实场景任务 1 冒烟和只读目录复核。
- **采用的 AI 输出：** `src/algorithms/rc_astar.py`、`src/algorithms/rrt_star.py`、`tests/test_rc_astar.py`、`tests/test_rrt_star.py`、`experiments/raw/smoke_rc_astar_A.txt`、`smoke_rc_astar_B.txt`、`smoke_rrt_star_A.txt`，以及 `src/algorithms/__init__.py` 的导入/导出注册。
- **RC-A* 实际验证：** 9 项定向测试通过；A/B 任务 1 均 success，路径节点、边、转角复核均为 0 违规。大包围盒精确中位数导致 A 冒烟 600 s 超时，随后采用确定性三维等距采样估计大盒中位数；均值仍使用精确二维前缀和，方法和影响记录在 `report/assumptions.md` 与 raw 日志。
- **RRT* 实际验证：** 8 项定向测试通过；A 任务 1 seed 0/1/2 各以 60 s 运行，均按预算返回 timeout。seed 0 在 11.4763 s 找到可行 incumbent，188 点路径的节点、边、转角违规均为 0；seed 1/2 无可行 incumbent。另以 seed 0、100000 次迭代上限运行并正常返回 success，指标与 incumbent 一致。超时结果保留 incumbent 指标，所有失败 run 保留在 raw，不把 timeout 改成 success。
- **代码审查与验证：** `python -m pytest tests/ -q` 为 `52 passed`；RRT* 最近邻改为精确 NumPy 向量化距离，Near 仍用空间桶；`gamma` 用理论阈值的 `math.nextafter` 向上值满足严格大于条件；`git diff --check` 和 `git diff -- 01_论文原文 02_公式提取 03_场景 04_任务书` 通过。
- **人工保留事项：** RC-A* 大盒中位数是性能适配估值，当前只作可运行性冒烟；RRT* 60 s 成功率不足以进入正式排名；两者均未实现 Informed RRT*，也没有修改公共风险公式或只读输入。

## 本次 Informed RRT* 实现与冒烟（2026-10-29）

- **Agent / 模型：** Codex，GPT-6 系列模型。
- **参与环节：** 按 Gammell 2014 原版路径长度椭球实现 Informed RRT* 采样器；父类只增加最短可行几何路径长度记录，Informed 子类只覆盖 `sample()`，复用 RRT* 的 `plan()`、选父、最近邻和重连。
- **人工提供的任务约束：** 不复制树结构或重连代码；首次可行解前全空间均匀采样，找到后按路径长度椭球连续采样；仅运行 A 场景任务 1 seed 0/1/2 冒烟，不做全量实验或排名。
- **采用的 AI 输出：** `src/algorithms/informed_rrt_star.py`、`src/algorithms/rrt_star.py` 的 `best_length` 记录、`src/algorithms/__init__.py` 注册、`tests/test_informed_rrt_star.py`、`experiments/raw/smoke_informed_rrt_star_A.txt`。
- **实际验证：** 9 项 Informed 定向测试通过；A 场景每 seed 60 s 的最终连续采样运行均为 `timeout`。seed 0 在 13.2171 s 找到 incumbent，树节点 30099，采样 140300 次，椭球启用 97832 次、接受 97776 次、越界回退 56 次，路径长 1763.4062 m，综合代价 705.3811；seed 1/2 未在预算内找到路径。`best_length` 与 seed 0 返回的 incumbent 几何长度一致。早期复跑日志作为历史记录保留，最终运行在 raw 日志最后一节。
- **口径限制：** 椭球按几何路径长度收缩，继承的 RRT* 父类仍按公共综合边代价选父/重连；因此本实现完成长度椭球采样，但不能据此声称综合代价目标下的渐近最优，详见 `report/assumptions.md`。冒烟不构成算法性能排名。
- **验证：** `python -m pytest tests/ -q` 为 `61 passed`；`python -m compileall -q src tests`、`git diff --check` 均通过；`git diff -- lib/01_论文原文 lib/02_公式提取 lib/03_场景 lib/04_任务书` 与对应 `git status --short` 均无输出。
- **结果位置：** `experiments/raw/smoke_informed_rrt_star_A.txt`；中文计划为 `docs/superpowers/plans/2026-10-29-informed-rrt-star.md`。
