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

r"""path_response.py - why the generator's noise does not look flat at high
sample rates: the test signal, the analog path or the ADC? (03.10.2026)

    python tools\path_response.py --port COM26        the board (nothing else on the port)
    python tools\path_response.py --fake              the GUI's stand-in (checks the method)

The generator plays white noise (siggen noise 1, f0 0, 8192 entries) on DAC2,
ADC core 5 reads it on RA8 (no wire: DACOUT2 and AD5AN3 share the pin). For
every configuration of a matrix - sample rate fs x play rate x SAMC - it grabs
16 times and averages Welch spectra (Hann segments of 512).

The point is the EXPECTED spectrum: the table is known bit for bit
(wavegen_model.wavegen() reproduces lib/wavegen exactly), and so is the play
rate the board reports (play_hz_actual). wavegen_model.playback() then gives
what an ideal ADC sampling at fs would read from an ideal DAC holding each
entry for 1/play - the zero-order hold's sin(x)/x and every alias folded back
below fs/2, the table's own line pattern included. Simulated over many random
start positions and put through the same Welch average, it is the test
signal's own share of the curve.

    residual(f) = measured(f) - expected(f)        (dB, per bin)

is then what the path from the DAC's output to the ADC's result adds:

  - the residual follows the ABSOLUTE frequency, the same at every fs and SAMC
      -> the analog path (DAC output settling, the pin with its touch pad, the
         ADC input network) - a continuous-time low-pass;
  - it changes with SAMC or with fs at the same frequency
      -> the ADC's sampling (acquisition time of the sample capacitor);
  - it is about 0 dB everywhere
      -> the test signal alone explains the curve.

The residual's level at low frequencies is the path's gain (DAC code -> ADC
count, both 12 bit on the same supply); its shape is normalised to that.

Writes build\path_response\<stamp>\: results.json (every spectrum, expected and
residual), summary.txt (the residual at fixed frequencies, per configuration),
response.png. A board run: docs/HARDWARE-LOG.md gets the entry.
"""
import argparse
import datetime
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wavegen_model  # noqa: E402
from adc_gui import parse_kv, siggen_commands, welch_power  # noqa: E402

NSEG = 512
N_TABLE = 8192
LO, HI = 800, 3500                 # the GUI's generator range (where the DAC follows)
GRABS = 16
SIM_GRABS = 48
# frequencies (Hz) the summary reports the residual at
REPORT_F = [10e3, 50e3, 100e3, 200e3, 300e3, 400e3, 600e3, 800e3, 1.2e6, 1.6e6, 2.4e6, 3.2e6]

# The matrix: (fs ksps, play Hz, SAMC, amplitude). A: rate x play rate (SAMC 0,
# the GUI's default); B: SAMC at two rates; C: the noise's amplitude - a DAC
# limited by its slew rate filters full-scale steps harder than small ones, a
# linear settling filters both alike. fs 500..8000: the range the board
# streams cleanly with nothing else running.
PARTS = {
    "A": [(fs, play, 0, 1.0) for fs in (500, 1000, 2000, 4000, 8000) for play in (250000, 500000, 1000000)],
    "B": [(fs, 1000000, samc, 1.0) for fs in (2000, 8000) for samc in (0, 8, 31)],
    "C": [(fs, 1000000, 0, amp) for fs in (4000, 8000) for amp in (1.0, 0.25, 0.1)],
    # D: the GUI's "flat noise" rule, play = min(2 fs, 1 MHz) - how flat is the raw spectrum
    "D": [(fs, int(min(2 * fs * 1000, 1000000)), 0, 1.0) for fs in (100, 250, 500, 1000, 2000, 8000)],
}
MATRIX = PARTS["A"] + PARTS["B"] + PARTS["C"]


def table_for(play_actual, amp):
    return wavegen_model.wavegen(N_TABLE, play_actual, 0.0, [0.0] * 6, 0.0, amp, LO, HI, 1.0)


def expected_spectrum(table, play_actual, fs, n, rng):
    """Welch power of what an ideal ADC reads (ideal DAC, hold, aliasing)."""
    acc = None
    for _ in range(SIM_GRABS):
        v = wavegen_model.playback(table, play_actual, fs, n, start_entry=rng.uniform(0, N_TABLE))
        f, p = welch_power(v, fs, NSEG)
        acc = p if acc is None else acc + p
    return f, acc / SIM_GRABS


