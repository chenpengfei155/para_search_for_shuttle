# para_search_for_shuttle
# Shuttle 方案参数搜索算法

这是一个 `shuttle` 方案参数搜索算法(对应para_alg_impl.py,其他文件不重要，只是用于测试和解释)，其功能是对输入参数进行合法性检查，并在参数合法的情况下，计算公钥尺寸、签名尺寸、组合尺寸以及对应的安全性估计。当前项目已经切换到双 sigma 版本；若需要对称实验，请取 sigma_1 = sigma_2。

## 输入参数

算法的输入参数包括：

- 模数 $q$
- 维度 $n$
- 矩阵行数 $m$
- 矩阵列数 $\ell$
- 离散高斯分布的标准差 $\sigma_1, \sigma_2$
- 参数 $\alpha_h$

## 功能说明

算法首先对输入参数进行合法性检查，包括：

1. 维度 $n$ 必须取为安全参数的 2 倍；
2. 模数 $q$ 必须为 NTT 素数；
3. 标准差 $\sigma_1, \sigma_2$ 必须满足：
   
   $$
   \sigma_1 \ge 0.5,\quad \sigma_2 \ge 0.5
   $$

4. 参数 $\alpha_h$ 必须为 2 的幂次。

在参数满足上述条件后，算法将依据给定公式计算：

- 公钥尺寸（Public Key Size）
- 签名尺寸（Signature Size）
- 组合尺寸（Combined Size）
- LWE_security_bit 
- SIS_UF_security_bit 
- SIS_sUF_security_bit

