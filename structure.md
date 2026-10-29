# 项目文件结构

以下路径相对于项目根目录；只列出当前仓库中的项目文件和目录。

```text
ffjj/
├── AGENTS.md                                  项目操作规范、只读边界和代码约定
├── plan.md                                    项目里程碑、实现安排和当前状态
├── structure.md                               项目目录和文件用途索引
├── .gitignore                                 Git 忽略规则
├── docs/
│   └── superpowers/plans/
│       ├── 2026-10-29-artifact-layout.md      实验产物目录整理计划
│       ├── 2026-10-29-astar.md                标准 A* 实现与验证计划
│       ├── 2026-10-29-full-r-generation.md    全量 R 生成与校验计划
│       ├── 2026-10-29-informed-rrt-star.md    Informed RRT* 椭球采样与冒烟计划
│       ├── 2026-10-29-m1-acceptance.md        M1 验收与已知差异处理计划
│       ├── 2026-10-29-m2-public-layer.md       M2 公共层接入真实 R 实施计划
│       ├── 2026-10-29-risk-astar.md             RiskA* 实现与校验计划
│       ├── 2026-10-29-rc-astar.md                RC-A* 实现与校验计划
│       ├── 2026-10-29-rrt-star.md                RRT* 实现与冒烟计划
│       └── 2026-10-29-r-risk-intermediates.md R 中间量实现与局部校验计划
├── lib/                                       只读输入资料
│   ├── 01_论文原文/
│   │   ├── _来源说明.md                        论文文件来源记录
│   │   ├── A_基于风险约束的城市空域无人机安全路径规划.pdf  风险约束路径规划论文
│   │   ├── B_风险矩阵方法_Drones2024_8_678.pdf 风险矩阵与降落伞模型论文
│   │   ├── C_RRTStar_Karaman_Frazzoli_2011.pdf RRT* 原始论文
│   │   ├── D_InformedRRTStar_Gammell_2014.pdf  Informed RRT* 原始论文
│   │   └── E_RiskA_Primatesta_2019_postprint.pdf RiskA* 论文
│   ├── 02_公式提取/
│   │   ├── 公式提取.md                         论文公式和符号索引
│   │   └── Drones_678_公式权威源.xml            风险矩阵论文公式的 XML 来源
│   ├── 03_场景/
│   │   ├── README.md                           场景数据契约、坐标、索引和校验说明
│   │   ├── config.json                         场景与模型参数来源
│   │   ├── A_真实深圳南山/
│   │   │   ├── city.npz                        场景 A 的城市数组
│   │   │   ├── ps_check/
│   │   │   │   ├── README.md                   P_s 基准文件说明
│   │   │   │   ├── ps_summary.json             P_s 全局基准统计
│   │   │   │   ├── ps_windows.npz              P_s 窗口基准
│   │   │   │   └── ps_probes.csv               P_s 探针基准
│   │   │   └── slices/
│   │   │       ├── README.md                   R 窗口与探针基准说明
│   │   │       ├── index.json                  R 窗口和探针索引清单
│   │   │       ├── probe_points.csv            R 探针坐标与基准值
│   │   │       ├── summary.json                R 全局统计摘要
│   │   │       ├── win_h030_highrisk.npz        高度 030 的高风险窗口基准数组
│   │   │       ├── win_h030_lowrisk.npz         高度 030 的低风险窗口基准数组
│   │   │       ├── win_h060_highrisk.npz        高度 060 的高风险窗口基准数组
│   │   │       ├── win_h060_lowrisk.npz         高度 060 的低风险窗口基准数组
│   │   │       ├── win_h090_highrisk.npz        高度 090 的高风险窗口基准数组
│   │   │       └── win_h090_lowrisk.npz         高度 090 的低风险窗口基准数组
│   │   ├── B_随机生成城市/
│   │   │   ├── city.npz                        场景 B 的城市数组
│   │   │   ├── 生成参数.md                      场景 B 的生成参数说明
│   │   │   ├── ps_check/
│   │   │   │   ├── README.md                   场景 B 的 P_s 基准文件说明
│   │   │   │   ├── ps_summary.json             场景 B 的 P_s 全局基准统计
│   │   │   │   ├── ps_windows.npz              场景 B 的 P_s 窗口基准
│   │   │   │   └── ps_probes.csv               场景 B 的 P_s 探针基准
│   │   │   └── slices/
│   │   │       ├── README.md                   场景 B 的 R 窗口与探针基准说明
│   │   │       ├── index.json                  场景 B 的 R 窗口和探针索引清单
│   │   │       ├── probe_points.csv            场景 B 的 R 探针坐标与基准值
│   │   │       ├── summary.json                场景 B 的 R 全局统计摘要
│   │   │       ├── win_h030_highrisk.npz       场景 B 高度 030 的高风险窗口基准
│   │   │       ├── win_h030_lowrisk.npz        场景 B 高度 030 的低风险窗口基准
│   │   │       ├── win_h060_highrisk.npz       场景 B 高度 060 的高风险窗口基准
│   │   │       ├── win_h060_lowrisk.npz        场景 B 高度 060 的低风险窗口基准
│   │   │       ├── win_h090_highrisk.npz       场景 B 高度 090 的高风险窗口基准
│   │   │       └── win_h090_lowrisk.npz        场景 B 高度 090 的低风险窗口基准
│   └── 04_任务书/
│       └── 任务书.md                            项目任务目标和交付要求
├── src/                                       项目 Python 模块
│   ├── core/
│   │   ├── collision.py                        节点和路径段碰撞检查
│   │   ├── coords.py                           世界坐标与风险栅格索引转换
│   │   ├── grid.py                             搜索网格、邻域和转角检查
│   │   ├── metrics.py                          路径长度、时间、风险和综合代价评估
│   │   └── types.py                             规划请求、路径结果、规划器基类和注册表
│   ├── algorithms/
│   │   ├── __init__.py                          导出并注册当前已实现的五个规划器
│   │   ├── astar.py                              只按几何距离搜索的标准 A* 实现
│   │   ├── informed_rrt_star.py                  Gammell 路径长度椭球采样并复用 RRT* 树逻辑
│   │   ├── rc_astar.py                           距离/风险加权、动态包围盒启发的 RC-A* 实现
│   │   ├── risk_astar.py                         纯风险积分 RiskA* 搜索和 LOS 后优化
│   │   └── rrt_star.py                           均匀采样、理论近邻半径和重连的标准 RRT* 实现
│   ├── experiments/
│   │   ├── __init__.py                          实验模块包声明
│   │   └── smoke_dataline.py                    真实 R 起终点直线数据流冒烟检查
│   ├── io/
│   │   └── scene.py                             只读加载场景数组、R 和规划任务配置
│   ├── inspection/
│   │   └── inspect_scene.py                    只读采集场景容器和基准文件信息
│   ├── risk/
│   │   ├── ps.py                                二维遮蔽系数 P_s 计算
│   │   ├── risk_matrix.py                      R 中间量与风险矩阵计算
│   │   ├── verify_ps.py                         P_s 基准校验及边界模式比较
│   │   └── verify_r.py                          R 单窗口/探针及全量校验
│   └── validation/
│       ├── check_data_contract.py               场景数组、文件和索引范围契约检查
│       └── verify_align.py                       风险摘要、窗口、探针和索引对齐检查
├── tests/
│   ├── test_astar.py                             标准 A* 的手算路径与终止状态测试
│   ├── test_collision.py                        碰撞检查玩具地图测试
│   ├── test_coords.py                           坐标转换玩具例测试
│   ├── test_grid.py                             网格邻域与转角玩具例测试
│   ├── test_informed_rrt_star.py                 椭球参数、采样边界、退化回退和父类复用测试
│   ├── test_metrics.py                          路径指标玩具例测试
│   ├── test_rc_astar.py                          RC-A* 边代价、启发式和转角约束测试
│   ├── test_risk_astar.py                        RiskA* 手算代价、平局和 LOS 测试
│   ├── test_rrt_star.py                          RRT* 步长、近邻、重连和障碍测试
│   ├── test_scene.py                            场景加载路径、R 缓存和数组契约测试
│   ├── test_scene_metrics.py                    真实 R 切片路径指标手算测试
│   └── test_types.py                             公共规划请求、结果和抽象接口测试
├── experiments/
│   ├── configs/                                 实验配置目录，当前为空
│   ├── raw/                                     实际运行原始记录与场景采集记录
│   │   ├── inspect_A.txt                        场景 A 信息采集记录
│   │   ├── inspect_B.txt                        场景 B 信息采集记录
│   │   ├── smoke_astar_A.txt                     场景 A A* 任务 1 真实场景冒烟记录
│   │   ├── smoke_astar_B.txt                     场景 B A* 任务 1 真实场景冒烟记录
│   │   ├── smoke_dataline_A.txt                  场景 A 真实 R 直线数据流冒烟记录
│   │   ├── smoke_dataline_B.txt                  场景 B 真实 R 直线数据流冒烟记录
│   │   ├── smoke_informed_rrt_star_A.txt          场景 A Informed RRT* seed 0/1/2 冒烟记录
│   │   ├── smoke_rc_astar_A.txt                  场景 A RC-A* 任务 1 冒烟记录
│   │   ├── smoke_rc_astar_B.txt                  场景 B RC-A* 任务 1 冒烟记录
│   │   ├── smoke_risk_astar_A.txt                场景 A RiskA* 冒烟与重试记录
│   │   ├── smoke_risk_astar_B.txt                场景 B RiskA* 任务 1 冒烟记录
│   │   └── smoke_rrt_star_A.txt                  场景 A RRT* seed 0/1/2 冒烟记录
│   ├── validation/                              检查脚本生成的日志和机器可读校验结果
│   │   ├── align_A.txt                          场景 A 风险基准索引对齐日志
│   │   ├── align_B.txt                          场景 B 风险基准索引对齐日志
│   │   ├── contract_A.json                      场景 A 数据契约检查结果
│   │   ├── contract_B.json                      场景 B 数据契约检查结果
│   │   ├── ps_check_A.txt                       场景 A P_s 基准校验日志
│   │   ├── ps_check_B.txt                       场景 B P_s 基准校验日志
│   │   ├── r_full_summary.txt                   A/B 全量 R 校验摘要
│   │   ├── r_probe_A.txt                         场景 A R 探针校验日志
│   │   ├── r_probe_B.txt                         场景 B R 探针校验日志
│   │   ├── r_window_A.txt                        场景 A R 窗口校验日志
│   │   ├── r_window_B.txt                        场景 B R 窗口校验日志
│   │   ├── validation_A.json                    场景 A 全量 R 校验机器结果
│   │   └── validation_B.json                    场景 B 全量 R 校验机器结果
│   ├── tables/                                  实验统计表输出目录，当前为空
│   └── figures/                                 实验图表输出目录，当前为空
└── report/                                      人工整理的说明、诊断和结论
    ├── AI使用说明.md                             M1/M2/M3 阶段 AI 使用和人工核查记录
    ├── assumptions.md                           参数假设、已知差异和待确认事项
    ├── data_validation.md                        场景数据契约检查摘要
    ├── dp_itemized.md                            开伞距离 d_p 单点逐项诊断
    ├── m1_acceptance.md                          M1 全量 R 验收记录和 M2 入口
    ├── openparachute_diagnosis.md                开伞伤亡面积口径诊断
    ├── parameter_sources.md                      参数来源、键路径、单位和候选模块映射
    ├── ps_diagnosis_A.md                          场景 A 的 P_s 输入与边界诊断
    ├── ps_diagnosis_B.md                          场景 B 的 P_s 输入与边界诊断
    ├── r_tolerance_decision.md                    R 校验工程容差决策记录
    ├── reflect_disambig.md                        reflect 边界映射消歧记录
    ├── residual_source.md                         R 残差来源诊断
    ├── speed_sensitivity.md                       巡航速度敏感性结果说明
    ├── summary_median_diagnosis.md                 summary 中位数口径诊断
    └── time_interval_explanation.md               开伞两阶段时间区间解释
```
