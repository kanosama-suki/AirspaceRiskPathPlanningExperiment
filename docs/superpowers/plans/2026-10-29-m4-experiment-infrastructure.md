# M4 实验基础设施实施计划

> **执行方式：** 按本计划直接实施；任务项用于追踪检查。

**目标：** 建立正式实验配置、统一路径合法性与指标复核的运行器，以及可记录并汇总预算扫描结果的轻量脚本。

**架构：** `base.json` 保存实验矩阵、预算、种子和输出约定；`experiments/run.py` 逐条件实例化注册规划器，统一检查返回路径并通过公共 metrics 重算指标，随后向 raw JSONL 追加一行；`budget_smoke.py` 复用运行器，分别执行时间预算和迭代预算扫描，并将有路径比例、首次可行时间和综合代价汇总到 tables CSV。

**技术栈：** Python、JSON/JSONL、CSV、NumPy、现有 `src.io.scene`、`src.core.collision`、`src.core.grid`、`src.core.metrics`。

**依据：** M4 用户规格、`AGENTS.md` 公平性纪律、`plan.md` 实验矩阵与路径评价要求。

## 文件

- 新建 `experiments/configs/base.json`：A/B、任务 1/2、五算法、确定性/采样 seed、占位预算、快测覆盖值和 raw 输出规则。
- 新建 `experiments/run.py`：配置加载、1 m 栅格重采样、碰撞/NaN/转角检查、状态细分、统一 metrics、JSONL 写入、smoke/full CLI。
- 新建 `experiments/budget_smoke.py`：完整时间/迭代预算扫描、图搜索计时、自测子集、CSV 汇总和预算推荐。
- 新建 `tests/test_experiments_run.py`：检查合法 timeout incumbent、空 timeout、合法 no_path、NaN、碰撞、转角、重采样和指标重算。
- 更新 `structure.md`、`AGENTS.md`、`report/AI使用说明.md`：登记入口、输出位置、当前 M4 状态和真实验证结果；不改 assumptions、README 和只读输入。

## 全局约束

- 不执行完整 A/B × 任务 1/2 × 五算法 × 20 seeds 实验。
- `experiments/raw/` 只追加真实运行记录和配置快照；不覆盖或删除失败 run。
- 输出路径统一调用公共碰撞、转角和 metrics API；任何无效路径不得获得有效综合代价。
- timeout 且有合法 incumbent 记录为 `timeout_with_solution`，不得改写为 `success`。
- 预算建议必须来自实际 budget-smoke 记录；快速自测只能给临时建议并明确标注样本不足。
- 不修改算法、公共层、风险公式和只读输入目录。

## Review Focus

- timeout 路径的合法 incumbent 必须保留为独立状态；测试覆盖带路径和无路径两种情况。
- 风险 NaN、建筑碰撞、边穿建筑、超限转角必须将运行降为 `invalid`；测试逐项覆盖。
- 对角线或非整米段重采样后的风险查询必须落到数据格心；测试覆盖对角线和重复格心去重。
- deterministic 算法只能执行一次，采样算法按 0–19 执行；配置矩阵选择测试覆盖。
- 重复运行不得覆盖旧 raw 行；测试验证 JSONL 追加和配置哈希字段。

## 步骤

- [ ] 新增正式实验配置和可校验的 `--smoke` 覆盖值。
- [ ] 编写运行器的合法性检查与状态映射单测，再实现 JSONL 矩阵执行入口。
- [ ] 编写预算扫描汇总单测，再实现完整扫描和 `--quick` 自测入口。
- [ ] 运行 `python -m experiments.run --smoke` 与一次预算 quick 自测。
- [ ] 运行全套 pytest、compileall、diff-check、只读目录 diff；更新项目记录和结构索引。
