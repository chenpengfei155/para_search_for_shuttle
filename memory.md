# Param Search Memory

迭代过程的累积结论 — 防止重复踩坑。

---

## 🎯 已确认可行参数区 (VIABLE ZONES) — **每轮迭代后必须更新这一节**

> 此处永久记录任何命中目标带的参数范围 / 具体点。代码 `param_search.py` 顶部也要同步维护一份精简注释版。

### target=128 (n=256) — **BOTH GOALS ✅**
- **Goal A (UF) ✅** (27 records)
  - 主区 1 (ell=3 m=2 小 q): `q ∈ {17921, 28289}, sigma ∈ [0.80, 1.05], alpha_h ∈ {128, 256}`
  - 主区 2 (ell=4 m=2 + alpha_h=4096 knee): `q=1500929, sigma ∈ [1.05, 1.20], alpha_h=4096`
  - **居中代表点**: `q=1500929, ell=4, m=2, sigma=1.10, alpha_h=4096` → LWE=134.67, UF=133.74
- **Goal B (sUF) ✅** (2 records)
  - `q=1123841, ell=4, m=2, alpha_h=1024, sigma ∈ {1.05, 1.10}`
  - 代表: `sigma=1.05` → LWE=137.09, sUF=139.58

### target=256 (n=512) — **BOTH GOALS ✅**
- **Goal A (UF) ✅** (7 records, all ell=3 m=2 alpha_h=4096)
  - `q ∈ {393473, 414209, 425473}, sigma ∈ [1.55, 1.70]`
  - **居中代表**: `q=414209, ell=3, m=2, sigma=1.70, alpha_h=4096` → LWE=267.96, UF=266.60
- **Goal B (sUF) ✅** (5 records, all ell=3 m=2 alpha_h=1024)
  - `q ∈ {151553, 160001, 170497, 201473}, sigma ∈ [1.00, 1.20]`
  - **居中代表**: `q=201473, ell=3, m=2, sigma=1.20, alpha_h=1024` → LWE=266.02, sUF=264.55
- **关键洞察**：Goal A 在 alpha_h=4096 (max) + sigma=1.55-1.70 (大噪声推 UF 下行)；Goal B 在 alpha_h=1024 (适中 UF)

### target=512 (n=1024) — **BOTH GOALS ✅**
- **Goal A (UF) ✅** (1 record)
  - `q=12000257, ell=3, m=1, sigma=0.70, alpha_h=256` → LWE=521.80, UF=519.47
  - m=1 减半 n_sis 是关键
- **Goal B (sUF) ✅** (1 record)
  - `q=326657, ell=3, m=2, sigma=0.70, alpha_h=4096` → LWE=518.01, sUF=520.05

---

## 自动产出: results/param_ideal.jsonl

由 `extract_ideal.py` 扫描所有 `results/*.jsonl` 后生成的"达标参数总表"，每条带 `goals: ["UF"|"sUF"|both]` 标记。
每轮 search 后跑：`/home/jipengzhang/micromamba/envs/py3_sage/bin/python extract_ideal.py`

**当前快照**（iter 1 之后）：23 条命中（全部 target=128 Goal UF）；target=256/512 / Goal sUF 暂无。

---

## Goal
对每个安全级别 target ∈ {128, 256, 512}，在固定 n ∈ {256, 512, 1024} 下，
找出参数 (q, ell, m, sigma, alpha_h) 使得：
- **Goal A (UF)** : LWE ∈ [target+5, target+12] **AND** SIS_UF ∈ [target+5, target+12]
- **Goal B (sUF)**: LWE ∈ [target+5, target+12] **AND** SIS_sUF ∈ [target+5, target+12]

## Algorithm internals (cheat sheet)
- `bk = sigma * sqrt((ell+m) * n)`
- `alpha_1 = ceil_pow2(sqrt(n) * sigma)`
- `r = ceil(scale * sqrt(alpha_1^2 / ell + bk^2))`，`scale = R_SCALING[n/2]`
- `bv = bs(r) + sqrt(n*m) * (alpha_h/4 + 1)`
- LWE 安全用 (n_lwe=ell·n, m_lwe=m·n, q, sigma)
- SIS_UF / SIS_sUF 用 (n_sis=m·n, m_sis=(ell+1+m)·n, q, 长度界=bv 或 2·bv)
- 用的是 `LWE.estimate.rough` / `SIS.estimate.rough` —— 估计粗（快）

