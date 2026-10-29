# 场景数据检查摘要

本文件汇总 `src/inspection/` 的场景信息采集记录和 `src/validation/` 的验证结果。检查读取配置、`city.npz`、切片索引和基准文件清单，没有生成风险矩阵或计算遮蔽系数。

## 检查结果

| 场景 | PASS | FAIL | 结论 |
|---|---:|---:|---|
| A | 4 | 5 | 未通过数据契约检查 |
| B | 4 | 5 | 未通过数据契约检查 |

两个场景通过的项目相同：`pop_density` 平面形状符合配置；索引列出的窗口文件和探针文件存在；`summary.json` 含所需统计字段；`ps_check/` 中可找到全局、窗口和探针三类基准。

两个场景失败的项目相同：`city.npz` 不含完整 `R` 数组。因此无法核实 `R.shape`、`R` 的 NaN 数与 `building_mask` 的对应关系、`building_mask.shape` 与实际 `R.shape` 的关系，也无法依据实际 `R.shape` 核验窗口和探针索引范围。检查没有用 summary 或窗口数组替代完整 `R`。

## M1 状态

当前结构与文件存在性检查不足以证明场景数据和风险矩阵验证通过。按规划书的 M1 验收条件，A、B 均有失败项，M1 尚未通过，不能进入 M2。阻断项是两个场景的 `city.npz` 均缺少可供契约检查的完整 `R` 数组；相关形状、NaN 语义及索引范围检查仍未完成。

## 检查记录

- 场景信息采集：`experiments/raw/inspect_A.txt`、`experiments/raw/inspect_B.txt`
- 基准索引检查：`experiments/validation/align_A.txt`、`experiments/validation/align_B.txt`
- 结构契约检查：`experiments/validation/contract_A.json`、`experiments/validation/contract_B.json`
