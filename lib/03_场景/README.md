# 03_场景 · 数据契约

写给做实验的人（或 Agent）。风险矩阵由 `04_工具\build_risk_matrix.py` 生成，本目录给的是它的输入、契约和校验数据。读完这一份即可开始写算法，不需要再看别的说明文件。

- 根目录：本文件所在目录，即 `03_场景\`
- 本文所有路径均相对于根目录，使用 Windows 反斜杠
- 权威数值以 `<场景>\slices\summary.json` 为准，本文表格为速查副本；两者冲突时以 JSON 为准
- 场景目录名只有两个合法取值：`A_真实深圳南山`、`B_随机生成城市`

## 0 任务映射

| 你要做的事 | 输入 | 输出 |
|---|---|---|
| 生成数据 | `04_工具\build_risk_matrix.py` + `city.npz` + `config.json` | 内存中的 `P_s`（1200×1200）与 `R`（1200×1200×61，建筑格 NaN） |
| 校验 | `<场景>\ps_check\` 与 `<场景>\slices\` | ALL PASS / FAIL |
| 路径规划 | `R` + `building_mask` + `config.json` 的 `table2` | 路径点序列与三个指标 |

## 1 文件清单

```
03_场景\
├─ README.md                          本文件
├─ config.json                        4.5 KB    全部参数的唯一来源
├─ A_真实深圳南山\
│  ├─ city.npz                        2158.9 KB 城市场景
│  ├─ ps_check\                       遮蔽系数校验（第一步对数）
│  └─ slices\
│     ├─ README.md                    3.5 KB    对数协议（本文件的精简版）
│     ├─ summary.json                 2 KB      期望统计量（权威）
│     ├─ probe_points.csv             7 KB      探针点期望值
│     ├─ index.json                   1 KB      窗口索引
│     ├─ win_h030_highrisk.npz        10 KB     64×64 风险窗口
│     ├─ win_h030_lowrisk.npz         10 KB
│     ├─ win_h060_highrisk.npz        11 KB
│     ├─ win_h060_lowrisk.npz         9 KB
│     ├─ win_h090_highrisk.npz        12 KB
│     └─ win_h090_lowrisk.npz         9 KB
└─ B_随机生成城市\
   ├─ city.npz                        5009.2 KB
   ├─ ps_check\                       遮蔽系数校验（结构同 A_真实深圳南山\ps_check\）
   ├─ 生成参数.md                     2.3 KB    该场景的生成器参数说明
   └─ slices\                         结构同 A_真实深圳南山\slices\
```

两套场景的 `slices\` 目录结构完全一致，代码写一次可以同时跑两个场景。

## 2 数据契约

### 2.1 `<场景>\city.npz`

```text
读取方式: np.load(path, allow_pickle=False)
文件性质: npz 容器，键值对，惰性加载

key = "building_mask"
    shape   = (1200, 1200, 61)
    dtype   = bool
    true 含义 = 该体素在建筑内部
    索引顺序 = [i, j, h_idx]

key = "pop_density"
    shape   = (1200, 1200)
    dtype   = float32
    单位    = 人/m²
    索引顺序 = [i, j]
    注意    = 只用于计算风险矩阵 R，不用于路径搜索的碰撞检测

key = "building_footprint"
    shape   = (1200, 1200)
    dtype   = bool
    true 含义 = 该地面格在建筑投影内

key = "meta"
    shape   = ()          标量
    dtype   = <U1559      numpy 字符串
    内容    = JSON 字符串，含 origin / resolution / axes_order / convention / data_source 等