## Lever effects (待验证, 部分来自先验)
- **sigma↑** → LWE↑（噪声大）, r↑ → bs↑ → bv↑ → SIS↓
- **q↑** → LWE↓, SIS↓
- **ell↑** (n_lwe↑) → LWE↑（维度高），但 bk↑ → r↑ → bs↑ → bv↑ → SIS↓
- **m↑** (n_sis↑) → SIS_dim↑（好），但 m_lwe↑ → 攻击样本↑ → LWE↓；并且 sqrt(n·m)项使 bv↑ → SIS↓
- **alpha_h↑** → bv↑ → SIS↓
- 综合：要拉高 sUF 主要靠 **alpha_h↓** 和减小 r（小 sigma / 小 ell+m）

## Iterations

### Pre-iter (旧数据 results/param_search.jsonl, ell=3, m=2)
**Status (旧 q 集 `[7681,...,334721]`, sigma 0.7..2.5, alpha_h≥128)**
- target=128 (950 records):
  - LWE: [97.5, 226.9], SIS_UF: [72.4, 212.6], SIS_sUF: [58.7, 169.9]
  - **Goal A (UF)**: ✅ 17 条命中
  - **Goal B (sUF)**: ❌ 0 条命中。LWE 在带内时 sUF 最高 123.8 (q=148609, sigma=1.7, alpha_h=128)
- target=256 (217 records, early-stopped):
  - LWE: [299.6, 458.1] —— **全部超过 target+12=268**
  - Goal A/B 0 条
- target=512 (28 records, early-stopped):
  - LWE: [679.2, 763.0] —— **远高于 target+12=524**
  - Goal A/B 0 条

**结论 → 下一轮方向**
- t=128 sUF: 把 alpha_h 拉到 32/64，试 ell=4 + 小 sigma 推 sUF
- t=256: 把 ell 从 3 降到 2 —— n_lwe 从 1536→1024，应能压 LWE ~50 bit
- t=512: 把 ell 降到 1 或 2 —— 大幅降 n_lwe

---

### Iter 1 (probe, 456 combos → 实际跑 249，缓存命中 207)
**已踩过的坑（DO NOT REPEAT）**
1. **t=256/512 用 ell=2 是过激的**：把 LWE 打得太低
   - t=256 ell=2 m=2: LWE ∈ [135.5, 208.1] (目标 [261,268])
   - t=512 ell=2 m=2: LWE ∈ [293, 423]
2. **t=512 用 ell=1 直接崩盘**: LWE ∈ [116, 190]
3. **m=1 + 任何 ell** SIS dim 太小（n_sis = m·n = n），SIS_UF/sUF 都 < 80 bits（n=256 时）。所以 **m≥2 是硬性约束**（除非把 m=1 当作 LWE 调节器看待，但牺牲 SIS）。

**t=128 各 (ell,m) 实测范围（n=256, q ∈ [12289,148609]，sigma 0.7..1.5，alpha_h ∈ {32,64,128,256}）**
| (ell, m) | LWE 范围 | SIS_UF 范围 | SIS_sUF 范围 | 评 |
|--|--|--|--|--|
| (3, 1) | [139.9, 235.4] | [39.4, 80.3] | [29.2, 61.6] | SIS dim 太小，UF/sUF 都不够 |
| (3, 2) | [104.5, 180.2] | [109.5, 204.7] | [87.9, 163.2] | **主力**：sUF/UF 都有空间，需细搜 |
| (4, 1) | [227.8, 364.4] | [36.8, 73.3] | [27.4, 56.4] | LWE 过高，SIS dim 不够 |
| (4, 2) | [170.2, 271.3] | [105.1, 195.3] | [84.4, 156.2] | LWE 偏高，可用大 q 拉低后再做 sUF |

**t=128 sUF 调谐关键发现**
- 当前 LWE 在带 [133,140] 时最佳 sUF=124.4 (`q=98561, ell=3, m=2, sigma=1.50, alpha_h=32`)，**差 8.6 bits**
- 当 LWE = 123.84 (略低于带) 时 sUF=134.03 (q=65537, sigma=1.0, alpha_h=32) — sUF 单独已达标
- **下一步杠杆**:
  1. alpha_h 继续往下 (4, 8, 16) — bv 二次项 sqrt(n·m)·(α/4+1) 仍可压
  2. ell=4 m=2 + 大 q (222977, 334721) 把 LWE 从 ~190 拉到带内，sUF 应 >130

