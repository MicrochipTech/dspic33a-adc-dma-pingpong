"""Screenshots for docs/GUI-MANUAL.md: one picture per card of both GUI tools,
with numbered markers on the controls the manual explains.

    python docs/gen_gui_screenshots.py            all pictures into docs/gui/
    python docs/gen_gui_screenshots.py --only adc  just the dsPIC33 GUI (or: fd)

Starts tools/adc_gui.py --fake (no board) and tools/filterdesign/gui/app.py on
spare ports, drives them with a headless Chrome (playwright, channel="chrome",
as tools/gui_ui_test.py) and cuts each card out of the page. The numbers in a
picture are the order of its MARKS entry below; the manual's legend under the
picture follows the same order - change both together.

Nothing is written outside docs/gui/: the dsPIC33 GUI gets a throw-away
settings file, FilterDesign is only looked at (no Save, no Install).
Needs: playwright, Pillow, and what the two GUIs need (system python).
"""
import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "gui")
SCALE = 1.5                     # device pixels per CSS pixel
PAD = 16                        # CSS px around a card (room for the markers)
BADGE = "#facc15"               # marker colour (amber, readable on dark and light)

try:
    FONT = ImageFont.truetype("arialbd.ttf", int(13 * SCALE))
except OSError:
    FONT = ImageFont.load_default()

missing = []


# ---------------------------------------------------------------- helpers
def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_port(port, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"server on port {port} did not come up")


KIND = {
    "field": ".q-field",
    "btn": ".q-btn",
    "cb": ".q-checkbox",
    "toggle": ".q-toggle",
    "chip": ".q-chip",
    "chart": ".nicegui-echart",
    "tab": ".q-tab",
    "table": "table",
}


def locate(scope, kind, text):
    """One element of `kind` inside `scope` whose text matches `text`
    (a regex; None = the first of that kind). kind "text" = a plain label."""
    if kind == "text":
        return scope.get_by_text(re.compile(text)).first
    loc = scope.locator(KIND[kind])
    if text is not None:
        loc = loc.filter(has_text=re.compile(text))
    return loc.first


def card(page, title):
    return page.locator(".q-card").filter(
        has=page.locator(".card-title", has_text=re.compile("^" + re.escape(title)))).first


def shot(page, region, marks, name, extra=None):
    """Cut `region` out of the page into docs/gui/<name>.png and put a numbered
    marker on each of `marks` [(kind, text), ...]. `extra` widens the cut to
    the union with further locators."""
    region.scroll_into_view_if_needed()
    page.mouse.move(1, 1)               # no tooltip from the last click
    time.sleep(0.4)
    page.evaluate("document.querySelectorAll('.q-notification, .q-tooltip').forEach(e => e.remove())")
    time.sleep(0.2)
    boxes = [region.bounding_box()] + [e.bounding_box() for e in (extra or [])]
    x0 = min(b["x"] for b in boxes) - PAD
    y0 = min(b["y"] for b in boxes) - PAD
    x1 = max(b["x"] + b["width"] for b in boxes) + PAD
    y1 = max(b["y"] + b["height"] for b in boxes) + PAD
    scroll = page.evaluate("[window.scrollX, window.scrollY]")
    x0 = max(x0, -scroll[0])            # the page cannot be cut left of / above its edge
    y0 = max(y0, -scroll[1])
    clip = {"x": x0 + scroll[0], "y": y0 + scroll[1], "width": x1 - x0, "height": y1 - y0}
    path = os.path.join(OUT, name + ".png")
    page.screenshot(path=path, clip=clip, full_page=True)

    img = Image.open(path).convert("RGB")
    d = ImageDraw.Draw(img)
    placed = []
    for n, (kind, text) in enumerate(marks, 1):
        el = locate(region if kind != "page" else page, kind if kind != "page" else "text", text)
        try:
            b = el.bounding_box(timeout=2000)
        except Exception:
            b = None
        if not b or b["width"] == 0:
            missing.append(f"{name} #{n}: {kind} {text!r}")
            continue
        bx0 = (b["x"] - x0) * SCALE
        by0 = (b["y"] - y0) * SCALE
        bx1 = bx0 + b["width"] * SCALE
        by1 = by0 + b["height"] * SCALE
        d.rounded_rectangle([bx0 - 2, by0 - 2, bx1 + 2, by1 + 2], radius=6,
                            outline=BADGE, width=max(2, int(2 * SCALE)))
        r = 9 * SCALE
        # left of the element, on its top edge: covers no label text
        cx, cy = bx0 - r - 3, by0 + r - 2
        if cx < r + 1:
            cx = r + 1
        for px, py in placed:               # keep two badges from covering each other
            if abs(px - cx) < 2 * r and abs(py - cy) < 2 * r:
                cx = px + 2 * r + 2
        placed.append((cx, cy))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BADGE, outline="#000000", width=2)
        d.text((cx, cy), str(n), fill="#000000", font=FONT, anchor="mm")
    img = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    img.save(path, optimize=True)
    print(f"  {name}.png  {img.size[0]}x{img.size[1]}  {len(marks)} marks")


