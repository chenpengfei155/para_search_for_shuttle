#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def add_estimator_paths() -> None:
    candidates = [
        SCRIPT_DIR / ".deps" / "lattice-estimator",
        SCRIPT_DIR.parent / ".deps" / "lattice-estimator",
        SCRIPT_DIR.parent.parent / ".deps" / "lattice-estimator",
    ]
    for candidate in candidates:
        if candidate.exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)


add_estimator_paths()

try:
    from estimator import LWE, ND, SIS
    from estimator.lwe_primal import PrimalUSVP
    from estimator.lwe_parameters import LWEParameters
    from estimator.reduction import RC
    from estimator.sis_parameters import SISParameters

    ESTIMATOR_AVAILABLE = True
except Exception:
    LWE = None
    ND = None
    PrimalUSVP = None
    RC = None
    SIS = None
    LWEParameters = None
    SISParameters = None
    ESTIMATOR_AVAILABLE = False


R_SCALING = {
    128: 2.75,
    256: 2.78,
    512: 2.81,
}
ALLOWED_N = {256, 512, 1024}


class ParameterValidationError(ValueError):
    pass


@dataclass(frozen=True)
class LWEParameterSpec:
    n: int
    q: int
    m: int
    sigma_1: float
    sigma_2: float
    tag: str | None = None


@dataclass(frozen=True)
class SISParameterSpec:
    n: int
    q: int
    length_bound: float
    m: int
    norm: int = 2
    tag: str | None = None


@dataclass(frozen=True)
class AlgorithmResult:
    n: int
    q: int
    ell: int
    m: int
    sigma_1: float
    sigma_2: float
    alpha_h: int
    lambda_bits: int
    bk: float
    alpha_1: int
    r: int
    mu_s: float
    v_s: float
    bs: float
    bv: float
    sigma_h: float
    a_h: float
    hh: float
    hh_regime: str
    pk_bytes: int
    sign_bytes: int
    sign_bytes_ceil: int
    combined_bytes: int
    lwe_usvp_security_bit: float | None
    lwe_dual_hybrid_security_bit: float | None
    lwe_security_bit: float | None
    lwe_best_attack: str | None
    sis_uf_security_bit: float | None
    sis_suf_security_bit: float | None
    lwe_spec: LWEParameterSpec
    sis_uf_spec: SISParameterSpec
    sis_suf_spec: SISParameterSpec
    estimator_available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "LWE_security_bit": self.lwe_security_bit,
            "SIS_UF_security_bit": self.sis_uf_security_bit,
            "SIS_sUF_security_bit": self.sis_suf_security_bit,
            "PkBytes": self.pk_bytes,
            "SignBytes": self.sign_bytes,
            "CombinedBytes": self.combined_bytes,
        }


@dataclass(frozen=True)
class AlgorithmArtifacts:
    result: AlgorithmResult
    lwe_param: Any | None
    sis_uf_param: Any | None
    sis_suf_param: Any | None


def extract_rop_bits(rop: Any) -> float:
    if rop is None or str(rop) == "+Infinity":
        return math.inf

    try:
        value = float(rop)
    except (OverflowError, TypeError, ValueError):
        return math.inf

    if math.isinf(value):
        return math.inf
    return math.log2(value)


def usvp_embedding_sample_count(lwe_param: Any) -> int:
    if lwe_param.Xs <= lwe_param.Xe:
        return lwe_param.m + lwe_param.n
    return lwe_param.m


def robust_usvp_bits(lwe_param: Any | None) -> float | None:
    if lwe_param is None:
        return None

    embedding_m = usvp_embedding_sample_count(lwe_param)
    low = 40
    high = embedding_m
    best_cost = None

    while low <= high:
        beta = (low + high) // 2
        cost = PrimalUSVP.cost_gsa(
            beta=beta,
            params=lwe_param,
            m=embedding_m,
            red_cost_model=RC.ADPS16,
        )
        if str(cost["rop"]) == "+Infinity":
            low = beta + 1
        else:
            best_cost = cost
            high = beta - 1

    if best_cost is None:
        return math.inf
    return extract_rop_bits(best_cost["rop"])


def is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


def floor_power_of_two(value: float) -> int:
    if value <= 1:
        return 1
    return 1 << math.floor(math.log2(value))


