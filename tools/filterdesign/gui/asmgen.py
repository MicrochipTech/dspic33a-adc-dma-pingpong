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

"""asmgen.py - the float cascade as dsPIC33A assembler (arithmetic "float_asm", 04.10.2026).

The same transposed direct form II as the generated C float code, per section

    y  = b0*x + s0
    s0 = (s1 + b1*x) + (-a1)*y
    s1 = (b2*x)      + (-a2)*y

but every "+ c*v" is one fused multiply-add of the dsPIC33A FPU (mac.s fa,fb,fd:
fd = fd + fa*fb, one rounding; XC-DSC compiles fmaf() to it). So the result is not
bit-exact to the C float code (that rounds after every multiply) but to C written
with fmaf() in this order - which is what host_reference_c() emits and what the
simulator test (test_asm_sim.py) compares against.

How it is fast: the whole block is one routine (no call per sample); the
coefficients are immediates loaded once into FPU registers, the state stays in
registers for the whole block; per section 7 FPU instructions (2 mov.s, 4 mac.s,
1 mul.s). The state update of section k (needs its output y) is emitted after
the next section's first mac, so it fills the time the FPU needs for that
result instead of waiting for it.

When the 32 FPU registers (F0-F7 scratch, F8-F31 saved and restored, XC-DSC
user guide DS50003918 "Mixing Assembly Language and C") run out:
  - coefficients beyond the registers are loaded as immediates right before use;
  - from 13 sections (u12) on, the state of the last sections is loaded from and
    stored to the state struct every sample.
Only W0-W7 are used (no W register to save).

Two entry points (io):
  "u12"  void sym(state *st, uint16_t *x, uint32_t n)
         the firmware's "sigproc user": x in place, 12-bit ADC samples; the filter
         gets x - 2048, the result + 2048.5 is clamped to 0..4095 and truncated -
         the same as sigproc.c's float user_cascade().
  "f32"  void sym(state *st, const float *in, float *out, uint32_t n)
         plain float samples, for the Code tab (in and out may be the same buffer).
The state is float s[N][2] (s0, s1 per section), the same layout as the C float filter.
"""

from __future__ import annotations

import struct

import numpy as np

NREGS = 32            # F0..F31
SCRATCH = 8           # F0..F7 need not be preserved

# what the u12 entry adds and clamps to (sigproc.c's float path)
U12_OFFSET = 2048.5
U12_MAX = 4095.0


def f32_bits(v: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(np.float32(v))))[0]


def kernel_coeffs(sos: np.ndarray) -> list[list[float]]:
    """Per section b0, b1, b2, -a1, -a2 as float32 values (the immediates of the code)."""
    return [[float(np.float32(v)) for v in (r[0], r[1], r[2], -r[4], -r[5])] for r in sos]


