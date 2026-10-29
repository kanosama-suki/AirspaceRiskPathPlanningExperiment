# M2 公共层接入真实 R 实施计划

> **执行者说明：** 本计划按已确认的 Native 方式由当前主代理逐项实施。

**目标：** 将 A/B 场景的真实风险矩阵接入公共层，定义规划请求与结果接口，并用直线数据流冒烟和真实 R 切片手算验证接口。

**方案：** `src/io/scene.py` 从配置解析只读场景输入，优先按显式缓存路径读取 R，否则调用现有 `compute_r_matrix` 在内存生成；单场景加载、完成检查后再处理下一场景。`src/core/types.py` 定义 `SceneData` 相关请求/结果契约和空注册表。冒烟程序将 1 m 直线采样映射到最近数据格心，记录碰撞、转角、NaN 和公共指标；穿建筑时明确报告路径指标无效。测试从真实场景 R 取 10×10×10 切片，用短路径独立手算综合代价并与公共 metrics 比较。

**技术栈：** Python 3.10+、NumPy、标准库 `dataclasses` / `hashlib` / `argparse`、pytest。

**依据：** 用户本轮 M2 任务；`AGENTS.md`；`plan.md` §3.1–§3.3；`lib/03_场景/README.md` §2.1、§3、§6；`lib/03_场景/config.json`；`lib/02_公式提取/公式提取.md`。

## 全局约束

- 不实现或运行五种算法，不修改 `src/algorithms/`。
- 不修改 `lib/01_论文原文/`、`lib/02_公式提取/`、`lib/03_场景/`、`lib/04_任务书/`，不改 `src/risk/risk_matrix.py` 的公式逻辑。
- 风险查询和碰撞分别使用公共 `metrics.py` 与 `collision.py`；建筑格的 NaN 不得转成零风险。
- 采样间隔、坐标映射、层范围、起终点、巡航速度、权重和栅格尺寸从 config 读取。
- 冒烟记录写入 `experiments/raw/`；不将直线冒烟解释为算法性能结论。
- R 按 A 后 B 顺序加载，不同时持有两场景的完整矩阵；不得写场景输入或缓存文件。

## 文件职责

- `src/io/scene.py`：定义 `SceneData` 与 `load_scene`，只读加载配置/场景数组，校验结构，生成或读取 R，并计算精确 `R_norm` 与配置哈希。
- `src/core/types.py`：定义 `PlanRequest`、`PathResult`、`PlannerBase` 和空的 `PLANNERS` 注册表。
- `src/core/metrics.py`：增加可传入已计算全局归一化量的兼容入口，并返回未归一化风险积分，避免多次扫描完整 R；保留原计算公式和默认行为。
- `src/experiments/smoke_dataline.py`：按场景/任务执行 1 m 直线采样数据流检查并写 A/B 原始日志。
- `tests/test_types.py`：固定公共请求/结果接口、抽象基类和空注册表契约。
- `tests/test_scene_metrics.py`：读取真实场景，切取一个 10×10×10 R 块，以有限格上的短路径手算并比对 metrics。
- `docs/superpowers/plans/2026-10-29-m2-public-layer.md`：保存本次中文实施步骤和验收命令。
- `report/AI使用说明.md`、`AGENTS.md`、`plan.md`：按项目工作流记录本次实现和 M2 状态。
- `experiments/raw/smoke_dataline_A.txt`、`smoke_dataline_B.txt`：保存实际运行的冒烟记录。

## Review Focus

- 配置路径从 `config.json` 所在目录解析，而不是依赖当前 shell 目录；由场景加载测试覆盖。
- R 缓存必须是用户显式提供的 `.npy` 或含 `R` 键的 `.npz`，形状与配置一致；由缓存测试覆盖。
- 真实建筑格仍为 NaN，且路径采样命中 NaN 时综合指标必须标无效；由冒烟日志和测试覆盖。
- 规划接口中的 `PlanRequest` 字段在规划书未明文列全；本次明确为 `scene_data`、`mission`、`start`、`goal`、`seed`、`time_budget_s`、`iteration_budget`，并由契约测试覆盖。
- A/B 完整矩阵内存占用较大；由单场景顺序加载、日志和进程运行验证确认未同时保留两场景 R。

---

### 任务 1：场景加载

**文件：**
- 新建：`src/io/scene.py`
- 测试：`tests/test_scene.py`

**接口：**
- 产出：`load_scene(scene_name: str, config_path: Path, r_cache_path: Path | None = None) -> SceneData`
- `SceneData` 包含 `R`、`building_mask`、`pop_density`、`h_low`、`h_high`、`step`、A/B 两组任务起终点、场景名、config 映射、精确 `r_norm` 和 `config_hash`。

