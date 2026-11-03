# 城市空域风险路径规划实验

本项目在同一城市地图、风险矩阵、起点、终点、搜索预算和合法性规则下，比较五种三维路径规划算法：

- A*
- RiskA*
- RC-A*
- RRT*
- Informed RRT*

所有路径都由公共评估器重新计算长度、风险积分和综合代价，并检查建筑碰撞、边碰撞、NaN 风险格与转角约束。最终排名以综合代价为主，同时报告严格成功率、合法路径发现率、运行时间和随机波动。

## 实验设计

项目使用两套场景：A 为深圳南山真实建筑场景，B 为随机生成城市。每个场景用 `route_seed=114514` 生成 1000 条合法候选路线，再按直线距离分位区间冻结 S/M/L 路线：

| 分组 | 距离分位区间 | 每场景路线数 |
|---|---|---:|
| S | p5–p15，代表点 p10 | 40 |
| M | p45–p55，代表点 p50 | 10 |
| L | p85–p95，代表点 p90 | 5 |

A/B 共 110 条正式路线。三种图搜索算法只运行一次，运行标识为 `deterministic=114514`；两种采样算法共享 `sampling seeds=0..19`。路线 seed、采样 seed 和路线编号分别记录，最终排名按场景、距离组和路线复杂度分层。

当前先进行预算与并行吞吐校准。校准完成后才冻结正式预算并启动完整矩阵；`experiments/configs/formal.toml` 中的 60/240/1200 s 是待校准的初始档位，校准结果会决定是否回填。

## 目录

```text
ffjj/
├── AGENTS.md                         项目操作规则和当前状态
├── README.md                         项目入口
├── structure.md                      详细文件索引
├── lib/
│   ├── plan.md                       当前实施规划
│   ├── 01_论文原文/                  论文 PDF，只读
│   ├── 02_公式提取/                  公式与来源索引，只读
│   ├── 03_场景/                      场景配置、地图、P_s/R 基准，只读
│   └── 04_任务书/                    任务书，只读
├── src/
│   ├── algorithms/                   五种规划器
│   ├── core/                         坐标、网格、碰撞、metrics 和公共类型
│   ├── experiments/                  配置、路线生成、复杂度、运行评估
│   ├── inspection/                   场景信息采集
│   ├── io/                           场景加载
│   ├── risk/                         P_s、R 与风险校验
│   └── validation/                   数据契约和路线清单审计
├── tests/                            单元测试、小地图测试和真实 R 切片测试
├── experiments/
│   ├── configs/                      formal、smoke、calibration 三套配置
│   ├── run.py                        正式运行器
│   ├── calibrate.py                  预算与 worker 校准
│   ├── aggregate.py                  原始记录汇总
│   ├── routes/                       冻结路线清单与 manifest
│   ├── raw/                          正式运行原始 JSONL
│   ├── validation/                   路线审计和历史校验结果
│   ├── tables/                       CSV/JSON 汇总
│   ├── figures/                      图表
│   └── archive/                      历史实验归档
├── report/                           人工可读报告、结论和 AI 使用说明
└── tmp/                              可删除的草稿与临时文件
```

`lib/01_论文原文/`、`lib/02_公式提取/`、`lib/03_场景/`、`lib/04_任务书/` 是只读输入。失败运行保留在 `experiments/raw/` 并参与成功率统计。

## 常用命令

```powershell
# 全量测试
python -m pytest -q -p no:cacheprovider

# 重新生成并冻结 S/M/L 路线；相同配置和 seed 会产生相同清单
python -m src.experiments.route_generator --config experiments/configs/formal.toml

# 审计冻结路线
python -m src.validation.audit_route_manifest `
  --config experiments/configs/formal.toml `
  --output experiments/validation/route_audit.json

# 单路线五算法冒烟
python -m experiments.run --smoke --run-id smoke

# 快速校准自测；原始 JSONL 写入 experiments/raw/calibration
python -m experiments.calibrate --config experiments/configs/calibration.toml --scope quick --workers 8
python -m experiments.calibrate --config experiments/configs/calibration.toml --scope pilot --workers 8
python -m experiments.calibrate --config experiments/configs/calibration.toml --scope full --workers 8

# 正式矩阵；预算校准和配置冻结完成后再运行
python -m experiments.run --config experiments/configs/formal.toml `
  --scope full --workers 8 --run-id sml-formal-v1

# 汇总正式原始记录
python -m experiments.aggregate `
  --config experiments/configs/formal.toml `
  --input experiments/raw/sml `
  --output experiments/tables/sml
```

正式运行器会保存配置快照和哈希，并区分 `success`、`timeout_with_solution`、`timeout_no_solution`、`no_path`、`invalid`。`timeout_with_solution` 不计入严格成功率；严格成功率低于 80% 的条件不参与最优排名，只报告可行性。

## 当前状态

代码、公共层、真实 R、冻结路线和运行器已经就绪。完整 S/M/L 正式矩阵尚未启动；当前下一步是对目标服务器完成预算和 worker 校准，再将校准后的预算回填正式配置。
