"""FilterDesign GUI - interactive IIR filter design with C code generation.

Run:  python app.py  [--host 127.0.0.1] [--port 8090] [--no-browser]

The design is computed by the fdesign command line tool (../fdesign), the
analysis and the code generation are done in Python (fdcore.py, codegen.py).
"""

from __future__ import annotations

import argparse
import math
import os
import time

import numpy as np
from nicegui import run as ng_run
from nicegui import ui
from scipy import signal

import codegen
import ctest
import fdcore
import firmware
import presets

TYPE_LABELS = {"lowpass": "Lowpass", "highpass": "Highpass", "bandpass": "Bandpass", "bandstop": "Bandstop"}
CHAR_LABELS = {"butterworth": "Butterworth", "chebyshev": "Chebyshev (type I)", "elliptic": "Elliptic (Cauer)"}
ARITH_LABELS = {"float": "float (32 bit)", "double": "double (64 bit)",
                "fixed32": "fixed point 32 bit", "fixed16": "fixed point 16 bit",
                "float_asm": "float (32 bit, dsPIC33A assembler)"}
# what the C test compiles and runs on the PC (not the dsPIC33A assembler)
TEST_LABELS = {k: v for k, v in ARITH_LABELS.items() if k in codegen.PC_TESTABLE}

# edge widgets in ascending frequency order: (label, list, index)
EDGE_LAYOUT = {
    "lowpass": [("Passband edge", "fpass", 0), ("Stopband edge", "fstop", 0)],
    "highpass": [("Stopband edge", "fstop", 0), ("Passband edge", "fpass", 0)],
    "bandpass": [("Lower stopband edge", "fstop", 0), ("Lower passband edge", "fpass", 0),
                 ("Upper passband edge", "fpass", 1), ("Upper stopband edge", "fstop", 1)],
    "bandstop": [("Lower passband edge", "fpass", 0), ("Lower stopband edge", "fstop", 0),
                 ("Upper stopband edge", "fstop", 1), ("Upper passband edge", "fpass", 1)],
}
# default edges as fraction of fs, ascending
EDGE_DEFAULTS = {"lowpass": [0.05, 0.1], "highpass": [0.15, 0.225],
                 "bandpass": [0.05, 0.1, 0.15, 0.225], "bandstop": [0.05, 0.1, 0.15, 0.225]}

N_FREQ = 2048
N_TIME_MAX = 4096
PALETTES = {
    "light": {"design": "#2563eb", "impl": "#f59e0b", "zero": "#2563eb", "pole": "#dc2626",
              "forbidden": "rgba(220, 38, 38, 0.10)", "grid": "#e5e7eb", "fg": "#374151",
              "axis": "#6b7280", "circle": "#9ca3af"},
    "dark": {"design": "#60a5fa", "impl": "#fbbf24", "zero": "#60a5fa", "pole": "#f87171",
             "forbidden": "rgba(248, 113, 113, 0.14)", "grid": "#334155", "fg": "#cbd5e1",
             "axis": "#64748b", "circle": "#64748b"},
}
START_DARK = True


def r6(x: float) -> float | None:
    if x is None or not math.isfinite(x):
        return None
    return float(f"{x:.6g}")


def xy(x: np.ndarray, y: np.ndarray) -> list:
    return [[r6(a), r6(b)] for a, b in zip(x, y)]


def base_chart(xname: str, yname: str, xtype: str = "value") -> dict:
    return {
        "animation": False,
        "grid": {"left": 70, "right": 30, "top": 40, "bottom": 80},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
        "legend": {"top": 5},
        "toolbox": {"right": 10, "feature": {"dataZoom": {}, "restore": {}, "saveAsImage": {}}},
        "xAxis": {"type": xtype, "name": xname, "nameLocation": "middle", "nameGap": 28},
        "yAxis": {"type": "value", "name": yname, "nameLocation": "middle", "nameGap": 50},
        "dataZoom": [{"type": "inside", "xAxisIndex": 0, "filterMode": "none"},
                     {"type": "slider", "xAxisIndex": 0, "filterMode": "none", "height": 18, "bottom": 10}],
        "series": [],
    }


def apply_theme(opt: dict, pal: dict) -> dict:
    """Colors text, axes, grid lines and controls of an ECharts option dict."""
    fg = {"color": pal["fg"]}
    opt["backgroundColor"] = "transparent"
    opt["textStyle"] = fg
    opt.setdefault("legend", {})["textStyle"] = fg
    for ax in ("xAxis", "yAxis"):
        a = opt.setdefault(ax, {})
        a["axisLine"] = {"lineStyle": {"color": pal["axis"]}}
        a["axisLabel"] = fg
        a["nameTextStyle"] = fg
        a["splitLine"] = {"lineStyle": {"color": pal["grid"]}}
    if "toolbox" in opt:
        opt["toolbox"]["iconStyle"] = {"borderColor": pal["fg"]}
    for dz in opt.get("dataZoom", []):
        if dz.get("type") == "slider":
            dz.update({"textStyle": fg, "borderColor": pal["axis"], "fillerColor": "rgba(96,165,250,0.15)",
                       "dataBackground": {"lineStyle": {"color": pal["axis"]}, "areaStyle": {"color": pal["grid"]}}})
    if "tooltip" in opt:
        opt["tooltip"].update({"backgroundColor": "#1e293b" if pal is PALETTES["dark"] else "#ffffff",
                               "borderColor": pal["axis"], "textStyle": fg})
    return opt


def line(name: str, data: list, color: str, dashed: bool = False, width: float = 2) -> dict:
    return {"name": name, "type": "line", "data": data, "showSymbol": False, "connectNulls": False,
            "lineStyle": {"color": color, "width": width, "type": "dashed" if dashed else "solid"},
            "itemStyle": {"color": color}}


TAB_NAMES = ["Magnitude", "Phase", "Group delay", "Pole / zero", "Impulse / step", "Sections", "C code", "C test",
             "dsPIC33"]
IMPL_COLORS = {"float": "#a78bfa", "double": "#34d399", "fixed32": "#fbbf24", "fixed16": "#f472b6",
               "float_asm": "#a78bfa"}
# distinct line patterns, so that coinciding curves stay distinguishable
IMPL_DASH = {"float": [10, 6], "double": [2, 4], "fixed32": [14, 4, 2, 4], "fixed16": "solid",
             "float_asm": [10, 6]}


def nice_limits(values, floor_span: float = 1e-12) -> tuple[float, float]:
    """Rounded axis limits enclosing all finite values (ECharts keeps old limits otherwise)."""
    v = np.concatenate([np.ravel(np.asarray(x, dtype=float)) for x in values]) if values else np.zeros(1)
    v = v[np.isfinite(v)]
    lo, hi = (float(v.min()), float(v.max())) if v.size else (0.0, 1.0)
    span = max(hi - lo, abs(hi) * 1e-3, floor_span)
    step = 10 ** math.floor(math.log10(span / 2))
    lo = math.floor((lo - 0.05 * span) / step) * step
    hi = math.ceil((hi + 0.05 * span) / step) * step
    return r6(lo), r6(hi)


