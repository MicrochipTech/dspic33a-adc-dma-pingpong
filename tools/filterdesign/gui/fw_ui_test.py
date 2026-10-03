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

"""fw_ui_test.py - headless-browser test of the FilterDesign GUI's dsPIC33 tab.

    python tools/filterdesign/gui/fw_ui_test.py            install, build, dsPIC33 GUI (fake)
    python tools/filterdesign/gui/fw_ui_test.py --flash    also "3 Flash" - PROGRAMS a connected
                                                           EV74H48A; without one it checks the
                                                           "programmer not found" path

The way a user goes, in the browser: the tab opens with its checks, "1 Install
into firmware" writes src/core/user_filter.h/.json (the installed label then says
"this design"), "2 Build" runs tools\\build.bat (the steps line then shows
"built"), and "4 Open dsPIC33 GUI" with "fake target" starts tools/adc_gui.py,
whose signal processing card must show the filter 'user' with the description
user_filter.json carries, and whose "noise test" (white noise from the signal
generator, with and without the filter) must draw the measured response close
to the design. No server-side exception in either GUI.

src/core/user_filter.h/.json are put back afterwards (the checked-in default);
build\\adc_dma_40msps.hex keeps the test's filter until the next build.
Needs playwright and Chrome, like tools/gui_ui_test.py.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import firmware  # noqa: E402


def free_port():
    with socket.socket() as so:
        so.bind(("127.0.0.1", 0))
        return so.getsockname()[1]


def pids_listening(port):
    """PIDs listening on a TCP port (netstat -ano), to stop the dsPIC33 GUI the tab started."""
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    return {int(m.group(1)) for m in re.finditer(rf":{port}\s+\S+\s+LISTENING\s+(\d+)", out)}


results = []


def check(name, ok, detail=""):
    results.append(ok)
    print((("PASS " if ok else "FAIL ") + name + ("  - " + detail if detail else "")).encode("ascii", "replace").decode())


def wait_for(fn, timeout):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        try:
            ok, last = fn()
            if ok:
                return True, last
        except Exception as e:                       # element not there yet
            last = str(e)
        time.sleep(0.5)
    return False, last


def server_errors(out):
    return [ln for ln in out.splitlines() if re.search(r"Traceback|exception", ln, re.I)
            and "10054" not in ln]


def main():
    flash = "--flash" in sys.argv
    backup = tempfile.mkdtemp(prefix="fw_ui_backup_")
    for f in (firmware.HEADER, firmware.INFO):
        shutil.copy(f, backup)
    presets_dir = tempfile.mkdtemp(prefix="fw_ui_presets_")
    port, gui_port = free_port(), free_port()
    log_path = os.path.join(tempfile.gettempdir(), "fw_ui_test_server.log")
    log = open(log_path, "w")
    app = subprocess.Popen([sys.executable, os.path.join(HERE, "app.py"), "--no-browser", "--port", str(port),
                            "--presets", presets_dir], stdout=log, stderr=subprocess.STDOUT, cwd=HERE)
    shot = os.path.join(tempfile.gettempdir(), "fw_ui_tab.png")
    try:
        time.sleep(8)
        with sync_playwright() as p:
            b = p.chromium.launch(channel="chrome", headless=True)
            page = b.new_page(viewport={"width": 1500, "height": 1300})
            page.goto(f"http://127.0.0.1:{port}/?tab=dspic33")
            ok, txt = wait_for(lambda: (page.get_by_text(re.compile(r"^Sample rate .* ksps")).count() > 0,
                                        ""), 30)
            check("tab opens with its checks", ok)

            page.get_by_role("button", name=re.compile("Install into firmware")).click()
            ok, txt = wait_for(lambda: (lambda t: ("this design" in t and "not this" not in t, t))(
                page.get_by_text(re.compile(r"id [0-9A-F]{8} - ")).first.inner_text()), 20)
            info = firmware.installed_info() or {}
            check("1 install: user_filter.h/.json written, label says 'this design'",
                  ok and firmware.header_id() == info.get("id"), f"{txt!r}, header id {firmware.header_id()}")

            page.get_by_role("button", name=re.compile(r"^\W*2\s+Build")).click()
            ok, txt = wait_for(lambda: (lambda t: ("Build EV74H48A - running" in t, t))(
                page.locator(".nicegui-code").last.inner_text()), 5)
            check("2 build: its output shows live while it runs (within 5 s)", ok, repr((txt or "")[:90]))
            ok, txt = wait_for(lambda: (lambda t: ("✔ built" in t, t))(
                page.get_by_text(re.compile(r"installed .*built")).first.inner_text()), 240)
            check("2 build: tools\\build.bat, steps line shows 'built'",
                  ok and firmware.hex_is_current("EV74H48A"), repr(txt))

            if flash:
                page.get_by_role("button", name=re.compile(r"^\W*3\s+Flash")).click()
                ok, txt = wait_for(lambda: (lambda t: ("=== Flash" in t, t))(
                    page.locator(".nicegui-code").last.inner_text()), 180)
                flashed = "OK after" in (txt or "").split("=== Flash", 1)[-1][:40]
                no_tool = "programmer not found" in (txt or "")
                check("3 flash: programmed, or 'programmer not found' without a board",
                      ok and (flashed or no_tool), "flashed" if flashed else "no programmer" if no_tool else txt[:200])

            page.get_by_text("fake target (no board)").click()
            page.get_by_label("HTTP port").fill(str(gui_port))
            page.get_by_role("button", name=re.compile("Open dsPIC33 GUI")).click()
            page.screenshot(path=shot, full_page=True)
            time.sleep(12)                            # the dsPIC33 GUI starts and connects to the fake
            g = b.new_page(viewport={"width": 1600, "height": 3000})
            g.goto(f"http://127.0.0.1:{gui_port}/")
            want = info.get("description", "?")
            card = g.locator(".tile", has=g.locator(".card-title", has_text="signal processing"))
            ok, txt = wait_for(lambda: (lambda t: (want in t and "user filter (tools/filterdesign" in t, t))(
                card.inner_text()), 40)
            check("4 dsPIC33 GUI (fake): filter 'user' selected, the board's description in its card",
                  ok, repr((txt or "")[:160]))
            fs_k = info["spec"]["fs"] / 1e3
            g.get_by_role("button", name="use its rate").click()
            ok, txt = wait_for(lambda: (lambda v: (abs(float(v) - fs_k) < 1e-6, v))(
                g.get_by_label(re.compile(r"^rate, kSPS")).input_value()), 10)
            check("4 'use its rate': the rate field takes the filter's design rate", ok, f"{txt} kSPS")
            g.get_by_role("button", name=re.compile(r"^\W*single$", re.I)).click()
            ok, txt = wait_for(lambda: (lambda t: ("user filter in the firmware" in t, t))(
                g.get_by_text(re.compile(r"^source:")).first.inner_text()), 30)
            check("4 single grab: processed by the user filter", ok, repr((txt or "")[:120]))
            # the noise test (03.10.2026): reference, filtered, the measured response
            g.get_by_role("button", name="noise test").click()
            resp = g.locator(".tile", has=g.locator(".card-title", has_text="filter response"))
            ok, txt = wait_for(lambda: (lambda t: ("median" in t, t))(
                resp.inner_text()), 150)
            m = re.search(r"passes \(> -3 dB\): median ([0-9.]+) dB", txt or "")
            check("5 noise test: the response card shows measured against design, median deviation < 1.5 dB",
                  ok and m is not None and float(m.group(1)) < 1.5, repr((txt or "")[:220]))
            g.screenshot(path=os.path.join(tempfile.gettempdir(), "fw_ui_adc_gui.png"), full_page=True)
            b.close()
    finally:
        for pid in pids_listening(gui_port):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        app.terminate()
        app.wait(10)
        log.close()
        for f in (firmware.HEADER, firmware.INFO):
            shutil.copy(os.path.join(backup, f.name), f)
        shutil.rmtree(backup, ignore_errors=True)
        shutil.rmtree(presets_dir, ignore_errors=True)
    errs = server_errors(open(log_path, errors="replace").read())
    check("no server-side exceptions (FilterDesign GUI)", not errs, "; ".join(errs[:3]))
    print(f"screenshot: {shot}")
    print("FW UI TEST " + ("PASS" if all(results) else "FAIL"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
