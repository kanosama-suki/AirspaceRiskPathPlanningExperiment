# RiskA* 实现计划

> **执行方式：** Native，由当前主代理按步骤完成。

**目标：** 按 Primatesta 2019 的风险积分目标实现 RiskA*，完成 LOS 后优化、玩具地图手算测试及 A/B 任务 1 真实 R 冒烟。

**方案：** 新规划器继承 `PlannerBase`，复用公共坐标、网格、碰撞、转角函数和 A* 的方向状态/父链模式；实际代价只累计 `r_c` 对距离的梯形积分，优先级使用 `g + k*h` 并以较低节点风险打破相同 `f`。LOS 优化按论文 Algorithm 2 插值并比较纯风险运动代价。由于公共 `PathResult` 没有 metadata 且本任务禁止修改公共层，在 RiskA* 模块内派生带 metadata 的结果类型。

**技术栈：** Python、NumPy、标准库 `heapq`、pytest。

**依据：** 用户本轮任务；`plan.md` §3.2、§4；`lib/03_场景/README.md` §2.1、§3；Primatesta 2019 PDF 第 9–10 页 Algorithm 1、式 (8)–(11) 与 Algorithm 2。

## 全局约束

- RiskA* 的 `g` 是纯 `r_c × distance` 梯形积分；`ALPHA1/ALPHA2` 不参与搜索。
- 固定高度 RiskA* 按本任务适配到 3D 26 邻域；所有几何、碰撞和转角检查调用公共层。
- `R_norm` 直接读取 `SceneData.r_norm`；建筑和无效格风险代价映射为 1，同时仍由碰撞检查禁止路径通过。
- LOS 只在其插值线段无建筑/无效风险时比较代价；替换还必须保持公共转角约束，并同时使 1 m 采样代价和离散端点梯形代价不增加；不修改公共层、`risk_matrix.py`、场景输入或其他算法。
- `k=0.75` 是模块参数常量；当前 config 没有 RiskA* 裁剪下界键，`eps` 暂取 float64 机器 epsilon 并记录到 assumptions。
- 冒烟日志保存到 `experiments/raw/`；不进行全量实验或算法排名。

## 文件职责

- `src/algorithms/risk_astar.py`：RiskA* 搜索、风险边/启发代价、LOS 优化、带 metadata 的 `PathResult` 子类及注册。
- `src/algorithms/__init__.py`：导出 A* 与 RiskA*，使导入算法包时两个已实现算法均注册。
- `tests/test_risk_astar.py`：5×5×3 玩具地图，手算 `g`/`h`/风险积分、平局风险优先和 LOS 代价取舍。
- `experiments/raw/smoke_risk_astar_A.txt`、`smoke_risk_astar_B.txt`：真实任务 1 的状态、LOS 前后路径点/长度/风险积分、耗时、展开数和失败原因。
- `report/assumptions.md`：记录缺少 `eps` 配置键及采用 float64 机器 epsilon 的影响。
- `AGENTS.md`、`plan.md`、`report/AI使用说明.md`、`structure.md`：同步 M3 状态、实现事实和文件用途。

## Review Focus

- 起点、终点或整条路径落在建筑/NaN 格：必须返回明确无效状态或拒绝 LOS，不能把无效风险当作可通行零风险；测试验证。
- 相同 `f` 的候选风险不同：优先低 `r_c`；独立测试优先队列键顺序。
- LOS 插值步长和风险积分必须使用米制距离且不采用综合代价；对高风险直线/低风险绕行路径验证不会被错误拉直。
- `PathResult` 的公共类型字段保持兼容；仅 RiskA* 派生类型附加 metadata，不编辑 `src/core/types.py`。
- A/B 冒烟成功路径须能通过公共节点/边碰撞复查，日志不能把 timeout 写成 success。

---

### 任务 1：RiskA* 搜索与纯代价函数

**文件：**
- 新建：`src/algorithms/risk_astar.py`
- 修改：`src/algorithms/__init__.py`
- 测试：`tests/test_risk_astar.py`

**接口：**
- `RiskAStarPlanner.name == "risk_astar"`
- `RiskAStarPlanner.plan(req: PlanRequest) -> PathResult`（实际返回兼容子类 `RiskPathResult`）
- `risk_edge_cost(r_prev, r_next, distance) -> float`
- `risk_heuristic(r_node, r_goal, distance, distance_min, risk_min) -> float`
- `post_optimize_path(path, R, building_mask, config, r_norm) -> tuple[Point3D, ...]`
- `RiskPathResult` 继承公共 `PathResult` 并追加 `metadata: Mapping[str, object]`。
- `PLANNERS["risk_astar"] = RiskAStarPlanner`。

- [x] 写手算代价/启发式测试：`r_c=0.1`、相邻距离 10 m 时，边代价 `1`；起终距离 20 m 时，给定公式的 `h=2`；RiskA* 输出路径纯风险积分与逐边手算相等。
- [x] 写平局测试：优先队列中 `f` 相同的状态，`r_c` 更小者先出队。
- [x] 写 LOS 测试：低风险绕行的累计风险低于高风险直线，优化不得替换成高风险直线；另验证低风险直线可移除多余路径点，并验证替换不能突破转角上限。
- [x] 实现按 `R/R_norm` 裁剪的风险代价场、`r_cmin`、梯形边代价及给定启发式；建筑/NaN 风险映射为 1。
- [x] 实现水平航向相关搜索状态、公共层合法邻域/转角/碰撞检查、父链回溯、低 g 更新、`f` 同值低风险优先及明确失败原因。
- [x] 实现论文 Algorithm 2 的线性 LOS 采样、纯风险积分比较与路径替换；metadata 保存优化前后路径、长度和风险积分。替换同时复核新连接两端的公共转角约束，并要求两种风险代价口径均不增加。
- [x] 运行 `python -m pytest tests/test_risk_astar.py -q` 并确认手算值和优化行为（10 passed）。

### 任务 2：真实 R 冒烟

**文件：**
- 运行产物：`experiments/raw/smoke_risk_astar_A.txt`
- 运行产物：`experiments/raw/smoke_risk_astar_B.txt`

- [x] 顺序加载 A、B，分别对任务 1 运行 RiskA*；不同时保留两场景的全量 R。
- [x] 每个日志记录状态、优化前/后路径点数、长度、纯风险积分、运行时间、展开数、`failure_reason` 和 LOS 优化说明；A 的早期 timeout 重试也保留。
- [x] A/B 均得到 `success`；A 的三次 300 s timeout 历史保留，后续缓存优化版本成功。
- [x] 成功路径用公共节点/边碰撞和转角函数复核，A/B 均为 0；未计算算法排名或综合代价。

### 任务 3：项目状态与最终验证

**文件：**
- 修改：`AGENTS.md`、`plan.md`、`report/AI使用说明.md`、`structure.md`、`report/assumptions.md`

- [x] 运行 `python -m pytest tests/ -q`。
- [x] 运行 `python -m compileall -q src tests`、`git diff --check` 和只读输入目录 diff 检查。
- [x] 更新中文计划勾选状态、M3 算法状态和新增文件结构说明。