def db(p):
    return 10.0 * np.log10(np.maximum(p, 1e-30))


def band_value(f, y, f0, rel=0.03):
    """Mean of y (dB) within +-3 % around f0, None if f0 is outside the bins."""
    if f0 >= f[-1] * 0.97 or f0 < f[2]:
        return None
    m = (f >= f0 * (1 - rel)) & (f <= f0 * (1 + rel))
    if not m.any():
        m = np.abs(f - f0) == np.min(np.abs(f - f0))
    return float(np.mean(y[m]))


def cmd(target, line, timeout=15.0):
    """target.cmd() with a longer timeout and one retry: 'stream off' with the
    generator on took longer than 5 s once on the board (03.10.2026)."""
    try:
        return target.cmd(line, timeout=timeout)
    except TimeoutError:
        time.sleep(1.0)
        return target.cmd(line, timeout=timeout)


def run(target, out_dir, log, matrix, source):
    rng = np.random.default_rng(7)
    results = []
    for k, (fs_k, play, samc, amp) in enumerate(matrix):
        t0 = time.time()
        cmd(target, "stream off")
        cmd(target, "sigproc off")
        cmd(target, "sigproc gz off")
        p = dict(on=True, dac=2, n=N_TABLE, play=play, f0=0.0, h={i: 0.0 for i in range(2, 8)}, decay=0.0,
                 amp=amp, lo=LO, hi=HI, snap=False, force=True, noise=1.0)
        ok_sg, reply = True, []
        for line in siggen_commands(p):
            ok_sg, reply = cmd(target, line)
            if not ok_sg:
                break
        if not ok_sg:
            log(f"[{k + 1}/{len(matrix)}] fs {fs_k} kSPS play {play} SAMC {samc}: siggen refused: {reply}")
            continue
        st = parse_kv(reply)
        play_actual = float(st.get("play_hz_actual", play) or play)
        ok_on, reply = cmd(target, f"stream on {fs_k} 5 3 {samc}")
        if not ok_on:
            log(f"[{k + 1}/{len(matrix)}] stream on refused: {reply}")
            continue
        pw, metas, n = [], [], None
        for _ in range(GRABS):
            ok, s, meta = target.grab()
            if not ok:
                continue
            s = np.asarray(s, float)
            n = len(s)
            fs = meta["ksps"] * 1e3
            f, pp = welch_power(s, fs, NSEG)
            pw.append(pp)
            metas.append({k2: meta.get(k2) for k2 in ("ksps", "overrun", "late", "missed")})
        if not pw:
            log(f"[{k + 1}/{len(matrix)}] no grab")
            continue
        meas = np.mean(pw, axis=0)
        table = table_for(play_actual, amp)
        fe, exp_ = expected_spectrum(table, play_actual, fs, n, rng)
        resid = db(meas) - db(exp_)
        gain = band_value(f, resid, 0.02 * fs) if band_value(f, resid, 0.02 * fs) is not None else float(resid[3])
        shape = resid - gain
        rep = {f"{int(x)}": band_value(f, shape, x) for x in REPORT_F}
        results.append(dict(fs_ksps=fs_k, fs_actual=fs, play=play, play_actual=play_actual, samc=samc, amp=amp, n=n,
                            grabs=len(pw), meta=metas, f=f.tolist(), measured_db=db(meas).tolist(),
                            expected_db=db(exp_).tolist(), residual_db=resid.tolist(), gain_db=gain,
                            shape_at=rep))
        write(results, out_dir, source)              # after every configuration: a crash keeps the rest
        log(f"[{k + 1}/{len(matrix)}] fs {fs / 1e3:g} kSPS, play {play_actual:g}, SAMC {samc}, amp {amp:g}: "
            f"gain {gain:+.2f} dB, "
            "shape " + ", ".join(f"{int(x / 1e3)}k {v:+.1f}" for x, v in zip(REPORT_F, rep.values())
                                 if v is not None) + f"  ({time.time() - t0:.0f} s)")
    cmd(target, "siggen off")
    cmd(target, "stream off")
    return results


