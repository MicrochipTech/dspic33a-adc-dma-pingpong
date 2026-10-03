# Copyright (C) 2026 Microchip Technology Inc. and its subsidiaries.
#
# Subject to your compliance with these terms, you may use Microchip software
# and any derivatives exclusively with Microchip products. It is your
# responsibility to comply with third party license terms applicable to your
# use of third party software (including open source software) that may
# accompany Microchip software.
#
# THIS SOFTWARE IS SUPPLIED BY MICROCHIP "AS IS". NO WARRANTIES, WHETHER
# EXPRESS, IMPLIED OR STATUTORY, APPLY TO THIS SOFTWARE, INCLUDING ANY IMPLIED
# WARRANTIES OF NON-INFRINGEMENT, MERCHANTABILITY, AND FITNESS FOR A
# PARTICULAR PURPOSE.
#
# IN NO EVENT WILL MICROCHIP BE LIABLE FOR ANY INDIRECT, SPECIAL, PUNITIVE,
# INCIDENTAL OR CONSEQUENTIAL LOSS, DAMAGE, COST OR EXPENSE OF ANY KIND
# WHATSOEVER RELATED TO THE SOFTWARE, HOWEVER CAUSED, EVEN IF MICROCHIP HAS
# BEEN ADVISED OF THE POSSIBILITY OR THE DAMAGES ARE FORESEEABLE. TO THE
# FULLEST EXTENT ALLOWED BY LAW, MICROCHIP'S TOTAL LIABILITY ON ALL CLAIMS IN
# ANY WAY RELATED TO THIS SOFTWARE WILL NOT EXCEED THE AMOUNT OF FEES, IF ANY,
# THAT YOU HAVE PAID DIRECTLY TO MICROCHIP FOR THIS SOFTWARE.

r"""test_user_filter_xcheck.py - "sigproc user" (src/core/sigproc.c with a
generated user_filter.h) against a model of the same arithmetic (03.10.2026).

    python tests\host\test_user_filter_xcheck.py

tools/filterdesign writes user_filter.h; sigproc.c centres the 12-bit
samples, scales them into the filter's sample type and back, clamps, and
clears the state on a gap. This script checks that whole path on a host gcc
for each arithmetic, with the fixtures in tests/host/user_filter/<arith>/
(written by `python tools/filterdesign/gui/firmware.py --fixtures
tests/host/user_filter`: the same elliptic band-pass in float, double -
long double in the firmware -, fixed32 and fixed16, each with its
user_filter.json):

- uf_harness.c and sigproc.c are compiled, -Wall -Wextra -Werror, with a
  copy of sigproc.c beside the fixture's user_filter.h (a quoted include
  looks in the including file's folder first, -I cannot override that);
- the input is a full-scale chirp with noise, clipped samples at 0 and 4095
  included, in blocks of 256 with a gap at block 5;
- the model, standard library only: fixed point bit-exact (the generated
  code's direct form I, 64-bit accumulator, round half up, saturate - Python
  integers shift right arithmetically like the C code assumes); float and
  long double in Python's double, the C result within 1 LSB (float's 24-bit
  mantissa against a 12-bit output);
- the harness's id, rate and description equal the fixture JSON's.
Standard library only, like every tests/host script (tools\hosttest.bat).
"""
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
FIX = os.path.join(HERE, "user_filter")
BLK, GAP_AT, NBLK = 256, 5, 12


def make_input():
    rnd = random.Random(1234)
    n = BLK * NBLK
    out = []
    for i in range(n):
        ph = 2.0 * math.pi * (0.002 * i + 0.125 * i * i / n)   # chirp, 0.002 .. 0.252 fs
        v = 2048 + 2100 * math.sin(ph) + rnd.gauss(0.0, 40.0)   # clips at both ends
        out.append(min(4095, max(0, int(round(v)))))
    return out


