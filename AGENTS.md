# AGENTS.md

## 0. 项目一句话
在同一地图/风险/起终点/预算下比较 A*、RC-A*、RiskA*、RRT*、Informed RRT*，判据为公共评估器的综合代价。

## 1. 必读顺序
1. `05_规划书/城市空域风险路径规划实验实施规划书.md`
2. `03_场景/README.md`
3. `03_场景/config.json`
4. `02_公式提取/公式提取.md`

规划书是执行计划的唯一详细来源；本文只写操作规则和当前状态。

## 2. 红线（详细见规划书 §2.1、§3.3、§4）
- `01_论文原文/`、`02_公式提取/`、`03_场景/`、`04_任务书/` 下原始文件只读，不改不删不移动。
- `03_场景/config.json` 是唯一参数源；实验变量走 `experiments/configs/`，结果存配置快照。
- `experiments/raw/` 不手改、不删失败 run；失败 run 落 raw 并参与成功率统计。
- 场景信息采集脚本放在 `src/inspection/`，采集记录放在 `experiments/raw/`；验证脚本放在 `src/validation/`，验证结果放在 `experiments/validation/`，人工检查摘要放在 `report/`。
- 综合代价只由 `src/core/metrics.py` 计算；风险统一小时制 `t_hour = d/(v×3600)`。
- 五算法先按原论文；适配变体必须单独命名（`RiskA*-W`、`Informed RRT*-C`、`RRT*-kNN`），不与原版混排名。
- 不捏造数据；不把单次采样最优当统计结论。
- 改完跑 `git diff -- 01_论文原文 02_公式提取 03_场景 04_任务书`；有输出先恢复，不能继续用新数据掩盖。

## 3. 架构与接口
- 五算法继承 `PlannerBase`，输入 `PlanRequest`，输出 `PathResult`；字段详见规划书 §3.2。
- 评估外置，算法不自评。
- 新算法：继承 → 实现 `plan()` → 注册 `PLANNERS` → 加小地图测试。
- 坐标统一 `(x,y,z)`，单位 m；风险查询和碰撞检查走公共函数，不在算法内重写。

## 4. 公平性纪律（详见规划书 §3.3、§5）
- 同条件同 `start/goal`、`risk_weight`、`budget`、步长、高度层。
- 图搜索用时间预算；采样用时间+迭代预算，均记录。
- 采样每条件 ≥20 seeds；失败 run 不赋惩罚值混入均值。
- 某条件成功率 <80%，该算法不参与该条件最优排名，只报告可行性。
- 所有路径统一重采样后用同一评估器。

## 5. 日常命令
```powershell
python -m src.risk.verify --scene A --config 03_场景/config.json
python -m pytest -q
python -m experiments.run --scenes A B --missions 1 --algorithms all --seeds 0 1 2 --smoke
python -m experiments.aggregate --input experiments/raw --output experiments/tables
git diff -- 01_论文原文 02_公式提取 03_场景 04_任务书
```

完整命令见规划书 §7。

## 6. 工作流
1. 读 §7 当前状态。
2. 只改允许目录；先 smoke 再全量。
3. 实验运行原始记录和场景信息采集记录落 `experiments/raw/`，场景验证结果落 `experiments/validation/`，汇总落 `experiments/tables/`。
4. 更新 `report/AI使用说明.md` 和 §7 状态。
5. 汇报：改动文件 + 验证命令 + 结果。

## 7. 当前状态
里程碑：M3 / 标准 A* 已实现并完成 A/B 任务 1 冒烟；其余四种算法尚未开始
已完成：M2 公共层与真实 R 数据流接口；标准 A* 仅按几何距离搜索并注册到 PLANNERS；小地图 7 项 A* 测试；A/B 任务 1 均 success；全套 25 项测试通过，src/tests 编译检查通过
下一步：按原论文实现 RC-A*，先做小地图手算测试，再继续其他算法
阻塞：无；A/B 真实冒烟只验证 A* 可运行，不构成算法性能比较或风险代价排名；B summary 差异仍按 assumptions 披露
更新日期：2026-10-29

## 8. 不确定时
写 `report/assumptions.md`，标注影响；不静默改参数、不跳过失败 run。

## 9. 代码规范（轻量）

### 9.1 import
- 顺序：标准库 → 第三方库 → 本地模块。
- 每组内：`from ... import ...` 在前，`import ...` 在后；组内按字母序。
- 同文件夹模块用相对导入；跨文件夹用 `from src.<layer>...` 绝对导入。
- 按第二层文件夹名分组，组内和组间均按字母序，不随机排列。

### 9.2 注释
- 新增或修改代码时，原有注释不删除；功能变化可改注释保持准确。
- 较长或较复杂的代码块补注释，说明功能和逻辑。

### 9.3 类型注解
- 接口契约（`PlanRequest` / `PlanResult` / `PlannerBase`）必须完整注解。
- 复杂函数、多参数函数补注解；简单局部变量可省略。
- 参数化泛型用 `typing` 标注。

### 9.4 变量
- 类型已确定（优先按类型注解）时，不用 `or` fallback 掩盖 None。
- 不确定类型时先查契约，不靠运行期猜测。

### 9.5 debug
- 不找兜底掩盖问题；先定位核心原因，再给建议。
- 采样失败、超时、无解必须记录 `failure_reason`，不静默重试。
