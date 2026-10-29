# 场景 A P_s 诊断

## 1. city.npz 键与 footprint
文件：C:\Users\kano\Desktop\ffjj\lib\03_场景\A_真实深圳南山\city.npz
所有键：['building_mask', 'pop_density', 'building_footprint', 'meta']
- building_mask: shape=(1200, 1200, 61), dtype=bool
- pop_density: shape=(1200, 1200), dtype=float32
- building_footprint: shape=(1200, 1200), dtype=bool
- meta: shape=(), dtype=<U1559
building_mask：shape=(1200, 1200, 61), dtype=bool, True 数=2921211
building_footprint：存在。
building_footprint：shape=(1200, 1200), dtype=bool, True 数=310184

## 2. 投影 vs footprint
building_mask.any(axis=2)：shape=(1200, 1200), True 数=144025
投影 True 数=144025
footprint True 数=310184
不一致格数=166159
不一致比例=0.115388194444（按全部平面格数计算）
前 10 个不一致坐标 (i,j)=[(0, 53), (0, 54), (0, 55), (0, 56), (0, 57), (0, 58), (0, 59), (0, 60), (0, 61), (0, 76)]

## 3. README 口径摘录
README.md §2.8 原文相关行：
> cov(i,j) = building_footprint 在 21×21 方形窗口内的均值，窗口以 (i,j) 为中心，边界 reflect 填充
> P_s(i,j) = 10 · min(1, cov(i,j) / 1)
> | `ps_summary.json` | 公式、参数、ps_min / ps_max / ps_mean / ps_median、满遮蔽格数、窗口索引 |
> | `ps_windows.npz` | `blocks` (6,64,64)、`files` (6,)、`i0`、`j0`、`z`、`meta`；`blocks[k][a,b] == P_s[i0[k]+a, j0[k]+b]` |
> | `ps_probes.csv` | 60 行 `i,j,Ps_expected`，其中 15 个点在边界 10 格以内 |
> 容差：绝对误差 ≤ 1e-6。`P_s` 无高度维。Drones 式(13) 的材质面积加权本数据集不用，改由局部建筑覆盖率折算，这是本数据集自定的简化，协议见 `ps_check\README.md`。

配置 supplementary.P_s_note 原文：
> Ps(i,j) = P_S_SCALE * min(1, cov/P_S_C_REF)；cov = building_footprint 在 P_S_WINDOW×P_S_WINDOW 方形窗口内的均值，窗口以该格为中心，边界用 reflect 填充。Drones 表1 的 0~10 遮蔽刻度（α=3.4e4 J 在 P_s=6 标定 P_f=50%）。Ps 无高度维。校验数据见各场景 ps_check/

ps_check/README.md 原文相关段落：
> cov(i,j) = building_footprint 在 21×21 方形窗口内的均值
>            窗口以 (i,j) 为中心，边界用 reflect 填充
> P_s(i,j) = 10 · min(1, cov(i,j) / 1)
> | `ps_summary.json` | 公式、参数、本场景的 min/max/mean/median、满遮蔽格数、窗口索引 |
> | `ps_windows.npz` | `blocks` (6,64,64) float32、`files` (6,)、`i0`/`j0`/`z` (6,)、`meta` |
> | `ps_probes.csv` | 60 行 `i,j,Ps_expected`，其中 15 个点落在边界 10 格以内 |

README 口径判读（仅根据上述原文）：
- 输入来源：README 写的是 building_footprint，不是 building_mask。
- reflect：原文只写 reflect 填充，没有指定具体镜像数组约定或边界轴位置。
- 窗口：原文规定 21×21 方形窗口，以 (i,j) 为中心；奇数边长对应中心格。
- 缩放：原文写 P_s(i,j) = 10 · min(1, cov(i,j) / 1)；配置写 P_S_SCALE * min(1, cov / P_S_C_REF)。

## 4. 诊断结论
- footprint 键：存在
- 投影与 footprint：不等价
- reflect 定义：仍有歧义（未说明使用哪一种镜像约定、反射轴落在边缘格还是边缘外一格）
- 窗口定义：已明确（21×21，以格点 (i,j) 为中心）
- 建议下一步：改用已有 building_footprint 作为 P_s 覆盖率输入；再单独核对 reflect 的具体实现约定。
