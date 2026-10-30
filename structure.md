# 项目文件结构

以下路径相对于项目根目录。原始资料只读；运行结果和人工报告按约定分目录保存。

```text
ffjj/
├── AGENTS.md                         项目边界、命令和当前状态
├── plan.md                           里程碑与实施计划
├── structure.md                      本目录索引
├── .gitignore                        忽略缓存、实验输出和报告
├── lib/                              只读资料与场景输入
│   ├── 01_论文原文/                  论文 PDF
│   ├── 02_公式提取/                  公式、符号和权威来源索引
│   ├── 03_场景/                      config、A/B city.npz、任务和 R/P_s 基准
│   └── 04_任务书/                    任务书
├── src/                              项目源码
│   ├── core/                         坐标、网格、碰撞、metrics 和公共类型
│   ├── algorithms/                   astar、risk_astar、rc_astar、rrt_star、informed_rrt_star
│   ├── io/                           场景加载与 SceneData
│   ├── risk/                         P_s、R、中间量和风险校验
│   ├── inspection/                   场景信息只读采集
│   └── validation/                   数据契约和基准对齐校验
├── tests/                            玩具地图、真实 R 切片和运行器测试（test_*.py）
├── experiments/                      正式实验配置、运行和输出
│   ├── configs/base.json             A/B、任务、算法、seed、预算和并行设置
│   ├── run.py                        正式运行器和统一合法性复核
│   ├── budget_smoke.py               预算扫描工具
│   ├── raw/                          原始运行记录，按红线保留失败和历史记录
│   │   ├── 60/                       本地 60 秒批次（已完成）
│   │   ├── 180/                      本地 180 秒批次（已完成）
│   │   ├── config_snapshots/         历史配置快照
│   │   └── 600/                      服务器 600 秒批次（已复制到本地）
│   ├── validation/                   校验脚本生成的日志和 JSON（运行时生成）
│   ├── tables/                       汇总 CSV（运行时生成）
│   └── figures/                      实验图表（运行时生成）
└── report/                           人工整理说明和结论（运行时或人工生成）
```