- [x] 写临时小配置与小场景测试：验证相对场景路径、数组形状、起终点映射、SHA-256 哈希、显式 R 缓存读取和错误形状拒绝。
- [x] 运行 `python -m pytest tests/test_scene.py -q`，确认接口、生成器路径与 NaN/建筑语义测试通过。
- [x] 实现 JSON/NPZ 只读加载；未传缓存时调用 `compute_r_matrix(building_footprint, pop_density, building_mask, config)`。输入数组不写回；场景数据形状、dtype 与配置不符时抛出明确异常。
- [x] 重跑 `python -m pytest tests/test_scene.py -q`，确认通过。

### 任务 2：公共规划接口

**文件：**
- 新建：`src/core/types.py`
- 测试：`tests/test_types.py`

**接口：**
- `PlanRequest(scene_data, mission, start, goal, seed=None, time_budget_s=None, iteration_budget=None)`。
- `PathResult` 字段使用规划书 §3.2 的状态、算法、场景、任务、seed、航点、路径点数、长度、风险期望、综合代价、运行时间、迭代/扩展数、样本数、失败原因和 `config_hash`。
- `PlannerBase` 为抽象基类，定义 `plan(req: PlanRequest) -> PathResult`；`PLANNERS` 初始为空字典。

- [x] 写测试验证请求/结果字段可构造、抽象 `plan` 不能直接实例化、注册表为空。
- [x] 运行 `python -m pytest tests/test_types.py -q`，确认接口测试通过。
- [x] 实现带完整类型注解的数据类、抽象类和注册表。
- [x] 重跑 `python -m pytest tests/test_types.py -q`，确认通过。

### 任务 3：指标接口供真实矩阵复用

**文件：**
- 修改：`src/core/metrics.py`
- 测试：`tests/test_metrics.py`

- [x] 增加一个使用调用者已计算 `r_norm` 的路径评估测试，并核对返回的原始风险积分等于逐段梯形积分。
- [x] 实现可选 `r_norm` 参数；未提供时保留现有从风险场计算的默认行为，不改变长度、小时制、风险和综合代价公式。
- [x] 运行 `python -m pytest tests/test_metrics.py -q`，确认旧手算测试和新增测试通过。

### 任务 4：A/B 直线数据流冒烟

**文件：**
- 新建：`src/experiments/smoke_dataline.py`
- 新建：`src/experiments/__init__.py`
- 运行产物：`experiments/raw/smoke_dataline_A.txt`、`smoke_dataline_B.txt`

- [x] 实现 `python -m src.experiments.smoke_dataline --scenes A B --config lib/03_场景/config.json`；每个场景按顺序加载，覆盖任务 1 和任务 2。
- [x] 每条起终点直线按 `GRID_SIZE` 最多间隔采样，将采样点映射到最近体素格心；统计节点碰撞、边碰撞、转角违规、风险查询 NaN 命中数。
- [x] 只有路径无碰撞且采样风险全有限时，才调用公共 evaluator 输出风险积分和综合代价；否则写 `INVALID` 与具体阻断原因，不用 0 代替。
- [x] 运行脚本，确认两个日志生成并有真实 R 形状/统计、四个任务结果、进程退出码 0。

### 任务 5：真实 R 切片指标测试与整体验收

**文件：**
- 新建：`tests/test_scene_metrics.py`
- 修改：`report/AI使用说明.md`、`AGENTS.md`、`plan.md`

- [x] 从 A 的真实风险矩阵区域取得 10×10×10 切片并选取其中三个相邻有限格作为短路径。
- [x] 以配置巡航速度、栅格尺寸、全局精确 `r_norm` 和真实端点 R 值独立手算长度、小时、未归一化风险积分及综合代价，并断言与 `metrics.py` 一致。
- [x] 运行 `python -m pytest tests/ -q`，确认全部测试通过（17 passed）。
- [x] 运行冒烟脚本并核对 A/B 原始日志；最终只读目录 diff 检查在实现后执行。
- [x] 更新 AI 使用说明与项目里程碑状态，记录运行命令、实际结果、直线路径碰撞导致指标无效的事实。

## 最终验收命令

```powershell
python -m pytest tests/ -q
python -m src.experiments.smoke_dataline --scenes A B --config lib/03_场景/config.json
git diff -- lib/01_论文原文 lib/02_公式提取 lib/03_场景 lib/04_任务书
```
