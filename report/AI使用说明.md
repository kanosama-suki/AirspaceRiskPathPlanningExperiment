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
