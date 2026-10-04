"""C code generator for designed IIR filters.

Emits a header and a source file that implement the filter as a cascade of
second order sections:

* float / double: transposed direct form II (good numerical behaviour in floating point)
* fixed16 / fixed32: direct form I with a 64 bit accumulator, rounding and saturation.
  The arithmetic is bit-exact to fdcore.fixed_filter(), so the GUI shows exactly
  what the target computes.
* float_asm: float, transposed direct form II, as dsPIC33A assembler (asmgen.py): a
  header plus a .s file. Runs on a dsPIC33A only - no PC test bench.
"""

from __future__ import annotations

import datetime
import re
import zlib

import numpy as np

import asmgen
from fdcore import Design, FixedPoint

ARITHMETICS = {
    "float": "32 bit floating point (float)",
    "double": "64 bit floating point (double)",
    "fixed32": "32 bit fixed point (int32_t data/coefficients, int64_t accumulator)",
    "fixed16": "16 bit fixed point (int16_t data/coefficients, int64_t accumulator)",
    "float_asm": "32 bit floating point, dsPIC33A assembler (FPU, fused multiply-add)",
}

# arithmetics a PC compiler can build and test (ctest.py, test benches)
PC_TESTABLE = ("float", "double", "fixed32", "fixed16")


def c_identifier(name: str) -> str:
    ident = re.sub(r"[^0-9a-zA-Z_]", "_", name.strip()).lower() or "iir_filter"
    if ident[0].isdigit():
        ident = "f_" + ident
    return ident


def _spec_comment(d: Design) -> str:
    s = d.spec
    n = 2 if s.two_edges else 1
    edges = lambda v: ", ".join(f"{x:g}" for x in v[:n])
    att = lambda v: ", ".join(f"{x:.2f}" for x in v)
    return (
        f" * Filter      : {s.characteristic} {s.type}, order {d.digital_order}, "
        f"{len(d.sos)} section(s)\n"
        f" * Sample rate : {s.fs:g} Hz\n"
        f" * Passband    : {edges(s.fpass)} Hz, max. {s.ap:g} dB attenuation (achieved {att(d.att_pass)} dB)\n"
        f" * Stopband    : {edges(s.fstop)} Hz, min. {s.as_:g} dB attenuation (achieved {att(d.att_stop)} dB)\n"
    )