```

### 2.2 `<场景>\slices\summary.json`

顶层键，全部为只读参考值。`null` 表示该字段缺失。

| 键 | 类型 | 单位 / 说明 |
|---|---|---|
| `scene` | str | `"real:osm_buildings+population"` 或 `"synthetic"` |
| `r_units` | str | `"casualties per flight hour"` |
| `shape` | [int×3] | `[1200, 1200, 61]` |
| `r_norm` | float | 式(19) 归一化基准 = min(r_mean, r_median) |
| `r_mean` | float | 全场风险均值，排除建筑格 |
| `r_median` | float | 全场风险中位数，排除建筑格。**本值是 log 直方图估计，非精确排序中位数** |
| `r_min` / `r_max` | float | 排除建筑格后的极值 |
| `n_finite_cells` | int | 非建筑格数量 |
| `n_obstacle_cells` | int | 建筑格数量（R 中应为 NaN 的个数） |
| `finite_ratio` | float | n_finite_cells / (1200×1200×61) |
| `layer_mean_h30` / `layer_mean_h90` | float | 30 m / 90 m 单层均值 |
| `layer_mean_monotonic_decreasing` | bool | 各层均值随高度是否单调递减 |
| `anchors` | object | 五个中间量，见 2.6 |
| `city` | object | 城市场景统计量，见 2.7 |
| `formulas` | str | 公式来源标注 |
| `simplifications` | [str] | 实现中采用的简化，实现者应在报告中复述 |

### 2.3 `<场景>\slices\probe_points.csv`

```text
编码: UTF-8
分隔符: 半角逗号
首行: 表头 i,j,h_idx,z,kind,R_expected
数据行数: A 场景 210 行，B 场景 200 行
列定义:
    i          int    体素 i 索引，范围 [0, 1199]
    j          int    体素 j 索引，范围 [0, 1199]
    h_idx      int    高度层索引，范围 [0, 60]
    z          float  对应高度（米），恒等于 30 + h_idx
    kind       str    "open" 或 "building"
    R_expected str    "open" 行为 %.10e 格式浮点字面量；"building" 行恒为字面量 NaN
```

统计：A 场景 `open` 180 行 + `building` 30 行；B 场景 `open` 180 行 + `building` 20 行（B 在 90 m 层无建筑）。

### 2.4 `<场景>\slices\index.json`

```json
{"windows": [{"file": "win_h030_highrisk.npz", "z": 30, "i0": 601, "j0": 936,
              "tag": "highrisk", "n_building_cells": 1056,
              "r_mean_in_window": 1.2913544678028188e-09}]}
```

| 字段 | 说明 |
|---|---|
| `file` | 相对 `slices\` 的文件名 |
| `z` | 窗口所在高度（米） |
| `i0`, `j0` | 窗口左上角在体素网格中的索引 |
| `tag` | `highrisk` = 该层风险均值最高的窗口；`lowrisk` = 最低 |
| `n_building_cells` | 窗口内建筑格数 |
| `r_mean_in_window` | 窗口内风险均值，排除建筑格 |

### 2.5 `<场景>\slices\win_*.npz`

```text
key = "R_win"   shape = (64, 64)  dtype = float32  建筑格为 NaN
key = "meta"    shape = ()        dtype = <U...    JSON 字符串，含 z / i0 / j0 / shape / convention

