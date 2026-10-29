# Informed RRT* 实现计划

> **执行方式：** 按本计划直接实施；任务项用于追踪检查。

**目标：** 继承标准 RRT*，仅增加 Gammell 2014 路径长度椭球采样，并用 A 场景任务 1 验证。

**架构：** 父类只记录已发现可行路径的最短几何长度，不改变树搜索、选父或重连。子类只覆盖 `sample(req)`，在有解后从起终点焦点椭球均匀采样；退化或越界时调用父类采样并记录计数。

**技术栈：** Python、NumPy、现有 `RRTStarPlanner`、`PlanRequest`、`SceneData`、pytest。

**依据：** 用户本轮 Informed RRT* 规格、Gammell 2014 原版路径长度椭球、项目 `AGENTS.md`。

## 文件

- 修改 `src/algorithms/rrt_star.py`：新增并维护 `best_length`，不改变搜索决策。
- 新建 `src/algorithms/informed_rrt_star.py`：椭球几何、均匀单位球采样、边界/退化回退及计数。
- 修改 `src/algorithms/__init__.py`：导出并注册 Informed RRT*。
- 新建 `tests/test_informed_rrt_star.py`：手算椭球参数、无解全空间采样、椭球内采样、退化回退。
- 生成 `experiments/raw/smoke_informed_rrt_star_A.txt`：A 任务 1 seed 0/1/2 实际运行记录。
- 更新 `AGENTS.md`、`plan.md`、`structure.md`、`report/AI使用说明.md` 与 `report/assumptions.md`。

## 全局约束

- Informed 椭球以欧氏路径长度 `c_best` 为长轴约束，焦点为起点和终点。
- 不复制或重写 RRT* 的树、最近邻、选父、重连及 `plan()`。
- 配置边界从场景数组尺寸、坐标原点和分辨率读取；随机数使用父类 RNG。
- 超时、无路和退化采样如实记录；只读输入目录保持不变。

## 步骤

- [x] 在父类记录最短已发现可行路径长度，并由 `sample()` 动态读取。
- [x] 新建椭球采样子类，测试手算中心/半轴、无限 `c_best`、连续椭球内采样和退化回退。
- [x] 注册规划器，跑定向测试和 A 场景三个 seed，保留原始日志及采样计数。
- [x] 跑全套 pytest、compileall、diff-check 和只读目录 diff，更新项目记录。
