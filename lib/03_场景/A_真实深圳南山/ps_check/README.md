# `A_真实深圳南山\ps_check` · 遮蔽系数对数

这里存的是遮蔽系数场 `P_s` 的期望值。生成器 `04_工具\build_risk_matrix.py` 会按下面的映射算出 `P_s`，和风险矩阵 R 分开验，目的是让"遮蔽映射改错"和"R 的公式改错"不互相掩盖。

上级契约见 `../../README.md`，判分与实验口径见 `../../../04_任务书/任务书_v3.md`。

## 1 公式

```
cov(i,j) = building_footprint 在 21×21 方形窗口内的均值
           窗口以 (i,j) 为中心，边界用 reflect 填充
P_s(i,j) = 10 · min(1, cov(i,j) / 1)
```

参数从 `../../config.json` 的 `supplementary` 读：`P_S_SCALE=10`、`P_S_C_REF=1`、`P_S_WINDOW=21`。不要另写常量。因为覆盖率 `cov` 恒在 [0,1]，本数据集中 `min(1, cov/1)` 等于 `cov` 本身，这个 min 是留给 `P_S_C_REF` 取别的值时用的。

`P_s` 是 0~10 的 Drones 表1 遮蔽刻度，**无高度维**：同一 `(i,j)` 在全部 61 层取值相同。

这个映射是本数据集自定的简化。Drones 原文的 `P_s` 是地面材质查表（式13 按面积加权），不是由建筑覆盖率算出来的。照原文去做，`P_s` 会是分段常数，R 就对不上。

## 2 文件

| 文件 | 内容 |
|---|---|
| `ps_summary.json` | 公式、参数、本场景的 min/max/mean/median、满遮蔽格数、窗口索引 |
| `ps_windows.npz` | `blocks` (6,64,64) float32、`files` (6,)、`i0`/`j0`/`z` (6,)、`meta` |
| `ps_probes.csv` | 60 行 `i,j,Ps_expected`，其中 15 个点落在边界 10 格以内 |

取值映射：

```
blocks[k][a, b] == P_s[i0[k] + a, j0[k] + b]
```

六个窗口与 `../slices/` 的六个风险窗口位置相同（`../slices/index.json` 给的是同一组 `i0`/`j0`），所以 P_s 窗口和 R 窗口可以对着看。窗口名里的 `h030/h060/h090` 只是沿用 R 窗口的命名，P_s 与高度无关。

## 3 校验

```python
import json
import numpy as np
from pathlib import Path

here = Path(".")
S = json.loads((here / "ps_summary.json").read_text(encoding="utf-8"))
Ps = ...                                   # 生成器的 P_s 输出，或你自己改过的版本，(1200,1200)

assert Ps.shape == (1200, 1200)
stats = {"ps_min": Ps.min(), "ps_max": Ps.max(),
         "ps_mean": Ps.mean(), "ps_median": np.median(Ps)}
for k, mine in stats.items():
    assert abs(float(mine) - float(S[k])) <= 1e-6, (k, mine, S[k])

W = np.load(here / "ps_windows.npz")
for k in range(len(W["files"])):
    ref = W["blocks"][k]
    mine = Ps[W["i0"][k]:W["i0"][k] + 64, W["j0"][k]:W["j0"][k] + 64]
    err = float(np.max(np.abs(mine - ref)))
    assert err <= 1e-6, (W["files"][k], err)

with open(here / "ps_probes.csv", encoding="utf-8") as fh:
    next(fh)
    for line in fh:
        i, j, exp = line.strip().split(",")
        err = abs(float(Ps[int(i), int(j)]) - float(exp))
        assert err <= 1e-6, (i, j, err)

print("PS PASS")
```

容差是绝对误差 1e-6。P_s 取值 0~10，这个容差等于"保留四位有效数字之后不追究"，够宽，但不足以让错误填充方式蒙混过关。

## 4 本场景参考值

```
ps_min    = 0.0
ps_max    = 10.0
ps_mean   = 2.154196428571429
ps_median = 1.360544217687075
满遮蔽格数 = 18926
```

## 5 三处容易踩的坑

1. 边界用零填充或 nearest。`ps_probes.csv` 里 15 个边界点会立刻挂。窗口边长 21，边界影响 10 格宽的一条，占比不小。
2. 把 `P_s` 当分段常数（建筑格 10、空地 0）。它的全场均值几乎和正确值一样，A 场景两者相差 1.41×10⁻⁴（2.15420 对 2.15406），所以拿均值查不出来；窗口和探针会立刻分开两者。这也是本目录要单给窗口、不只给统计量的原因。
3. 窗口不居中，把 21×21 当成从 `(i,j)` 向右下展开。整体平移 10 格，`blocks[k][0,0]` 就对不上。

## 6 MUST NOT

```
1. 不得修改本目录下的 ps_summary.json / ps_windows.npz / ps_probes.csv
2. 不得把 P_s 写成与 i、j 无关的常数
3. 不得给 P_s 加高度维
4. 不得跳过这一步直接算 R
```