def q_select(page, field, option):
    """Choose `option` (regex) in a Quasar select."""
    field.click()
    time.sleep(0.4)
    page.locator(".q-menu .q-item").filter(has_text=re.compile(option)).first.click()
    time.sleep(0.6)


def wait_text(loc, pattern, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if re.search(pattern, loc.inner_text(timeout=1000)):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


# ---------------------------------------------------------------- dsPIC33 GUI
def adc_gui(p):
    port = free_port()
    tmp = tempfile.mkdtemp()
    settings = os.path.join(tmp, "adc_gui_settings.json")
    shutil.copy(os.path.join(ROOT, "tools", "adc_gui_defaults.json"), settings)
    srv = subprocess.Popen([sys.executable, "adc_gui.py", "--fake", "--no-browser",
                            "--http-port", str(port), "--settings", settings],
                           cwd=os.path.join(ROOT, "tools"),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_port(port)
        b = p.chromium.launch(channel="chrome", headless=True, args=["--lang=en-US"])
        page = b.new_page(viewport={"width": 1500, "height": 1000}, device_scale_factor=SCALE, locale="en-US")
        page.goto(f"http://127.0.0.1:{port}/")
        conn = page.locator(".q-chip").filter(has_text="adc_dma_40msps").first
        wait_text(conn, ".", 20)
        # the throw-away settings path would show in the settings card
        page.evaluate("""() => { for (const e of document.querySelectorAll('.mono'))
            if (e.textContent.includes('adc_gui_settings.json'))
                e.textContent = 'tools/adc_gui_settings.json'; }""")
        cyc = page.locator("div.text-slate-300.mono").first

        def single(n=1):
            for _ in range(n):
                before = cyc.inner_text()
                page.get_by_role("button", name=re.compile(r"^\W*single$")).click()
                t0 = time.time()
                while cyc.inner_text() == before and time.time() - t0 < 20:
                    time.sleep(0.3)
                time.sleep(0.8)

        print("dsPIC33 GUI: test input")
        single()
        page.evaluate("window.scrollTo(0, 0)")
        shot(page, page.locator(".q-header"), [
            ("btn", "documentation"), ("cb", "tooltips"), ("field", "port"),
            ("btn", "connect"), ("chip", "adc_dma")], "adc_header")
        sc = card(page, "settings file")
        shot(page, sc, [("text", r"adc_gui_settings\.json"), ("btn", "save$"),
                        ("btn", "save as"), ("btn", "standard"), ("field", "setup")], "adc_settings")
        chip_row = cyc.locator("xpath=following-sibling::div[1]")
        shot(page, chip_row, [
            ("page", r"^grab \d"), ("chip", "overrun"), ("chip", "late"), ("chip", "missed"),
            ("chip", "actual rate"), ("chip", "halves"), ("chip", "CPU load"),
            ("chip", "trigger|trig @|no trigger"), ("chip", "loop")], "adc_chips",
            extra=[cyc])
        tri = card(page, "triangle verdict")
        shot(page, tri, [("chip", "PASS|FAIL"), ("chip", "turning points"), ("chip", "^up"),
                         ("chip", "^down"), ("chip", "slip"), ("chip", "slope/model")],
             "adc_verdict")
        ts = card(page, "time signal")
        shot(page, ts, [("field", "reference voltage"), ("text", "^source:"), ("chart", None)],
             "adc_time_triangle")
        shot(page, card(page, "buffer"), [("field", "buffer size"), ("btn", "apply"),
                                          ("text", "^buf")], "adc_buffer")
        shot(page, card(page, "dac2"), [("field", "^dac2"), ("field", "low"), ("field", "high"),
                                        ("field", "SLPDAT"), ("cb", "force"),
                                        ("text", "period|invalid"), ("btn", "apply dac2")], "adc_dac2")
        pin =card(page, "chip · pinout")
        shot(page, pin, [("field", "eval kit"), ("field", "^core"), ("field", "channel"),
                         ("field", "signal source")], "adc_pinout")
        shot(page, card(page, "board · where"), [], "adc_board")
        shot(page, card(page, "console"), [], "adc_console")

        print("dsPIC33 GUI: custom input, trigger")
        acq = card(page, "acquisition")
        q_select(page, locate(acq, "field", "^input"), "custom input")
        acq.locator(".q-checkbox").filter(has_text=re.compile("^trigger")).first.click()
        time.sleep(0.5)
        single(2)
        shot(page, acq, [("field", "rate, kSPS"), ("text", "guidance|board ran clean"),
                         ("field", "^input"), ("field", "^core"), ("field", "PINSEL"),
                         ("field", "SAMC"), ("field", "grab interval"), ("cb", "^trigger"),
                         ("field", "^level"), ("field", "^edge"), ("field", "hysteresis"),
                         ("btn", "single"), ("btn", "live")], "adc_acquisition")
        shot(page, ts, [("chart", None)], "adc_time_trigger")
        # the custom input switched the stand-in to its sine: now the card shows its fields
        shot(page, card(page, "fake target signal"), [("field", "signal"), ("field", "frequency"),
                                                      ("field", "amplitude"), ("field", "noise"),
                                                      ("field", "2nd"), ("field", "3rd")], "adc_fake")
        sp = card(page, "spectrum")
        shot(page, sp, [("cb", "average"), ("field", "grabs"), ("chart", None)], "adc_spectrum")
        shot(page, card(page, "signal evaluation"), [
            ("chip", "fundamental"), ("chip", "level"), ("chip", "noise floor"), ("chip", "SNR"),
            ("chip", "THD"), ("chip", "H2")], "adc_evaluation")

        print("dsPIC33 GUI: signal generator loop")
        sg = card(page, "signal generator")
        sg.get_by_role("button", name=re.compile("loop preset")).click()
        time.sleep(3.0)
        single(2)
        shot(page, sg, [("field", "^generator"), ("field", "^output"), ("field", "^n, table"),
                        ("field", "play rate"), ("field", "^f0"), ("field", "^noise"),
                        ("field", "^h2"), ("field", "decay"), ("field", "^amp"),
                        ("field", "^lo"), ("field", "^hi"), ("cb", "snap"), ("cb", "force"),
                        ("btn", "loop preset"), ("btn", "flat noise"), ("btn", "apply$"),
                        ("text", "^on:|^off|not connected"), ("chart", None)], "adc_siggen")
        shot(page, ts, [("chart", None)], "adc_time_loop",
             extra=[page.locator(".q-chip").filter(has_text=re.compile("^loop")).first])

        print("dsPIC33 GUI: user filter, noise test")
        spc = card(page, "signal processing")
        q_select(page, locate(spc, "field", "filter \\(in"), "user filter")
        spc.locator(".q-checkbox").filter(has_text=re.compile("Goertzel")).first.click()
        time.sleep(1.0)
        single()
        shot(page, spc, [("toggle", "filter on"), ("field", "filter \\(in"), ("cb", "Goertzel"),
                         ("field", "threshold"), ("text", "designed for|kSPS"),
                         ("btn", "use its rate"), ("btn", "noise test"), ("chip", "fs/16")],
             "adc_sigproc")
        nt = spc.get_by_role("button", name=re.compile("noise test"))
        nt.click()
        resp = card(page, "filter response")
        t0 = time.time()
        while time.time() - t0 < 900 and not wait_text(resp, r"grabs, |incomplete", 30):
            print("   ", resp.inner_text().splitlines()[-1][:70])
        time.sleep(1.5)
        shot(page, resp, [("text", r"grabs, |incomplete"), ("chart", None)],
             "adc_noise_test")
        b.close()
    finally:
        srv.terminate()
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- FilterDesign
def filterdesign(p):
    port = free_port()
    srv = subprocess.Popen([sys.executable, "app.py", "--no-browser", "--port", str(port)],
                           cwd=os.path.join(ROOT, "tools", "filterdesign", "gui"),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_port(port)
        b = p.chromium.launch(channel="chrome", headless=True, args=["--lang=en-US"])
        page = b.new_page(viewport={"width": 1500, "height": 1100}, device_scale_factor=SCALE, locale="en-US")
        page.goto(f"http://127.0.0.1:{port}/")
        chip = page.locator(".q-header .q-chip, .q-header .q-badge").first
        time.sleep(6)
        page.evaluate("window.scrollTo(0, 0)")
        print("FilterDesign: default design")

        def fd_card(text):
            return page.locator(".q-card").filter(has_text=re.compile(text)).first

        shot(page, page.locator(".q-header"), [("btn", None), ("text", "specification|design failed|check")],
             "fd_header")
        shot(page, fd_card("^Parameter set"), [("text", r"\.json"), ("field", "Load from presets"),
                                               ("btn", "Save$"), ("btn", "Save as"),
                                               ("btn", "Load file")], "fd_paramset")
        shot(page, fd_card("^Specification"), [("field", "Filter type"), ("field", "Characteristic"),
                                               ("field", "Sampling rate"), ("field", "edge"),
                                               ("field", "Passband ripple"),
                                               ("field", "Stopband atten")], "fd_spec")
        shot(page, fd_card("^Implementation"), [("field", "Arithmetic"), ("cb", "Section scaling"),
                                                ("field", "Output gain"), ("cb", "Auto Q"),
                                                ("field", "Fractional bits"), ("field", "C name")],
             "fd_impl")
        shot(page, fd_card("Max. pole radius"), [("text", "^Order"), ("text", "^Passband atten"),
                                                 ("text", "^Stopband atten"),
                                                 ("text", "Coefficient format"),
                                                 ("text", "Impl. passband")], "fd_summary")
        tabs = page.locator(".q-tab-panels").first

        def tab(name, marks, out, wait=1.5):
            page.locator(".q-tab").filter(has_text=re.compile("^" + re.escape(name))).first.click()
            time.sleep(wait)
            shot(page, tabs, marks, out, extra=[page.locator(".q-tabs").first])

        tab("Magnitude", [("btn", "^dB$"), ("btn", "log f"),
                          ("cb", "Tolerance"), ("cb", "Implemented"), ("chart", None)],
            "fd_tab_magnitude")
        tab("Pole / zero", [("chart", None), ("text", "^Poles")], "fd_tab_polezero")
        tab("Sections", [("text", "headroom|Q[0-9]"), ("table", None)], "fd_tab_sections")
        tab("C code", [("btn", "Download .h"), ("btn", "Download .[cs]")], "fd_tab_ccode")
        page.locator(".q-tab").filter(has_text="C test").first.click()
        time.sleep(1)
        page.locator("button:visible", has_text="Compile").first.click()
        t0 = time.time()
        while time.time() - t0 < 180 and not page.get_by_text(re.compile("^Results for")).count():
            time.sleep(1)
        time.sleep(2)
        tab("C test", [("field", "Implementations"), ("field", "^Signal"),
                       ("field", "Amplitude"), ("field", "Samples"), ("field", "C compiler"),
                       ("btn", "Compile"), ("btn", "Test bench"), ("text", "^Results for"),
                       ("text", "^Implementation$"), ("btn", "^output$")], "fd_tab_ctest", wait=0.5)

        print("FilterDesign: dsPIC33 tab with the firmware's default preset")
        q_select(page, locate(fd_card("^Parameter set"), "field", "Load from presets"),
                 "dspic33_default_lowpass_200k")
        dlg = page.get_by_role("button", name=re.compile("Discard"))
        if dlg.count():
            dlg.first.click()
        time.sleep(3)
        tab("dsPIC33", [("text", "^Sample rate"), ("text", "^CPU budget"),
                        ("text", "Installed in the firmware"), ("field", "Board"),
                        ("text", "installed .* built"), ("btn", "Install"), ("btn", "Build"),
                        ("btn", "Flash"), ("btn", "in one go"), ("btn", "Open dsPIC33"),
                        ("field", "COM port"), ("field", "HTTP port"), ("cb", "fake target")],
            "fd_tab_dspic33")
        b.close()
    finally:
        srv.terminate()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["adc", "fd"])
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        if a.only in (None, "adc"):
            adc_gui(p)
        if a.only in (None, "fd"):
            filterdesign(p)
    if missing:
        print("markers not found:")
        for m in missing:
            print("  " + m)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
