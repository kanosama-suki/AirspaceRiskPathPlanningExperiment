# M1 全量 R 验收与 M2 入口

## M1 最终状态

A/B 全量 R 均已按现有实现重新生成并校验。窗口和探针逐点结果在已记录的工程容差内，结构及 NaN 位置检查通过。README 的 `1e-5` 严格逐点 MISMATCH 仍如实保留；B 的全局 summary `r_median` / `r_norm` 与精确统计量相差 `1.144675%`，超过 README 的 `1%` 统计容差。该项按 `report/assumptions.md` 记录的 log 直方图基准精度限制接受，不写作计算通过，不阻断 M2。

本次 `python -m src.risk.verify_r --scope full --accept-known-diff` 退出码为 `0`，终端明确打印“B summary 差异已按 assumptions 接受，退出码 0”。另以不带 `--accept-known-diff` 的 full 命令验证，仍以退出码 `1` 结束。`experiments/validation/validation_B.json` 继续保留 `summary_status: MISMATCH`，并另记 `known_summary_difference_accepted: true`、`run_accepted: true`；两种状态含义不同。

## 场景结构与统计确认

| 场景 | R.shape | NaN 数 | finite 数 | NaN 与建筑体素数 |
|---|---|---:|---:|---|
| A | `(1200, 1200, 61)` | `2,921,211` | `84,918,789` | 一致 |
| B | `(1200, 1200, 61)` | `8,416,476` | `79,423,524` | 一致 |

窗口/探针相对误差和状态来自 `experiments/validation/validation_A.json`、`validation_B.json`：

| 场景 | 全量窗口最大相对误差 | 超出工程容差窗口点 | 全部探针严格通过/失败 | 超出工程容差探针 |
|---|---:|---:|---:|---:|
| A | `3.169514e-5` | `0` | `150 / 60` | `0` |
| B | `3.170661e-5` | `0` | `140 / 60` | `0` |

探针列中的“严格失败”仍按 README `1e-5` 阈值统计；超出工程容差探针数均为 `0`。summary 对比：A 的精确 median 与估值差异为 `0.888700%`，在 1% 内；B 为 `1.144675%`，保留 `r_median` / `r_norm` MISMATCH，并按已知差异接受。

## 下一步：M2 入口

M1 进入 M2 公共规划框架。以玩具地图上的 `src/core` 公共坐标、网格、碰撞和指标接口及其测试为入口；公共层测试通过后，再接入真实 R 做冒烟。五算法实现属于后续 M3，不在本次验收范围内。

## 复核文件

- `report/assumptions.md`：M1 全局统计容差与 B 场景 summary 差异接受口径。
- `experiments/validation/validation_A.json`、`validation_B.json`：全量校验数据、严格 MISMATCH 和本次运行接受状态。
- `experiments/validation/r_full_summary.txt`：全量逐点与 summary 校验摘要。
