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

"""firmware.py - the way from a designed filter to the dsPIC33 board.

The FilterDesign GUI's "dsPIC33" tab calls these, in this order:

  install()     writes src/core/user_filter.h and user_filter.json (codegen.generate_firmware())
  build()       tools\\build.bat [nano] -> build\\adc_dma_40msps[_nano].hex
  flash()       EV74H48A: MPLAB IPE's ipecmd through the board's PKOB4;
                EV17P63A: copies the .hex onto the Curiosity Nano's USB drive (nEDBG)
  start_adc_gui()   tools/adc_gui.py, the dsPIC33 GUI, where "sigproc user" runs it

Also usable without the GUI, e.g. to regenerate the checked-in default filter:

  python firmware.py --default        the default filter into src/core (no build)
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]                       # tools/filterdesign/gui -> repository root
TOOLS = REPO / "tools"
CORE = REPO / "src" / "core"
HEADER = CORE / "user_filter.h"
INFO = CORE / "user_filter.json"

# The two board profiles of the repository (src/app/board.h, tools/build.bat)
BOARDS = {
    "EV74H48A": {"label": "EV74H48A Curiosity Platform (dsPIC33AK512MPS512, PKOB4)",
                 "build_arg": None, "hex": REPO / "build" / "adc_dma_40msps.hex",
                 "device": "33AK512MPS512"},
    "EV17P63A": {"label": "EV17P63A Curiosity Nano (dsPIC33AK512MPS506, nEDBG)",
                 "build_arg": "nano", "hex": REPO / "build" / "adc_dma_40msps_nano.hex",
                 "device": "33AK512MPS506"},
}
CPU_HZ = 200e6                               # the CPU clock sigproc.h budgets with

# The default filter checked in as src/core/user_filter.h: a low-pass for the
# signal generator's harmonics (siggen f0 = 10 kHz, h2..h7 above 20 kHz)
DEFAULT_SPEC = {"type": "lowpass", "characteristic": "elliptic", "fs": 200000.0,
                "fpass": [15000.0, 0.0], "fstop": [25000.0, 0.0], "ap": 0.5, "as_": 60.0}
DEFAULT_ARITH = "float"


def installed_info() -> dict | None:
    """user_filter.json as installed, or None."""
    try:
        return json.loads(INFO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def install(d, arithmetic: str, sos, fixed) -> dict:
    """Writes the filter into the firmware's sources; returns the JSON written."""
    import codegen                           # here: firmware.py --default runs without the GUI
    text, info = codegen.generate_firmware(d, arithmetic, sos, fixed)
    HEADER.write_text(text, encoding="ascii", newline="\n")
    INFO.write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8", newline="\n")
    return info


def preview_id(d, arithmetic: str, sos, fixed) -> str:
    """The id install() would write - to tell whether the installed filter is this one."""
    import codegen
    return codegen.generate_firmware(d, arithmetic, sos, fixed)[1]["id"]


def header_id() -> str | None:
    """USER_FILTER_ID as it stands in src/core/user_filter.h."""
    try:
        m = re.search(r"#define USER_FILTER_ID\s+0x([0-9A-Fa-f]{8})u", HEADER.read_text(encoding="ascii"))
    except OSError:
        return None
    return m.group(1).upper() if m else None


def hex_is_current(board: str) -> bool:
    """True when the board's .hex was built after user_filter.h was written."""
    h = BOARDS[board]["hex"]
    try:
        return h.stat().st_mtime >= HEADER.stat().st_mtime
    except OSError:
        return False


# ------------------------------------------------------------------ processes
@dataclass
class Result:
    ok: bool
    log: str
    seconds: float