def hint_entropy(r: int, alpha_h: int) -> tuple[float, str, float, float]:
    sigma_h = 2 * r / alpha_h
    a_h = 1 + 2 * math.exp(-1 / (2 * sigma_h**2)) + 2 * math.exp(-2 / sigma_h**2)

    if sigma_h >= 1:
        hh = 0.5 * math.log2(2 * math.pi * math.e * sigma_h**2)
        return hh, "Gauss", sigma_h, a_h

    hh = math.log2(a_h) + (
        math.exp(-1 / (2 * sigma_h**2)) + 4 * math.exp(-2 / sigma_h**2)
    ) / (sigma_h**2 * a_h * math.log(2))
    return hh, "theoretical-entropy-estimate", sigma_h, a_h


def build_estimator_objects(
    lwe_spec: LWEParameterSpec,
    sis_uf_spec: SISParameterSpec,
    sis_suf_spec: SISParameterSpec,
) -> tuple[Any | None, Any | None, Any | None]:
    if not ESTIMATOR_AVAILABLE:
        return None, None, None

    lwe_param = LWEParameters(
        n=lwe_spec.n,
        q=lwe_spec.q,
        Xs=ND.DiscreteGaussian(lwe_spec.sigma_1),
        Xe=ND.DiscreteGaussian(lwe_spec.sigma_2),
        m=lwe_spec.m,
        tag=lwe_spec.tag,
    )
    sis_uf_param = SISParameters(
        n=sis_uf_spec.n,
        q=sis_uf_spec.q,
        length_bound=sis_uf_spec.length_bound,
        m=sis_uf_spec.m,
        norm=sis_uf_spec.norm,
        tag=sis_uf_spec.tag,
    )
    sis_suf_param = SISParameters(
        n=sis_suf_spec.n,
        q=sis_suf_spec.q,
        length_bound=sis_suf_spec.length_bound,
        m=sis_suf_spec.m,
        norm=sis_suf_spec.norm,
        tag=sis_suf_spec.tag,
    )
    return lwe_param, sis_uf_param, sis_suf_param


def estimate_lwe_security_bits(lwe_param: Any | None) -> tuple[float | None, float | None, float | None, str | None]:
    if lwe_param is None:
        return None, None, None, None

    result = LWE.estimate.rough(lwe_param, quiet=True)
    usvp_bits = robust_usvp_bits(lwe_param)
    dual_hybrid_bits = extract_rop_bits(result.get("dual_hybrid", {}).get("rop"))

    if dual_hybrid_bits <= usvp_bits:
        return usvp_bits, dual_hybrid_bits, dual_hybrid_bits, "dual_hybrid"
    return usvp_bits, dual_hybrid_bits, usvp_bits, "usvp"


def estimate_sis_security_bits(sis_param: Any | None) -> float | None:
    if sis_param is None:
        return None

    result = SIS.estimate.rough(sis_param, quiet=True)
    return extract_rop_bits(result.get("lattice", {}).get("rop"))