class Plan:
    """Which value lives in which FPU register."""

    def __init__(self, n: int, io: str):
        self.used = 0                                 # registers F0..F(used-1) are in use

        def take() -> str:
            assert self.used < NREGS
            self.used += 1
            return f"f{self.used - 1}"
        self.ring = [take(), take()]                  # v_k: section input / output
        self.k_off = self.k_zero = self.k_max = None
        if io == "u12":
            self.k_off, self.k_zero, self.k_max = take(), take(), take()
        fixed = 2 + (3 if io == "u12" else 0)
        if 7 * n + fixed <= NREGS:                    # everything in registers
            ctemp, mtemp, n_state, n_coef = 0, 0, n, n
        else:
            ctemp = 2
            if fixed + ctemp + 2 * n <= NREGS:
                mtemp, n_state = 0, n
            else:
                mtemp = 2
                n_state = (NREGS - fixed - ctemp - mtemp) // 2
            n_coef = min(n, (NREGS - fixed - ctemp - mtemp - 2 * n_state) // 5)
        self.ctemp = [take() for _ in range(ctemp)]
        self.mtemp = [take() for _ in range(mtemp)]
        self.state = [(take(), take()) if k < n_state else None for k in range(n)]
        self.coef = [[take() for _ in range(5)] if k < n_coef else None for k in range(n)]
        self.n_state, self.n_coef = n_state, n_coef


def kernel(sym: str, sos: np.ndarray, io: str = "u12") -> list[str]:
    """The assembler lines of one routine (global symbol _<sym>)."""
    assert io in ("u12", "f32")
    n = len(sos)
    c = kernel_coeffs(sos)
    p = Plan(n, io)
    lab = f".L_{sym}"
    out: list[str] = []
    emit = lambda s: out.append("\t" + s)
    ctoggle = [0]

    def coef(k: int, j: int) -> str:
        if p.coef[k] is not None:
            return p.coef[k][j]
        t = p.ctemp[ctoggle[0]]
        ctoggle[0] ^= 1
        emit(f"mov.l\t#0x{f32_bits(c[k][j]):08x},{t}\t; s{k} {['b0', 'b1', 'b2', '-a1', '-a2'][j]}")
        return t

    def regs_of(k: int) -> tuple[str, str]:
        return p.state[k] if p.state[k] is not None else (p.mtemp[0], p.mtemp[1])

    def tail(k: int, y: str) -> None:
        """The part of section k that needs its output y."""
        s0, s1 = regs_of(k)
        emit(f"mac.s\t{coef(k, 3)},{y},{s0}")
        emit(f"mac.s\t{coef(k, 4)},{y},{s1}")
        if p.state[k] is None:                        # state lives in memory
            emit(f"mov.l\t{s0},[w0+{8 * k}]")
            emit(f"mov.l\t{s1},[w0+{8 * k + 4}]")

    saved = [f"f{r}" for r in range(SCRATCH, p.used)]
    head = [
        f"; {sym}: {n} section(s), float32, generated by tools/filterdesign (asmgen.py)",
        f"; registers: {p.n_coef} of {n} section(s) with coefficients in FPU registers, "
        f"{p.n_state} with the state in registers",
        "\t.pushsection .text,code",
        "\t.align\t4",
        f"\t.global\t_{sym}",
        f"\t.type\t_{sym},@function",
        f"_{sym}:",
    ]
    out.extend(head)
    for r in saved:
        emit(f"push.l\t{r}")
    if io == "u12":
        emit(f"mov.l\t#0x{f32_bits(U12_OFFSET):08x},{p.k_off}\t; {U12_OFFSET}")
        emit(f"mov.l\t#0x00000000,{p.k_zero}\t; 0.0")
        emit(f"mov.l\t#0x{f32_bits(U12_MAX):08x},{p.k_max}\t; {U12_MAX}")
    for k in range(n):
        if p.coef[k] is not None:
            for j, r in enumerate(p.coef[k]):
                emit(f"mov.l\t#0x{f32_bits(c[k][j]):08x},{r}\t; s{k} {['b0', 'b1', 'b2', '-a1', '-a2'][j]}")
        if p.state[k] is not None:
            emit(f"mov.l\t[w0+{8 * k}],{p.state[k][0]}")
            emit(f"mov.l\t[w0+{8 * k + 4}],{p.state[k][1]}")
    # loop set-up: u12 w1 = x, w2 = n -> w3 = end, w5 = -2048; f32 w1 = in, w2 = out, w3 = n
    if io == "u12":
        emit("cp.l\tw2,#0")
        emit(f"bra\tz,{lab}_done")
        emit("add.l\tw2,w2,w3")
        emit("add.l\tw1,w3,w3")
        emit("movs.l\t#0xF800,w5\t; -2048")
    else:
        emit("cp.l\tw3,#0")
        emit(f"bra\tz,{lab}_done")
    out.append(f"{lab}_loop:")
    v0 = p.ring[0]
    if io == "u12":
        emit("mov.w\t[w1],w4")
        emit("add.l\tw4,w5,w4")
        emit(f"mov.l\tw4,{v0}")
        emit(f"li2f.s\t{v0},{v0}")
    else:
        emit(f"mov.l\t[w1++],{v0}")
    pending = None                                    # section whose tail is still due
    for k in range(n):
        x, y = p.ring[k % 2], p.ring[(k + 1) % 2]
        s0, s1 = regs_of(k)
        if p.state[k] is None:
            emit(f"mov.l\t[w0+{8 * k}],{s0}")
            emit(f"mov.l\t[w0+{8 * k + 4}],{s1}")
        emit(f"mov.s\t{s0},{y}")
        emit(f"mac.s\t{coef(k, 0)},{x},{y}\t; y{k}")
        if pending is not None:
            tail(pending, x)                          # the previous section's y is this x
            pending = None
        emit(f"mov.s\t{s1},{s0}")
        emit(f"mac.s\t{coef(k, 1)},{x},{s0}")
        emit(f"mul.s\t{coef(k, 2)},{x},{s1}")
        if p.state[k] is not None:
            pending = k
        else:
            tail(k, y)
    vn, t = p.ring[n % 2], p.ring[(n + 1) % 2]
    if io == "u12":
        emit(f"add.s\t{vn},{p.k_off},{t}")
        if pending is not None:
            tail(pending, vn)
        emit(f"maxnm.s\t{t},{p.k_zero},{t}")
        emit(f"minnm.s\t{t},{p.k_max},{t}")
        emit(f"f2li.sz\t{t},{t}")
        emit(f"mov.l\t{t},w4")
        emit("mov.w\tw4,[w1++]")
        emit("cp.l\tw1,w3")
    else:
        emit(f"mov.l\t{vn},[w2++]")
        if pending is not None:
            tail(pending, vn)
        emit("sub.l\tw3,#1,w3")
    emit(f"bra\tnz,{lab}_loop")
    out.append(f"{lab}_done:")
    for k in range(n):
        if p.state[k] is not None:
            emit(f"mov.l\t{p.state[k][0]},[w0+{8 * k}]")
            emit(f"mov.l\t{p.state[k][1]},[w0+{8 * k + 4}]")
    for r in reversed(saved):
        emit(f"pop.l\t{r}")
    emit("return")
    out.append(f"\t.size\t_{sym}, .-_{sym}")
    out.append("\t.popsection")
    return out


def loop_instructions(lines: list[str]) -> int:
    """Instructions per sample: the lines of the loop, label to branch back."""
    i = next(k for k, l in enumerate(lines) if l.endswith("_loop:"))
    j = next(k for k, l in enumerate(lines) if l.endswith("_done:"))
    return sum(1 for l in lines[i + 1:j] if l.startswith("\t"))


def as_c_asm_block(lines: list[str]) -> str:
    """The lines as one file-scope __asm__ statement for a C header."""
    body = "".join("    \"" + l.replace("\\", "\\\\").replace("\"", "\\\"") + "\\n\"\n" for l in lines)
    return "__asm__(\n" + body + ");\n"


def host_reference_c(fn: str, ident: str, io: str = "u12", name: str | None = None) -> str:
    """C with fmaf() in the order of the assembler: the host stand-in in the firmware
    header and the reference of the simulator test. Uses <ident>_kcoeffs (b0 b1 b2 -a1 -a2).
    name overrides the function name (<ident>_block_u12 / <ident>_process_block)."""
    up = ident.upper()
    if io == "u12":
        sig = f"void {name or ident + '_block_u12'}({ident}_state_t *st, uint16_t *x, uint32_t n)"
        get = "        float v = (float)((int32_t)x[i] - 2048);\n"
        put = ("        v = v + 2048.5f;\n"
               "        v = (v > 0.0f) ? v : 0.0f;\n"
               "        v = (v < 4095.0f) ? v : 4095.0f;\n"
               "        x[i] = (uint16_t)v;\n")
    else:
        sig = (f"void {name or ident + '_process_block'}({ident}_state_t *st, const float *in, "
               "float *out, uint32_t n)")
        get = "        float v = in[i];\n"
        put = "        out[i] = v;\n"
    return (
        f"{fn}{sig}\n{{\n"
        "    uint32_t i;\n    int k;\n\n"
        "    for (i = 0; i < n; i++) {\n" + get +
        f"        for (k = 0; k < {up}_NUM_SECTIONS; k++) {{\n"
        f"            const float *c = {ident}_kcoeffs[k];\n"
        "            float *s = st->s[k];\n"
        "            const float y = fmaf(c[0], v, s[0]);\n\n"
        "            s[0] = fmaf(c[3], y, fmaf(c[1], v, s[1]));\n"
        "            s[1] = fmaf(c[4], y, c[2] * v);\n"
        "            v = y;\n"
        "        }\n" + put + "    }\n}\n")


def kcoeffs_c(ident: str, sos: np.ndarray, fn_static: str = "static ") -> str:
    """The coefficient table host_reference_c() reads (b0 b1 b2 -a1 -a2, float)."""
    up = ident.upper()
    rows = ",\n".join("    {" + ", ".join(f"{v:.9g}f" if "." in f"{v:.9g}" or "e" in f"{v:.9g}"
                                           else f"{v:.9g}.0f" for v in r) + "}"
                      for r in kernel_coeffs(sos))
    return (f"/* per section: b0, b1, b2, -a1, -a2 - the immediates of the assembler */\n"
            f"{fn_static}const float {ident}_kcoeffs[{up}_NUM_SECTIONS][5] = {{\n{rows}\n}};\n\n")