### Iter 2 (137 combos)
**新发现**
- t=256 **ell=3 m=4** 是中间档位（LWE 在 m=3 偏高 vs m=2 偏低中间）：
  - q=12289 sigma=0.5: LWE=275.09（超目标 7 bits，逼近）
  - q=12289 sigma=0.7: LWE=303 (略高)
- t=512 **ell=3 m=4** 同样有效：q=326657 sigma=0.7 alpha_h=128 → **LWE=514.47**（差 2.5 bits 进带）
- 但 t=256/512 当 LWE 进入带内时 **SIS_UF / SIS_sUF 报 inf**（远超目标，估计器输出 ∞）
- early-stop 阈值 20 太激进 → 把 t=128 的 alpha_h=4 探索全杀了。改成 **EARLY_STOP_MARGIN=200**(基本禁用)

### Iter 3 (376 combos, 关键发现)
**t=128 sUF 帕累托饱和**
- ell=3 m=2, n=256：LWE-sUF Pareto sum 锁在 ~255-257：
  - q=43649 sigma=1.30 alpha_h=4: LWE=138.5, sUF=117.1, sum=255.6
  - q=131713 sigma=1.40 alpha_h=4: LWE=125.0, sUF=132.3, sum=257.3
- 因为 bv ≈ bs(r) （在 alpha_h 小时被 bs 主导）→ alpha_h 4 vs 16 几乎无差别
- **结论：ell=3 m=2 不可能命中 sUF goal**，需换 (ell, m)
- **方案**：ell=4 m=2 (从 iter1 数据 sum ≈ 328) + 把 q 拉到 1M+，可让 LWE & sUF 同步降到 135

**t=256 LWE 已进带，但 SIS 卡 inf**
- q=19457 ell=3 m=4 sigma=0.5 alpha_h=2048: **LWE=264.30** (恰好在带[261,268])
- 但同位置 SIS_UF=521.51, SIS_sUF=441.5 — 远超 [261,268]
- alpha_h 已达上限（sigma_h ≥ 0.05 约束 alpha_h ≤ ~3520）
- **诊断**：在 m=4 (n_sis=2048) 维度下 SIS 太硬。要换更小 n_sis (m=2 或 3)
- **方案**：ell=4 m=2 (n_lwe=2048 保 LWE 高, n_sis=1024 让 SIS 降出 inf 区)

**t=512 同 t=256 模式**
- q=216577 ell=3 m=4 sigma=0.65 alpha_h=512: **LWE=518.75** (在带[517,524]中央)
- 但同位置 SIS = inf
- 同样需换更小 n_sis 或更大 alpha_h (上限尚未碰到，可试 4096)

### Iter 4 (45 records)
**关键发现**
- t=128 ell=4 m=2 在 q∈[334k..1.1M] sigma∈[0.7..1.0] alpha_h∈{8,16,32}: **LWE+sUF sum 锁在 313-322**
- 与 q/alpha_h 关系：q 翻倍 LWE 跌 30，sUF 涨 22 → sum 微涨
- alpha_h 翻倍 sUF 跌 ~1 bit（bs 项主导 bv，alpha_h 二项无足轻重）
- 结论：固定 (ell, m, n) 时 Pareto sum 基本不可移动

### Iter 5 (183 records, worker=20 with BLAS=1)
**(ell, m) Pareto sum 在 n=256 普查**
| (ell, m) | LWE 范围 | sUF 范围 | sum | 评 |
|--|--|--|--|--|
| (2, 3) | [62, 95] | [200, 270] | ~290 | LWE 过低 |
| (3, 2) | [104, 180] | [88, 163] | **~255** | sum 低，跨不过 (135, 135) |
| (3, 3) | [62, 154] | [205, inf] | ~340 | sum 太高 |
| (4, 2) | [126, 364] | [55, 196] | ~315 | sum 不够低，sUF 进不去 |

→ **n=256 上任何整数 (ell, m) 都没有 sum ≈ 270 的位置**

**t=256 真正接近：**
- `q=49409 ell=4 m=2 sigma=0.50 alpha_h=2048` → LWE=386.90, **UF=257.84**, sUF=215.20
  - UF 仅差 3.16 bits 进带 [261, 268]
- `q=3002113 ell=4 m=2 sigma=0.50 alpha_h=2048` → **LWE=262.56** (在带), UF=393, sUF=330（仍超）

