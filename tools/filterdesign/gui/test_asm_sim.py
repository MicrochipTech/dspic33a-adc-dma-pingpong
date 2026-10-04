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

r"""test_asm_sim.py - the "float, dsPIC33A assembler" arithmetic in the MPLAB X simulator (04.10.2026).

    python tools\filterdesign\gui\test_asm_sim.py [--keep] [-v]

The assembler (asmgen.py) runs on a dsPIC33A only, so a PC compiler cannot test
it. This script builds one test program with XC-DSC that holds, for filters of
1 to 16 sections (every register plan of asmgen.Plan: all in registers,
coefficients as immediates, state in memory), both entry points - u12 (the
firmware's "sigproc user") and f32 (the Code tab's .s file) - and runs it in
the MPLAB X simulator through MDB. On the target it compares

  - the assembler with the C reference of the same arithmetic
    (asmgen.host_reference_c(): fmaf() in the assembler's order, XC-DSC compiles
    it to the same mac.s): every output sample and the state after the run
    must be bit-identical;
  - the u12 output with sigproc.c's plain float path (multiply, then add): at
    most 1 LSB apart;
over a 12-bit chirp with noise and runs of 0 and 4095, in blocks of 1, 7, 0,
256, 300 and the rest, so the state carries over block edges and n = 0 is
taken.

No cycle figures: the simulator has no timers and no interrupts, and MDB's
simulator does not go on after a breakpoint (W0101-SIM, 04.10.2026) - one
halt per session, at test_end(). The [plan] lines give the instructions per
sample of each generated loop; the board's "load=" figure is the measurement.

Needs XC-DSC, the dsPIC33AK-MP pack and MPLAB X (MDB); about 1-2 minutes.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools"))

import asmgen  # noqa: E402
import fdcore  # noqa: E402
import sim_trap  # noqa: E402

DEVICE = "dsPIC33AK512MPS512"
SECTIONS = (1, 2, 3, 4, 7, 12, 13, 16)
BLOCKS = (1, 7, 0, 256, 300)               # then the rest of NS
NS = 700


def find_tool(pattern: str) -> str | None:
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None


def random_sos(n: int, rng: np.random.Generator) -> np.ndarray:
    """n stable biquads, zeros on the unit circle, each scaled to about 0 dB peak."""
    rows = []
    for _ in range(n):
        r, th = rng.uniform(0.5, 0.97), rng.uniform(0.05, 3.0)
        zt = rng.uniform(0.0, np.pi)
        b = np.array([1.0, -2.0 * np.cos(zt), 1.0])
        a = np.array([1.0, -2.0 * r * np.cos(th), r * r])
        w = np.linspace(0, np.pi, 512)
        z = np.exp(-1j * w)
        h = np.abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z))
        rows.append(np.concatenate([b / h.max(), a]))
    return np.array(rows)


def designs() -> list[tuple[str, np.ndarray]]:
    rng = np.random.default_rng(20261004)
    out = []
    for n in SECTIONS:
        out.append((f"r{n}", random_sos(n, rng)))
    d = fdcore.design(fdcore.Spec())               # the tool's default design, section-scaled
    sos, _, _ = fdcore.implement(d.sos, d.spec.fs, "float_asm", True, None)
    out.append(("dflt", sos))
    return out


def test_source(filters: list[tuple[str, np.ndarray]]) -> str:
    parts = ["#include <stdint.h>\n#include <string.h>\n#include <math.h>\n\n"]
    for ident, sos in filters:
        up = ident.upper()
        n = len(sos)
        parts.append(f"#define {up}_NUM_SECTIONS {n}\n"
                     f"typedef struct {{ float s[{up}_NUM_SECTIONS][2]; }} {ident}_state_t;\n")
        parts.append(asmgen.kcoeffs_c(ident, sos))
        parts.append(f"void {ident}_u12({ident}_state_t *st, uint16_t *x, uint32_t n);\n"
                     f"void {ident}_f32({ident}_state_t *st, const float *in, float *out, uint32_t n);\n")
        parts.append(asmgen.as_c_asm_block(asmgen.kernel(f"{ident}_u12", sos, "u12")))
        parts.append(asmgen.as_c_asm_block(asmgen.kernel(f"{ident}_f32", sos, "f32")))
        parts.append(asmgen.host_reference_c("static ", ident, "u12", name=f"{ident}_ref_u12"))
        parts.append(asmgen.host_reference_c("static ", ident, "f32", name=f"{ident}_ref_f32"))
        # sigproc.c's float path for a generated C float filter: multiply, then add
        parts.append(
            f"static void {ident}_plain_u12({ident}_state_t *st, uint16_t *x, uint32_t n)\n{{\n"
            "    for (uint32_t i = 0; i < n; i++) {\n"
            "        float v = (float)x[i] - 2048.0f;\n"
            f"        for (int k = 0; k < {up}_NUM_SECTIONS; k++) {{\n"
            f"            const float *c = {ident}_kcoeffs[k];\n"
            "            float *s = st->s[k];\n"
            "            const float y = c[0] * v + s[0];\n"
            "            s[0] = c[1] * v + c[3] * y + s[1];\n"
            "            s[1] = c[2] * v + c[4] * y;\n"
            "            v = y;\n"
            "        }\n"
            "        const float o = v + 2048.5f;\n"
            "        x[i] = (o < 0.0f) ? 0u : (o >= 4095.0f) ? 4095u : (uint16_t)o;\n"
            "    }\n}\n\n")
    parts.append(f"""