def compute_parameters(n: int, q: int, ell: int, m: int, sigma_1: float, sigma_2: float, alpha_h: int) -> AlgorithmArtifacts:
    if n not in ALLOWED_N:
        raise ParameterValidationError("n不合法")
    if q <= 1:
        raise ParameterValidationError("q不合法")
    if ell <= 0 or m <= 0:
        raise ParameterValidationError("l和m必须为正整数")
    if alpha_h <= 0:
        raise ParameterValidationError("alpha_h必须为正整数")
    if sigma_1 < 0.5:
        raise ParameterValidationError("sigma_1不合法，离散高斯中分布标准差太小")
    if sigma_2 < 0.5:
        raise ParameterValidationError("sigma_2不合法，离散高斯中分布标准差太小")

    lambda_bits = n // 2
    if (q - 1) % lambda_bits != 0:
        raise ParameterValidationError("q不合法，n/2不整除(q-1)，q不是NTT素数")

    bk = math.sqrt(1 + ell * n * sigma_1**2 + m * n * sigma_2**2)
    alpha_1 = floor_power_of_two(math.sqrt(n) * sigma_1)

    scale = R_SCALING[lambda_bits]
    r = math.ceil(scale * math.sqrt(alpha_1**2 - 1 + bk**2))

    mu_s = n * (r / alpha_1) ** 2 + ell * n * r**2 + m * n * r**2
    v_s = 2 * n * (r / alpha_1) ** 4 + 2 * ell * n * r**4 + 2 * m * n * r**4
    bs = math.sqrt(mu_s + 6.13 * math.sqrt(v_s))
    bv = bs + math.sqrt(n * m) * (alpha_h / 4 + 1)

    sigma_h = 2 * r / alpha_h
    if sigma_h < 0.05:
        raise ParameterValidationError("alpha_h太大，请调整")
    if not is_power_of_two(alpha_h):
        raise ParameterValidationError("alpha_h不是2的幂次")

    hh, hh_regime, sigma_h, a_h = hint_entropy(r, alpha_h)

    lwe_spec = LWEParameterSpec(
        n=ell * n,
        q=q,
        m=m * n,
        sigma_1=sigma_1,
        sigma_2=sigma_2,
        tag=None,
    )
    sis_uf_spec = SISParameterSpec(
        n=m * n,
        q=q,
        length_bound=bv,
        m=(ell + 1 + m) * n,
        norm=2,
        tag=None,
    )
    sis_suf_spec = SISParameterSpec(
        n=m * n,
        q=q,
        length_bound=2 * bv,
        m=(ell + 1 + m) * n,
        norm=2,
        tag=None,
    )

    pk_bytes = lambda_bits // 8 + math.ceil(n * m * math.ceil(math.log2(q)) / 8)
    sign_bytes_formula = (
        lambda_bits
        + n / 2 * math.log2(2 * math.pi * math.e * (r / alpha_1) ** 2)
        + ell * n / 2 * math.log2(2 * math.pi * math.e * r**2)
        + n * m * hh
    ) / 8
    sign_bytes = math.ceil(sign_bytes_formula)
    combined_bytes = pk_bytes + sign_bytes

    lwe_param, sis_uf_param, sis_suf_param = build_estimator_objects(lwe_spec, sis_uf_spec, sis_suf_spec)
    lwe_usvp_security_bit, lwe_dual_hybrid_security_bit, lwe_security_bit, lwe_best_attack = estimate_lwe_security_bits(
        lwe_param
    )
    sis_uf_security_bit = estimate_sis_security_bits(sis_uf_param)
    sis_suf_security_bit = estimate_sis_security_bits(sis_suf_param)

    result = AlgorithmResult(
        n=n,
        q=q,
        ell=ell,
        m=m,
        sigma_1=sigma_1,
        sigma_2=sigma_2,
        alpha_h=alpha_h,
        lambda_bits=lambda_bits,
        bk=bk,
        alpha_1=alpha_1,
        r=r,
        mu_s=mu_s,
        v_s=v_s,
        bs=bs,
        bv=bv,
        sigma_h=sigma_h,
        a_h=a_h,
        hh=hh,
        hh_regime=hh_regime,
        pk_bytes=pk_bytes,
        sign_bytes=sign_bytes,
        sign_bytes_ceil=sign_bytes,
        combined_bytes=combined_bytes,
        lwe_usvp_security_bit=lwe_usvp_security_bit,
        lwe_dual_hybrid_security_bit=lwe_dual_hybrid_security_bit,
        lwe_security_bit=lwe_security_bit,
        lwe_best_attack=lwe_best_attack,
        sis_uf_security_bit=sis_uf_security_bit,
        sis_suf_security_bit=sis_suf_security_bit,
        lwe_spec=lwe_spec,
        sis_uf_spec=sis_uf_spec,
        sis_suf_spec=sis_suf_spec,
        estimator_available=ESTIMATOR_AVAILABLE,
    )
    return AlgorithmArtifacts(result=result, lwe_param=lwe_param, sis_uf_param=sis_uf_param, sis_suf_param=sis_suf_param)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compute the handwritten parameter-generation algorithm.")
    parser.add_argument("--n", type=int, required=True)
    parser.add_argument("--q", type=int, required=True)
    parser.add_argument("--l", type=int, required=True, dest="ell")
    parser.add_argument("--m", type=int, required=True)
    parser.add_argument("--sigma-1", type=float, required=True, dest="sigma_1")
    parser.add_argument("--sigma-2", type=float, required=True, dest="sigma_2")
    parser.add_argument("--alpha-h", type=int, required=True, dest="alpha_h")
    parser.add_argument("--indent", type=int, default=2)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        artifacts = compute_parameters(
            n=args.n,
            q=args.q,
            ell=args.ell,
            m=args.m,
            sigma_1=args.sigma_1,
            sigma_2=args.sigma_2,
            alpha_h=args.alpha_h,
        )
    except ParameterValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(artifacts.result.to_dict(), ensure_ascii=False, indent=args.indent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())