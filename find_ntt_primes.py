#!/usr/bin/env python3

from __future__ import annotations

from math import isqrt


TARGET_NS = [256, 512, 1024]
COUNT_PER_N = 10
MIN_Q_BY_N = {
    256: 7681,
    512: 12289,
    1024: 23041,
}


def is_prime(value: int) -> bool:
    if value < 2:
        return False
    if value in (2, 3):
        return True
    if value % 2 == 0:
        return False

    limit = isqrt(value)
    divisor = 3
    while divisor <= limit:
        if value % divisor == 0:
            return False
        divisor += 2
    return True


def find_primes_for_n(n: int, count: int) -> list[int]:
    step = n // 2
    min_q = MIN_Q_BY_N[n]
    primes: list[int] = []
    multiplier = 1

    while len(primes) < count:
        candidate = step * multiplier + 1
        lower_bound = min_q if not primes else max(min_q, (3 * primes[-1] + 1) // 2)
        if candidate >= lower_bound and is_prime(candidate):
            primes.append(candidate)
        multiplier += 1

    return primes


def main() -> None:
    for n in TARGET_NS:
        primes = find_primes_for_n(n, COUNT_PER_N)
        print(f"n={n}: {primes}")


if __name__ == "__main__":
    main()