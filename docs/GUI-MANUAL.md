# User manual: the two GUI tools

This repository comes with two browser tools. Both are Python programs (NiceGUI) that
open a page in your browser:

| Tool | Start | Page | What it is for |
|---|---|---|---|
| **dsPIC33 GUI** (`tools/adc_gui.py`) | `adc_gui.bat` | http://localhost:8080 | drive the board's console: stream the ADC, grab buffers, show time signal and spectrum, set the DACs, the signal generator and the firmware's filter |
| **FilterDesign** (`tools/filterdesign/gui/app.py`) | `filterdesign.bat` | http://127.0.0.1:8090 | design an IIR filter, check it, generate C code, and put it into the firmware as the `user` filter: install, build, flash, then open the dsPIC33 GUI |

This manual says how to operate them, task by task. Background on why things work the
way they do is in `README.md` ("The GUI: capture, plot, FFT", "The triangle verdict",
the settings key table) and in `tools/filterdesign/README.md`. Every control in the
dsPIC33 GUI also has a tooltip naming the console command it sends.

Contents:

1. [Installation](#1-installation)
2. [dsPIC33 GUI](#2-dspic33-gui-adc_guipy)
   - [Quick start without a board](#21-quick-start-without-a-board)
   - [First measurement on the board](#22-first-measurement-on-the-board)
   - [The page, card by card](#23-the-page-card-by-card)
   - [Typical tasks](#24-typical-tasks)
   - [Command line](#25-command-line)
3. [FilterDesign](#3-filterdesign)
   - [Quick start](#31-quick-start)
   - [The page](#32-the-page)
   - [Putting a filter onto the board (dsPIC33 tab)](#33-putting-a-filter-onto-the-board-dspic33-tab)
   - [Command line](#34-command-line)
4. [When something goes wrong](#4-when-something-goes-wrong)

---

## 1. Installation

Needed on the PC:

- **Python 3.10 or newer** on the PATH.
- For FilterDesign: a **host gcc** (MinGW-w64 or MSYS2 on Windows). The design program
  `fdesign` is compiled on first use, and the "C test" tab compiles the generated code.
- To build and flash from FilterDesign: **XC-DSC** (used by `tools\build.bat`) and
  **MPLAB X** (its `ipecmd.exe` flashes the EV74H48A).

Once, in the repository root:

```
gui_setup.bat
```

This creates a private Python environment in `tools\.venv` (nothing goes into the system
Python), installs NiceGUI, pyserial, numpy, scipy and matplotlib, and runs the dsPIC33
GUI's self-test. Run it again after a `git pull` that changed `tools\requirements-*.txt`.
Both start scripts use `tools\.venv` by themselves. Linux/macOS: `tools/gui_setup.sh`,
then `tools/.venv/bin/python tools/adc_gui.py ...`.

---

## 2. dsPIC33 GUI (`adc_gui.py`)

The GUI talks to the firmware's console over the board's virtual COM port (115200 baud).
Every command waits for the firmware's acknowledgement before the next one goes out, so
the GUI and the board never talk over each other. You can watch the traffic in the
**console** pane at the bottom of the page.

### 2.1 Quick start without a board

```
adc_gui.bat --fake
```

The browser opens, the GUI connects to a built-in stand-in for the board, and the header
chip turns green. Then:

1. In the **acquisition** card press **single**: one buffer is grabbed and drawn in the
   **time signal** and **spectrum** plots. With the default input (the test triangle) the
   **triangle verdict** card shows **PASS**.
2. Press **live**: the GUI grabs again and again (every 500 ms by default). Press
   **stop** to end it.
3. Set **input** to **custom input**: the stand-in now plays a sine (set in the **fake
   target signal** card), and the **signal evaluation** chips show SNR, THD and harmonics.
4. Pick an entry in the **setup** list of the **settings file** card to see ready-made
   configurations (DAC triangles, signal generator shapes, Goertzel checks, noise tests).

`--fake --fake-board EV17P63A` makes the stand-in report the Curiosity Nano instead.

### 2.2 First measurement on the board

1. Flash the firmware (`tools\build.bat`, then MPLAB X/IPE, or from FilterDesign's
   dsPIC33 tab). Plug in the board's USB. On the EV74H48A the console is the MCP2221A's
   COM port; on the Curiosity Nano it is the nEDBG's.
2. Start the GUI with the port: `adc_gui.bat --port COM7` (your number), or start
   `adc_gui.bat`, choose the port in the **port** list in the header and press
   **connect**. The list is read when the page is built: a board plugged in later needs
   a page reload (F5).
3. The header chip shows the first line of the firmware's `version` reply, the board, and
   the round trip time ("RTT 3 ms"). The GUI switches to the board the firmware reports
   by itself.
4. Leave **input** at **RA8 / DAC2 test triangle**: the firmware drives its own triangle
   on DAC2, and ADC core 5 reads it back on RA8 inside the chip, so no wiring is needed.
5. Press **single**, then **live**. Watch the counter chips above the plots: **overrun**,
   **late** and **missed** must stay green (0). The **triangle verdict** must say
   **PASS**.
6. Raise **rate, kSPS** step by step. The hint under the field tells you where the board
   has shown trouble before: clean to about 8000 kSPS, DMA overruns from about 10000,
   lost triggers from about 16000. It is guidance, not a limit.
7. Press **stop** before you unplug, or press **disconnect**: the GUI stops the stream
   (`stream off`) and closes the port.

### 2.3 The page, card by card

Clicking a card's title folds it away (▸) or opens it again (▾). The folded cards are
remembered at once. The **tooltips** checkbox in the header turns all tooltips off once
you know the page.

#### Header

| Control | What it does |
|---|---|
| **documentation** | shows `docs/ARCHITECTURE.md` in a dialog |
| **tooltips** | tooltips on/off (saved with the settings) |
| **port** | `fake` (stand-in), `remote` (a remote bench, see `README.md` "Optional: remote bench"), or a COM port |
| **connect / disconnect** | opens or closes the connection |
| status chip | grey "not connected", green with firmware version, board and RTT, red "connect failed: ..." |

#### Left column

**settings file** - every value on the page lives in a JSON file.

- **save** writes the current page to the file shown (default `tools/adc_gui_settings.json`,
  private, not in git). It is read at the next start.
- **save as** writes to another file, which then becomes the file shown.
- **standard** puts every control back to `tools/adc_gui_defaults.json` (the standard
  in git). Press **save** to keep it.
- **setup** applies a ready-made configuration at once (and to the board, if connected):
  input, rate, DACs, generator, filter, trigger. Everything a setup does not name stays.
  The last entry, **from a file ...**, loads a settings file.

**acquisition · triggered chain** - what the ADC samples and how fast.

| Control | Meaning |
|---|---|
| **rate, kSPS (1..40000)** | sample rate. The board uses the nearest rate it can make; the **actual rate** chip shows what it made. A change while live is taken over before the next grab. |
| **input** | **RA8 / DAC2 test triangle** (core 5, PINSEL 3, the firmware's own signal) or **custom input** |
| **core (1..5)**, **PINSEL**, **SAMC** | the custom input: ADC core, its input channel, sample time. Locked while the test input is selected. The info line under PINSEL names the pin; the **chip · pinout** and **board · where to wire it** cards show where it is. |
| **grab interval, ms** | pause between two grabs in live mode |
| **trigger**, **level**, **edge**, **hysteresis** | make the time plot stand still like an oscilloscope: the plot starts where the signal crosses *level* on the chosen *edge*. Display only - the stream, the FFT and the verdict are not affected. |
| **single** | start the stream if needed, grab once, stop the stream |
| **live / stop** | grab repeatedly until **stop**; **stop** sends `stream off` |

While live runs the stream never stops: each grab sends the buffer pair just completed
while the DMA carries on in the other one.

**signal processing** - the filter running in the firmware on every buffer half.

| Control | Meaning |
|---|---|
| **filter on** | switches between off and the last filter chosen |
| **filter (in the firmware)** | **off**, **low-pass / high-pass / band-pass at fs/8** (built in, they scale with the rate), **user filter** (from FilterDesign, valid at its design rate only) |
| **Goertzel at fs/16**, **threshold, LSB** | a tone detector at fs/16; the chip beside it says DETECTED or not detected |
| **use its rate** | (user filter, only when the rate differs) sets the rate to the filter's design rate |
| **noise test** | (user filter) measures the filter's frequency response on the board, see 2.4 |

When the user filter is selected the card shows its description from the board. An amber
"NOT the filter in src/core/user_filter.json" means the board runs a different filter
than the one installed in the source tree: build and flash.

**fake target signal** - only for `--fake`: what the stand-in plays on a custom input
(sine with frequency, amplitude, noise and 2nd/3rd harmonic, or one of the DAC triangles).

**dac1 · triangle (RA1)** and **dac2 · triangle (RA8)** - each DAC can make a triangle
between **low** and **high** with the slope **SLPDAT**. The period is shown under the
fields. A change goes to the board by itself 0.8 s after the last edit; **apply** sends at
once. DAC2's **auto** is the firmware's own test triangle. **force** lets values outside
the datasheet's limits through. DAC1 (RA1) is only read through a custom input (core 5,
PINSEL 1).

**signal generator · table -> DMA2 -> DAC** - an arbitrary waveform from a table played
by DMA channel 2 onto a DAC.

| Control | Meaning |
|---|---|
| **generator**, **output** | on/off, DAC1 (RA1) or DAC2 (RA8) |
| **n**, **play rate** | table length and how many table entries per second; the table repeats every n / play rate |
| **f0** | fundamental; with **snap f0 to the table** it is moved to fit a whole number of periods into the table. 0 = no tone |
| **h2 .. h7** | harmonics as multiples of f0's amplitude |
| **noise** | white noise, in multiples of f0's amplitude (f0 0 = noise alone) |
| **decay** | envelope exp(-decay x t) in 1/s from the table's start; 0 = steady tone. To fall to 1 % within T: decay = 4.6 / T |
| **amp**, **lo**, **hi** | amplitude and the DAC code range (800..3500 by default: the DAC does not follow below about 780) |
| **loop preset** | 1 kHz + 3rd harmonic on DAC2, read back on RA8 (core 5, PINSEL 3): the time plot then overlays the expected curve and the **loop** chip shows how well it matches |
| **flat noise for this rate** | white noise on DAC2, played at twice the sample rate (max. 1 MHz) |
| **apply** | send now (otherwise 0.8 s after the last edit) |

The plot under the card is a preview of the table. The generator and the DAC card share
the DAC: while the generator plays, the DAC card leaves the DAC alone. The test input
needs DAC2 for its own triangle, so selecting it switches a generator on DAC2 off.

**buffer** - **buffer size, total** is one ping-pong pair (both halves), even, 32 to the
board's maximum (2048). **apply** sends `buf`; a running stream restarts with the next
grab.

#### Right column

**Grab line and chips** (top): grab number, length, the actual rate, the CPU cycles per
sample, grabs/s, then chips:

| Chip | Meaning |
|---|---|
| **overrun / late / missed** | errors since the previous grab: DMA overruns, late interrupts, halves the processing was too slow for. Green = 0. |
| **actual rate** | the sample rate the board really ran; the plots use it |
| **CPU load** | share of a half period the processing took; green below 70 %, red above 100 % |
| **trig @ k / no trigger** | where the trigger fired |
| **loop** | in the generator loop: rms difference to the expected curve, gain, table entry |

**time signal** - samples over time. Left axis ADC counts (0..4095), right axis volts
(set **reference voltage, V**, default 3.3), top axis time. The line above the plot says
what the input is and the min/max of this grab. Hover for single values. The plot can be
zoomed with the mouse.

**spectrum · Hann window** - FFT of the grab in dBFS (0 dB = full scale). **average**
with **grabs** averages the power of the last N grabs (useful for noise); it starts over
when the rate, length or filter changes. Dashed lines mark fs/8 (filter corner) and fs/16
(Goertzel).

**filter response · noise test** - appears after a noise test (see 2.4): measured and
designed response of the user filter.

**signal evaluation** - fundamental frequency, level, noise floor, SNR (green from 40 dB),
THD (harmonics 2..5) and H2..H5 in dBc. Meaningful for a sine; for a triangle the
harmonics are of course large.

**triangle verdict · test input only** - checks the firmware's test triangle sample by
sample, with the same code as the firmware's own chain test: a lost or repeated sample
moves the turning points off the grid (**slip**) and gives **FAIL**. Hidden when there is
no triangle to check (custom input, filter on, DAC2 off).

**chip · pinout** and **board · where to wire it** - the package and the evaluation board
with the selected input and the DAC outputs marked. Hover a pin for all its functions.
Changing core/channel/source here changes the acquisition card too.

**console** - every line sent to and received from the board, with time stamps (last 1000
lines). First place to look when something does not do what you expect.

### 2.4 Typical tasks

**Measure an external signal.** Set **input** to **custom input**, pick **core** and
**PINSEL** so that the info line (and the board card) show the pin you wired to. Keep the
signal within 0..3.3 V. Choose a rate at least twice the highest frequency in the signal,
press **live**. Switch **trigger** on for a still picture, **average** for a clean
spectrum.

**Check that nothing is lost at a rate.** Test input, set the rate, **live** for a while.
Every grab must show PASS and overrun/late/missed at 0. Repeat with a filter on: then the
CPU load chip shows whether the processing keeps up (missed counts the halves it did not).

**Look at a waveform from the generator.** Pick a "generator - ..." entry in **setup**, or
press **loop preset**. The time plot shows the measured signal and the expected curve.

**Measure the user filter's response on the board.**

1. Select **user filter** in the signal processing card. Press **use its rate** if it is
   offered (the filter's coefficients hold only at its design rate).
2. Press **noise test**. The GUI stops live, plays white noise on DAC2, grabs N times with
   the filter off (reference), N times with the filter on, and draws the measured
   response against the design in **filter response · noise test**. The summary line gives
   the deviation in the pass band and the stop band level.

The setups "noise - white noise on DAC2, the user filter, 200 kSPS" and "... no filter"
show the same by hand. Above 500 kSPS the generator cannot play the noise fast enough.

**Detect a tone (Goertzel).** Tick **Goertzel at fs/16**, set the **threshold**. The four
"Goertzel check" setups show a tone that should be detected and three that should not.

**Keep a configuration.** **save** (personal default for the next start) or **save as**
(a named file; load it again with setup -> **from a file ...** or `--settings <file>`).

### 2.5 Command line

```
adc_gui.bat [options]
```

| Option | Meaning |
|---|---|
| `--port COM7` | connect to this port at start |
| `--fake` | connect to the built-in stand-in |
| `--fake-board EV17P63A` | the stand-in reports the Curiosity Nano |
| `--remote`, `--bench-client PATH` | connect through a remote bench (`README.md`, "Optional: remote bench") |
| `--settings FILE` | settings file to read and save |
| `--sigproc off\|lp\|hp\|bp\|user` | preselect the firmware filter (FilterDesign starts the GUI with `user`) |
| `--http-port N` | page port (default 8080) |
| `--no-browser` | do not open a browser window |
| `--selftest` | no page: run the stand-in through a cycle and print PASS/FAIL |

---

## 3. FilterDesign

### 3.1 Quick start

```
filterdesign.bat
```

The page opens at http://127.0.0.1:8090 with the last saved parameter set
(`presets/default.json`). On the very first design the tool compiles its design program
`fdesign` with gcc (a few seconds); without gcc a red box says so.

1. In **Specification** choose **Filter type** (Lowpass, Highpass, Bandpass, Bandstop) and
   **Characteristic** (Butterworth, Chebyshev, Elliptic).
2. Enter the **Sampling rate** and the band edges (Hz), the **Passband ripple** and the
   **Stopband atten.** (dB). The filter order follows from these - there is no order field.
3. Every change redesigns the filter after 0.3 s. The chip at the top right says
   "specification met" (green), "check result" (amber) or "design failed" (red).
4. Look at the **Magnitude** tab: the red shaded areas are the tolerance scheme, the curve
   must stay out of them. The dashed curve is the implementation with the chosen
   arithmetic.

Or simply load a ready-made set: **Parameter set** -> **Load from presets folder**, e.g.
`dspic33_default_lowpass_200k` (the firmware's default user filter).

### 3.2 The page

#### Left panel

**Parameter set** - load and save complete designs as JSON files in
`tools/filterdesign/gui/presets/`.

- **Load from presets folder** (with the refresh button to rescan the folder).
- **Save** overwrites the current file, **Save as** asks for a name, **Load file** loads
  any `.json` without copying it into the folder.
- "• modified" behind the name means unsaved changes; loading another set then asks
  before discarding them.

**Specification** - see 3.1. The edge fields change with the filter type and are always
in ascending frequency order.

**Implementation** - how the filter is computed.

| Control | Meaning |
|---|---|
| **Arithmetic** | float (32 bit), double (64 bit), fixed point 32 bit, fixed point 16 bit, float (32 bit, dsPIC33A assembler) |
| **Section scaling** | scales each biquad section to 0 dB at every node; keep it on for fixed point, otherwise high-order filters overflow |
| **Output gain** | dB, folded into the last section at no cost. Above 0 dB the output clips at 0/4095 for large signals. The plots are shown without it. |
| **Auto Q / Fractional bits** | fixed point only: the Q format of the coefficients, normally chosen automatically |
| **C name** | prefix of the generated functions (`<name>_init`, `<name>_process`, `<name>_process_block`) and files |

#### Right panel

**Summary** - order and number of sections, achieved pass band and stop band
attenuation (against the specification), largest pole radius, settling time, group delay,
for fixed point the coefficient format and the overflow test, and the pass/stop band of the
quantized implementation. A red or amber warning below says when the fixed-point version
overflows or misses the specification.

**Tabs:**

| Tab | Content |
|---|---|
| **Magnitude** | dB/linear, linear/log frequency, tolerance scheme, the implemented (quantized) response |
| **Phase** | unwrapped or wrapped |
| **Group delay** | in samples or ms |
| **Pole / zero** | z plane with the unit circle, and the lists of poles and zeros |
| **Impulse / step** | design and implementation |
| **Sections** | the biquad coefficients b0..b2, a1, a2 per section, pole radius/frequency/Q, peak gain and L1 norm |
| **C code** | the generated `.h` and `.c` (or `.s` for the assembler); **Download .h / .c** saves them to the browser's download folder |
| **C test** | compiles and runs the generated code on the PC, see below |
| **dsPIC33** | puts the filter onto the board, see 3.3 |

All plots: mouse wheel or the box tool to zoom, restore button, save as image.

**C test tab.** Choose the **Implementations** (float, double, fixed 32, fixed 16), the
**Signal** (impulse, step, sine, chirp, white noise, multitone), **f1/f2**, **Amplitude**
and **Samples**, then **Compile & run**. The table shows per implementation whether it
built, whether it matches the bit-exact model, saturations, the error against the double
precision reference, SNR, and the measured pass/stop band. The plot shows the output, the
error, or the measured magnitude. **Test bench (.zip)** downloads the filter with a test
program, input and expected output, and a Makefile: `make test` prints PASS or FAIL on any
machine with gcc. The assembler variant cannot be tested on the PC.

### 3.3 Putting a filter onto the board (dsPIC33 tab)

The firmware has a slot for one designed filter, `sigproc user` (`src/core/user_filter.h`).
The dsPIC33 tab fills it and gets it running in four steps.

**Before you start:**

- The **Sampling rate** must be a whole number of kHz (1 kHz .. 40 MHz): the board streams
  at whole kSPS. The filter is valid only at that rate.
- The **Checks** list on the left must not show a red line. It also gives the CPU budget
  (cycles per sample at this rate) - below 60 cycles the install is refused; above about
  8 MSPS the stream itself starts to lose samples.
- An amber "misses the specification" is only a warning.
- Close MPLAB X's project (or MPLAB X) if it holds the board's programmer.

**Select the Board:** EV74H48A (flashed through the on-board PKOB4 with `ipecmd`) or
EV17P63A Curiosity Nano (flashed by copying the .hex onto its USB drive).

| Button | What it does |
|---|---|
| **1 Install into firmware** | writes `src/core/user_filter.h` and `src/core/user_filter.json` |
| **2 Build** | runs `tools\build.bat` (or `build.bat nano`), about 20 s |
| **3 Flash** | programs the board, 20 to 40 s. **Do not unplug the board or close the page meanwhile.** |
| **1-3 in one go** | all three, stops at the first failure |
| **4 Open dsPIC33 GUI** | starts `adc_gui.py` in its own window with the `user` filter preselected; fill in the **COM port** (or leave it empty and choose in the GUI), or tick **fake target (no board)** |

The status line shows "installed / built / flashed" with a tick for each step done for
the current design. The log below shows the output of every step, newest on top.

**In the dsPIC33 GUI:** signal processing card -> **user filter** -> **use its rate** ->
**filter on**, then **live**; or press **noise test** to measure the response against
the design (section 2.4).

**Back to the default filter.** Installing changes two files tracked in git. To restore
the default (elliptic low-pass, 200 kSPS, 15/25 kHz):

```
python tools\filterdesign\gui\firmware.py --default
```

then build and flash again. Or load the preset `dspic33_default_lowpass_200k` and run
steps 1-3.

### 3.4 Command line

```
filterdesign.bat [--port 8090] [--host 0.0.0.0] [--no-browser] [--light] [--presets DIR]
```

`?tab=<name>` in the URL opens a tab directly (e.g. `?tab=ctest`, `?tab=dspic33`).

---

## 4. When something goes wrong

| Symptom | Cause / what to do |
|---|---|
| `adc_gui.bat`: "No tools\.venv yet" | run `gui_setup.bat` once |
| COM port missing in the list | plugged in after the page was built: reload the page (F5). Check the Device Manager. |
| "connect failed" | wrong port, or the port is open in another program (terminal, MPLAB X data visualizer). Close it and connect again. |
| connected, but **single** gives "stream on refused" | look at the **console** pane for the firmware's reply; an old firmware may lack the command - flash the current one |
| overrun / late / missed red | the rate is too high for the stream or for the filter; lower it, or switch the filter off |
| "NOT the filter in src/core/user_filter.json" | the board runs an older user filter: build and flash |
| user filter response looks wrong | the stream rate is not the filter's design rate: **use its rate** |
| FilterDesign: "fdesign executable not found" | no gcc on the PATH; install MinGW-w64/MSYS2 or set `CC` / `FDESIGN` |
| "Not installed: Sample rate ..." | design for a whole number of kHz |
| "The .hex is older than user_filter.h - build first" | press **2 Build** before **3 Flash** |
| Flash: "programmer not found" | the board's PKOB4 USB port is not connected |
| Flash failed, MPLAB X running | MPLAB X holds the programmer: close the project or MPLAB X, flash again |
| Flash: "err -10121" | the PKOB4's USB link is stuck: **unplug the board's USB cable and plug it in again**, then flash. Retrying without that does not help. The chip may be erased until a flash succeeds. |
| Flash hangs | wait - the tool stops it by itself after 240 s. **Never kill `ipecmd` or java by hand**: that leaves the PKOB4 stuck until a USB re-plug. |

Every flash from FilterDesign adds a line to `build/flashlogs/history.txt`; a failed one
also saves `build/flashlogs/<time>/` with the programmer's output and the processes that
were running. More on the firmware side: `docs/TROUBLESHOOTING.md`.
