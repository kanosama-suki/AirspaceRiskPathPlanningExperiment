# B 场景 summary 中位数口径诊断

诊断范围：只读取 A/B 的 `slices/summary.json`、场景 README 与已有全量校验 JSON。没有重算或写出全量 R。现有全量校验 JSON 中的精确统计量来自已生成的完整 R，精确中位数采用 `numpy.partition`。

## 1. summary.json 的 median 来源

B 的 `slices/summary.json` 原始统计字段：

| 字段 | 原始值 | 说明 |
|---|---:|---|
| `shape` | `[1200, 1200, 61]` | 原始字段 |
| `r_mean` | `1.6431347589892868e-09` | 原始字段 |
| `r_median` | `5.30884444230988e-10` | 原始字段 |
| `r_norm` | `5.30884444230988e-10` | 原始字段 |
| `r_min` | `8.617466007269925e-13` | 原始字段 |
| `r_max` | `1.847495134654764e-08` | 原始字段 |
| `n_finite_cells` | `79423524` | 有限值格数 |
| `n_obstacle_cells` | `8416476` | summary 没有 `nan_count` 字段；README 契约说明它对应 R 中应为 NaN 的建筑格数 |
| `finite_ratio` | `0.9041840163934426` | 原始字段 |

B 的 summary 根层及嵌套字段中均不存在 `histogram`、`bins`、`counts`、`edges`、`quantile`。所以没有可复核的桶边界或桶计数。README 明确称 summary 的 `r_median` 是“log 直方图估计”，因此它是估值，不是精确排序中位数；但现有材料不能确定该估值具体采用桶中心还是桶内插值。

## 2. 三种中位数口径对比

比较基准为 B summary 的 `r_median = 5.30884444230988e-10`。相对误差按 `abs(计算值 - summary值) / abs(summary值)` 计算。

| 口径 | 中位数 | 相对误差 | 计算状态 |
|---|---:|---:|---|
| 精确中位数（当前完整 R 的有限值排序统计，`numpy.partition`） | `5.369613460126125e-10` | `1.1446750508%` | 已有 `experiments/validation/validation_B.json` 全量统计 |
| 直方图桶中心中位数 | 无法计算 | 无法计算 | summary 未提供 bins / edges / counts |
| 直方图累计频率线性插值中位数 | 无法计算 | 无法计算 | summary 未提供 bins / edges / counts |

summary 的 `r_median` 已由 README 定性为 log 直方图估值，但缺少实际分桶数据与估值规则，无法在“桶中心”和“桶内线性插值”两种口径之间判断哪种更接近它。也无法用自选分桶替代缺失的基准分桶来得出结论。已知的精确中位数比 summary 值高 `1.1446750508%`，超过 README 的 `1%` 统计容差。

## 3. r_norm 口径

B summary 中 `min(r_mean, r_median) = 5.30884444230988e-10`，与其 `r_norm` 完全相等。A summary 也满足同一关系。已有全量校验统计中，B 精确 `r_mean = 1.643152702393654e-09`、精确 `r_median = 5.369613460126125e-10`，所以按精确统计计算的 `min(r_mean, r_median)` 为 `5.369613460126125e-10`。

| B 的 median 口径 | `min(summary r_mean, median)` | 与 summary `r_norm` 的关系 |
|---|---:|---|
| summary log 直方图估值 | `5.30884444230988e-10` | 等于 summary `r_norm` |
| 当前完整 R 的精确中位数 | `5.369613460126125e-10` | 比 summary `r_norm` 高 `1.1446750508%` |
| 直方图桶中心 | 无法计算 | 缺少分桶数据 |
| 直方图线性插值 | 无法计算 | 缺少分桶数据 |

建议风险计算继续对当前 R 使用实际计算得到的中位数，并按 `r_norm = min(r_mean, r_median)` 计算；与 summary 对照时保留“精确值对直方图估值”的比较。不要直接把 summary 的估值写回精确统计或归一化计算。B 的 `r_norm` 仍应标记为超过 1% 阈值的 MISMATCH；若要复现 summary 的 `r_norm`，需要先取得原始直方图分桶和估值算法。

## 4. A 场景对照

A 的 summary 同样没有 `histogram`、`bins`、`counts`、`edges`、`quantile` 字段。README 对 summary `r_median` 的定义适用于此数据契约：它也是 log 直方图估值，而非精确排序中位数。

| A 字段 | summary 原始值 | 已有全量精确统计值 |
|---|---:|---:|
| `r_mean` | `5.748326583935336e-10` | `5.748376018438183e-10` |
| `r_median` | `4.31519076827765e-10` | `4.2768416752084244e-10` |
| `r_norm` | `4.31519076827765e-10` | `4.2768416752084244e-10` |
| `n_finite_cells` | `84918789` | `84918789` |
| `n_obstacle_cells` | `2921211` | `2921211` |

A 精确中位数相对 summary 估值低 `0.8886998311%`，在 README 的 `1%` 容差内。A 与 B 都使用 summary 直方图估值这一口径，但误差幅度不同；A 在容差内不能证明 B 的误差也应在容差内，更不能反推出两场景采用的桶边界或估值细节。

## 5. README 容差语义

README 原文：

> 对照 `summary.json` 的 `r_mean`、`r_median`、`r_min`、`r_max`、`r_norm`，要求相对误差 ≤ 1%。
>
> `r_median` 我方用 log 直方图估计，不是精确排序中位数。若你的精确中位数与它相差 1% 以内，视为通过。

README 另将 `r_norm` 定义为 `min(r_mean, r_median)`，并在统计量字段说明中注明 summary 的 median 是 log 直方图估计、非精确排序中位数。

因此，对 median 而言，1% 容差明确用于“重算的精确中位数 vs summary 的直方图估值”，不是两个精确统计量之间的比较。README 没说明 log 直方图的 bins / edges / counts，也没说明采用桶中心还是桶内插值；仅从现有材料无法判断 summary 估值的具体算法。

## 6. 结论

- summary 的 `r_median` 是 log 直方图估值，不是精确排序中位数；summary 文件没有保存 histogram 的 bins、edges 或 counts。
- B 的精确中位数与 summary 相差 `1.1446750508%`。分桶造成该差异在数值上可能，但因基准分桶和算法均缺失，当前不能确认或复现这一解释；两种指定的直方图候选值也无法计算。
- 已知 summary 的 `r_norm` 等于 `min(summary r_mean, summary r_median)`；当前完整 R 的 `r_norm` 应继续由当前完整 R 的 `r_mean` 和精确中位数计算。B 与 summary 的对照继续保留 MISMATCH。
- 不建议现在把 `1.144675%` 定为已确认的“直方图估值精度限制”或写成已接受结论。若要在 assumptions 中记录，只能写成待确认假设，并保留当前 MISMATCH，直到取得基准直方图数据或其生成规则。
- 待人工确认：B summary 直方图的实际 bin edges / counts、log 空间分桶定义、桶内中位数估值方法，以及 `r_norm` 在基准生成端是否直接使用该估值。