def _parts(d: Design, ident: str, arithmetic: str, sos: np.ndarray, fixed: FixedPoint | None,
           fn: str = "", ctype: str | None = None) -> dict:
    """The pieces generate() and generate_firmware() assemble.

    fn prefixes every function definition ("" for a .c file, "static inline " for a
    header-only filter); ctype overrides the C type of float/double (the firmware's
    "long double", because XC-DSC's double has 32 bits)."""
    up = ident.upper()
    n = len(sos)
    p: dict = {"includes": "#include <string.h>\n\n"}
    if arithmetic in ("float", "double"):
        t = ctype or arithmetic
        suffix = {"float": "f", "double": "", "long double": "L"}[t]
        fmt = "{:.9g}" if arithmetic == "float" else "{:.17g}"

        def lit(v: float) -> str:
            s = fmt.format(v)
            if not re.search(r"[.eEn]", s):
                s += ".0"
            return s + suffix

        p["structure"] = (
            f" *\n * Structure   : {n} second order section(s), transposed direct form II\n"
            " *               y = b0*x + s0;  s0 = b1*x - a1*y + s1;  s1 = b2*x - a2*y\n */\n\n")
        p["std_includes"] = "#include <stddef.h>\n\n"
        p["defs"] = (
            f"#define {up}_NUM_SECTIONS {n}\n#define {up}_SAMPLE_RATE {d.spec.fs:g}\n\n"
            f"typedef struct {{\n    {t} s[{up}_NUM_SECTIONS][2];\n}} {ident}_state_t;\n\n")
        rows = ",\n".join(
            "    {" + ", ".join(lit(v) for v in (r[0], r[1], r[2], r[4], r[5])) + "}"
            for r in sos)
        coeffs = (f"/* per section: b0, b1, b2, a1, a2  (a0 = 1) */\n"
                  f"static const {t} {ident}_coeffs[{up}_NUM_SECTIONS][5] = {{\n{rows}\n}};\n\n")
        sections = (
            f"    for (k = 0; k < {up}_NUM_SECTIONS; k++) {{\n"
            f"        const {t} *c = {ident}_coeffs[k];\n"
            f"        {t} *s = st->s[k];\n"
            f"        {t} y = c[0] * x + s[0];\n\n"
            f"        s[0] = c[1] * x - c[3] * y + s[1];\n"
            f"        s[1] = c[2] * x - c[4] * y;\n"
            f"        x = y;\n"
            f"    }}\n")
    else:
        assert fixed is not None
        w = fixed.word
        t = f"int{w}_t"
        vmax, vmin = (1 << (w - 1)) - 1, -(1 << (w - 1))
        vmin_c = f"(-{vmax} - 1)" if w == 32 else str(vmin)
        p["structure"] = (
            f" *\n * Structure   : {n} second order section(s), direct form I, 64 bit accumulator\n"
            f" *               y = sat((b0*x + b1*x1 + b2*x2 - a1*y1 - a2*y2 + 2^(F-1)) >> F)\n"
            f" * Coefficients: Q{w - 1 - fixed.frac}.{fixed.frac} in {t} "
            f"(F = {up}_FRAC_BITS = {fixed.frac}, range +/-{fixed.coeff_range:g})\n"
            f" * Samples     : {t}, any scaling (e.g. Q{w - 1}); input and output use the same scaling\n"
            f" * Note        : relies on an arithmetic right shift of negative int64_t values\n"
            f" *               (true for GCC, Clang, XC16, XC32, IAR, Keil)\n */\n\n")
        p["std_includes"] = "#include <stddef.h>\n#include <stdint.h>\n\n"
        p["defs"] = (
            f"#define {up}_NUM_SECTIONS {n}\n#define {up}_FRAC_BITS {fixed.frac}\n"
            f"#define {up}_SAMPLE_RATE {d.spec.fs:g}\n\n"
            f"typedef struct {{\n    {t} x[{up}_NUM_SECTIONS][2];  /* x[n-1], x[n-2] */\n"
            f"    {t} y[{up}_NUM_SECTIONS][2];  /* y[n-1], y[n-2] */\n}} {ident}_state_t;\n\n")
        rows = []
        for q, r in zip(fixed.coeffs, sos):
            ints = ", ".join(f"{int(v):>{12 if w == 32 else 7}d}" for v in q)
            flt = ", ".join(f"{v:.9g}" for v in (r[0], r[1], r[2], r[4], r[5]))
            rows.append(f"    {{{ints}}}  /* {flt} */")
        coeffs = (
            f"#define {up}_MAX ({vmax})\n#define {up}_MIN {vmin_c}\n"
            f"#define {up}_ROUND (((int64_t)1 << {up}_FRAC_BITS) >> 1)\n\n"
            f"/* per section: b0, b1, b2, a1, a2  (a0 = 1), Q{fixed.frac} */\n"
            f"static const {t} {ident}_coeffs[{up}_NUM_SECTIONS][5] = {{\n" + ",\n".join(rows) + "\n};\n\n")
        sections = (
            f"    for (k = 0; k < {up}_NUM_SECTIONS; k++) {{\n"
            f"        const {t} *c = {ident}_coeffs[k];\n"
            f"        {t} *xs = st->x[k];\n"
            f"        {t} *ys = st->y[k];\n"
            f"        int64_t acc = (int64_t)c[0] * x\n"
            f"                    + (int64_t)c[1] * xs[0]\n"
            f"                    + (int64_t)c[2] * xs[1]\n"
            f"                    - (int64_t)c[3] * ys[0]\n"
            f"                    - (int64_t)c[4] * ys[1];\n\n"
            f"        acc = (acc + {up}_ROUND) >> {up}_FRAC_BITS;\n"
            f"        if (acc > {up}_MAX) {{\n            acc = {up}_MAX;\n"
            f"        }} else if (acc < {up}_MIN) {{\n            acc = {up}_MIN;\n        }}\n"
            f"        xs[1] = xs[0];\n        xs[0] = x;\n"
            f"        ys[1] = ys[0];\n        ys[0] = ({t})acc;\n"
            f"        x = ({t})acc;\n"
            f"    }}\n")
    p["t"] = t
    p["body"] = (
        coeffs
        + f"{fn}void {ident}_init({ident}_state_t *st)\n{{\n    memset(st, 0, sizeof *st);\n}}\n\n"
        + f"{fn}{t} {ident}_process({ident}_state_t *st, {t} x)\n{{\n    int k;\n\n"
        + sections + "    return x;\n}\n\n"
        + f"{fn}void {ident}_process_block({ident}_state_t *st, const {t} *in, {t} *out, size_t n)\n{{\n"
        + "    size_t i;\n\n"
        + f"    for (i = 0; i < n; i++) {{\n        out[i] = {ident}_process(st, in[i]);\n    }}\n}}\n")
    p["protos"] = (
        f"/* Clears the filter state. */\n"
        f"void {ident}_init({ident}_state_t *st);\n\n"
        f"/* Filters one sample. */\n"
        f"{t} {ident}_process({ident}_state_t *st, {t} x);\n\n"
        f"/* Filters n samples; in and out may point to the same buffer. */\n"
        f"void {ident}_process_block({ident}_state_t *st, const {t} *in, {t} *out, size_t n);\n\n")
    return p


