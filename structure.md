# 项目文件结构

以下路径相对于项目根目录。`lib/01_论文原文/`、`lib/02_公式提取/`、`lib/03_场景/`、`lib/04_任务书/` 为只读输入；`experiments/raw/` 保存原始运行记录，`experiments/validation/` 保存校验和校准结果，`experiments/tables/` 保存汇总表，`report/` 保存人工整理的报告。

```text
ffjj/
├── AGENTS.md                           项目边界、操作规则和当前状态
├── README.md                           项目简介、实验设计和常用命令
├── structure.md                        本文件索引
├── .gitignore                          缓存、临时和可再生产物忽略规则
├── lib/
│   ├── plan.md                         当前 S/M/L 多路线实施规划
│   ├── 01_论文原文/                    论文 PDF（只读）
│   ├── 02_公式提取/                    公式与来源索引（只读）
│   ├── 03_场景/                        config、A/B 地图、P_s/R 基准（只读）
│   └── 04_任务书/                      任务书（只读）
├── src/
│   ├── algorithms/
│   │   ├── astar.py                    标准几何 A*
│   │   ├── risk_astar.py               RiskA*、LOS 后优化和风险积分搜索
│   │   ├── rc_astar.py                 RC-A*、动态风险启发和转角约束
│   │   ├── rrt_star.py                 RRT*、选父、重连和理论近邻半径
│   │   └── informed_rrt_star.py        Informed RRT* 椭球采样
│   ├── core/
│   │   ├── coords.py                   世界坐标与体素索引转换
│   │   ├── grid.py                     26 邻域、边界和转角过滤
│   │   ├── collision.py                节点/边碰撞与 NaN 风险检查
│   │   ├── metrics.py                  长度、小时制风险和综合代价
│   │   └── types.py                    PlanRequest、PathResult、PlannerBase、PLANNERS
│   ├── experiments/
│   │   ├── config.py                   严格类型化 TOML 配置加载与哈希
│   │   ├── route_generator.py          候选起终点、S/M/L 分位和路线冻结
│   │   ├── route_complexity.py         路线复杂度诊断
│   │   └── evaluate_run.py             单次路径合法性复核和指标计算
│   ├── io/
│   │   └── scene.py                    场景、真实 R 和任务端点加载
│   ├── risk/
│   │   ├── ps.py                       P_s 遮蔽系数
│   │   ├── risk_matrix.py              R 中间量和全量矩阵
│   │   ├── verify_ps.py                P_s 基准校验
│   │   └── verify_r.py                 R 窗口、探针与全局校验
│   ├── inspection/
│   │   └── inspect_scene.py            场景只读信息采集
│   └── validation/
│       ├── check_data_contract.py      场景数组契约检查
│       ├── verify_align.py             窗口与探针索引对齐检查
│       └── audit_route_manifest.py     冻结路线合法性、配额和统计审计
├── tests/
│   ├── test_astar.py                   标准 A* 手算测试
│   ├── test_risk_astar.py              RiskA* 代价、启发、LOS 和失败状态
│   ├── test_rc_astar.py                RC-A* 边代价、包围盒和转角
│   ├── test_rrt_star.py                Steer、Near、选父、重连和避障
│   ├── test_informed_rrt_star.py       椭球中心、半轴、退化与父类复用
│   ├── test_experiment_config.py       三套配置和严格字段校验
│   ├── test_route_generation.py        候选池、seed 复现、分位和冻结清单
│   ├── test_route_audit.py             路线合法性审计
│   ├── test_experiments_run.py         状态、合法性复核、并发、断点和配置快照
│   ├── test_calibration.py             预算和 worker 校准
│   └── test_aggregate.py               成功率、分层统计、80% 门槛和覆盖审计
├── experiments/
│   ├── configs/
│   │   ├── formal.toml                 S/M/L 正式实验配置
│   │   ├── smoke.toml                  单路线五算法冒烟配置
│   │   └── calibration.toml            预算与并行吞吐校准配置
│   ├── run.py                          路线驱动正式运行器
│   ├── calibrate.py                    时间预算、迭代预算和 worker 校准
│   ├── aggregate.py                    原始 JSONL 汇总与排名
│   ├── routes/
│   │   ├── sml_routes.jsonl            110 条冻结正式路线
│   │   ├── sml_routes.manifest.json    候选池、分位和配额审计信息
│   │   └── smoke_routes.jsonl          冒烟路线
│   ├── raw/
│   │   ├── smoke/                      五算法数据流冒烟原始记录
│   │   ├── calibration/                预算与 worker 校准原始记录
│   │   └── sml/                        正式原始记录和配置快照
│   ├── validation/
│   │   ├── route_audit.json            冻结路线审计结果
│   │   └── legacy/                     早期冒烟和快速校准历史记录
│   ├── tables/
│   │   ├── calibration_summary.csv     校准汇总
│   │   ├── calibration_summary.recommendation.json
│   │   └── sml/                        正式 S/M/L 汇总
│   ├── figures/                        图表产物
│   └── archive/                        历史固定任务及预算矩阵归档
├── report/
│   ├── 实验报告.md                     历史 60/180/600 s 固定任务实验报告
│   ├── assumptions.md                  工程假设、容差和口径记录
│   └── AI使用说明.md                   AI 参与环节与人工核查说明
└── tmp/                                可删除的草稿、缓存和一次性诊断
```

文件放置规则：

- 实际运行产生的原始 JSONL 放 `experiments/raw/`。
- 冒烟和校准的运行原始 JSONL 放 `experiments/raw/`。
- 路线审计、数据契约、对齐和模型校验等脚本结果放 `experiments/validation/`。
- 汇总 CSV/JSON 放 `experiments/tables/`，图表放 `experiments/figures/`。
- 人工整理的说明和结论放 `report/`。
- 草稿和一次性文件放 `tmp/`，不进入正式实验数据链。
