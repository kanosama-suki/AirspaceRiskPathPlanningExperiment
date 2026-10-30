# 城市空域风险路径规划实验

本项目在同一城市地图、风险矩阵、起终点和预算下，对比五种路径规划算法：

- A*
- RiskA*
- RC-A*
- RRT*
- Informed RRT*

最终比较指标由公共评估器统一计算，主要包括路径长度、风险积分和综合代价。算法返回的路径还会统一检查建筑碰撞、边碰撞、NaN 风险格和转角约束。

项目使用两套城市场景：A 为深圳南山真实建筑场景，B 为随机生成城市。实验包含两个同高度任务和一个跨高度任务，采样算法使用多个随机 seed，图搜索算法使用固定 seed。

## 目录结构

```text
├── README.md                         项目简介、运行入口和目录说明
├── AGENTS.md                         项目边界、操作规则和当前状态
├── plan.md                           实施计划和验收要求
├── structure.md                      完整目录索引
├── lib/                              只读原始资料和场景输入
│   ├── 01_论文原文/                  论文 PDF
│   ├── 02_公式提取/                  公式索引和符号说明
│   ├── 03_场景/                      config、A/B city.npz、P_s/R 基准
│   └── 04_任务书/                    任务书
├── src/
│   ├── core/                         坐标、网格、碰撞、metrics、公共类型
│   ├── io/                           SceneData 和场景加载
│   ├── risk/                         P_s、R、中间量和风险校验
│   ├── algorithms/                   五种规划算法
│   ├── inspection/                   场景信息采集
│   └── validation/                   数据契约和对齐校验
├── tests/                            小地图、真实 R 切片和运行器测试
├── experiments/
│   ├── configs/base.json             场景、任务、算法、seed、预算和并行配置
│   ├── run.py                        正式实验运行器
│   ├── budget_smoke.py               预算扫描工具
│   ├── raw/                          每次运行的原始 JSONL，失败记录也保留
│   ├── validation/                   机器生成的校验日志和 JSON
│   ├── tables/                       汇总表
│   └── figures/                      实验图表
└── report/                           人工整理的实验报告和 AI 使用说明
```

`lib/` 下的原始目录`experiments/raw/` 保存真实运行记录，`experiments/validation/` 保存校验结果，`report/` 保存解释性文字和结论。

## 结论

1. 在当前已完成的 60 s 和 180 s 和600 s中，不变。
2. A* 适合较快完成较简单的任务；RC-A* 在相同成功条件下综合代价略低。
3. 需要稳定路径时优先 RC-A*；需要较短响应时间且任务较简单时可选择 A*；RiskA*、RRT* 和 Informed RRT* 需要更多实验场景和数据
4. 一致。地图复杂度主要影响运行时间和采样算法可行率，没有改变当前条件中结论。

## 常用命令

安装依赖后，在项目根目录执行：

```powershell
# 运行全部测试
python -m pytest -q -p no:cacheprovider

# 检查场景数据契约
python -m src.validation.check_data_contract --config lib/03_场景/config.json --scenes A B

# 校验 P_s
python -m src.risk.verify_ps --config lib/03_场景/config.json --scenes A B

# 校验 R 的样本范围
python -m src.risk.verify_r --config lib/03_场景/config.json --scene A --scope sample
python -m src.risk.verify_r --config lib/03_场景/config.json --scene B --scope sample

# 运行 A/B 的任务 3，8 个进程，60 秒预算
python -m experiments.run --profile short_60s --workers 8 --scenes A B --missions 3 --run-id local_60s_task3_8p

# 运行 A/B 的任务 3，8 个进程，180 秒预算
python -m experiments.run --profile local_180s --workers 8 --scenes A B --missions 3 --run-id local_180s_task3_8p
```

正式运行器会为每条条件保存场景、任务、算法、seed、预算、配置哈希、状态、路径指标和合法性检查结果。状态包括 `success`、`timeout_with_solution`、`timeout_no_solution`、`no_path` 和 `invalid`。

