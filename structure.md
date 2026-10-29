# 项目文件结构

以下路径相对于项目根目录。每项简述对应文件或目录的用途。

```text
ffjj/
├── AGENTS.md                         项目执行规范、目录边界和代码约定
├── plan.md                           项目计划与实施安排
├── structure.md                      项目文件结构及文件用途索引
├── .gitignore                        Git 忽略规则
├── 05_规划书/                         规划书及相关材料目录
├── lib/                              论文、公式、场景数据和任务书等输入资料
│   ├── 01_论文原文/
│   │   ├── _来源说明.md               论文原文文件来源说明
│   │   ├── A_基于风险约束的城市空域无人机安全路径规划.pdf
│   │   ├── B_风险矩阵方法_Drones2024_8_678.pdf
│   │   ├── C_RRTStar_Karaman_Frazzoli_2011.pdf
│   │   ├── D_InformedRRTStar_Gammell_2014.pdf
│   │   └── E_RiskA_Primatesta_2019_postprint.pdf
│   │       上述 PDF 分别保存路径规划、风险矩阵、RRT*、Informed RRT* 和 RiskA* 的论文原文
│   ├── 02_公式提取/
│   │   ├── 公式提取.md                论文公式及符号的整理记录
│   │   └── Drones_678_公式权威源.xml   风险矩阵论文公式的 XML 来源材料
│   ├── 03_场景/
│   │   ├── README.md                  场景数据格式、索引和校验数据契约
│   │   ├── config.json                场景及参数配置来源
│   │   ├── A_真实深圳南山/
│   │   │   ├── city.npz               场景 A 的城市数组数据
│   │   │   ├── ps_check/
│   │   │   │   ├── README.md          遮蔽系数校验资料说明
│   │   │   │   ├── ps_summary.json    全局遮蔽系数校验摘要
│   │   │   │   ├── ps_windows.npz     窗口遮蔽系数校验数据
│   │   │   │   └── ps_probes.csv      探针遮蔽系数校验数据
│   │   │   └── slices/
│   │   │       ├── README.md          风险切片校验数据说明
│   │   │       ├── summary.json       风险切片统计摘要
│   │   │       ├── index.json         风险窗口及索引清单
│   │   │       ├── probe_points.csv   探针坐标及基准值
│   │   │       ├── win_h030_highrisk.npz 高度 030 的高风险窗口基准数组
│   │   │       ├── win_h030_lowrisk.npz  高度 030 的低风险窗口基准数组
│   │   │       ├── win_h060_highrisk.npz 高度 060 的高风险窗口基准数组
│   │   │       ├── win_h060_lowrisk.npz  高度 060 的低风险窗口基准数组
│   │   │       ├── win_h090_highrisk.npz 高度 090 的高风险窗口基准数组
│   │   │       └── win_h090_lowrisk.npz  高度 090 的低风险窗口基准数组
│   │   └── B_随机生成城市/
│   │       ├── city.npz               场景 B 的城市数组数据
│   │       ├── 生成参数.md            场景 B 的生成参数说明
│   │       ├── ps_check/              场景 B 的遮蔽系数校验资料，文件用途同场景 A
│   │       └── slices/                场景 B 的风险切片校验资料，文件用途同场景 A，含同名窗口基准数组
│   └── 04_任务书/
│       └── 任务书.md                  项目任务目标、约束和交付要求
├── src/                              项目 Python 程序
│   ├── core/                         公共坐标、网格、碰撞和路径评估模块目录
│   ├── algorithms/                   路径规划算法模块目录
│   ├── io/                           配置、场景及结果读写模块目录
│   ├── risk/                         风险矩阵生成、读取和风险模型相关校验模块目录
│   ├── inspection/
│   │   └── inspect_scene.py           只读读取场景容器和现有资料，并输出场景信息记录
│   └── validation/
│       ├── verify_align.py            只读检查风险摘要、窗口、探针和索引信息
│       └── check_data_contract.py     只读检查场景数据形状、文件及索引范围契约
├── tests/                            自动化测试目录
├── experiments/
│   ├── configs/                      实验批次配置目录
│   ├── raw/                          实验原始记录及场景信息采集记录目录
│   │   ├── inspect_A.txt              场景 A 容器与现有资料信息记录
│   │   └── inspect_B.txt              场景 B 容器与现有资料信息记录
│   ├── validation/                   场景验证程序的机器可读结果目录
│   │   ├── align_A.txt                场景 A 风险基准索引检查日志
│   │   ├── align_B.txt                场景 B 风险基准索引检查日志
│   │   ├── contract_A.json            场景 A 数据契约检查结果
│   │   └── contract_B.json            场景 B 数据契约检查结果
│   ├── tables/                       实验汇总表目录
│   └── figures/                      实验图表目录
└── report/
    ├── parameter_sources.md           参数来源、键路径、单位和候选使用模块映射
    ├── assumptions.md                 审计假设、待核对事项及其分类记录
    └── data_validation.md             场景数据检查事实、失败项和 M1 阻断摘要
```

场景 A 与场景 B 的 `ps_check/`、`slices/` 中同名文件用途相同，分别对应各自场景的数据。