def _kill_tree(pid: int) -> None:
    """ipecmd.exe -> cmd -> ipecmd.bat -> java: killing ipecmd.exe alone leaves the java
    running, and it keeps the PKOB4 (03.10.2026) - the whole tree goes."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def _run(cmd: list[str], cwd: Path, timeout: float, on_line=None) -> Result:
    """Runs cmd with no stdin (a tool that asks would otherwise wait for ever), the
    whole process tree killed on a timeout. on_line(text) gets every output line the
    moment it comes (from a reader thread): the GUI shows a running build or flash
    live - with the output only at the end, a slow run looked like a hung one, and a
    flash stopped half-way for that reason wedged the PKOB4 (03.10.2026)."""
    t0 = time.monotonic()
    try:
        p = subprocess.Popen(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    except OSError as e:
        return Result(False, f"cannot start {cmd[0]}: {e}", time.monotonic() - t0)
    lines: list[str] = []

    def reader():
        for ln in p.stdout:
            ln = ln.rstrip("\r\n")
            lines.append(ln)
            if on_line:
                on_line(ln)

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    try:
        p.wait(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_tree(p.pid)
        p.wait()
        timed_out = True
    th.join(5)
    tail = (f"[timeout after {timeout:.0f} s - stopped]" if timed_out else f"[exit code {p.returncode}]")
    if on_line:
        on_line(tail)
    return Result(not timed_out and p.returncode == 0, "\n".join(lines + ["", tail]), time.monotonic() - t0)


def mplab_ide_running() -> bool:
    """MPLAB X IDE open (mplab_ide64.exe): it may hold the PKOB4, and ipecmd then fails."""
    if sys.platform != "win32":
        return False
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mplab_ide64.exe", "/NH"], capture_output=True, text=True)
    return "mplab_ide64.exe" in r.stdout.lower()


def build(board: str, on_line=None) -> Result:
    """tools\\build.bat [nano] (xc-dsc, -Wall -Wextra). OK only if it returns 0 AND
    the .hex is newer than user_filter.h - build.bat's own exit code is not trusted alone."""
    if sys.platform != "win32":
        return Result(False, "build.bat needs Windows (tools/Makefile is the other way)", 0.0)
    # full path: with NoDefaultCurrentDirectoryInExePath set, cmd does not look in the cwd
    cmd = ["cmd", "/c", str(TOOLS / "build.bat")] + ([BOARDS[board]["build_arg"]] if BOARDS[board]["build_arg"] else [])
    r = _run(cmd, TOOLS, timeout=600, on_line=on_line)
    warnings = [ln for ln in r.log.splitlines() if "warning:" in ln]
    errors = [ln for ln in r.log.splitlines() if "error" in ln.lower() and "0 error" not in ln.lower()]
    ok = r.ok and hex_is_current(board) and not errors
    if warnings:
        r.log += f"\n[{len(warnings)} warning(s) - the repository's builds are -Wall -Wextra clean]"
    return Result(ok, r.log, r.seconds)


def find_ipecmd() -> str | None:
    """MPLAB IPE's command line programmer, newest MPLAB X first ($IPECMD wins)."""
    if os.environ.get("IPECMD"):
        return os.environ["IPECMD"]
    hits = glob.glob(r"C:\Program Files\Microchip\MPLABX\v*\mplab_platform\mplab_ipe\ipecmd.exe")
    hits.sort(key=lambda p: [int(x) for x in re.findall(r"\d+", Path(p).parents[2].name)] or [0])
    return hits[-1] if hits else None


def find_nano_drive() -> str | None:
    """The Curiosity Nano's mass-storage drive (nEDBG): the root holding KIT-INFO.TXT."""
    if sys.platform != "win32":
        return None
    for letter in string.ascii_uppercase[3:]:
        root = f"{letter}:\\"
        try:
            if os.path.isfile(os.path.join(root, "KIT-INFO.TXT")):
                return root
        except OSError:
            continue
    return None