def model_fixed(x, info):
    word, frac = info["fixed"]["word"], info["fixed"]["frac"]
    coeffs = info["fixed"]["coeffs"]
    shift = word - 12
    vmax, vmin = (1 << (word - 1)) - 1, -(1 << (word - 1))
    rnd = (1 << frac) >> 1
    out = []
    st = None
    for i, s in enumerate(x):
        b = i // BLK
        if i % BLK == 0 and (b == 0 or b == GAP_AT):
            st = [[0, 0, 0, 0] for _ in coeffs]             # x1 x2 y1 y2 per section
        v = (s - 2048) << shift
        for c, z in zip(coeffs, st):
            acc = c[0] * v + c[1] * z[0] + c[2] * z[1] - c[3] * z[2] - c[4] * z[3]
            acc = (acc + rnd) >> frac
            acc = vmax if acc > vmax else vmin if acc < vmin else acc
            z[1], z[0] = z[0], v
            z[3], z[2] = z[2], acc
            v = acc
        o = ((v + (1 << (shift - 1))) >> shift) + 2048
        out.append(min(4095, max(0, o)))
    return out


def model_float(x, info):
    sos = info["sos"]
    out = []
    st = None
    for i, s in enumerate(x):
        b = i // BLK
        if i % BLK == 0 and (b == 0 or b == GAP_AT):
            st = [[0.0, 0.0] for _ in sos]
        v = float(s) - 2048.0
        for r, z in zip(sos, st):                          # transposed direct form II
            y = r[0] * v + z[0]
            z[0] = r[1] * v - r[4] * y + z[1]
            z[1] = r[2] * v - r[5] * y
            v = y
        o = v + 2048.5
        out.append(0 if o < 0 else 4095 if o >= 4095 else int(o))
    return out


def main():
    gcc = shutil.which("gcc")
    if not gcc:
        print("test_user_filter_xcheck: no gcc on the PATH - FAIL")
        return 1
    x = make_input()
    work = tempfile.mkdtemp(prefix="uf_xcheck_")
    inp = os.path.join(work, "input.txt")
    with open(inp, "w") as f:
        f.write("\n".join(str(v) for v in x) + "\n")
    src = os.path.join(ROOT, "src")
    inc = [f"-I{os.path.join(src, d)}" for d in ("drivers", "app", "core", "lab", "lib", "sim", "port")]
    failed = 0
    try:
        for arith in ("float", "double", "fixed32", "fixed16"):
            fdir = os.path.join(FIX, arith)
            with open(os.path.join(fdir, "user_filter.json"), encoding="utf-8") as f:
                info = json.load(f)
            exe = os.path.join(work, f"uf_{arith}.exe")
            # sigproc.c's #include "user_filter.h" looks in sigproc.c's own folder before
            # any -I: a copy of sigproc.c goes next to a copy of the fixture's header
            cdir = os.path.join(work, arith)
            os.makedirs(cdir)
            shutil.copy(os.path.join(src, "core", "sigproc.c"), cdir)
            shutil.copy(os.path.join(fdir, "user_filter.h"), cdir)
            cc = [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror", f"-I{cdir}"] + inc + [
                os.path.join(FIX, "uf_harness.c"), os.path.join(cdir, "sigproc.c"), "-o", exe, "-lm"]
            r = subprocess.run(cc, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"  {arith}: BUILD FAILED\n{r.stdout}{r.stderr}")
                failed += 1
                continue
            r = subprocess.run([exe, inp, str(BLK), str(GAP_AT)], capture_output=True, text=True)
            lines = r.stdout.splitlines()
            if r.returncode != 0 or not lines:
                print(f"  {arith}: harness failed: {r.stderr.strip()}")
                failed += 1
                continue
            head = lines[0].split(" ", 5)
            got = [int(v) for v in lines[1:]]
            ok_meta = (head[1] == info["id"] and int(head[3]) == round(info["spec"]["fs"])
                       and head[5] == info["description"])
            exp = model_fixed(x, info) if info["fixed"] else model_float(x, info)
            diff = [abs(a - b) for a, b in zip(got, exp)]
            limit = 0 if info["fixed"] else 1
            n_diff = sum(1 for d in diff if d)
            clipped = sum(1 for v in got if v in (0, 4095))
            ok = ok_meta and len(got) == len(exp) and max(diff) <= limit
            print(f"  {arith:8s} id {head[1]} {'ok' if ok_meta else 'MISMATCH'}; {len(got)} samples, "
                  f"max |C - model| = {max(diff)} LSB (limit {limit}), {n_diff} differ, "
                  f"{clipped} at the clamp -> {'PASS' if ok else 'FAIL'}")
            failed += 0 if ok else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"test_user_filter_xcheck: {'PASS' if not failed else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