**t=512 LWE 已可控:**
- `q=326657 ell=3 m=2 sigma=0.70 alpha_h=1024` → **LWE=518.01** (在带), UF=756, sUF=640（仍超）

### CPU 利用率诊断 (15% 现象)
- `lattice-estimator` 速度强依赖目标安全比特：
  - 安全很高 (>500) 或很低 (<150): ~0.1s（estimator 立即结束）
  - 接近目标带的"真攻击"区: 5-80s（需要遍历大量 BKZ block size）
- 慢任务集中在 band 附近 → 大多数 workers 跑完快任务后等待少数慢任务
- 实测 bench 60 任务 24 慢: 13 workers=128s, 20=121s, 28=112s — worker 增加边际收益小
- 当前用 **workers=20** + BLAS_NUM_THREADS=1

### Iter 6 (~60 combos, 当前)
1. t=128 ell=3 m=2 fine-grain (确认 Pareto 锁)
2. t=128 ell=4 m=2 大 sigma + 极大 alpha_h
3. t=128 ell=2 m=2 大 sigma 推高 LWE
4. t=256 ell=4 m=2 sigma=0.7 alpha_h=4096
5. t=256 ell=4 m=1 (n_sis 减半逃 SIS 锁)
6. t=512 ell=3 m=2 alpha_h=4096
7. t=512 ell=3 m=1

### Iter 7-19 完整记录 (压缩版)

**Iter 7**: t=128 双 goal 命中
  - Goal A: `q=1500929 ell=4 m=2 sigma=1.05-1.20 alpha_h=4096` (4 hits)
  - Goal B: `q=1123841 ell=4 m=2 sigma=1.05/1.10 alpha_h=1024` (2 hits)
  - **alpha_h=4096 (max) 是关键 "knee"**

**Iter 8-9**: t=512 Goal A 命中
  - Iter9: `q=12000257 ell=3 m=1 sigma=0.70 alpha_h=256` → LWE=521.80 UF=519.47
  - 关键：**m=1 减半 n_sis** 让 SIS 出 inf

**Iter 10**: t=512 Goal B 命中
  - `q=326657 ell=3 m=2 sigma=0.70 alpha_h=4096` → LWE=518.01 sUF=520.05

**Iter 11-13**: t=256 失败尝试（ell=3 m=1 LWE/UF Pareto 在 [261,268] 不交叉）

**Iter 14-15**: t=256 sUF 接近但 LWE 总是过高（ell=3 m=3 alpha_h=8192 LWE 锁在 ~310）

**Iter 16-17**: t=256 ell=3 m=2 + alpha_h knee 探索
  - Goal B 命中: `q∈{151553..201473} sigma∈[1.0,1.2] alpha_h=1024` (5 hits)

**Iter 18-19**: t=256 Goal A 命中
  - **Iter 19**: `q∈{393473,414209,425473} sigma∈[1.55,1.70] alpha_h=4096` (7 hits)
  - 关键：**sigma=1.55-1.70 (大噪声推 UF 下行) + alpha_h=4096 (max knee)**

---

## 🏆 全 6 个目标格已命中！

| Target | Goal A (UF) | Goal B (sUF) |
|--------|-------------|--------------|
| 128    | ✅ 27 hits  | ✅ 2 hits    |
| 256    | ✅ 7 hits   | ✅ 5 hits    |
| 512    | ✅ 1 hit    | ✅ 1 hit     |

共 **43 个候选参数** 已写入 `results/param_ideal.jsonl`

### 总结：通用调参策略
1. **n 固定为 256/512/1024 对应 target=128/256/512**
2. **ell 是最重要的整数维度旋钮**：n_lwe = ell·n 决定 LWE 安全大盘
3. **m 与 alpha_h 的耦合是关键**：m 决定 n_sis 维度上限；alpha_h 是 SIS β=bv 的"细调旋钮"
4. **"alpha_h knee" 是命中关键**：alpha_h 在 sigma_h≥0.05 约束下取到最大值时，SIS 安全性发生急剧跌落，往往是带入 band 的唯一路径
5. **大 sigma 解锁更大 alpha_h**: 因为 sigma_h = 2r/alpha_h，sigma↑ → r↑ → alpha_h_max↑

### 用法
- 生成搜索结果总表：`python3 extract_ideal.py`
- HTML 可视化：`python3 gen_html.py` → 浏览器打开 `results/param_search.html`
- 新增搜索：编辑 `PARAM_GROUPS`，运行 `python3 param_search.py`