def flash(board: str, on_line=None) -> Result:
    """Programs the board's .hex.

    EV74H48A: ipecmd -TPPKOB4 -P33AK512MPS512 -M -F<hex> -OL - program all memory,
    release from reset (the command the repository's remote bench uses; ~20-30 s,
    almost all of it ipecmd's own start and connect). Exit code 9 = no programmer.
    EV17P63A: the Curiosity Nano programs a .hex copied onto its USB drive.
    """
    hexfile = BOARDS[board]["hex"]
    if not hexfile.is_file():
        return Result(False, f"{hexfile} does not exist - build first", 0.0)
    if board == "EV17P63A":
        drive = find_nano_drive()
        if not drive:
            return Result(False, "no Curiosity Nano drive found (a drive with KIT-INFO.TXT) - "
                                 "is the board plugged in?", 0.0)
        t0 = time.monotonic()
        try:
            shutil.copyfile(hexfile, os.path.join(drive, hexfile.name))
        except OSError as e:
            return Result(False, f"copy to {drive} failed: {e}", time.monotonic() - t0)
        time.sleep(3.0)                      # the nEDBG programs after the copy completes
        status = ""
        try:
            status = Path(drive, "STATUS.TXT").read_text(errors="replace")
        except OSError:
            pass
        ok = "fail" not in status.lower()
        return Result(ok, f"copied {hexfile.name} to {drive}\n{status}".rstrip(), time.monotonic() - t0)
    ipe = find_ipecmd()
    if not ipe:
        return Result(False, "ipecmd.exe not found (MPLAB X ...\\mplab_platform\\mplab_ipe) - set IPECMD", 0.0)
    work = Path(tempfile.mkdtemp(prefix="ipecmd_"))    # ipecmd writes its log files into the cwd
    r = _run([ipe, "-TPPKOB4", f"-P{BOARDS[board]['device']}", "-M", f"-F{hexfile}", "-OL"],
             work, timeout=240, on_line=on_line)   # a run killed while programming wedged the PKOB4 (03.10.2026): generous
    shutil.rmtree(work, ignore_errors=True)
    # ipecmd's exit code is not enough: "Connection Failed" / "Programming Target Failed"
    # have been seen with an exit code of 0 (03.10.2026)
    if re.search(r"Failed|failed \(err", r.log):
        r.ok = False
    if "exit code 9" in r.log:
        r.log += "\n-> programmer not found: is the board's PKOB4 USB port connected?"
    elif not r.ok:
        hint = ["\n-> the PKOB4 did not answer or is held by another program."]
        if mplab_ide_running():
            hint.append("MPLAB X IDE is running: if it has this board's tool (an open project with "
                        "the PKOB4, a debug session), close the project or MPLAB X, then flash again.")
        hint.append("Otherwise unplug the board's USB cable, plug it in again and retry.")
        r.log += " ".join(hint)
    return r


def start_adc_gui(http_port: int = 8080, com_port: str | None = None, fake: bool = False) -> subprocess.Popen:
    """Starts the dsPIC33 GUI (tools/adc_gui.py) with this Python, in its own process.
    --sigproc user selects the filter there once it is connected."""
    cmd = [sys.executable, str(TOOLS / "adc_gui.py"), "--http-port", str(http_port), "--sigproc", "user"]
    if fake:
        cmd.append("--fake")
    elif com_port:
        cmd += ["--port", com_port]
    flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    return subprocess.Popen(cmd, cwd=str(TOOLS), creationflags=flags)


def default_design():
    """(design, sos, fixed) of DEFAULT_SPEC, as the GUI computes them."""
    import fdcore
    d = fdcore.design(fdcore.Spec(**DEFAULT_SPEC))
    sos, fixed, _ = fdcore.implement(d.sos, d.spec.fs, DEFAULT_ARITH, True, None)
    return d, sos, fixed


def write_fixtures(out_dir: Path) -> list[str]:
    """tests/host/user_filter's fixtures (test_user_filter_xcheck.py): the firmware
    example's elliptic band-pass - narrow, so the fixed-point rounding shows - in each
    arithmetic, user_filter.h and .json per folder, without a time stamp (they are
    checked in; test_codegen.py compares them with a fresh run)."""
    import codegen
    import fdcore
    d = fdcore.design(fdcore.Spec())
    done = []
    for arith in ("float", "double", "fixed32", "fixed16"):
        sos, fixed, _ = fdcore.implement(d.sos, d.spec.fs, arith, True, None)
        text, info = codegen.generate_firmware(d, arith, sos, fixed)
        text = re.sub(r"on \d{4}-\d\d-\d\d \d\d:\d\d", "by firmware.py --fixtures", text)
        info["generated"] = "firmware.py --fixtures"
        out = out_dir / arith
        out.mkdir(parents=True, exist_ok=True)
        (out / "user_filter.h").write_text(text, encoding="ascii", newline="\n")
        (out / "user_filter.json").write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8",
                                              newline="\n")
        done.append(f"{out}: {info['description']} (id {info['id']})")
    return done


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--default", action="store_true", help="install the default filter into src/core")
    ap.add_argument("--fixtures", metavar="DIR",
                    help="write tests/host/user_filter's fixtures: one user_filter.h/.json per arithmetic")
    a = ap.parse_args()
    if a.fixtures:
        for line in write_fixtures(Path(a.fixtures)):
            print(line)
    elif a.default:
        d, sos, fixed = default_design()
        info = install(d, DEFAULT_ARITH, sos, fixed)
        print(f"{HEADER.relative_to(REPO)}: {info['description']} (id {info['id']})")
    else:
        ap.print_help()