def write(results, out_dir, source):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "results.json"), "w") as fh:
        json.dump({"source": source, "nseg": NSEG, "results": results}, fh)
    lines = [f"path_response.py, {source}, {datetime.datetime.now():%Y-%m-%d %H:%M}",
             "residual = measured - expected (ideal DAC hold + ideal ADC), dB; 'gain' at 2 % of fs,",
             "the columns: the residual's shape (gain removed) at that frequency", ""]
    hdr = f"{'fs kSPS':>8} {'play':>8} {'SAMC':>4} {'amp':>5} {'gain':>6} " + " ".join(f"{int(x / 1e3):>6}k" for x in REPORT_F)
    lines.append(hdr)
    for r in results:
        cells = " ".join(f"{r['shape_at'][str(int(x))]:+7.1f}" if r["shape_at"][str(int(x))] is not None
                         else f"{'':>7}" for x in REPORT_F)
        lines.append(f"{r['fs_ksps']:>8} {int(r['play_actual']):>8} {r['samc']:>4} {r['amp']:>5g} "
                     f"{r['gain_db']:+6.1f} {cells}")
    with open(os.path.join(out_dir, "summary.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(3, 1, figsize=(11, 13))
        for r in results:
            if r["play"] == 1000000 and r["samc"] == 0 and r["amp"] == 1.0:
                f = np.asarray(r["f"]) / 1e3
                ax[0].plot(f, r["measured_db"], lw=0.8, label=f"measured {r['fs_ksps']} kSPS")
                ax[0].plot(f, r["expected_db"], lw=0.8, ls="--", color="grey")
        ax[0].set(title="noise played at 1 MHz: measured (colour) and expected for an ideal DAC + ADC (grey)",
                  xlabel="kHz", ylabel="dB", xscale="log")
        for r in results:
            if r["samc"] == 0:
                f = np.asarray(r["f"]) / 1e3
                ax[1].plot(f, np.asarray(r["residual_db"]) - r["gain_db"], lw=0.8,
                           label=f"{r['fs_ksps']} kSPS, play {int(r['play'] / 1e3)}k, amp {r['amp']:g}")
        ax[1].set(title="residual (path + ADC), gain removed - against ABSOLUTE frequency", xlabel="kHz",
                  ylabel="dB", xscale="log", ylim=(-15, 5))
        for r in results:
            if r["play"] == 1000000 and r["fs_ksps"] in (2000, 8000):
                f = np.asarray(r["f"]) / 1e3
                ax[2].plot(f, np.asarray(r["residual_db"]) - r["gain_db"], lw=0.8,
                           label=f"{r['fs_ksps']} kSPS, SAMC {r['samc']}")
        ax[2].set(title="residual at SAMC 0 / 8 / 31 (the ADC's acquisition time)", xlabel="kHz", ylabel="dB",
                  xscale="log", ylim=(-15, 5))
        for a in ax:
            a.grid(True, which="both", alpha=0.3)
            a.legend(fontsize=7, ncol=3)
        fig.tight_layout()
        fig.savefig(os.path.join(out_dir, "response.png"), dpi=110)
    except ImportError:
        pass
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--port", help="the board's console (e.g. COM26)")
    g.add_argument("--fake", action="store_true", help="the GUI's stand-in")
    ap.add_argument("--out", default=None, help="output folder (default build/path_response/<stamp>)")
    ap.add_argument("--parts", default="ABC", help="which parts of the matrix: A rate x play rate, B SAMC, "
                                                    "C amplitude, D the flat-noise rule (default ABC)")
    a = ap.parse_args()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = a.out or os.path.join(HERE, "..", "build", "path_response", stamp + ("_fake" if a.fake else ""))
    if a.fake:
        from adc_gui import FakeTarget
        target, source = FakeTarget(), "fake target"
    else:
        from protocol import Target
        target, source = Target(a.port), f"board on {a.port}"
        ok, lines = target.cmd("version")
        source += " - " + " ".join(lines)[:120]
    t0 = time.time()
    matrix = [c for part in a.parts.upper() for c in PARTS[part]]
    results = run(target, out, lambda s: print(s, flush=True), matrix, source)
    print(write(results, out, source))
    print(f"\n{len(results)} configurations in {time.time() - t0:.0f} s -> {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