ASM_STRUCTURE = (
    " *\n * Structure   : {n} second order section(s), transposed direct form II, per section\n"
    " *               y = b0*x + s0;  s0 = (s1 + b1*x) - a1*y;  s1 = b2*x - a2*y\n"
    " *               every '+ c*v' one fused multiply-add (mac.s, one rounding): not\n"
    " *               bit-exact to the C float code, but to fmaf() in this order\n"
    " * Target      : dsPIC33A only (XC-DSC, FPU) - cannot be built or run on a PC\n */\n\n")


def _asm_defs(d: Design, ident: str, n: int) -> str:
    up = ident.upper()
    return (f"#define {up}_NUM_SECTIONS {n}\n#define {up}_SAMPLE_RATE {d.spec.fs:g}\n\n"
            f"typedef struct {{\n    float s[{up}_NUM_SECTIONS][2];   /* s0, s1 per section */\n"
            f"}} {ident}_state_t;\n\n")


def _generate_asm(d: Design, ident: str, sos: np.ndarray, head: str) -> tuple[str, str, str, str]:
    """float_asm for the Code tab: <ident>.h and <ident>.s (float in, float out)."""
    up = ident.upper()
    header = (
        head + ASM_STRUCTURE.format(n=len(sos)) + f"#ifndef {up}_H\n#define {up}_H\n\n"
        "#include <stdint.h>\n#include <string.h>\n\n" + _asm_defs(d, ident, len(sos))
        + f"/* Clears the filter state. */\n"
        f"static inline void {ident}_init({ident}_state_t *st)\n{{\n    memset(st, 0, sizeof *st);\n}}\n\n"
        f"/* Filters n samples ({ident}.s); in and out may point to the same buffer. */\n"
        f"void {ident}_process_block({ident}_state_t *st, const float *in, float *out, uint32_t n);\n\n"
        f"#endif /* {up}_H */\n")
    lines = asmgen.kernel(f"{ident}_process_block", sos, "f32")
    source = ("".join("; " + l[3:].rstrip() + "\n" if l.startswith(" * ") else
                      ";" + l[2:].rstrip() + "\n" if l.startswith(" *") else ""
                      for l in head.splitlines())
              + "; C: void " + f"{ident}_process_block({ident}_state_t *st, const float *in, "
              "float *out, uint32_t n)\n"
              "; W0 = st, W1 = in, W2 = out, W3 = n; F8 and up are saved and restored\n\n"
              + "\n".join(lines) + "\n")
    return f"{ident}.h", header, f"{ident}.s", source


def generate(d: Design, name: str, arithmetic: str, sos: np.ndarray,
             fixed: FixedPoint | None = None) -> tuple[str, str, str, str]:
    """Returns (header_filename, header, source_filename, source).

    sos is the (optionally section-scaled) cascade; for fixed point, `fixed`
    holds its quantized coefficients. float_asm returns a .s file as the source.
    """
    ident = c_identifier(name)
    up = ident.upper()
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    head = (
        f"/*\n * {ident} - IIR filter generated by FilterDesign GUI ({stamp})\n *\n"
        f"{_spec_comment(d)}"
        f" * Arithmetic  : {ARITHMETICS[arithmetic]}\n"
    )
    if arithmetic == "float_asm":
        return _generate_asm(d, ident, sos, head)
    p = _parts(d, ident, arithmetic, sos, fixed)
    header = (head + p["structure"] + f"#ifndef {up}_H\n#define {up}_H\n\n" + p["std_includes"]
              + p["defs"] + p["protos"] + f"#endif /* {up}_H */\n")
    source = head + " */\n\n" + p["includes"] + f"#include \"{ident}.h\"\n\n" + p["body"]
    return f"{ident}.h", header, f"{ident}.c", source


