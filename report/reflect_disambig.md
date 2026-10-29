# reflect 模式消歧诊断
验证容差：绝对误差 ≤ 1e-06（README.md §2.8）
范围：只读读取 city.npz/ps_check 基准；只重算角点局部 P_s，不生成整幅 P_s 或 R。

## 1. reflect_index 实际实现片段
以下为 src/risk/verify_ps.py 中 reflect_index 的实际函数体：
```python
def reflect_index(idx: int, n: int, mode: str) -> int:
    """将越界索引按三个候选 reflect 约定独立映射回有效范围。"""
    if n <= 0:
        raise ValueError("反射轴长度 n 必须为正数。")
    if mode not in REFLECT_CANDIDATES:
        raise ValueError(f"不支持的 reflect 候选模式：{mode}")
    if n == 1:
        return 0

    if mode == "edge_center":
        # 例：[-1] -> [0]、[n] -> [n-1]，边缘格本身为镜像中心。
        period = 2 * n
        folded = idx % period
        return folded if folded < n else period - 1 - folded

    # 按任务给定的零起始示例，edge_axis 与 symmetric 都满足
    # [-k] -> [k]、[n-1+k] -> [n-1-k]，两者因此是相同索引映射。
    period = 2 * (n - 1)
    folded = idx % period
    return folded if folded < n else period - folded
```
实现判断：函数只对 edge_center 单独分支；edge_axis 和 symmetric 进入同一个 else 分支，所用周期和折返表达式相同。

## 2. n=5 的一维索引映射
| pad | 输入索引范围 | edge_axis 映射 | symmetric 映射 | 两者逐项相同 |
|---:|---|---|---|---|
| 3 | [-3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7] | [3, 2, 1, 0, 1, 2, 3, 4, 3, 2, 1] | [3, 2, 1, 0, 1, 2, 3, 4, 3, 2, 1] | 是 |
| 10 | [-10, -9, -8, -7, -6, -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14] | [2, 1, 0, 1, 2, 3, 4, 3, 2, 1, 0, 1, 2, 3, 4, 3, 2, 1, 0, 1, 2, 3, 4, 3, 2] | [2, 1, 0, 1, 2, 3, 4, 3, 2, 1, 0, 1, 2, 3, 4, 3, 2, 1, 0, 1, 2, 3, 4, 3, 2] | 是 |

映射范围结论：对 n>1，edge_axis 与 symmetric 使用相同的 period = 2*(n-1) 和折返规则，因此所有非负整数 pad、所有整数输入索引都相同；n=1 时两者都映射为 0。不存在两者不同的 pad 范围。

## 3. A/B 角点基准与局部重算
### 场景 A
building_footprint.shape=(1200, 1200)；窗口边长=21；边缘影响半径=10 格。
角点附近探针：4 个；角点附近窗口：0 个。
角点探针逐项比较（基准列 Ps_expected）：
- CSV 行 2，(i,j)=(0,0)，模式=edge_axis：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
- CSV 行 2，(i,j)=(0,0)，模式=symmetric：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
  两模式该探针输出相同：是。
- CSV 行 3，(i,j)=(1199,1199)，模式=edge_axis：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
- CSV 行 3，(i,j)=(1199,1199)，模式=symmetric：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
  两模式该探针输出相同：是。
- CSV 行 4，(i,j)=(0,1199)，模式=edge_axis：MATCH；重算=10；基准=10；绝对误差=0；相对误差=0。
- CSV 行 4，(i,j)=(0,1199)，模式=symmetric：MATCH；重算=10；基准=10；绝对误差=0；相对误差=0。
  两模式该探针输出相同：是。
- CSV 行 5，(i,j)=(1199,0)，模式=edge_axis：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
- CSV 行 5，(i,j)=(1199,0)，模式=symmetric：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
  两模式该探针输出相同：是。

### 场景 B
building_footprint.shape=(1200, 1200)；窗口边长=21；边缘影响半径=10 格。
角点附近探针：4 个；角点附近窗口：1 个。
角点探针逐项比较（基准列 Ps_expected）：
- CSV 行 2，(i,j)=(0,0)，模式=edge_axis：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
- CSV 行 2，(i,j)=(0,0)，模式=symmetric：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
  两模式该探针输出相同：是。
- CSV 行 3，(i,j)=(1199,1199)，模式=edge_axis：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
- CSV 行 3，(i,j)=(1199,1199)，模式=symmetric：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
  两模式该探针输出相同：是。
- CSV 行 4，(i,j)=(0,1199)，模式=edge_axis：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
- CSV 行 4，(i,j)=(0,1199)，模式=symmetric：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
  两模式该探针输出相同：是。
- CSV 行 5，(i,j)=(1199,0)，模式=edge_axis：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
- CSV 行 5，(i,j)=(1199,0)，模式=symmetric：MATCH；重算=0；基准=0；绝对误差=0；相对误差=0。
  两模式该探针输出相同：是。
角点窗口逐项比较（仅重算该基准块，不生成整幅 P_s）：
- ps_win_h090_highrisk.npz，起点=(0,0)，形状=(64, 64)，模式=edge_axis：MATCH；最大绝对误差=7.12958053706e-09；最大相对误差=3.4272669685e-08。
- ps_win_h090_highrisk.npz，起点=(0,0)，形状=(64, 64)，模式=symmetric：MATCH；最大绝对误差=7.12958053706e-09；最大相对误差=3.4272669685e-08。

## 4. 结论
两种边界模式实现相同；n=5、pad=3 与 pad=10 的映射逐项相同，函数实现表明所有 pad 均相同。A/B 角点基准对 edge_axis 和 symmetric 的局部重算结果相同；现有基准不能区分两个标签，因为当前函数映射本身等价。
分类：等价。不存在需要补充才能区分这两个实现的测试点；增加测试点也不会使相同映射分离。