#define NS {NS}
static uint16_t in_u[NS], a_u[NS], b_u[NS], c_u[NS];
static float in_f[NS], a_f[NS], b_f[NS];
static const uint32_t blocks[] = {{ {", ".join(str(b) for b in BLOCKS)}, NS }};
volatile uint32_t res_bad_u12, res_bad_f32, res_bad_state, res_far, res_checks, res_moved,
                  res_first_bad, res_done;

/* the one breakpoint: MDB's simulator does not go on after a halt (W0101-SIM) */
void __attribute__((noinline)) test_end(void) {{ __asm__ volatile (""); }}

static void make_input(void)
{{
    uint32_t r = 12345u;
    for (uint32_t i = 0; i < NS; i++) {{
        r = r * 1103515245u + 12345u;
        const float ph = 0.00004f * (float)i * (float)i;
        int32_t v = 2048 + (int32_t)(1900.0f * sinf(ph)) + (int32_t)((r >> 16) % 301u) - 150;
        if (i >= 400 && i < 420) {{ v = 4095; }}        /* runs at the rails */
        if (i >= 500 && i < 520) {{ v = 0; }}
        if (v < 0) {{ v = 0; }}
        if (v > 4095) {{ v = 4095; }}
        in_u[i] = (uint16_t)v;
        in_f[i] = ((float)v - 2048.0f) * 1.37f;
    }}
}}

#define RUN(ID, IDX) do {{ \\
    ID##_state_t sa, sb, sc; \\
    memset(&sa, 0, sizeof sa); memset(&sb, 0, sizeof sb); memset(&sc, 0, sizeof sc); \\
    memcpy(a_u, in_u, sizeof a_u); memcpy(b_u, in_u, sizeof b_u); memcpy(c_u, in_u, sizeof c_u); \\
    uint32_t at = 0; \\
    for (uint32_t b = 0; b < sizeof blocks / sizeof blocks[0] && at < NS; b++) {{ \\
        uint32_t n = (blocks[b] > NS - at) ? NS - at : blocks[b]; \\
        ID##_u12(&sa, a_u + at, n); ID##_ref_u12(&sb, b_u + at, n); ID##_plain_u12(&sc, c_u + at, n); \\
        at += n; \\
    }} \\
    for (uint32_t i = 0; i < NS; i++) {{ \\
        res_checks++; \\
        if (a_u[i] != b_u[i]) {{ res_bad_u12++; if (!res_first_bad) res_first_bad = IDX; }} \\
        int32_t d = (int32_t)a_u[i] - (int32_t)c_u[i]; \\
        if (d > 1 || d < -1) {{ res_far++; if (!res_first_bad) res_first_bad = 100 + IDX; }} \\
        if (i > 0 && a_u[i] != a_u[i - 1]) res_moved++; \\
    }} \\
    if (memcmp(&sa, &sb, sizeof sa) != 0) {{ res_bad_state++; if (!res_first_bad) res_first_bad = 200 + IDX; }} \\
    memset(&sa, 0, sizeof sa); memset(&sb, 0, sizeof sb); \\
    at = 0; \\
    for (uint32_t b = 0; b < sizeof blocks / sizeof blocks[0] && at < NS; b++) {{ \\
        uint32_t n = (blocks[b] > NS - at) ? NS - at : blocks[b]; \\
        ID##_f32(&sa, in_f + at, a_f + at, n); ID##_ref_f32(&sb, in_f + at, b_f + at, n); \\
        at += n; \\
    }} \\
    if (memcmp(a_f, b_f, sizeof a_f) != 0 || memcmp(&sa, &sb, sizeof sa) != 0) \\
        {{ res_bad_f32++; if (!res_first_bad) res_first_bad = 300 + IDX; }} \\
}} while (0)