取值映射: R_win[a, b] == R[i0 + a, j0 + b, h_idx]，其中 h_idx = z - 30
```

### 2.6 `summary.json → anchors`

风险模型中间量，用于定位公式链错误。两套场景数值相同，因为这些量只依赖机体参数与高度。

| 键 | 值 | 单位 |
|---|---|---|
| `v_p_ter_m_s` | 4.281501814003186 | m/s，开伞终端速度 |
| `E_crash_p_J` | 84.32378580323783 | J，开伞碰撞能量 |
| `E_crash_b_h30_J` | 2704.7999999999997 | J，30 m 高度弹道碰撞能量 |
| `A_c_b_h30_m2` | 3.7532642751082506 | m²，30 m 高度伤亡面积 |
| `A_c_b_h90_m2` | 2.829719657490776 | m²，90 m 高度伤亡面积 |

`E_crash_p_J` = 84.32 > β = 34，因此降落伞三分段公式恒走第一分支。若生成器的输出落进第二或第三分支，开伞终端速度或质量参数用错了。

### 2.7 `config.json`

| 段 | 键数 | 内容 |
|---|---|---|
| `table1` | 7 | 论文表1：P_LOC、G、ALPHA、BETA、MASS、V_CRUISE |
| `table2` | 17 | 论文表2：SCENE_SIZE、GRID_SIZE、H_LOW、H_HIGH、N_H、STEP、THETA_MAX、ALPHA1、ALPHA2、START1、GOAL1、START2、GOAL2 |
| `supplementary` | 19 | 风险模型补充参数（Drones 2024, 8(11):678）。旧版的 `P_S_BUILDING`、`P_S_OPEN` 已删除：没有任何公式引用它们，留着只会让人误以为 P_s 是二值模型 |
| `citygen` | 12 | 场景 B 生成参数 |
| `coords` | 4 | 坐标约定 |
| `paths` | 5 | 场景相对位置 |
| `scenes` | 2 | 两套地图来源与统计量 |
| `_说明` | 1 | 使用约定 |

关键值（`table2`）：

```text
SCENE_SIZE = [1200, 1200]     GRID_SIZE = 1.0
H_LOW      = 30.0             H_HIGH    = 90.0        N_H = 61
STEP       = 10.0             THETA_MAX = 1.0471975511965976   (π/3)
ALPHA1     = 0.4              ALPHA2    = 0.6
START1 = [100, 1100, 30]      GOAL1 = [1100, 100, 30]
START2 = [900, 1150, 30]      GOAL2 = [10, 10, 30]
```

`START2` 取 900。论文正文 3.2 节写 950，表2 写 900，本数据集按表2，城市与切片均按 900 生成。

### 2.8 `<场景>\ps_check\`（遮蔽系数）

```
cov(i,j) = building_footprint 在 21×21 方形窗口内的均值，窗口以 (i,j) 为中心，边界 reflect 填充
P_s(i,j) = 10 · min(1, cov(i,j) / 1)
```

| 键 / 文件 | 内容 |
|---|---|
| `ps_summary.json` | 公式、参数、ps_min / ps_max / ps_mean / ps_median、满遮蔽格数、窗口索引 |
| `ps_windows.npz` | `blocks` (6,64,64)、`files` (6,)、`i0`、`j0`、`z`、`meta`；`blocks[k][a,b] == P_s[i0[k]+a, j0[k]+b]` |
| `ps_probes.csv` | 60 行 `i,j,Ps_expected`，其中 15 个点在边界 10 格以内 |

容差：绝对误差 ≤ 1e-6。`P_s` 无高度维。Drones 式(13) 的材质面积加权本数据集不用，改由局部建筑覆盖率折算，这是本数据集自定的简化，协议见 `ps_check\README.md`。

## 3 坐标与索引约定

```text
数组索引     [i, j, h_idx]
世界坐标     (x, y, z) = (i * 1.0, j * 1.0, 30.0 + h_idx)
             i↔x，j↔y，h_idx↔z；单位米