# --------------------------------------------------------------------------------------
# dsPIC33 firmware (src/core/user_filter.h, "sigproc user")
# --------------------------------------------------------------------------------------

FIRMWARE_IDENT = "user_filter"

_MCHP_LICENSE = """/*******************************************************************************
 * Copyright (C) 2026 Microchip Technology Inc. and its subsidiaries.
 *
 * Subject to your compliance with these terms, you may use Microchip software
 * and any derivatives exclusively with Microchip products. It is your
 * responsibility to comply with third party license terms applicable to your
 * use of third party software (including open source software) that may
 * accompany Microchip software.
 *
 * THIS SOFTWARE IS SUPPLIED BY MICROCHIP "AS IS". NO WARRANTIES, WHETHER
 * EXPRESS, IMPLIED OR STATUTORY, APPLY TO THIS SOFTWARE, INCLUDING ANY IMPLIED
 * WARRANTIES OF NON-INFRINGEMENT, MERCHANTABILITY, AND FITNESS FOR A
 * PARTICULAR PURPOSE.
 *
 * IN NO EVENT WILL MICROCHIP BE LIABLE FOR ANY INDIRECT, SPECIAL, PUNITIVE,
 * INCIDENTAL OR CONSEQUENTIAL LOSS, DAMAGE, COST OR EXPENSE OF ANY KIND
 * WHATSOEVER RELATED TO THE SOFTWARE, HOWEVER CAUSED, EVEN IF MICROCHIP HAS
 * BEEN ADVISED OF THE POSSIBILITY OR THE DAMAGES ARE FORESEEABLE. TO THE
 * FULLEST EXTENT ALLOWED BY LAW, MICROCHIP'S TOTAL LIABILITY ON ALL CLAIMS IN
 * ANY WAY RELATED TO THIS SOFTWARE WILL NOT EXCEED THE AMOUNT OF FEES, IF ANY,
 * THAT YOU HAVE PAID DIRECTLY TO MICROCHIP FOR THIS SOFTWARE.
 ******************************************************************************/
"""


def firmware_description(d: Design, arithmetic: str) -> str:
    """One line for the console's status (USER_FILTER_DESC), ASCII only."""
    s = d.spec
    n = 2 if s.two_edges else 1
    edges = "-".join(f"{x:g}" for x in s.fpass[:n])
    return f"{s.characteristic} {s.type} {edges} Hz, order {d.digital_order}, {arithmetic}"


def _firmware_asm_parts(d: Design, ident: str, sos: np.ndarray) -> dict:
    """float_asm in user_filter.h: the assembler routine as a file-scope __asm__ (so
    that, as with the C variants, no build needs another source file), and for any
    other compiler (host tests, trace builds) the same arithmetic in C."""
    up = ident.upper()
    asm = asmgen.as_c_asm_block(asmgen.kernel(f"{ident}_block_u12", sos, "u12"))
    body = (
        f"static inline void {ident}_init({ident}_state_t *st)\n{{\n    memset(st, 0, sizeof *st);\n}}\n\n"
        "/*\n * The whole block of \"sigproc user\" (sigproc.c, user_cascade()), x in place:\n"
        " * x - 2048 into the cascade, the result + 2048.5 clamped to 0..4095 and truncated.\n */\n"
        f"#define {up}_ASM 1\n"
        "#if defined(__XC_DSC__) && defined(__dsPIC33A__)\n"
        f"void {ident}_block_u12({ident}_state_t *st, uint16_t *x, uint32_t n);\n\n"
        + asm +
        "#else\n"
        "/* Host stand-in (host tests, trace builds): the same arithmetic in C, fmaf() in\n"
        " * the order of the assembler above. Not the code the board runs. */\n"
        + asmgen.kcoeffs_c(ident, sos)
        + asmgen.host_reference_c("static inline ", ident, "u12")
        + "#endif\n")
    return {"structure": ASM_STRUCTURE.format(n=len(sos)),
            "std_includes": "#include <stddef.h>\n#include <math.h>\n\n",
            "includes": "#include <string.h>\n\n",
            "defs": _asm_defs(d, ident, len(sos)), "t": "float", "body": body}


