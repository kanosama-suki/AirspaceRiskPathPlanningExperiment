# `B_随机生成城市\slices` · 对数数据契约

写给实现者（人或 Agent）。本文件只覆盖"风险矩阵对数"这一步。完整的场景数据契约、`config.json` 字段说明、坐标约定见上级文件 `../../README.md`。

风险矩阵之前的遮蔽系数 P_s 单独对数，见 `../ps_check/README.md`。那一步不通过，这里一定不对。

- 根目录：本文件所在目录，即 `03_场景\B_随机生成城市\slices\`
- 所有路径相对本文件所在目录
- 本目录所有文件为只读参考数据，不得修改
- 权威数值以 `summary.json` 为准，本文表格为副本

## 1 文件清单

| 文件 | 大小 |
|---|---|
| `index.json` | 1.2 KB |
| `probe_points.csv` | 6.9 KB |
| `summary.json` | 1.5 KB |
| `win_h030_highrisk.npz` | 12.5 KB |
| `win_h030_lowrisk.npz` | 14.4 KB |
| `win_h060_highrisk.npz` | 12.6 KB |
| `win_h060_lowrisk.npz` | 14.5 KB |
| `win_h090_highrisk.npz` | 9.9 KB |
| `win_h090_lowrisk.npz` | 14.5 KB |

## 2 权威期望值

本场景的风险矩阵，算完后逐项对照。形状恒为 `(1200, 1200, 61)`，建筑格为 `np.nan`。

```text
scene                = "synthetic"
r_units              = "casualties per flight hour"
shape                = [1200, 1200, 61]
n_obstacle_cells     = 8416476
n_finite_cells       = 79423524
finite_ratio         = 0.9041840163934426
r_min                = 8.617466007269925e-13
r_max                = 1.847495134654764e-8
r_mean               = 1.6431347589892868e-9
r_median             = 5.30884444230988e-10
r_norm               = 5.30884444230988e-10
layer_mean_h30       = 2.0317983765555577e-9
layer_mean_h90       = 1.4482712686003652e-9
layer_mean_monotonic_decreasing = true
```

中间量（两套场景相同，只依赖机体参数与高度）：

```text
v_p_ter_m_s          = 4.281501814003186
E_crash_p_J          = 84.32378580323783
E_crash_b_h30_J      = 2704.7999999999997
A_c_b_h30_m2         = 3.7532642751082506
A_c_b_h90_m2         = 2.829719657490776
```

`E_crash_p_J = 84.32` 大于 β = 34，降落伞三分段公式恒走第一分支。

## 3 窗口清单

映射关系：`R_win[a, b] == R[i0 + a, j0 + b, int(z) - 30]`

| 文件 | z (m) | i0 | j0 | tag | 建筑格数 | 窗口风险均值 |
|---|---|---|---|---|---|---|
| `win_h030_highrisk.npz` | 30 | 497 | 255 | highrisk | 644 | 9.0482004111e-9 |
| `win_h030_lowrisk.npz` | 30 | 466 | 1081 | lowrisk | 0 | 1.4124535959e-12 |
| `win_h060_highrisk.npz` | 60 | 497 | 255 | highrisk | 644 | 8.5603408806e-9 |
| `win_h060_lowrisk.npz` | 60 | 466 | 1081 | lowrisk | 0 | 1.4336541936e-12 |
| `win_h090_highrisk.npz` | 90 | 0 | 0 | highrisk | 0 | 7.7745960780e-9 |
| `win_h090_lowrisk.npz` | 90 | 466 | 1081 | lowrisk | 0 | 1.4579738241e-12 |

`tag = highrisk` 表示该高度层内风险均值最高的 64×64 窗口，`lowrisk` 表示最低。同一高度层内两者的比值：30 m 层 6406.0 倍、60 m 层 5971.0 倍、90 m 层 5332.5 倍。

`win_*.npz` 内两个键：`R_win`（float32，(64,64)，建筑格 NaN）、`meta`（JSON 字符串，含 z / i0 / j0 / shape / convention）。

## 4 探针文件

`probe_points.csv`，共 200 行数据（`open` 180 行，`building` 20 行）。

```text
编码     UTF-8
首行     i,j,h_idx,z,kind,R_expected
sort     未排序，顺序无意义
i        int     体素 i 索引，[0,1199]
j        int     体素 j 索引，[0,1199]
h_idx    int     高度层索引，[0,60]
z        float   = 30 + h_idx
kind     str     "open" 或 "building"
R_expected str   open 行为 %.10e 浮点字面量；building 行恒为 NaN
```

## 5 对数协议

三步，顺序执行，前一步不通过不进入下一步。

| 步骤 | 内容 | 阈值 |
|---|---|---|
| 1 | 五个全局统计量与三个计数 | 统计量相对误差 ≤ 1%；计数完全相等 |
| 2 | 六个窗口逐元素 | NaN 位置完全一致；空中格相对误差 ≤ 1e-5 |
| 3 | 200 个探针点逐点 | open 行相对误差 ≤ 1e-5；building 行必须是 NaN |

误差落在 1e-5 与 1e-2 之间要排查精度来源，超过 1e-2 判不通过。

`r_median` 我方用 log 直方图估计，不是精确排序中位数。你的精确中位数与它相差 1% 以内即算通过。

## 6 校验脚本

放在本目录下直接运行。`R` 换成 `04_工具\build_risk_matrix.py` 算出来的阵列即可。

```python
import json
import numpy as np
from pathlib import Path