体素范围     i ∈ [0,1199]，j ∈ [0,1199]，h_idx ∈ [0,60]，z ∈ [30,90]
原点         (0, 0, 30)
分辨率       1.0 m
搜索步长     10 m（算法层，不是数据层）
搜索节点     体素每 10 格取一个：x, y ∈ {0,10,...,1190}，z ∈ {30,...,90}
```

索引顺序是 `[i, j, h_idx]`，**不是** `[x, y, z]`，也不是 `[h, i, j]`。

`THETA_MAX = π/3` 指相邻两段的水平航向变化，不是爬升角。10 m 节点网格的 26 邻域下，最大俯仰角 45°，所以它对爬升不构成约束；对航向是硬约束（转 45° 可行，转 90° 不可行）。这个解释与 `04_任务书\任务书_v3.md` 的固定条件表一致。

## 4 两套场景的期望值

场景 A 与场景 B 共用同一套 `config.json` 参数，只有城市不同。

| 指标 | A_真实深圳南山 | B_随机生成城市 |
|---|---|---|
| `scene` | real:osm_buildings+population | synthetic |
| `n_obstacle_cells` | 2921211 | 8416476 |
| `n_finite_cells` | 84918789 | 79423524 |
| `finite_ratio` | 0.9667439549180328 | 0.9041840163934426 |
| `r_min` | 2.1457998572449455e-11 | 8.617466007269925e-13 |
| `r_max` | 8.254288808018373e-09 | 1.847495134654764e-08 |
| `r_mean` | 5.748326583935336e-10 | 1.6431347589892868e-09 |
| `r_median` | 4.31519076827765e-10 | 5.30884444230988e-10 |
| `r_norm` | 4.31519076827765e-10 | 5.30884444230988e-10 |
| `layer_mean_h30` | 6.256230786076545e-10 | 2.0317983765555577e-09 |
| `layer_mean_h90` | 5.516933366420006e-10 | 1.4482712686003652e-09 |
| 建筑数 | 546 | 219 |
| 建筑格数 @ h_idx=0（z=30 m） | 144025 | 335423 |
| 建筑格数 @ h_idx=30（z=60 m） | 20052 | 110957 |
| 建筑格数 @ h_idx=60（z=90 m） | 8195 | 0 |
| 存在建筑的最高层 | h_idx=60（z=90 m） | h_idx=49（z=79 m） |
| 地面覆盖率 | 0.21540555555555554 | 0.26958125 |
| 体素占空比 | 0.033256045081967216 | 0.09581598360655738 |
| 人口密度均值 | 0.017064208164811134 | 0.014117836020886898 |
| 人口密度中位数 | 0.017704304307699203 | 0.0053386688232421875 |
| 折算总人数 | 24572.459757328033 | 20329.683870077133 |

两套场景的 `r_norm` 都等于 `r_median`，因为两个场景里中位数都小于均值。

风险场形态差异（用于解释后续算法表现差异）：

```text
同层内高危窗口与低危窗口的风险均值之比（三个高度层）
    A_真实深圳南山 : 6.1 / 8.8 / 8.0 倍
    B_随机生成城市 : 6406 / 5971 / 5333 倍
```

## 5 对数协议

`04_工具\build_risk_matrix.py --verify` 会把这套协议跑一遍并打印逐项结果。你也可以自己写校验脚本，口径以本文件为准。

四步，顺序执行，前一步不通过不要进入下一步。

### 步骤 0：遮蔽系数

`<场景>\ps_check\` 三步走完：全局 min/max/mean/median、六个 64×64 窗口逐点、60 个探针逐点，全部要求绝对误差 ≤ 1e-6。协议和参考脚本见 `<场景>\ps_check\README.md`。这一步不通过，R 一定不对，不要往下算。

### 步骤 1：全局统计量

对照 `summary.json` 的 `r_mean`、`r_median`、`r_min`、`r_max`、`r_norm`，要求相对误差 ≤ 1%。

`r_median` 我方用 log 直方图估计，不是精确排序中位数。若你的精确中位数与它相差 1% 以内，视为通过。

同时核对两个计数，要求完全相等：

```text
isnan(R).sum()        == n_obstacle_cells
isfinite(R).sum()     == n_finite_cells
R.shape               == (1200, 1200, 61)
```

### 步骤 2：窗口逐点

对 `index.json` 中每个窗口，按 `R_win[a, b] == R[i0+a, j0+b, z-30]` 逐元素比较。

```text
两侧 NaN 位置必须完全一致
空中格相对误差 ≤ 1e-5    → 通过
1e-5 < 误差 ≤ 1e-2       → 需要排查精度来源
误差 > 1e-2              → 不通过
```

### 步骤 3：探针逐点

按 `probe_points.csv` 每行给出的 `(i, j, h_idx)` 取值比较，阈值同步骤 2。

### 参考实现

可直接改用的校验脚本。`R` 换成 `04_工具\build_risk_matrix.py` 算出来的阵列即可，其余不需要改。

```python
import json
import numpy as np
from pathlib import Path