def generate_firmware(d: Design, arithmetic: str, sos: np.ndarray,
                      fixed: FixedPoint | None = None) -> tuple[str, dict]:
    """The filter as the dsPIC33 firmware runs it ("sigproc user", src/core/sigproc.c).

    Returns (text of src/core/user_filter.h, contents of src/core/user_filter.json).
    The header holds the same code generate() writes into a .c file, made static
    inline so that sigproc.c - the only file including it - needs no new source
    file in any build. "double" becomes long double: XC-DSC's double has 32 bits.
    float_asm puts the assembler into the header as a file-scope __asm__ with a C
    stand-in for other compilers (_firmware_asm_parts()).
    The id is a CRC-32 of the generated code; the firmware reports it ("sigproc"
    status, user_id) and the JSON carries it, so the dsPIC33 GUI can tell whether
    the board runs the filter described there.
    """
    ident = FIRMWARE_IDENT
    up = ident.upper()
    ctype = "long double" if arithmetic == "double" else None
    if arithmetic == "float_asm":
        p = _firmware_asm_parts(d, ident, sos)
    else:
        p = _parts(d, ident, arithmetic, sos, fixed, fn="static inline ", ctype=ctype)
    fid = zlib.crc32((arithmetic + "\n" + p["defs"] + p["body"]).encode("ascii")) & 0xFFFFFFFF
    desc = firmware_description(d, arithmetic)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    is_fixed = arithmetic.startswith("fixed")
    word = fixed.word if is_fixed else 0
    shown_arith = "64 bit floating point (long double, XC-DSC's double is 32 bit)" \
        if arithmetic == "double" else ARITHMETICS[arithmetic]
    text = (
        _MCHP_LICENSE + "\n"
        f"/*\n * {ident}.h - the filter \"sigproc user\" runs (src/core/sigproc.c).\n *\n"
        f" * GENERATED by tools/filterdesign (dsPIC33 tab) on {stamp} - do not edit by\n"
        " * hand: design the filter there and press \"Install into firmware\". The\n"
        " * description of the same filter for the dsPIC33 GUI is user_filter.json\n"
        " * next to this file (same id).\n *\n"
        + _spec_comment(d)
        + f" * Arithmetic  : {shown_arith}\n"
        + p["structure"]
        + "/*\n * How sigproc.c drives it: the 12-bit ADC result x is centred, x - 2048,\n"
        + (f" * and put into the top 12 bits of an int{word}_t (Q{word - 1}: full scale = 1.0);\n"
           " * the result is shifted back with rounding, + 2048, clamped to 0..4095.\n"
           if is_fixed else
           " * as a floating-point number; the result + 2048 is rounded and clamped to 0..4095.\n")
        + " * The filter's peak gain is 0 dB. On a gap in the stream the state is cleared.\n */\n"
        + f"#ifndef {up}_H\n#define {up}_H\n\n"
        + p["std_includes"].replace("\n\n", "\n") + "#include <stdint.h>\n" * (not is_fixed)
        + p["includes"]
        + f"#define {up}_ID          0x{fid:08X}u   /* CRC-32 of the code below */\n"
        + f"#define {up}_DESC        \"{desc}\"\n"
        + f"#define {up}_FS_HZ       {int(round(d.spec.fs))}u   /* designed for this sample rate */\n"
        + f"#define {up}_FIXED_BITS  {word}   /* 0: floating point; else the word width of the samples */\n"
        + f"typedef {p['t']} {ident}_sample_t;\n\n"
        + p["defs"] + p["body"]
        + f"\n#endif /* {up}_H */\n"
    )
    info = {
        "format": "user_filter", "version": 1, "id": f"{fid:08X}", "generated": stamp,
        "description": desc, "arithmetic": arithmetic,
        "spec": {"type": d.spec.type, "characteristic": d.spec.characteristic, "fs": d.spec.fs,
                 "fpass": list(d.spec.fpass[:2 if d.spec.two_edges else 1]),
                 "fstop": list(d.spec.fstop[:2 if d.spec.two_edges else 1]),
                 "ap": d.spec.ap, "as": d.spec.as_},
        "order": d.digital_order,
        # what the firmware computes with: the (scaled) cascade, and for fixed point the
        # quantized coefficients as floats - rows b0 b1 b2 a0 a1 a2 like scipy's sos
        "sos": [[float(v) for v in r] for r in (fixed.as_float_sos() if fixed is not None else sos)],
        "fixed": ({"word": fixed.word, "frac": fixed.frac,
                   "coeffs": [[int(v) for v in r] for r in fixed.coeffs]} if fixed is not None else None),
    }
    return text, info


# --------------------------------------------------------------------------------------
# Test bench
# --------------------------------------------------------------------------------------

# Pass criterion of the test bench: max. abs. error <= TOL * max(|expected|)
# (fixed point: exact match of the integers)
TESTBENCH_TOL = {"float": 1e-3, "double": 1e-9, "fixed32": 0.0, "fixed16": 0.0}