sl = Path(".")                                  # 本目录，即 B_随机生成城市\slices
S = json.loads((sl / "summary.json").read_text(encoding="utf-8"))

R = ...                                         # 生成器的输出，shape (1200,1200,61)，建筑格为 np.nan

# --- 结构与计数 ---
assert R.shape == (1200, 1200, 61), R.shape
assert int(np.isnan(R).sum()) == S["n_obstacle_cells"]
assert int(np.isfinite(R).sum()) == S["n_finite_cells"]

# --- 全局统计量，相对误差 <= 1% ---
finite = R[np.isfinite(R)]
r_mean = float(finite.mean())
r_min = float(finite.min())
r_max = float(finite.max())
r_median = ...                                  # 你的中位数实现
r_norm = min(r_mean, r_median)                  # 式(19)

def rel(x, y):
    return abs(x - y) / abs(y)

for name, mine, ref in [("r_mean", r_mean, S["r_mean"]),
                        ("r_median", r_median, S["r_median"]),
                        ("r_min", r_min, S["r_min"]),
                        ("r_max", r_max, S["r_max"]),
                        ("r_norm", r_norm, S["r_norm"])]:
    err = rel(mine, ref)
    print(f"{name:10s} mine={mine:.6e} ref={ref:.6e} rel={err:.3e}")
    assert err <= 0.01, (name, err)

# --- 窗口逐点 ---
idx = json.loads((sl / "index.json").read_text(encoding="utf-8"))
for w in idx["windows"]:
    ref = np.load(sl / w["file"])["R_win"]
    mine = R[w["i0"]:w["i0"] + 64, w["j0"]:w["j0"] + 64, int(w["z"]) - 30]
    assert mine.shape == (64, 64), w["file"]
    assert np.array_equal(np.isnan(mine), np.isnan(ref)), f"{w['file']}: NaN 位置不一致"
    m = np.isfinite(ref)
    if m.any():
        err = np.max(np.abs(mine[m].astype(np.float64) - ref[m]) / np.abs(ref[m]))
        assert err <= 1e-5, (w["file"], err)

# --- 探针逐点 ---
with open(sl / "probe_points.csv", encoding="utf-8") as fh:
    header = fh.readline().strip()
    assert header == "i,j,h_idx,z,kind,R_expected", header
    n = 0
    for line in fh:
        i, j, h_idx, z, kind, r_exp = line.strip().split(",")
        i, j, h_idx = int(i), int(j), int(h_idx)
        mine = R[i, j, h_idx]
        n += 1
        if kind == "building":
            assert np.isnan(mine), f"探针 ({i},{j},{h_idx}) 应为 NaN"
        else:
            ref = float(r_exp)
            assert rel(float(mine), ref) <= 1e-5, (i, j, h_idx, mine, ref)

print("ALL PASS", n, "probes")
```

## 7 本场景特有的事实

```text
城市来源              Voronoi 六分区程序化生成，种子 42
建筑格数 @ h_idx=0    335423
建筑格数 @ h_idx=30   110957
建筑格数 @ h_idx=60   0
存在建筑的最高层      h_idx=49（z=79 m）
```

这三个分层建筑格数是体素化的硬校验点，不涉及任何公式，纯数布尔值。79 m 以上没有建筑，90 m 层全空，这是这套城市与真实城市的显著差异。

## 8 MUST NOT

```text
1. 不得修改本目录下的 summary.json / probe_points.csv / index.json / win_*.npz
2. 不得把 building 类探针填成 0，必须是 np.nan
3. 不得用均值或中位数单独作为归一化基准，式(19) 取两者较小值
4. 不得跳过计数校验直接比统计量，建筑格填 0 会让统计量看起来接近而实际全错
5. 不得假设本场景的数值适用于另一套场景
```