int main(void)
{{
    make_input();
""")
    for i, (ident, _) in enumerate(filters, start=1):
        parts.append(f"    RUN({ident}, {i});\n")
    parts.append("    res_done = 1;\n    test_end();\n    for (;;) { }\n}\n")
    return "".join(parts)


def build(src: str, work: str, verbose: bool) -> str:
    cc = find_tool(r"C:\Program Files\Microchip\xc-dsc\v*\bin\xc-dsc-gcc.exe")
    dfp = find_tool(r"C:\Program Files\Microchip\MPLABX\v*\packs\Microchip\dsPIC33AK-MP_DFP\*\xc16")
    if not cc or not dfp:
        sys.exit(f"missing: xc-dsc-gcc={cc} dsPIC33AK-MP_DFP={dfp}")
    c = os.path.join(work, "asm_sim.c")
    elf = os.path.join(work, "asm_sim.elf")
    with open(c, "w", encoding="ascii", newline="\n") as f:
        f.write(src)
    cmd = [cc, "-mcpu=33AK512MPS512", f"-mdfp={dfp}", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
           "-T" + os.path.join(dfp, "support", "dsPIC33A", "gld", "p33AK512MPS512.gld"),
           c, "-o", elf, f"-Wl,-Map={os.path.join(work, 'asm_sim.map')}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if verbose or r.returncode:
        print(out)
    if r.returncode or not os.path.exists(elf):
        sys.exit("build failed")
    return elf


def func_address(elf: str, name: str) -> int:
    out = subprocess.run([sim_trap.find_nm(), elf], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[2] == "_" + name:
            return int(p[0], 16)
    sys.exit(f"{name} not in {elf}")


def wait_new(m, start: int, pattern: str, timeout: float) -> bool:
    """Whether an MDB line after index start matches pattern within timeout."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if any(re.search(pattern, l) for l in m.lines[start:]):
            return True
        time.sleep(0.2)
    return False


HALTED = r"Simulator halted"


def value(lines: list[str], name: str) -> int | None:
    for l in lines:
        m = re.match(rf"{name}\s*=\s*(-?\d+)", l)
        if m:
            return int(m.group(1))
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", action="store_true", help="keep the work folder (source, ELF, map)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    filters = designs()
    for ident, sos in filters:
        for io in ("u12", "f32"):
            p = asmgen.Plan(len(sos), io)
            print(f"[plan] {ident} {io}: {len(sos)} section(s), {p.used} FPU registers, "
                  f"coefficients in registers for {p.n_coef}, state for {p.n_state}, "
                  f"{asmgen.loop_instructions(asmgen.kernel('k', sos, io))} instructions per sample")
    work = tempfile.mkdtemp(prefix="asm_sim_")
    t0 = time.time()
    elf = build(test_source(filters), work, a.verbose)
    print(f"[build] {elf} ({time.time() - t0:.0f} s)")

    bat = sim_trap.find_mdb()
    if not bat:
        sys.exit("MDB not found (MPLAB X)")
    m = sim_trap.Mdb(bat, a.verbose)
    names = ["res_done", "res_checks", "res_bad_u12", "res_bad_f32", "res_bad_state", "res_far",
             "res_moved", "res_first_bad"]
    problems = []
    try:
        m.cmd(f"Device {DEVICE}", 3)
        m.cmd("Hwtool SIM", 2)
        if not m.wait_for(r">|Resetting", 60):
            sys.exit("simulator did not come up")
        m.cmd(f'Program "{elf}"', 2)
        if not m.wait_for(r"Program succeeded", 90):
            sys.exit("programming failed:\n" + "\n".join(m.lines[-10:]))
        m.cmd(f"Break *0x{func_address(elf, 'test_end'):x}", 1)
        t1 = time.time()
        start = len(m.lines)
        m.cmd("Run", 1)
        if not wait_new(m, start, HALTED, 600):
            m.cmd("Halt", 2)
        got = m.print_symbols(names)
        vals = {n: value(got, n) for n in names}
        print(f"[run] comparisons {time.time() - t1:.0f} s: " +
              ", ".join(f"{n}={vals.get(n)}" for n in names))
        if vals.get("res_done") != 1:
            problems.append("the comparisons did not finish (res_done != 1)")
        else:
            for n in ("res_bad_u12", "res_bad_f32", "res_bad_state", "res_far"):
                if vals.get(n) != 0:
                    problems.append(f"{n} = {vals.get(n)} (first failing check {vals.get('res_first_bad')}: "
                                    "1..: u12 sample, 101..: >1 LSB from plain float, 201..: state, "
                                    "301..: f32)")
            if vals.get("res_checks") != NS * len(filters):
                problems.append(f"res_checks = {vals.get('res_checks')}, expected {NS * len(filters)}")
            if (vals.get("res_moved") or 0) < NS * len(filters) // 4:
                problems.append(f"res_moved = {vals.get('res_moved')}: the outputs hardly change - "
                                "the comparison would prove little")
    finally:
        m.quit()
        if not a.keep:
            for f in glob.glob(os.path.join(work, "*")):
                os.remove(f)
            os.rmdir(work)
        else:
            print(f"[keep] {work}")
    if problems:
        for p in problems:
            print("[FAIL]", p)
        print("[asm-sim] FAIL")
        return 1
    print("[asm-sim] PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
