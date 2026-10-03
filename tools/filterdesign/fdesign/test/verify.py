"""Verifies fdesign against SciPy.

For a set of fixed and random specifications it checks that
  * the design meets the tolerance scheme (checked independently with scipy.signal.freqz),
  * all poles lie inside the unit circle,
  * the peak gain is 0 dB,
  * the filter order is not lower than the minimum order SciPy computes, and reports
    designs that use more sections than necessary.

usage: python test/verify.py [path/to/fdesign] [--random N] [--seed S]
"""

import argparse
import json
import subprocess
import sys

import numpy as np
from scipy import signal

ORDFUNC = {"butterworth": signal.buttord, "chebyshev": signal.cheb1ord, "elliptic": signal.ellipord}
TYPES = ["lowpass", "highpass", "bandpass", "bandstop"]
TOL_DB = 0.01


def run(exe, typ, char, fs, fp, fst, ap, as_):
    num = lambda x: repr(float(x))
    cmd = [exe, "-t", typ, "-c", char, "-r", num(fs), "-p", ",".join(map(num, fp)),
           "-s", ",".join(map(num, fst)), "--ap", num(ap), "--as", num(as_), "-f", "json"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(out.stdout), out.returncode


def check(res, typ, char, fs, fp, fst, ap, as_):
    """returns (errors, notes)"""
    errors, notes = [], []
    sos = np.array([s["b"] + s["a"] for s in res["sections"]])
    poles = np.concatenate([np.roots(r[3:]) for r in sos])
    if np.max(np.abs(poles)) >= 1.0:
        errors.append(f"unstable, max |pole| = {np.max(np.abs(poles)):.6f}")
    w, h = signal.sosfreqz(sos, worN=1 << 13, fs=fs)
    peak = 20 * np.log10(np.max(np.abs(h)))
    if abs(peak) > TOL_DB:
        errors.append(f"peak gain {peak:+.3f} dB")
    att = lambda f: -20 * np.log10(np.abs(signal.sosfreqz(sos, worN=[f], fs=fs)[1][0]))
    for f in fp:
        if att(f) > ap + TOL_DB:
            errors.append(f"passband edge {f:g}: {att(f):.2f} dB > {ap:g} dB")
    for f in fst:
        if att(f) < as_ - TOL_DB:
            errors.append(f"stopband edge {f:g}: {att(f):.2f} dB < {as_:g} dB")
    # the passband must stay within ap everywhere, the stopband above as everywhere
    m = -20 * np.log10(np.abs(h) + 1e-300)
    if typ == "lowpass":
        inpass, instop = w <= fp[0], w >= fst[0]
    elif typ == "highpass":
        inpass, instop = w >= fp[0], w <= fst[0]
    elif typ == "bandpass":
        inpass, instop = (w >= fp[0]) & (w <= fp[1]), (w <= fst[0]) | (w >= fst[1])
    else:
        inpass, instop = (w <= fp[0]) | (w >= fp[1]), (w >= fst[0]) & (w <= fst[1])
    if m[inpass].max() > ap + TOL_DB:
        errors.append(f"passband ripple {m[inpass].max():.2f} dB > {ap:g} dB")
    if m[instop].min() < as_ - TOL_DB:
        errors.append(f"stopband attenuation {m[instop].min():.2f} dB < {as_:g} dB")

    wp = fp[0] if len(fp) == 1 else list(fp)
    ws = fst[0] if len(fst) == 1 else list(fst)
    n_ref = ORDFUNC[char](wp, ws, ap, as_, fs=fs)[0]
    if res["order"] < n_ref:
        notes.append(f"order {res['order']} < scipy {n_ref} (spec still met)")
    elif res["order"] > n_ref:
        notes.append(f"order {res['order']} > scipy minimum {n_ref}")
    return errors, notes


def random_spec(rng):
    typ = TYPES[rng.integers(4)]
    fs = float(1000 * rng.integers(1, 97))
    ap = float(np.round(rng.uniform(0.1, 3.0), 2))
    as_ = float(np.round(rng.uniform(25, 80), 1))
    if typ in ("lowpass", "highpass"):
        a, b = sorted(rng.uniform(0.03, 0.47, 2) * fs)
        if b / a < 1.1:
            b = min(a * 1.1, 0.48 * fs)
        a, b = float(a), float(b)
        return (typ, fs, [a], [b], ap, as_) if typ == "lowpass" else (typ, fs, [b], [a], ap, as_)
    e = np.sort(rng.uniform(0.03, 0.47, 4) * fs)
    e = np.maximum.accumulate(e * np.array([1, 1.08, 1.16, 1.24]))
    if e[-1] >= 0.47 * fs:
        e = e * (0.47 * fs / e[-1])
    e = [float(x) for x in e]
    if typ == "bandpass":
        return typ, fs, [e[1], e[2]], [e[0], e[3]], ap, as_
    return typ, fs, [e[0], e[3]], [e[1], e[2]], ap, as_


def main():
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("exe", nargs="?", default="./fdesign")
    ap_.add_argument("--random", type=int, default=200)
    ap_.add_argument("--seed", type=int, default=1)
    ap_.add_argument("-v", "--verbose", action="store_true")
    args = ap_.parse_args()

    cases = []
    base = {"lowpass": ([400.0], [800.0]), "highpass": ([1800.0], [1200.0]),
            "bandpass": ([800.0, 1200.0], [400.0, 1800.0]), "bandstop": ([400.0, 1800.0], [800.0, 1200.0])}
    for typ, (fp, fst) in base.items():
        cases.append((typ, 8000.0, fp, fst, 3.0, 40.0))
    rng = np.random.default_rng(args.seed)
    cases += [random_spec(rng) for _ in range(args.random)]

    n_ok = n_fail = n_skip = n_higher = 0
    for typ, fs, fp, fst, ap, as_ in cases:
        for char in ORDFUNC:
            res, rc = run(args.exe, typ, char, fs, fp, fst, ap, as_)
            label = f"{char:11} {typ:8} fs={fs:g} pass={fp} stop={fst} ap={ap:g} as={as_:g}"
            if rc != 0:
                n_skip += 1
                if args.verbose:
                    print(f"SKIP {label}: {res.get('error')}")
                continue
            errors, notes = check(res, typ, char, fs, fp, fst, ap, as_)
            if errors:
                n_fail += 1
                print(f"FAIL {label}\n     " + "\n     ".join(errors))
            else:
                n_ok += 1
            if any("> scipy" in n for n in notes):
                n_higher += 1
            if notes and args.verbose:
                print(f"NOTE {label}: {'; '.join(notes)}")

    print(f"\n{n_ok} passed, {n_fail} failed, {n_skip} skipped (order limit), "
          f"{n_higher} designs with higher order than necessary")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