def generate_testbench(name: str, arithmetic: str) -> tuple[str, str]:
    """Returns (filename, source) of a test program for the generated filter.

    usage: <prog> input.txt [expected.txt]
    Reads one input sample per line, filters it and prints one output sample per line.
    With expected.txt the program compares its output and reports PASS/FAIL (exit code 0/1).
    float/double samples are plain numbers, fixed-point samples are integers.
    """
    ident = c_identifier(name)
    is_fixed = arithmetic.startswith("fixed")
    t = f"int{arithmetic[5:]}_t" if is_fixed else arithmetic
    tol = TESTBENCH_TOL[arithmetic]
    if is_fixed:
        read = "long long v;\n        if (fscanf(in, \"%lld\", &v) != 1) break;"
        emit = "printf(\"%lld\\n\", (long long)y);"
        limit = "0.0"
    else:
        read = "double v;\n        if (fscanf(in, \"%lf\", &v) != 1) break;"
        emit = "printf(\"%.17g\\n\", (double)y);"
        limit = f"{tol!r} * (max_ref > 0.0 ? max_ref : 1.0)"
    src = f"""/*
 * {ident}_test - test bench for {ident} ({ARITHMETICS[arithmetic]})
 * Generated by FilterDesign GUI.
 *
 * usage: {ident}_test input.txt [expected.txt]
 *   input.txt     one input sample per line ({'integers' if is_fixed else 'numbers'})
 *   expected.txt  optional reference output; the program then prints PASS or FAIL to
 *                 stderr and returns 0 (pass) or 1 (fail)
 * The filter output is written to stdout, one sample per line.
 * Pass criterion: {'exact match' if is_fixed else f'max. abs. error <= {tol:g} * max(|expected|)'}
 */

#include <math.h>
#include <stdio.h>

#include "{ident}.h"

int main(int argc, char **argv)
{{
    FILE *in, *ex = NULL;
    {ident}_state_t st;
    long n = 0, missing = 0;
    double max_err = 0.0, max_ref = 0.0, limit;

    if (argc < 2) {{
        fprintf(stderr, "usage: %s input.txt [expected.txt]\\n", argv[0]);
        return 2;
    }}
    in = fopen(argv[1], "r");
    if (!in) {{
        perror(argv[1]);
        return 2;
    }}
    if (argc > 2) {{
        ex = fopen(argv[2], "r");
        if (!ex) {{
            perror(argv[2]);
            return 2;
        }}
    }}

    {ident}_init(&st);
    for (;;) {{
        {t} y;
        {read}
        y = {ident}_process(&st, ({t})v);
        {emit}
        if (ex) {{
            double e;
            if (fscanf(ex, "%lf", &e) == 1) {{
                double d = fabs((double)y - e);
                if (d > max_err) max_err = d;
                if (fabs(e) > max_ref) max_ref = fabs(e);
            }} else {{
                missing++;
            }}
        }}
        n++;
    }}
    fclose(in);
    if (!ex) {{
        return 0;
    }}
    fclose(ex);
    limit = {limit};
    fprintf(stderr, "%ld samples, max. abs. error %.6g (limit %.6g)%s -> %s\\n", n, max_err, limit,
            missing ? ", expected file too short" : "", (max_err <= limit && !missing) ? "PASS" : "FAIL");
    return (max_err <= limit && !missing) ? 0 : 1;
}}
"""
    return f"{ident}_test.c", src


def generate_makefile(name: str) -> str:
    ident = c_identifier(name)
    return (
        f"# Test bench for {ident} - generated by FilterDesign GUI\n"
        "#   make        build the test program\n"
        "#   make test   filter input.txt and compare with expected.txt\n\n"
        "ifeq ($(origin CC),default)\nCC = gcc\nendif\n"
        "CFLAGS ?= -std=c99 -O2 -Wall -Wextra\n\n"
        f"PROG = {ident}_test\n\n"
        ".PHONY: all test clean\n\n"
        "all: $(PROG)\n\n"
        f"$(PROG): {ident}_test.c {ident}.c {ident}.h\n"
        f"\t$(CC) $(CFLAGS) -o $@ {ident}_test.c {ident}.c -lm\n\n"
        "test: $(PROG)\n"
        "\t./$(PROG) input.txt expected.txt > output.txt\n\n"
        "clean:\n"
        "\t-rm -f $(PROG) $(PROG).exe output.txt\n"
    )