def band_masks(spec: fdcore.Spec, f: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Boolean masks of the passband and the stopband(s) of a specification."""
    if spec.type == "lowpass":
        return f <= spec.fpass[0], f >= spec.fstop[0]
    if spec.type == "highpass":
        return f >= spec.fpass[0], f <= spec.fstop[0]
    if spec.type == "bandpass":
        return ((f >= spec.fpass[0]) & (f <= spec.fpass[1]),
                (f <= spec.fstop[0]) | (f >= spec.fstop[1]))
    return ((f <= spec.fpass[0]) | (f >= spec.fpass[1]),
            (f >= spec.fstop[0]) & (f <= spec.fstop[1]))


@ui.page("/")
def index(tab: str = "magnitude") -> None:
    """Main page; ?tab=phase etc. opens a specific tab."""
    dark = ui.dark_mode(value=START_DARK)

    def P() -> dict:
        return PALETTES["dark" if dark.value else "light"]

    state = {
        "spec": fdcore.Spec(),
        "edges": {t: None for t in EDGE_LAYOUT},
        "design": None,
        "timer": None,
        "preset": presets.DEFAULT_NAME,   # current parameter file
        "dirty": False,                   # parameters changed since load/save
        "loading": False,                 # suppresses reactions while a parameter set is applied
    }
    # initial bandpass edges like the firmware example
    state["edges"]["bandpass"] = [400.0, 800.0, 1200.0, 1800.0]

    ui.add_head_html("<style>.q-field--dense .q-field__control{height:36px}</style>")

    # ------------------------------------------------------------------ header
    with ui.header().classes("items-center bg-slate-800 text-white px-4 py-2"):
        ui.label("FilterDesign").classes("text-xl font-semibold")
        ui.label("IIR filter design · Butterworth · Chebyshev · Elliptic").classes("text-sm opacity-70 ml-3")
        ui.space()
        theme_btn = ui.button(icon="light_mode").props("flat round color=white").tooltip("Light / dark mode")
        status_chip = ui.label("").classes("text-sm px-3 py-1 rounded")

    with ui.row().classes("w-full no-wrap items-start gap-4 p-4"):
        # ============================================================== left panel
        with ui.column().classes("w-80 shrink-0 gap-3"):
            with ui.card().classes("w-full gap-1"):
                with ui.row().classes("w-full items-center no-wrap"):
                    ui.label("Parameter set").classes("text-base font-semibold")
                    ui.space()
                    preset_state = ui.label("").classes("text-xs opacity-70")
                with ui.row().classes("w-full items-center no-wrap gap-1"):
                    preset_sel = ui.select([], label="Load from presets folder").props("dense").classes("grow")
                    preset_refresh = ui.button(icon="refresh").props("flat round dense").tooltip(
                        "Rescan the presets folder")
                with ui.row().classes("w-full no-wrap gap-1"):
                    save_btn = ui.button("Save", icon="save").props("dense flat no-caps")
                    save_as_btn = ui.button("Save as", icon="save_as").props("dense flat no-caps")
                    load_file_btn = ui.button("Load file", icon="upload_file").props("dense flat no-caps")
            with ui.card().classes("w-full"):
                ui.label("Specification").classes("text-base font-semibold")
                type_sel = ui.select(TYPE_LABELS, value="bandpass", label="Filter type").props("dense").classes("w-full")
                char_sel = ui.select(CHAR_LABELS, value="elliptic", label="Characteristic").props("dense").classes("w-full")
                fs_in = ui.number("Sampling rate", value=8000, min=1, suffix="Hz", format="%.6g").props("dense").classes("w-full")
                edge_in = [ui.number(f"Edge {i + 1}", value=0, min=0, suffix="Hz", format="%.6g").props("dense").classes("w-full")
                           for i in range(4)]
                with ui.row().classes("w-full no-wrap gap-2"):
                    ap_in = ui.number("Passband ripple", value=1.0, min=0.001, step=0.1, suffix="dB",
                                      format="%.4g").props("dense").classes("w-1/2")
                    as_in = ui.number("Stopband atten.", value=40.0, min=1, step=1, suffix="dB",
                                      format="%.4g").props("dense").classes("w-1/2")

            with ui.card().classes("w-full"):
                ui.label("Implementation").classes("text-base font-semibold")
                arith_sel = ui.select(ARITH_LABELS, value="fixed32", label="Arithmetic").props("dense").classes("w-full")
                scale_chk = ui.checkbox("Section scaling (L∞, 0 dB per node)", value=True)
                with ui.row().classes("w-full no-wrap items-center gap-2"):
                    auto_q = ui.checkbox("Auto Q", value=True)
                    frac_in = ui.number("Fractional bits", value=30, min=0, max=31, step=1,
                                        format="%d").props("dense").classes("grow")
                name_in = ui.input("C name", value="iir_filter").props("dense").classes("w-full")

            error_box = ui.label("").classes("w-full text-sm text-red-500 bg-red-500/10 p-2 rounded hidden")

        # ============================================================== right panel
        with ui.column().classes("grow min-w-0"):
            with ui.card().classes("w-full py-2"):
                summary = ui.grid(columns=3).classes("w-full gap-x-10 gap-y-0 text-sm")
                warn_box = ui.column().classes("w-full gap-0 text-sm")
            with ui.tabs().classes("w-full") as tabs:
                t_mag = ui.tab("Magnitude")
                t_phase = ui.tab("Phase")
                t_gd = ui.tab("Group delay")
                t_pz = ui.tab("Pole / zero")
                t_time = ui.tab("Impulse / step")
                t_sec = ui.tab("Sections")
                t_code = ui.tab("C code")
                t_test = ui.tab("C test")
                t_fw = ui.tab("dsPIC33")
            tab_widgets = [t_mag, t_phase, t_gd, t_pz, t_time, t_sec, t_code, t_test, t_fw]
            wanted = next((w for w, n in zip(tab_widgets, TAB_NAMES)
                           if n.lower().replace(" ", "").replace("/", "").startswith(tab.lower())), t_mag)
            with ui.tab_panels(tabs, value=wanted).classes("w-full"):
                with ui.tab_panel(t_mag):
                    with ui.row().classes("items-center gap-6"):
                        mag_scale = ui.toggle({"db": "dB", "lin": "linear"}, value="db")
                        mag_xlog = ui.toggle({"lin": "linear f", "log": "log f"}, value="lin")
                        mag_mask = ui.checkbox("Tolerance scheme", value=True)
                        mag_impl = ui.checkbox("Implemented (quantized)", value=True)
                    mag_chart = ui.echart(base_chart("Frequency (Hz)", "Magnitude (dB)")).classes("w-full h-[520px]")
                with ui.tab_panel(t_phase):
                    phase_wrap = ui.toggle({"unwrap": "unwrapped", "wrap": "wrapped (±180°)"}, value="unwrap")
                    phase_chart = ui.echart(base_chart("Frequency (Hz)", "Phase (°)")).classes("w-full h-[520px]")
                with ui.tab_panel(t_gd):
                    gd_unit = ui.toggle({"samples": "samples", "ms": "ms"}, value="samples")
                    gd_chart = ui.echart(base_chart("Frequency (Hz)", "Group delay (samples)")).classes("w-full h-[520px]")
                with ui.tab_panel(t_pz):
                    with ui.row().classes("w-full items-start gap-6"):
                        pz_chart = ui.echart({"series": []}).classes("w-[560px] h-[560px]")
                        pz_table = ui.column().classes("text-sm")
                with ui.tab_panel(t_time):
                    time_kind = ui.toggle({"impulse": "impulse response", "step": "step response"}, value="impulse")
                    time_chart = ui.echart(base_chart("Sample n", "Amplitude")).classes("w-full h-[520px]")
                with ui.tab_panel(t_sec):
                    sec_info = ui.label("").classes("text-sm opacity-70")
                    sec_table = ui.table(columns=[], rows=[], row_key="k").classes("w-full").props("dense flat")
                with ui.tab_panel(t_code):
                    with ui.row().classes("items-center gap-3"):
                        dl_h = ui.button("Download .h", icon="download")
                        dl_c = ui.button("Download .c", icon="download")
                        code_note = ui.label("").classes("text-sm opacity-70")
                    with ui.row().classes("w-full no-wrap gap-4 items-start"):
                        with ui.column().classes("w-1/2 min-w-0"):
                            h_title = ui.label("").classes("font-mono text-sm")
                            h_code = ui.code("", language="c").classes("w-full text-xs")
                        with ui.column().classes("w-1/2 min-w-0"):
                            c_title = ui.label("").classes("font-mono text-sm")
                            c_code = ui.code("", language="c").classes("w-full text-xs")
                with ui.tab_panel(t_test):
                    with ui.row().classes("w-full items-end gap-3"):
                        test_impls = ui.select(TEST_LABELS, multiple=True, value=list(TEST_LABELS),
                                               label="Implementations").props("dense use-chips").classes("min-w-[340px]")
                        test_sig = ui.select(ctest.SIGNALS, value="noise", label="Signal").props("dense").classes("w-44")
                        test_f1 = ui.number("f1", value=1000, min=0, suffix="Hz", format="%.6g").props("dense").classes("w-28")
                        test_f2 = ui.number("f2", value=2000, min=0, suffix="Hz", format="%.6g").props("dense").classes("w-28")
                        test_amp = ui.number("Amplitude", value=0.9, min=0.0001, max=1, step=0.05, suffix="FS",
                                             format="%.4g").props("dense").classes("w-28")
                        test_n = ui.number("Samples", value=2048, min=16, max=65536, step=256,
                                           format="%d").props("dense").classes("w-28")
                        test_cc = ui.input("C compiler", value=os.environ.get("CC", "gcc")).props("dense").classes("w-64")
                    with ui.row().classes("w-full items-center gap-3 mt-2"):
                        run_btn = ui.button("Compile & run", icon="play_arrow")
                        tb_btn = ui.button("Test bench (.zip)", icon="download").props("outline")
                        ui.label("for the selected arithmetic in the Implementation panel").classes("text-sm opacity-70")
                    test_info = ui.label("Compiles the generated C code of each selected implementation with its test "
                                         "bench, runs it with the test signal and compares the output with the double "
                                         "precision reference and the bit-exact fixed-point model."
                                         ).classes("text-sm opacity-70")
                    test_table = ui.table(columns=[], rows=[], row_key="impl").classes("w-full").props("dense flat")
                    with ui.row().classes("w-full items-center gap-4"):
                        test_view = ui.toggle({"out": "output", "err": "error", "freq": "measured magnitude",
                                               "dev": "deviation from design"}, value="out")
                        ui.label("Click a legend entry to hide or show a curve.").classes("text-xs opacity-70")
                    test_chart_box = ui.element("div").classes("w-full")
                    with ui.expansion("Compiler commands and test bench messages", icon="terminal").classes("w-full"):
                        test_log = ui.code("", language="text").classes("w-full text-xs")
                with ui.tab_panel(t_fw):
                    # the way into the dsPIC33 example of this repository (firmware.py):
                    # src/core/user_filter.h -> build -> flash -> tools/adc_gui.py, "sigproc user"
                    ui.label("Runs this design on the dsPIC33 board: the firmware's signal processing "
                             "('sigproc user', src/core/sigproc.c) filters every half of the ADC's "
                             "ping-pong buffer with it, and the dsPIC33 GUI shows the result."
                             ).classes("text-sm opacity-70")
                    with ui.row().classes("w-full items-start gap-6 no-wrap"):
                        with ui.column().classes("w-1/2 min-w-0 gap-1"):
                            ui.label("Checks").classes("font-semibold")
                            fw_checks = ui.column().classes("w-full gap-1 text-sm")
                        with ui.column().classes("w-1/2 min-w-0 gap-1"):
                            ui.label("Installed in the firmware").classes("font-semibold")
                            fw_installed = ui.label("").classes("text-sm font-mono whitespace-pre-line")
                            fw_board = ui.select({k: v["label"] for k, v in firmware.BOARDS.items()},
                                                 value="EV74H48A", label="Board").props("dense").classes("w-full")
                            fw_steps = ui.label("").classes("text-sm mt-2")
                    with ui.row().classes("w-full items-center gap-2 mt-2"):
                        fw_install_btn = ui.button("1  Install into firmware", icon="input").props("no-caps")
                        fw_build_btn = ui.button("2  Build", icon="build").props("no-caps")
                        fw_flash_btn = ui.button("3  Flash", icon="memory").props("no-caps")
                        ui.separator().props("vertical")
                        fw_all_btn = ui.button("1-3 in one go", icon="fast_forward").props("no-caps outline")
                    with ui.row().classes("w-full items-end gap-2"):
                        fw_gui_btn = ui.button("4  Open dsPIC33 GUI", icon="open_in_browser").props("no-caps")
                        fw_com = ui.input("COM port (empty: choose in the GUI)").props("dense").classes("w-64")
                        fw_http = ui.number("HTTP port", value=8080, min=1024, max=65535, format="%d"
                                            ).props("dense").classes("w-28")
                        fw_fake = ui.checkbox("fake target (no board)", value=False)
                    fw_log = ui.code("", language="text").classes("w-full text-xs")

    code_files = {"h": ("", ""), "c": ("", "")}
    dl_h.on_click(lambda: ui.download.content(code_files["h"][1], code_files["h"][0]))
    dl_c.on_click(lambda: ui.download.content(code_files["c"][1], code_files["c"][0]))

    # ------------------------------------------------------------------ helpers
    def load_edges() -> None:
        t = type_sel.value
        if state["edges"][t] is None:
            state["edges"][t] = [round(f * (fs_in.value or 8000), 6) for f in EDGE_DEFAULTS[t]]
        layout = EDGE_LAYOUT[t]
        for i, w in enumerate(edge_in):
            if i < len(layout):
                w.props(f'label="{layout[i][0]}"')
                w.set_value(state["edges"][t][i])
                w.set_visibility(True)
            else:
                w.set_visibility(False)

    def read_spec() -> fdcore.Spec:
        t = type_sel.value
        layout = EDGE_LAYOUT[t]
        vals = [float(edge_in[i].value or 0) for i in range(len(layout))]
        state["edges"][t] = vals
        fpass, fstop = [0.0, 0.0], [0.0, 0.0]
        for (label, lst, idx), v in zip(layout, vals):
            (fpass if lst == "fpass" else fstop)[idx] = v
        return fdcore.Spec(type=t, characteristic=char_sel.value, fs=float(fs_in.value or 0),
                           fpass=fpass, fstop=fstop, ap=float(ap_in.value or 0), as_=float(as_in.value or 0))

    def implementation(d: fdcore.Design):
        arith = arith_sel.value
        frac = None
        if arith.startswith("fixed") and not auto_q.value:
            frac = int(frac_in.value or 0)
        sos, fixed, impl_sos = fdcore.implement(d.sos, d.spec.fs, arith, scale_chk.value, frac)
        if fixed is not None and auto_q.value:
            frac_in.set_value(fixed.frac)
        return sos, fixed, impl_sos

    def schedule(*_):
        mark_dirty()
        if state["timer"] is not None:
            state["timer"].cancel()
        state["timer"] = ui.timer(0.3, update, once=True)

    # ------------------------------------------------------------------ main update
    def update() -> None:
        state["timer"] = None
        try:
            spec = read_spec()
            d = fdcore.design(spec)
        except fdcore.DesignError as e:
            error_box.text = str(e)
            error_box.classes(remove="hidden")
            status_chip.text = "design failed"
            status_chip.classes(replace="text-sm px-3 py-1 rounded bg-red-600")
            return
        error_box.classes(add="hidden")
        state["design"] = d
        fs = spec.fs
        sos, fixed, impl_sos = implementation(d)

        # ---------------- frequency domain
        f = fdcore.freq_axis(fs, N_FREQ, log=mag_xlog.value == "log")
        h = fdcore.response(d.sos, f, fs)
        hi = fdcore.response(impl_sos, f, fs)
        render_magnitude(spec, f, h, hi)
        flin = fdcore.freq_axis(fs, N_FREQ)
        hl = fdcore.response(d.sos, flin, fs)
        render_phase(flin, hl)
        gd = fdcore.group_delay(d.sos, flin, fs)
        render_group_delay(spec, flin, gd)

        # ---------------- poles / zeros
        z, p = fdcore.zeros_poles(d.sos)
        render_pz(z, p, fs)

        # ---------------- time domain
        settle = fdcore.settle_length(d.sos)
        n_time = int(min(max(settle * 1.2, 64), N_TIME_MAX))
        sat = None
        fixed_imp = None
        fixed_time = None
        if fixed is not None:
            fixed_imp, sat = fdcore.fixed_impulse_response(fixed, n_time)
            fixed_time = fdcore.fixed_step_response(fixed, n_time) if time_kind.value == "step" else fixed_imp
        render_time(d, impl_sos, fixed_time, n_time)

        # ---------------- sections, implementation check
        render_sections(d, sos, fixed, fs)
        att_impl_pass = [-20 * math.log10(abs(fdcore.response(impl_sos, [x], fs)[0]) + 1e-300)
                         for x in spec.fpass[:len(d.att_pass)]]
        att_impl_stop = [-20 * math.log10(abs(fdcore.response(impl_sos, [x], fs)[0]) + 1e-300)
                         for x in spec.fstop[:len(d.att_stop)]]
        impl_ok = all(a <= spec.ap + 0.01 for a in att_impl_pass) and all(a >= spec.as_ - 0.01 for a in att_impl_stop)

        # ---------------- summary
        summary.clear()
        pole_r = float(np.max(np.abs(p))) if len(p) else 0.0
        fc = (math.sqrt(spec.fpass[0] * spec.fpass[1]) if spec.type == "bandpass"
              else spec.fpass[0] / 2 if spec.type == "lowpass" else 0.0)
        gd_fc = float(fdcore.group_delay(d.sos, np.array([fc]), fs)[0]) if spec.type in ("lowpass", "bandpass") else None
        fmt = lambda v: ", ".join(f"{x:.2f}" for x in v)
        rows = [
            ("Order", f"{d.digital_order}  ({len(d.sos)} sections)"),
            ("Passband atten.", f"{fmt(d.att_pass)} dB  (≤ {spec.ap:g})"),
            ("Stopband atten.", f"{fmt(d.att_stop)} dB  (≥ {spec.as_:g})"),
            ("Max. pole radius", f"{pole_r:.6f}"),
            ("Settling (−80 dB)", f"{settle} samples = {settle / fs * 1e3:.3g} ms"),
        ]
        if gd_fc is not None and math.isfinite(gd_fc):
            rows.append(("Group delay @ " + f"{fc:.4g} Hz", f"{gd_fc:.2f} samples = {gd_fc / fs * 1e3:.3g} ms"))
        if fixed is not None:
            rows.append(("Coefficient format", f"Q{fixed.word - 1 - fixed.frac}.{fixed.frac} (int{fixed.word}_t)"
                         + ("  CLIPPED!" if fixed.clipped else "")))
            rows.append(("Impulse test (½ FS)", f"{sat} saturation(s)"))
        rows.append(("Impl. passband", f"{fmt(att_impl_pass)} dB"))
        rows.append(("Impl. stopband", f"{fmt(att_impl_stop)} dB"))
        with summary:
            for k, v in rows:
                with ui.row().classes("w-full no-wrap justify-between gap-2"):
                    ui.label(k).classes("opacity-70 whitespace-nowrap")
                    ui.label(v).classes("text-right font-mono whitespace-nowrap")
        warn_box.clear()
        with warn_box:
            if fixed is not None and (fixed.clipped or sat):
                ui.label("Fixed point overflow: enable section scaling or reduce the fractional bits."
                         ).classes("text-red-500 mt-1")
            if not impl_ok:
                ui.label("The quantized implementation violates the specification."
                         ).classes("text-amber-500 mt-1")

        ok = d.spec_met and impl_ok and not (fixed is not None and (fixed.clipped or sat))
        status_chip.text = (f"{CHAR_LABELS[spec.characteristic]} {TYPE_LABELS[spec.type].lower()}, "
                            f"order {d.digital_order} · " + ("specification met" if ok else "check result"))
        status_chip.classes(replace="text-sm px-3 py-1 rounded " + ("bg-green-600" if ok else "bg-amber-600"))

        state["impl"] = (arith_sel.value, sos, fixed, sat, impl_ok)
        render_firmware()

        # ---------------- code
        files = codegen.generate(d, name_in.value or "iir_filter", arith_sel.value, sos, fixed)
        code_files["h"] = (files[0], files[1])
        code_files["c"] = (files[2], files[3])
        h_title.text, c_title.text = files[0], files[2]
        dl_c.text = "Download " + os.path.splitext(files[2])[1]
        h_code.content, c_code.content = files[1], files[3]
        code_note.text = (f"{ARITH_LABELS[arith_sel.value]}, {len(sos)} sections"
                          + (", section scaling" if scale_chk.value else ""))
        if state.get("test") is not None:
            render_test()

    # ------------------------------------------------------------------ renderers
    def show(chart, opt: dict) -> None:
        # note: nicegui merges new options into the old ones while the number of series is
        # unchanged, so a chart whose views use different axis limits must always set them
        chart.options.clear()
        chart.options.update(apply_theme(opt, P()))
        chart.update()

    def render_magnitude(spec: fdcore.Spec, f, h, hi) -> None:
        lin = mag_scale.value == "lin"
        opt = base_chart("Frequency (Hz)", "Magnitude" if lin else "Magnitude (dB)",
                         "log" if mag_xlog.value == "log" else "value")
        opt["xAxis"].update({"min": r6(f[0]), "max": r6(f[-1])})
        if lin:
            y, yi = np.abs(h), np.abs(hi)
            opt["yAxis"].update({"min": 0, "max": 1.1})
            pass_lim, stop_lim, top, bottom = 10 ** (-spec.ap / 20), 10 ** (-spec.as_ / 20), 1.1, 0
        else:
            y, yi = fdcore.magnitude_db(h), fdcore.magnitude_db(hi)
            bottom = -10 * math.ceil((spec.as_ + 40) / 10)
            opt["yAxis"].update({"min": bottom, "max": 5})
            pass_lim, stop_lim, top = -spec.ap, -spec.as_, 5
        series = line("Design", xy(f, y), P()["design"])
        if mag_mask.value:
            nyq = spec.fs / 2
            f0 = r6(f[0])
            areas = []
            pa = {"lowpass": [(f0, spec.fpass[0])], "highpass": [(spec.fpass[0], nyq)],
                  "bandpass": [(spec.fpass[0], spec.fpass[1])],
                  "bandstop": [(f0, spec.fpass[0]), (spec.fpass[1], nyq)]}[spec.type]
            sa = {"lowpass": [(spec.fstop[0], nyq)], "highpass": [(f0, spec.fstop[0])],
                  "bandpass": [(f0, spec.fstop[0]), (spec.fstop[1], nyq)],
                  "bandstop": [(spec.fstop[0], spec.fstop[1])]}[spec.type]
            for a, b in pa:
                areas.append([{"xAxis": a, "yAxis": bottom}, {"xAxis": b, "yAxis": pass_lim}])
            for a, b in sa:
                areas.append([{"xAxis": a, "yAxis": stop_lim}, {"xAxis": b, "yAxis": top}])
            series["markArea"] = {"silent": True, "itemStyle": {"color": P()["forbidden"]}, "data": areas}
        else:
            series["markArea"] = {"data": []}   # explicit: nicegui would keep the old areas
        opt["series"].append(series)
        if mag_impl.value:
            opt["series"].append(line(f"Implemented ({ARITH_LABELS[arith_sel.value]})", xy(f, yi),
                                      P()["impl"], dashed=True, width=1.5))
        show(mag_chart, opt)

    def render_phase(f, h) -> None:
        ph = fdcore.phase_deg(h) if phase_wrap.value == "unwrap" else np.degrees(np.angle(h))
        opt = base_chart("Frequency (Hz)", "Phase (°)")
        opt["xAxis"].update({"min": 0, "max": r6(f[-1])})
        opt["series"].append(line("Phase", xy(f, ph), P()["design"]))
        show(phase_chart, opt)

    def render_group_delay(spec, f, gd) -> None:
        ms = gd_unit.value == "ms"
        y = gd / spec.fs * 1e3 if ms else gd
        opt = base_chart("Frequency (Hz)", "Group delay (ms)" if ms else "Group delay (samples)")
        opt["xAxis"].update({"min": 0, "max": r6(f[-1])})
        finite = y[np.isfinite(y)]
        if len(finite):
            hi = float(np.percentile(finite, 99.5))
            lo = float(np.min(finite))
            opt["yAxis"].update({"min": min(0, math.floor(lo)), "max": math.ceil(hi * 1.1) if hi > 0 else 1})
        opt["series"].append(line("Group delay", xy(f, y), P()["design"]))
        show(gd_chart, opt)

    def cluster(points: np.ndarray) -> list:
        groups: list[list] = []
        for c in points:
            for g in groups:
                if abs(g[0] - c) < 1e-5:
                    g[1] += 1
                    break
            else:
                groups.append([c, 1])
        return groups

    def render_pz(z, p, fs) -> None:
        rmax = max(1.15, float(np.max(np.abs(np.concatenate([z, p])))) * 1.1 if len(z) + len(p) else 1.15)
        th = np.linspace(0, 2 * np.pi, 361)

        def pts(groups, color):
            out = []
            for c, m in groups:
                item = {"value": [r6(c.real), r6(c.imag)]}
                if m > 1:
                    item["label"] = {"show": True, "formatter": str(m), "position": "right", "color": color}
                out.append(item)
            return out

        cross = "path://M2,0 L5,3 L8,0 L10,2 L7,5 L10,8 L8,10 L5,7 L2,10 L0,8 L3,5 L0,2 Z"
        opt = {
            "animation": False,
            "grid": {"left": 60, "right": 30, "top": 40, "bottom": 50},
            "legend": {"top": 5},
            "tooltip": {"trigger": "item"},
            "toolbox": {"right": 10, "feature": {"dataZoom": {}, "restore": {}, "saveAsImage": {}}},
            "xAxis": {"type": "value", "min": -r6(rmax), "max": r6(rmax), "name": "Real",
                      "nameLocation": "middle", "nameGap": 28},
            "yAxis": {"type": "value", "min": -r6(rmax), "max": r6(rmax), "name": "Imaginary",
                      "nameLocation": "middle", "nameGap": 40},
            "series": [
                {"name": "Unit circle", "type": "line", "data": xy(np.cos(th), np.sin(th)), "showSymbol": False,
                 "silent": True, "lineStyle": {"color": P()["circle"], "type": "dashed", "width": 1},
                 "itemStyle": {"color": P()["circle"]}},
                {"name": "Zeros", "type": "scatter", "data": pts(cluster(z), P()["zero"]), "symbol": "circle",
                 "symbolSize": 11, "itemStyle": {"color": "rgba(0,0,0,0)", "borderColor": P()["zero"],
                                                 "borderWidth": 2}},
                {"name": "Poles", "type": "scatter", "data": pts(cluster(p), P()["pole"]), "symbol": cross,
                 "symbolSize": 11, "itemStyle": {"color": P()["pole"]}},
            ],
        }
        show(pz_chart, opt)

        pz_table.clear()
        with pz_table:
            ui.label("Poles").classes("font-semibold")
            for c, m in cluster(p):
                if c.imag >= -1e-12:
                    ui.label(f"r = {abs(c):.6f}   f = {abs(np.angle(c)) * fs / (2 * np.pi):9.2f} Hz"
                             + (f"   ×{m}" if m > 1 else "")).classes("font-mono")
            ui.label("Zeros").classes("font-semibold mt-2")
            for c, m in cluster(z):
                if c.imag >= -1e-12:
                    ui.label(f"r = {abs(c):.6f}   f = {abs(np.angle(c)) * fs / (2 * np.pi):9.2f} Hz"
                             + (f"   ×{m}" if m > 1 else "")).classes("font-mono")

    def render_time(d, impl_sos, fixed_imp, n) -> None:
        step = time_kind.value == "step"
        k = np.arange(n)
        y = fdcore.step_response(d.sos, n) if step else fdcore.impulse_response(d.sos, n)
        opt = base_chart("Sample n", "Amplitude")
        opt["series"].append(line("Design", xy(k, y), P()["design"]))
        if fixed_imp is not None:
            yi = fixed_imp
            opt["series"].append(line("Fixed point", xy(k, yi), P()["impl"], dashed=True, width=1.5))
        else:
            yi = fdcore.step_response(impl_sos, n) if step else fdcore.impulse_response(impl_sos, n)
            opt["series"].append(line("Implemented", xy(k, yi), P()["impl"], dashed=True, width=1.5))
        show(time_chart, opt)

    def render_sections(d, sos, fixed, fs) -> None:
        peaks = fdcore.partial_peak_gains(sos, fs)
        x = np.zeros(8192)
        x[0] = 1
        cols = [{"name": "k", "label": "#", "field": "k", "align": "right"},
                {"name": "ord", "label": "Order", "field": "ord", "align": "right"}]
        for nme in ("b0", "b1", "b2", "a1", "a2"):
            cols.append({"name": nme, "label": nme, "field": nme, "align": "right", "classes": "font-mono"})
        cols += [{"name": "pr", "label": "Pole r", "field": "pr", "align": "right"},
                 {"name": "pf", "label": "Pole f (Hz)", "field": "pf", "align": "right"},
                 {"name": "q", "label": "Pole Q", "field": "q", "align": "right"},
                 {"name": "pk", "label": "Peak gain at output", "field": "pk", "align": "right"},
                 {"name": "l1", "label": "L1 norm at output", "field": "l1", "align": "right"}]
        rows = []
        y = x
        for i, row in enumerate(sos):
            y = signal.sosfilt(row[None, :], y)
            p = np.roots(row[3:]) if row[5] != 0 else np.roots(row[3:5])
            pc = p[np.argmax(np.abs(p.imag))] if len(p) else 0
            r = abs(pc)
            theta = abs(np.angle(pc))
            # Q of the equivalent analog pole pair s = fs * ln(z)
            q = (math.hypot(math.log(r), theta) / (2 * abs(math.log(r)))
                 if row[5] != 0 and 0 < r < 1 and theta > 0 else None)
            if fixed is not None:
                vals = [str(int(v)) for v in fixed.coeffs[i]]
            else:
                vals = [f"{v:.9g}" for v in (row[0], row[1], row[2], row[4], row[5])]
            rows.append({"k": i + 1, "ord": d.section_order[i], **dict(zip(("b0", "b1", "b2", "a1", "a2"), vals)),
                         "pr": f"{r:.5f}", "pf": f"{theta * fs / (2 * np.pi):.1f}",
                         "q": f"{q:.2f}" if q else "–",
                         "pk": f"{20 * math.log10(peaks[i]):+.2f} dB",
                         "l1": f"{np.sum(np.abs(y)):.3f}"})
        sec_table.columns = cols
        sec_table.rows = rows
        sec_table.update()
        l1max = max(float(r["l1"]) for r in rows)
        sec_info.text = (
            ("Coefficients as integers in " + f"Q{fixed.frac} (int{fixed.word}_t). " if fixed is not None
             else "Coefficients in floating point. ")
            + ("Section scaling is on: the peak gain at every section output is 0 dB. " if scale_chk.value
               else "Section scaling is off. ")
            + f"Worst case input-to-node gain (L1 norm) is {l1max:.2f}, so "
            + f"{max(0, math.ceil(math.log2(l1max))) if l1max > 0 else 0} bit(s) of headroom avoid any overflow.")

    # ------------------------------------------------------------------ C test
    def frac_override() -> dict:
        """Manual Q of the Implementation panel applies to the selected fixed-point arithmetic."""
        if arith_sel.value.startswith("fixed") and not auto_q.value:
            return {arith_sel.value: int(frac_in.value or 0)}
        return {}

    def test_args() -> dict:
        return {"kind": test_sig.value, "n": int(test_n.value or 2048),
                "amplitude": float(min(max(test_amp.value or 0.9, 1e-4), 1.0)),
                "f1": float(test_f1.value or 0), "f2": float(test_f2.value or 0)}

    async def run_test() -> None:
        d = state["design"]
        if d is None:
            ui.notify("No valid design to test.", type="warning")
            return
        cc = ctest.find_compiler(test_cc.value)
        if cc is None:
            ui.notify(f"C compiler '{test_cc.value}' not found.", type="negative")
            return
        ariths = [a for a in fdcore.ARITHMETICS if a in (test_impls.value or [])]
        if not ariths:
            ui.notify("Select at least one implementation.", type="warning")
            return
        a = test_args()
        run_btn.props("loading")
        try:
            tr = await ng_run.io_bound(ctest.run_tests, d, ariths, a["kind"], a["n"], a["amplitude"],
                                       a["f1"], a["f2"], cc, scale_chk.value, frac_override())
        finally:
            run_btn.props(remove="loading")
        state["test"] = (tr, d)
        render_test()
        failed = [r.arith for r in tr.results if not r.ok or r.testbench_pass is False or r.bit_exact is False]
        ui.notify("All implementations passed." if not failed else f"Check: {', '.join(failed)}",
                  type="positive" if not failed else "warning")

    # ------------------------------------------------------------------ dsPIC33 tab
    fw = {"flashed": {}, "done_log": ""}       # board -> id last flashed from here; finished entries

    def fw_check_rows(d, arith, fixed, sat, impl_ok) -> list[tuple[str, str]]:
        """(level, text) per check; level ok / warn / bad (bad: not installed)."""
        fs = d.spec.fs
        rows = []
        if fs != round(fs / 1000.0) * 1000.0 or not 1000.0 <= fs <= 40e6:
            rows.append(("bad", f"Sample rate {fs:g} Hz: the board's stream runs at whole ksps, 1 to "
                                f"40000 ('stream on <ksps>'). Design for a multiple of 1 kHz."))
        else:
            rows.append(("ok", f"Sample rate {fs / 1000:g} ksps: the dsPIC33 GUI must stream at the same "
                               f"rate - the coefficients hold for this rate only."))
        budget = firmware.CPU_HZ / fs
        lvl = "ok" if budget >= 200 else "warn" if budget >= 60 else "bad"
        rows.append((lvl, f"CPU budget {budget:,.0f} cycles per sample (200 MHz / fs) for {len(d.sos)} "
                          f"section(s) plus the conversion. For scale: the firmware's built-in 2-section "
                          f"float filter costs about 43 (board, 02.10.2026). The dsPIC33 GUI's load "
                          f"figure shows the real cost."))
        if fs > 8e6:
            rows.append(("warn", "Above 8 MSPS the stream itself loses samples (docs/HARDWARE-LOG.md)."))
        if arith == "double":
            rows.append(("warn", "double: the firmware uses long double (XC-DSC's double has 32 bits) - "
                                 "much slower than float."))
        if arith == "float_asm":
            rows.append(("warn", "dsPIC33A assembler: 7 FPU instructions per section and about 12 per "
                                 "sample, fused multiply-add (not bit-exact to the C float code). The PC "
                                 "test cannot run it; the C stand-in in the header is what the host tests "
                                 "see, the board (or test_asm_sim.py in the MPLAB simulator) runs the "
                                 "assembler."))
        if fixed is not None and (fixed.clipped or sat):
            rows.append(("bad", "Fixed-point overflow in the impulse test - enable section scaling."))
        rows.append(("ok" if d.spec_met and impl_ok else "warn",
                     "Specification met, also quantized." if d.spec_met and impl_ok
                     else "The (quantized) design misses the specification."))
        return rows

    def render_firmware() -> None:
        d, impl = state.get("design"), state.get("impl")
        if d is None or impl is None:
            return
        arith, sos, fixed, sat, impl_ok = impl
        fw_checks.clear()
        colors = {"ok": "text-green-500", "warn": "text-amber-500", "bad": "text-red-500"}
        icons = {"ok": "check_circle", "warn": "warning", "bad": "error"}
        with fw_checks:
            for lvl, text in fw_check_rows(d, arith, fixed, sat, impl_ok):
                with ui.row().classes("w-full no-wrap items-start gap-2"):
                    ui.icon(icons[lvl]).classes(colors[lvl] + " mt-0.5")
                    ui.label(text)
        info = firmware.installed_info()
        this_id = firmware.preview_id(d, arith, sos, fixed)
        if info is None:
            fw_installed.text = "nothing (src/core/user_filter.json missing)"
        else:
            same = info.get("id") == this_id
            fw_installed.text = (f"{info.get('description', '?')}\nid {info.get('id', '?')} - "
                                 + ("this design" if same else f"not this design (id {this_id})"))
        board = fw_board.value
        installed = firmware.header_id() == this_id
        built = installed and firmware.hex_is_current(board)
        flashed = built and fw["flashed"].get(board) == this_id
        fw_steps.text = "   ".join(("✔ " if ok else "○ ") + name for name, ok in
                                   (("installed", installed), ("built", built), ("flashed", flashed)))

    def fw_log_add(title: str, r: firmware.Result | None = None, text: str = "") -> None:
        body = text if r is None else (f"{'OK' if r.ok else 'FAILED'} after {r.seconds:.1f} s\n"
                                       + "\n".join(r.log.strip().splitlines()[-60:]))
        fw["done_log"] = (f"=== {title}\n{body}\n\n" + fw["done_log"])[:20000]
        fw_log.content = fw["done_log"]

    async def fw_live(title: str, note: str, fn, *args) -> firmware.Result:
        """Runs fn(*args, on_line=...) in a worker thread and shows its output as it comes,
        with the seconds running, above the earlier entries - so a slow step is seen to
        be busy and is not stopped half-way (a flash stopped while programming wedged the
        PKOB4 until its USB cable was plugged again, 03.10.2026)."""
        lines: list[str] = []
        t0 = time.monotonic()

        def show() -> None:
            fw_log.content = (f"=== {title} - running {time.monotonic() - t0:.0f} s. {note}\n"
                              + "\n".join(lines[-60:]) + "\n\n" + fw["done_log"])

        timer = ui.timer(0.5, show)
        try:
            r = await ng_run.io_bound(fn, *args, on_line=lines.append)
        finally:
            timer.cancel()
        if r is None:                                   # cancelled (page closed)
            r = firmware.Result(False, "\n".join(lines) + "\n[cancelled]", time.monotonic() - t0)
        fw_log_add(title, r)
        return r

    def fw_set_busy(on: bool) -> None:
        for b in (fw_install_btn, fw_build_btn, fw_flash_btn, fw_all_btn):
            if on:
                b.props("disable")
            else:
                b.props(remove="disable")

    def fw_install() -> bool:
        d, impl = state.get("design"), state.get("impl")
        if d is None or impl is None:
            ui.notify("No valid design.", type="warning")
            return False
        arith, sos, fixed, sat, impl_ok = impl
        bad = [t for lvl, t in fw_check_rows(d, arith, fixed, sat, impl_ok) if lvl == "bad"]
        if bad:
            ui.notify("Not installed: " + bad[0], type="negative", multi_line=True)
            fw_log_add("Install", text="refused: " + "\n".join(bad))
            return False
        info = firmware.install(d, arith, sos, fixed)
        fw_log_add("Install", text=f"{firmware.HEADER}\n{firmware.INFO}\n{info['description']}, id {info['id']}")
        render_firmware()
        return True

    async def fw_build() -> bool:
        board = fw_board.value
        fw_set_busy(True)
        fw_build_btn.props("loading")
        try:
            r = await fw_live(f"Build {board}", "xc-dsc takes about 20 s.", firmware.build, board)
        finally:
            fw_build_btn.props(remove="loading")
            fw_set_busy(False)
        ui.notify("Build OK" if r.ok else "Build failed - see the log", type="positive" if r.ok else "negative")
        render_firmware()
        return r.ok

    async def fw_flash() -> bool:
        board = fw_board.value
        if not firmware.hex_is_current(board):
            ui.notify("The .hex is older than user_filter.h - build first.", type="warning")
            return False
        fw_set_busy(True)
        fw_flash_btn.props("loading")
        note = ("ipecmd takes 20 to 40 s - do not unplug the board or close this page; a hung run "
                "is stopped by itself after 240 s." if board == "EV74H48A" else "Copying to the Nano.")
        try:
            r = await fw_live(f"Flash {board}", note, firmware.flash, board)
        finally:
            fw_flash_btn.props(remove="loading")
            fw_set_busy(False)
        if r.ok:
            fw["flashed"][board] = firmware.header_id()
        ui.notify("Flashed" if r.ok else "Flash failed - see the log", type="positive" if r.ok else "negative")
        render_firmware()
        return r.ok

    async def fw_all() -> None:
        if fw_install() and await fw_build():
            await fw_flash()

    def fw_open_gui() -> None:
        port = int(fw_http.value or 8080)
        try:
            firmware.start_adc_gui(port, (fw_com.value or "").strip() or None, bool(fw_fake.value))
        except OSError as e:
            ui.notify(f"Cannot start tools/adc_gui.py: {e}", type="negative")
            return
        fw_log_add("dsPIC33 GUI", text=f"started tools/adc_gui.py on http://127.0.0.1:{port} in its own "
                                       f"window - it opens its browser tab itself, filter 'user' preselected")

    fw_install_btn.on_click(fw_install)
    fw_build_btn.on_click(fw_build)
    fw_flash_btn.on_click(fw_flash)
    fw_all_btn.on_click(fw_all)
    fw_gui_btn.on_click(fw_open_gui)
    fw_board.on_value_change(lambda _: render_firmware())

    def download_testbench() -> None:
        d = state["design"]
        if d is None:
            return
        if arith_sel.value not in codegen.PC_TESTABLE:
            ui.notify("dsPIC33A assembler: no PC test bench - it runs on the dsPIC33A only "
                      "(dsPIC33 tab, or tools/filterdesign/gui/test_asm_sim.py in the MPLAB simulator).",
                      type="warning")
            return
        a = test_args()
        name = name_in.value or "iir_filter"
        frac = frac_override().get(arith_sel.value)
        data = ctest.testbench_zip(d, name, arith_sel.value, a["kind"], a["n"], a["amplitude"],
                                   a["f1"], a["f2"], scale_chk.value, frac)
        ui.download.content(data, f"{codegen.c_identifier(name)}_{arith_sel.value}_testbench.zip",
                            "application/zip")

    def fmt_num(v: float | None, spec: str = ".3g") -> str:
        if v is None:
            return "–"
        if isinstance(v, float) and math.isinf(v):
            return "∞"
        if isinstance(v, float) and math.isnan(v):
            return "–"
        return format(v, spec)

    def render_test() -> None:
        tr, d_test = state["test"]
        stale = d_test is not state["design"]
        sig = ctest.SIGNALS[tr.signal]
        test_info.text = (f"Results for {d_test.spec.characteristic} {d_test.spec.type}, order "
                          f"{d_test.digital_order}: {sig}, {tr.n} samples, amplitude {tr.amplitude:g} FS"
                          + ("  —  the design has changed since this test, run it again." if stale else ""))
        cols = [{"name": "impl", "label": "Implementation", "field": "impl", "align": "left"},
                {"name": "build", "label": "Build", "field": "build", "align": "center"},
                {"name": "tb", "label": "Test bench", "field": "tb", "align": "center"},
                {"name": "exact", "label": "Bit-exact vs. model", "field": "exact", "align": "center"},
                {"name": "q", "label": "Format", "field": "q", "align": "right"},
                {"name": "sat", "label": "Saturations", "field": "sat", "align": "right"},
                {"name": "maxerr", "label": "Max |error|", "field": "maxerr", "align": "right"},
                {"name": "lsb", "label": "Max |error| (LSB)", "field": "lsb", "align": "right"},
                {"name": "rms", "label": "RMS error", "field": "rms", "align": "right"},
                {"name": "snr", "label": "SNR (dB)", "field": "snr", "align": "right"},
                {"name": "pdev", "label": "Passband max |Δ| (dB)", "field": "pdev", "align": "right"},
                {"name": "satt", "label": f"Stopband min. atten. (dB, spec {d_test.spec.as_:g})", "field": "satt",
                 "align": "right"}]
        rows, log = [], []
        for r in tr.results:
            ok = "✔" if r.ok else "✘"
            pdev = satt = None
            if r.ok:
                pm, sm = band_masks(d_test.spec, r.f_meas)
                with np.errstate(divide="ignore"):
                    hd = np.abs(fdcore.response(d_test.sos, r.f_meas, d_test.spec.fs))
                    dev = 20 * np.log10(r.h_meas + 1e-300) - 20 * np.log10(hd + 1e-300)
                pdev = float(np.max(np.abs(dev[pm]))) if pm.any() else None
                satt = float(np.min(-20 * np.log10(r.h_meas[sm] + 1e-300))) if sm.any() else None
            rows.append({
                "impl": ARITH_LABELS[r.arith], "build": ok,
                "tb": "–" if r.testbench_pass is None else ("PASS" if r.testbench_pass else "FAIL"),
                "exact": "–" if r.bit_exact is None else ("✔" if r.bit_exact else "✘"),
                "q": (f"Q{r.frac}" if r.frac is not None else r.arith),
                "sat": "–" if r.saturations is None else str(r.saturations),
                "maxerr": fmt_num(r.max_err), "lsb": fmt_num(r.max_err / r.lsb, ".1f") if r.lsb and r.ok else "–",
                "rms": fmt_num(r.rms_err), "snr": fmt_num(r.snr_db, ".1f"),
                "pdev": fmt_num(pdev, ".3g"),
                "satt": "–" if satt is None else (f"{satt:.1f}" + ("" if satt >= d_test.spec.as_ - 0.01 else "  ✘")),
            })
            log.append(f"[{r.arith}] {r.compile_cmd}".rstrip())
            if r.testbench_msg:
                log.append(f"[{r.arith}] test bench: {r.testbench_msg}")
            if r.message:
                log.append(f"[{r.arith}] ERROR: {r.message}")
        test_table.columns = cols
        test_table.rows = rows
        test_table.update()
        test_log.content = "\n".join(log)

        ok = [r for r in tr.results if r.ok]
        view = test_view.value
        if view in ("freq", "dev"):
            spec = d_test.spec
            opt = base_chart("Frequency (Hz)", "Magnitude (dB)" if view == "freq" else "Measured − design (dB)")
            opt["xAxis"].update({"min": 0, "max": r6(spec.fs / 2)})
            if view == "freq":
                bottom = -10 * math.ceil((spec.as_ + 60) / 10)
                opt["yAxis"].update({"min": bottom, "max": 5})
                design = line("Design", xy(tr.f_design, fdcore.magnitude_db(tr.h_design)), P()["design"], width=6)
                design["lineStyle"]["opacity"] = 0.35
                design["z"] = 1
                opt["series"].append(design)
            else:
                # stopband shaded: there the deviation shows the noise floor, not a design error
                _, sm = band_masks(spec, tr.f_design)
                areas, start = [], None
                for fv, inside in zip(tr.f_design, sm):
                    if inside and start is None:
                        start = fv
                    elif not inside and start is not None:
                        areas.append([{"xAxis": r6(start)}, {"xAxis": r6(fv)}])
                        start = None
                if start is not None:
                    areas.append([{"xAxis": r6(start)}, {"xAxis": r6(tr.f_design[-1])}])
                zero = line("Design (0 dB)", xy(tr.f_design[[0, -1]], [0.0, 0.0]), P()["design"], width=1)
                zero["markArea"] = {"silent": True, "itemStyle": {"color": P()["forbidden"]}, "data": areas,
                                    "label": {"show": True, "position": "insideTop", "formatter": "stopband",
                                              "color": P()["fg"]}}
                opt["series"].append(zero)
            dev_all = []
            for r in ok:
                with np.errstate(divide="ignore"):
                    y = fdcore.magnitude_db(r.h_meas)
                    if view == "dev":
                        hd = np.abs(fdcore.response(d_test.sos, r.f_meas, spec.fs))
                        y = 20 * np.log10(r.h_meas + 1e-300) - 20 * np.log10(hd + 1e-300)
                        dev_all.append(y)
                s = line(f"{r.arith} (C)", xy(r.f_meas, y), IMPL_COLORS[r.arith], width=1.8)
                s["lineStyle"]["type"] = IMPL_DASH[r.arith]
                s["z"] = 3
                opt["series"].append(s)
            if view == "dev":
                # the deviation diverges at the zeros of the design: limit the axis to +/-60 dB
                lo, hi = nice_limits([np.clip(v, -60, 60) for v in dev_all] + [np.zeros(1)], floor_span=1e-3)
                opt["yAxis"].update({"min": lo, "max": hi})
        else:
            n_show = min(tr.n, 4096)
            k = np.arange(n_show)
            opt = base_chart("Sample n", "Amplitude (FS)" if view == "out" else "Error (FS)")
            opt["xAxis"].update({"min": 0, "max": n_show - 1})
            if ok and view == "out":
                opt["series"].append(line("Input", xy(k, ok[0].x[:n_show]), P()["circle"], width=1))
                opt["series"].append(line("Reference (double)", xy(k, ok[0].ref[:n_show]), P()["design"]))
            for r in ok:
                y = r.y[:n_show] if view == "out" else (r.y - r.ref)[:n_show]
                s = line(f"{r.arith} (C)", xy(k, y), IMPL_COLORS[r.arith], width=1.5)
                s["lineStyle"]["type"] = IMPL_DASH[r.arith]
                opt["series"].append(s)
            if tr.n > n_show:
                opt["title"] = {"text": f"first {n_show} of {tr.n} samples", "right": 60, "top": 5,
                                "textStyle": {"fontSize": 12, "color": P()["fg"]}}
        # recreate the chart: nicegui would merge this view into the previous one (stale axis
        # limits, titles and shaded areas) because the number of series is often the same
        test_chart_box.clear()
        with test_chart_box:
            ui.echart(apply_theme(opt, P())).classes("w-full h-[460px]")

    def update_test_inputs(_=None) -> None:
        kind = test_sig.value
        test_f1.set_visibility(kind in ("sine", "chirp", "multitone"))
        test_f2.set_visibility(kind in ("chirp", "multitone"))

    def default_test_freqs() -> None:
        """Sine at the passband center, second tone in the stopband."""
        s = read_spec()
        if s.type == "lowpass":
            f1, f2 = s.fpass[0] / 2, s.fstop[0] * 1.2
        elif s.type == "highpass":
            f1, f2 = (s.fpass[0] + s.fs / 2) / 2, s.fstop[0] / 2
        elif s.type == "bandpass":
            f1, f2 = math.sqrt(s.fpass[0] * s.fpass[1]), s.fstop[1] * 1.1
        else:
            f1, f2 = s.fpass[0] / 2, math.sqrt(s.fstop[0] * s.fstop[1])
        test_f1.set_value(round(min(f1, 0.49 * s.fs), 3))
        test_f2.set_value(round(min(f2, 0.49 * s.fs), 3))

    run_btn.on_click(run_test)
    tb_btn.on_click(download_testbench)
    test_sig.on_value_change(update_test_inputs)
    test_view.on_value_change(lambda: render_test() if state.get("test") is not None else None)

    # ------------------------------------------------------------------ wiring
    def on_type_change(_=None):
        load_edges()
        schedule()

    def toggle_theme():
        dark.value = not dark.value
        theme_btn.props(f'icon={"light_mode" if dark.value else "dark_mode"}')
        mark_dirty()
        update()

    theme_btn.on_click(toggle_theme)
    theme_btn.props(f'icon={"light_mode" if dark.value else "dark_mode"}')
    type_sel.on_value_change(on_type_change)
    frac_in.on_value_change(lambda: None if auto_q.value else schedule())
    for w in (char_sel, fs_in, ap_in, as_in, arith_sel, scale_chk, auto_q, name_in,
              mag_scale, mag_xlog, mag_mask, mag_impl, phase_wrap, gd_unit, time_kind, *edge_in):
        w.on_value_change(schedule)
    frac_in.bind_enabled_from(auto_q, "value", backward=lambda v: not v)

    type_sel.on_value_change(default_test_freqs)

    # ------------------------------------------------------------------ parameter sets (JSON)
    def collect_params() -> dict:
        read_spec()   # stores the visible edges in state["edges"]
        return {
            "spec": {
                "type": type_sel.value, "characteristic": char_sel.value, "fs": fs_in.value,
                "ap": ap_in.value, "as": as_in.value,
                "edges": {t: v for t, v in state["edges"].items() if v is not None},
            },
            "implementation": {
                "arithmetic": arith_sel.value, "section_scaling": scale_chk.value, "auto_q": auto_q.value,
                "frac_bits": int(frac_in.value or 0), "c_name": name_in.value,
            },
            "view": {
                "dark": dark.value, "magnitude_scale": mag_scale.value, "frequency_axis": mag_xlog.value,
                "tolerance_scheme": mag_mask.value, "implemented_response": mag_impl.value,
                "phase": phase_wrap.value, "group_delay_unit": gd_unit.value, "time_response": time_kind.value,
                "test_view": test_view.value,
            },
            "test": {
                "implementations": list(test_impls.value or []), "signal": test_sig.value,
                "f1": test_f1.value, "f2": test_f2.value, "amplitude": test_amp.value,
                "samples": int(test_n.value or 0), "compiler": test_cc.value,
            },
        }

    def apply_params(p: dict) -> list[str]:
        """Sets all widgets from a parameter set; invalid or missing entries keep their value."""
        warnings: list[str] = []

        def pick(section: str, key: str, conv, ok=lambda v: True):
            raw = (p.get(section) or {}).get(key)
            if raw is None:
                return None
            try:
                v = conv(raw)
            except (TypeError, ValueError):
                v = None
            if v is None or not ok(v):
                warnings.append(f"{section}.{key}: invalid value {raw!r} ignored")
                return None
            return v

        def put(widget, value) -> None:
            if value is not None:
                widget.set_value(value)

        boolean = lambda v: v if isinstance(v, bool) else None
        state["loading"] = True
        try:
            for t, vals in ((p.get("spec") or {}).get("edges") or {}).items():
                try:
                    if t in EDGE_LAYOUT and len(vals) == len(EDGE_LAYOUT[t]):
                        state["edges"][t] = [float(v) for v in vals]
                    else:
                        raise ValueError
                except (TypeError, ValueError):
                    warnings.append(f"spec.edges.{t}: invalid value ignored")
            put(fs_in, pick("spec", "fs", float, lambda v: v > 0))
            put(type_sel, pick("spec", "type", str, lambda v: v in TYPE_LABELS))
            load_edges()
            put(char_sel, pick("spec", "characteristic", str, lambda v: v in CHAR_LABELS))
            put(ap_in, pick("spec", "ap", float, lambda v: v > 0))
            put(as_in, pick("spec", "as", float, lambda v: v > 0))

            put(arith_sel, pick("implementation", "arithmetic", str, lambda v: v in ARITH_LABELS))
            put(scale_chk, pick("implementation", "section_scaling", boolean))
            put(auto_q, pick("implementation", "auto_q", boolean))
            put(frac_in, pick("implementation", "frac_bits", int, lambda v: 0 <= v <= 31))
            put(name_in, pick("implementation", "c_name", str))

            d = pick("view", "dark", boolean)
            if d is not None and d != dark.value:
                dark.value = d
                theme_btn.props(f'icon={"light_mode" if dark.value else "dark_mode"}')
            put(mag_scale, pick("view", "magnitude_scale", str, lambda v: v in ("db", "lin")))
            put(mag_xlog, pick("view", "frequency_axis", str, lambda v: v in ("lin", "log")))
            put(mag_mask, pick("view", "tolerance_scheme", boolean))
            put(mag_impl, pick("view", "implemented_response", boolean))
            put(phase_wrap, pick("view", "phase", str, lambda v: v in ("unwrap", "wrap")))
            put(gd_unit, pick("view", "group_delay_unit", str, lambda v: v in ("samples", "ms")))
            put(time_kind, pick("view", "time_response", str, lambda v: v in ("impulse", "step")))
            put(test_view, pick("view", "test_view", str, lambda v: v in ("out", "err", "freq", "dev")))

            put(test_impls, pick("test", "implementations", lambda v: [a for a in v if a in TEST_LABELS]))
            put(test_sig, pick("test", "signal", str, lambda v: v in ctest.SIGNALS))
            put(test_f1, pick("test", "f1", float, lambda v: v >= 0))
            put(test_f2, pick("test", "f2", float, lambda v: v >= 0))
            put(test_amp, pick("test", "amplitude", float, lambda v: 0 < v <= 1))
            put(test_n, pick("test", "samples", int, lambda v: 16 <= v <= 65536))
            put(test_cc, pick("test", "compiler", str, lambda v: bool(v.strip())))
            update_test_inputs()
            schedule()
        finally:
            state["loading"] = False
        return warnings

    def mark_dirty(*_) -> None:
        if state["loading"] or state["dirty"]:
            return
        state["dirty"] = True
        refresh_preset_label()

    def refresh_preset_label() -> None:
        if not presets.exists(state["preset"]):
            suffix = " • not saved in folder"
        elif state["dirty"]:
            suffix = " • modified"
        else:
            suffix = ""
        preset_state.text = state["preset"] + suffix

    def refresh_list() -> None:
        names = presets.list_presets()
        state["loading"] = True
        try:
            preset_sel.set_options(names, value=state["preset"] if state["preset"] in names else None)
        finally:
            state["loading"] = False

    def finish_load(name: str, warnings: list[str], dirty: bool = False) -> None:
        state["preset"] = name
        state["dirty"] = dirty
        refresh_list()
        refresh_preset_label()
        if warnings:
            ui.notify(f"{name} loaded with warnings: " + "; ".join(warnings), type="warning", multi_line=True)
        else:
            ui.notify(f"{name} loaded", type="positive")

    with ui.dialog() as confirm_dlg, ui.card():
        confirm_text = ui.label("")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: confirm_dlg.submit(False)).props("flat")
            ui.button("Discard changes", on_click=lambda: confirm_dlg.submit(True)).props("color=negative")

    async def confirm_discard() -> bool:
        if not state["dirty"]:
            return True
        confirm_text.text = f"The parameters of {state['preset']} have unsaved changes. Discard them?"
        return bool(await confirm_dlg)

    async def on_preset_selected(e) -> None:
        if state["loading"] or not e.value or e.value == state["preset"] and not state["dirty"]:
            return
        if not await confirm_discard():
            refresh_list()
            return
        try:
            data = presets.read(e.value)
        except presets.PresetError as ex:
            ui.notify(str(ex), type="negative")
            refresh_list()
            return
        finish_load(presets.sanitize(e.value), apply_params(data))

    def save() -> None:
        try:
            path = presets.write(state["preset"], collect_params())
        except (OSError, presets.PresetError) as ex:
            ui.notify(f"Save failed: {ex}", type="negative")
            return
        state["dirty"] = False
        refresh_list()
        refresh_preset_label()
        ui.notify(f"Saved {path}", type="positive")

    with ui.dialog() as save_dlg, ui.card().classes("w-96"):
        ui.label("Save parameter set as").classes("text-base font-semibold")
        save_name = ui.input("File name").props("dense autofocus").classes("w-full")
        save_hint = ui.label("").classes("text-xs opacity-70 break-all")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=save_dlg.close).props("flat")
            save_ok = ui.button("Save", icon="save")

    def update_save_hint(*_) -> None:
        try:
            name = presets.sanitize(save_name.value or "")
        except presets.PresetError:
            save_hint.text = "Enter a file name."
            save_ok.disable()
            return
        save_ok.enable()
        save_hint.text = (f"{presets.PRESET_DIR / name}"
                          + ("  —  exists and will be overwritten" if presets.exists(name) else ""))

    def do_save_as(*_) -> None:
        try:
            name = presets.sanitize(save_name.value or "")
            path = presets.write(name, collect_params())
        except (OSError, presets.PresetError) as ex:
            ui.notify(f"Save failed: {ex}", type="negative")
            return
        save_dlg.close()
        state["preset"] = name
        state["dirty"] = False
        refresh_list()
        refresh_preset_label()
        ui.notify(f"Saved {path}", type="positive")

    def open_save_as() -> None:
        save_name.set_value(state["preset"][:-5] if state["preset"].endswith(".json") else state["preset"])
        update_save_hint()
        save_dlg.open()

    with ui.dialog() as upload_dlg, ui.card().classes("w-96"):
        ui.label("Load parameter set from file").classes("text-base font-semibold")
        uploader = ui.upload(auto_upload=True, max_files=1).props('accept=".json" flat bordered').classes("w-full")
        ui.label("The file is loaded but not copied into the presets folder. Use Save to store it there."
                 ).classes("text-xs opacity-70")
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=upload_dlg.close).props("flat")

    async def on_upload(e) -> None:
        try:
            data = presets.check(await e.file.json())
            name = presets.sanitize(e.file.name)
        except (ValueError, presets.PresetError) as ex:
            ui.notify(f"{e.file.name}: {ex}", type="negative")
            return
        finally:
            uploader.reset()
        if not await confirm_discard():
            return
        upload_dlg.close()
        finish_load(name, apply_params(data), dirty=not presets.exists(name))

    preset_sel.tooltip(str(presets.PRESET_DIR))
    preset_sel.on_value_change(on_preset_selected)
    preset_refresh.on_click(lambda: (refresh_list(), refresh_preset_label()))
    save_btn.on_click(save)
    save_as_btn.on_click(open_save_as)
    save_name.on_value_change(update_save_hint)
    save_name.on("keydown.enter", do_save_as)
    save_ok.on_click(do_save_as)
    load_file_btn.on_click(upload_dlg.open)
    uploader.on_upload(on_upload)
    for w in (test_impls, test_sig, test_f1, test_f2, test_amp, test_n, test_cc, test_view):
        w.on_value_change(mark_dirty)

    # ------------------------------------------------------------------ start: load default.json
    load_edges()
    default_test_freqs()
    update_test_inputs()
    if presets.exists(presets.DEFAULT_NAME):
        try:
            warnings = apply_params(presets.read(presets.DEFAULT_NAME))
            if warnings:
                ui.notify("default.json: " + "; ".join(warnings), type="warning", multi_line=True)
        except presets.PresetError as ex:
            ui.notify(f"default.json not loaded: {ex}", type="negative")
    else:
        try:
            presets.write(presets.DEFAULT_NAME, collect_params())
        except OSError as ex:
            ui.notify(f"Cannot create default.json: {ex}", type="warning")
    state["dirty"] = False
    refresh_list()
    refresh_preset_label()
    if state["timer"] is not None:
        state["timer"].cancel()
        state["timer"] = None
    update()


def main() -> None:
    ap = argparse.ArgumentParser(description="FilterDesign GUI")
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to allow access from other machines")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--light", action="store_true", help="start in light mode (default: dark)")
    ap.add_argument("--presets", metavar="DIR", help=f"folder of the JSON parameter sets (default: {presets.PRESET_DIR})")
    args = ap.parse_args()
    if args.presets:
        presets.set_directory(args.presets)
    global START_DARK
    START_DARK = not args.light
    ui.run(title="FilterDesign", host=args.host, port=args.port, show=not args.no_browser, reload=False, favicon="〰️")


if __name__ in {"__main__", "__mp_main__"}:
    main()