scene = Path("A_真实深圳南山")            # 或 B_随机生成城市
sl = scene / "slices"
S = json.loads((sl / "summary.json").read_text(encoding="utf-8"))

R = ...                                    # 生成器的输出，shape (1200,1200,61)，建筑格为 np.nan

# --- 结构与计数 ---
assert R.shape == (1200, 1200, 61), R.shape
assert int(np.isnan(R).sum()) == S["n_obstacle_cells"]
assert int(np.isfinite(R).sum()) == S["n_finite_cells"]

# --- 全局统计量，相对误差 <= 1% ---
finite = R[np.isfinite(R)]
r_mean = float(finite.mean())
r_min = float(finite.min())
r_max = float(finite.max())
r_median = ...                             # 你的中位数实现（直方图估计即可）
r_norm = min(r_mean, r_median)             # 式(19)

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

## 6 MUST / MUST NOT

```text
MUST
1. R 的形状为 (1200, 1200, 61)，索引顺序 [i, j, h_idx]
2. 建筑体素在 R 中为 np.nan，不是 0
3. R_norm 取 min(r_mean, r_median)，不是均值也不是中位数
4. 参数只从 config.json 读取，不在代码里另写常量
5. 两套场景使用同一份算法代码，场景路径通过参数传入

MUST NOT
1. 不得用 pop_density 做路径搜索的碰撞检测；碰撞检测只用 building_mask
2. 不得把 R 的索引顺序换成 [x, y, z] 或 [h, i, j]
3. 不得在 building 类型的探针点上填数值，必须是 NaN
4. 不得修改 summary.json / probe_points.csv / index.json / win_*.npz
5. 不得假设两套场景的风险分布相同
```

## 7 已知陷阱

| 现象 | 原因 | 检查方法 |
|---|---|---|
| `ps_mean` 对得上、窗口对不上 | 边界用了零填充或 nearest，应为 reflect | `ps_check\ps_probes.csv` 的 15 个边界点 |
| 高密度区风险偏高 | P_s 写成二值（建筑 10 / 空地 0），等于把覆盖率截成 0 或 1 | `ps_check\ps_windows.npz`。注意全局均值分辨不出来：A 场景两者只差 1.4×10⁻⁴ |
| `r_mean` 明显偏低 | 建筑格填了 0 而不是 NaN，参与了统计 | `isnan(R).sum()` 应等于 `n_obstacle_cells` |
| 所有风险代价整体偏小 | 归一化基准用了均值或中位数单个，而不是两者取小 | 本数据集中两者取小的结果恒等于 `r_median` |
| 90 m 层建筑格数对不上 | 体素化高度上界写错，或把 `h_idx` 当成高度米数 | A 场景 h_idx=60 层应为 8195 格；B 场景 h_idx=60 层应为 0 格，最高建筑到 h_idx=49 |
| 窗口比对整体差一个平移 | `i0`/`j0` 与 `a`/`b` 加减方向写反 | 用 `R_win[0,0] == R[i0, j0, h_idx]` 单点核对 |
| M2 三个分支落错 | `E_crash,p` 未与 β=34 比较，或开伞终端速度算错 | 对照 `anchors.v_p_ter_m_s = 4.2815` |
| 单层均值不随高度递减 | 遮蔽系数 P_s 未按局部建筑覆盖率导出 | `layer_mean_monotonic_decreasing` 应为 true |

## 8 本目录没有的东西

```text
没有 R 本身                  不预存 npz：单场景 float32 阵列 351 MB，压缩后 238 MB。用 04_工具\build_risk_matrix.py 现算，约 10 秒
没有算法实现                astar.py / rc_astar.py / rrt_star.py 等均不在本目录
没有判分标准                见 04_任务书\任务书_v3.md 第 3、4 节
```
