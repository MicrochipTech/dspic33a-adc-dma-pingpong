"""Core of the FilterDesign GUI: runs the fdesign command line tool and analyses the result.

The filter design itself is done by the C library (../fdesign). This module only
evaluates the returned second order sections (frequency response, poles/zeros,
time responses) and models the fixed-point implementation that codegen.py emits.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal

HERE = Path(__file__).resolve().parent
FDESIGN_DIR = HERE.parent / "fdesign"

TYPES = ["lowpass", "highpass", "bandpass", "bandstop"]
CHARACTERISTICS = ["butterworth", "chebyshev", "elliptic"]


class DesignError(Exception):
    """Raised when fdesign rejects the specification or the design fails."""


def find_fdesign() -> Path:
    """Locates the fdesign executable (env FDESIGN, ../fdesign, PATH)."""
    candidates = []
    if os.environ.get("FDESIGN"):
        candidates.append(Path(os.environ["FDESIGN"]))
    exe = "fdesign.exe" if sys.platform == "win32" else "fdesign"
    candidates.append(FDESIGN_DIR / exe)
    on_path = shutil.which("fdesign")
    if on_path:
        candidates.append(Path(on_path))
    for c in candidates:
        if c.is_file():
            return c
    built = build_fdesign()
    if built:
        return built
    raise DesignError(
        f"fdesign executable not found. Build it first: cd {FDESIGN_DIR} && make "
        "(Windows: mingw32-make), or set the environment variable FDESIGN."
    )


def build_fdesign() -> Path | None:
    """Builds ../fdesign with the host gcc, the Makefile's default build without make
    (not git-tracked, so the first start of the GUI in a fresh checkout does this)."""
    exe = FDESIGN_DIR / ("fdesign.exe" if sys.platform == "win32" else "fdesign")
    gcc = shutil.which(os.environ.get("CC", "gcc"))
    if not gcc:
        return None
    cmd = [gcc, "-O2", "-std=c99", "-Ilib", "-Isrc", "-DFLD_REAL_TYPE=double", "-o", exe.name,
           "src/main.c", "src/fdesign.c", "lib/filter_design.c", "-lm"]
    try:
        r = subprocess.run(cmd, cwd=str(FDESIGN_DIR), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return exe if r.returncode == 0 and exe.is_file() else None


@dataclass
class Spec:
    type: str = "bandpass"
    characteristic: str = "elliptic"
    fs: float = 8000.0
    fpass: list[float] = field(default_factory=lambda: [800.0, 1200.0])
    fstop: list[float] = field(default_factory=lambda: [400.0, 1800.0])
    ap: float = 1.0
    as_: float = 40.0

    @property
    def two_edges(self) -> bool:
        return self.type in ("bandpass", "bandstop")


@dataclass
class Design:
    spec: Spec
    order: int
    digital_order: int
    sos: np.ndarray            # shape (n, 6): b0 b1 b2 a0 a1 a2
    section_order: list[int]   # 1 or 2 per section
    att_pass: list[float]
    att_stop: list[float]
    spec_met: bool
    raw: dict


def design(spec: Spec, exe: Path | None = None) -> Design:
    exe = exe or find_fdesign()
    n = 2 if spec.two_edges else 1
    num = lambda x: repr(float(x))
    cmd = [str(exe), "-t", spec.type, "-c", spec.characteristic, "-r", num(spec.fs),
           "-p", ",".join(num(f) for f in spec.fpass[:n]),
           "-s", ",".join(num(f) for f in spec.fstop[:n]),
           "--ap", num(spec.ap), "--as", num(spec.as_), "-f", "json"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except OSError as e:
        raise DesignError(f"cannot run {exe}: {e}") from e
    try:
        res = json.loads(out.stdout)
    except json.JSONDecodeError as e:
        raise DesignError(f"unexpected output from fdesign: {out.stdout or out.stderr}") from e
    if "error" in res:
        raise DesignError(res["error"])
    sos = np.array([s["b"] + s["a"] for s in res["sections"]], dtype=float)
    return Design(spec=spec, order=res["order"], digital_order=res["digital_order"], sos=sos,
                  section_order=[s["order"] for s in res["sections"]],
                  att_pass=res["att_pass"], att_stop=res["att_stop"],
                  spec_met=res["spec_met"], raw=res)


# --------------------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------------------

def freq_axis(fs: float, n: int = 2048, log: bool = False) -> np.ndarray:
    if log:
        return np.logspace(np.log10(fs / 2 / 1e4), np.log10(fs / 2), n)
    return np.linspace(0, fs / 2, n)


def response(sos: np.ndarray, f: np.ndarray, fs: float) -> np.ndarray:
    return signal.sosfreqz(sos, worN=f, fs=fs)[1]


def magnitude_db(h: np.ndarray, floor: float = -200.0) -> np.ndarray:
    return np.maximum(20 * np.log10(np.abs(h) + 1e-300), floor)


def phase_deg(h: np.ndarray) -> np.ndarray:
    return np.degrees(np.unwrap(np.angle(h)))


def group_delay(sos: np.ndarray, f: np.ndarray, fs: float) -> np.ndarray:
    """Group delay in samples (sum over the sections)."""
    gd = np.zeros_like(f)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for row in sos:
            b, a = row[:3], row[3:]
            if row[2] == 0 and row[5] == 0:
                b, a = b[:2], a[:2]
            gd += signal.group_delay((b, a), w=f, fs=fs)[1]
    gd[~np.isfinite(gd)] = np.nan
    return gd


def zeros_poles(sos: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    zs, ps = [], []
    for row in sos:
        k = 2 if (row[2] != 0 or row[5] != 0) else 1
        zs.append(np.roots(row[:k + 1]) if np.any(row[1:k + 1]) else np.zeros(k))
        ps.append(np.roots(row[3:4 + k]))
    return np.concatenate(zs), np.concatenate(ps)


def impulse_response(sos: np.ndarray, n: int) -> np.ndarray:
    x = np.zeros(n)
    x[0] = 1.0
    return signal.sosfilt(sos, x)


def step_response(sos: np.ndarray, n: int) -> np.ndarray:
    return signal.sosfilt(sos, np.ones(n))


def settle_length(sos: np.ndarray, rel: float = 1e-4, nmax: int = 1 << 15) -> int:
    """Number of samples until the impulse response has decayed below rel * peak."""
    h = impulse_response(sos, nmax)
    peak = np.max(np.abs(h))
    above = np.nonzero(np.abs(h) > rel * peak)[0]
    return int(above[-1] + 1) if len(above) else 1


def partial_peak_gains(sos: np.ndarray, fs: float, n: int = 4096) -> np.ndarray:
    """Peak gain (linear) at the output of each section of the cascade."""
    f = freq_axis(fs, n)
    h = np.ones(len(f), complex)
    peaks = []
    for row in sos:
        h = h * signal.sosfreqz(row[None, :], worN=f, fs=fs)[1]
        peaks.append(np.max(np.abs(h)))
    return np.array(peaks)


def scale_sections(sos: np.ndarray, fs: float) -> np.ndarray:
    """L-infinity scaling: the peak gain at every section output becomes 1 (0 dB).

    Distributes the overall gain over the cascade so that no internal node of a
    fixed-point implementation exceeds the input range. The overall response is unchanged.
    """
    out = sos.copy()
    f = freq_axis(fs, 4096)
    h = np.ones(len(f), complex)
    for k in range(len(out)):
        hk = signal.sosfreqz(out[k][None, :], worN=f, fs=fs)[1]
        peak = np.max(np.abs(h * hk))
        g = 1.0 / peak if peak > 0 else 1.0
        if k == len(out) - 1:
            g = 1.0   # keep the overall gain of the design
        if k + 1 < len(out):
            out[k, :3] *= g
            out[k + 1, :3] /= g
        h = h * hk * g
    return out


# --------------------------------------------------------------------------------------
# Fixed point model (identical to the C code emitted by codegen.py)
# --------------------------------------------------------------------------------------

@dataclass
class FixedPoint:
    word: int                 # 16 or 32 bit data and coefficients
    frac: int                 # fractional bits of the coefficients
    coeffs: np.ndarray        # int, shape (n, 5): b0 b1 b2 a1 a2
    clipped: bool             # True if a coefficient did not fit into the word

    @property
    def coeff_range(self) -> float:
        return 2.0 ** (self.word - 1 - self.frac)

    def as_float_sos(self) -> np.ndarray:
        c = self.coeffs.astype(float) / (1 << self.frac)
        return np.column_stack([c[:, 0], c[:, 1], c[:, 2], np.ones(len(c)), c[:, 3], c[:, 4]])


def auto_frac_bits(sos: np.ndarray, word: int) -> int:
    """Largest number of fractional bits for which all coefficients fit into the word."""
    cmax = np.max(np.abs(sos[:, [0, 1, 2, 4, 5]]))
    int_bits = 0
    while cmax >= 2.0 ** int_bits * (1 - 2.0 ** -(word - 1)):
        int_bits += 1
    return word - 1 - int_bits


def quantize(sos: np.ndarray, word: int, frac: int) -> FixedPoint:
    c = sos[:, [0, 1, 2, 4, 5]] * (1 << frac)
    q = np.sign(c) * np.floor(np.abs(c) + 0.5)      # round half away from zero
    lo, hi = -(1 << (word - 1)), (1 << (word - 1)) - 1
    clipped = bool(np.any(q < lo) or np.any(q > hi))
    q = np.clip(q, lo, hi).astype(np.int64)
    return FixedPoint(word=word, frac=frac, coeffs=q, clipped=clipped)


def fixed_filter(fp: FixedPoint, x: np.ndarray) -> tuple[np.ndarray, int]:
    """Bit-exact model of the generated fixed-point code (direct form I, 64 bit accumulator,
    rounding, saturation). x are integer samples. Returns (y, number of saturations)."""
    lo, hi = -(1 << (fp.word - 1)), (1 << (fp.word - 1)) - 1
    rnd = 1 << (fp.frac - 1) if fp.frac > 0 else 0
    coeffs = [tuple(int(v) for v in row) for row in fp.coeffs]
    state = [[0, 0, 0, 0] for _ in coeffs]          # x1 x2 y1 y2
    y = np.empty(len(x), dtype=np.int64)
    sat = 0
    for i, xi in enumerate(x.tolist()):
        v = int(xi)
        for (b0, b1, b2, a1, a2), s in zip(coeffs, state):
            acc = b0 * v + b1 * s[0] + b2 * s[1] - a1 * s[2] - a2 * s[3]
            out = (acc + rnd) >> fp.frac
            if out > hi:
                out, sat = hi, sat + 1
            elif out < lo:
                out, sat = lo, sat + 1
            s[1], s[0] = s[0], v
            s[3], s[2] = s[2], out
            v = out
        y[i] = v
    return y, sat


def fixed_impulse_response(fp: FixedPoint, n: int, amplitude: float = 0.5) -> tuple[np.ndarray, int]:
    """Impulse response of the fixed-point filter, scaled back to 1.0 = impulse height."""
    full = (1 << (fp.word - 1)) - 1
    imp = int(round(amplitude * full))
    x = np.zeros(n, dtype=np.int64)
    x[0] = imp
    y, sat = fixed_filter(fp, x)
    return y / imp, sat


def fixed_step_response(fp: FixedPoint, n: int, amplitude: float = 0.5) -> np.ndarray:
    """Step response of the fixed-point filter, scaled back to 1.0 = step height."""
    full = (1 << (fp.word - 1)) - 1
    level = int(round(amplitude * full))
    y, _ = fixed_filter(fp, np.full(n, level, dtype=np.int64))
    return y / level


ARITHMETICS = ["float", "double", "fixed32", "fixed16"]


def gain_factor(gain_db: float) -> float:
    """The output gain as a factor (0 dB -> 1.0)."""
    return 10.0 ** (float(gain_db) / 20.0)


def implement(design_sos: np.ndarray, fs: float, arith: str, scaled: bool = True,
              frac: int | None = None,
              gain_db: float = 0.0) -> tuple[np.ndarray, FixedPoint | None, np.ndarray]:
    """Builds the implementation of a design for one arithmetic.

    Returns (sos, fixed, impl_sos): the (optionally scaled) cascade, its quantized
    coefficients for fixed point (else None) and the cascade with the coefficients
    the target actually uses (float32-rounded / quantized) for response plots.
    frac=None selects the fractional bits automatically.

    gain_db (04.10.2026) is an output gain folded into b0..b2 of the last section:
    no extra operation per sample in any arithmetic, and every node before the
    output keeps the section scaling's 0 dB. The returned cascades include it.
    """
    sos = scale_sections(design_sos, fs) if scaled else design_sos.copy()
    if gain_db:
        sos = sos.copy()
        sos[-1, :3] *= gain_factor(gain_db)
    fixed = None
    if arith.startswith("fixed"):
        word = int(arith[5:])
        f = auto_frac_bits(sos, word) if frac is None else int(max(0, min(word - 1, frac)))
        fixed = quantize(sos, word, f)
        impl_sos = fixed.as_float_sos()
    elif arith in ("float", "float_asm"):
        impl_sos = sos.astype(np.float32).astype(float)
    else:
        impl_sos = sos
    return sos, fixed, impl_sos
