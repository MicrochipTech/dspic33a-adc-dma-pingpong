"""replay_target.py - a stand-in for protocol.Target: answers like the
firmware's console would for the commands the host-side tests send
(version, help, status, regs, chain all, stream on/grab, route list, ...),
with a few injectable faults. Used by tests/host/fake_bench_client.py, which
plays a bench_client tunnel for tools/remote.py's and tools/adc_gui.py's
self-tests - no board, no relay. Taken out of the former board-run runner,
the command table unchanged.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import numpy as np  # noqa: E402
import protocol  # noqa: E402
from eval_chain import synth as chain_synth  # noqa: E402

DEFAULT_CHAIN_ALL_LINES = [
    "@S0.1 hz=160000000 expect=160000000 -> PASS",
    "@S4.1 ksps=1000 xfer=1000 expect=1000 tol=5 overrun=0 brake=0 -> PASS",
    "@S4.2 ksps=4000 xfer=4000 expect=4000 tol=5 overrun=0 brake=0 -> PASS",
    "@S4.3 ksps=8000 xfer=8000 expect=8000 tol=5 overrun=0 brake=0 -> PASS",
    "@S5.0 ksps=100 slip_x100=5 zero=0 dbl=0 up=1 dn=1 slip_n=2 ratio_x1000=1000 -> PASS",
    "@S5.1 ksps=1000 slip_x100=5 zero=0 dbl=0 up=1 dn=1 slip_n=2 ratio_x1000=1000 -> PASS",
    "@S5.2 ksps=4000 slip_x100=5 zero=0 dbl=0 up=1 dn=1 slip_n=2 ratio_x1000=1000 -> PASS",
    "@S5.3 ksps=8000 slip_x100=5 zero=0 dbl=0 up=1 dn=1 slip_n=2 ratio_x1000=1000 -> PASS",
    "@S5.4 ksps=10000 slip_x100=8 zero=0 dbl=0 up=1 dn=1 slip_n=2 ratio_x1000=1000 -> PASS",
    "@S6.1 ksps=1000 xfer=1000 expect=1000 tol=5 overrun=0 late=0 missed=0 isr=2 half=1 "
    "done=1 brake=0 guard_ok=1 load_max_x10=200 free_cyc_per_sample=10 -> PASS",
    "@S6.2 ksps=4000 xfer=4000 expect=4000 tol=5 overrun=0 late=0 missed=0 isr=2 half=1 "
    "done=1 brake=0 guard_ok=1 load_max_x10=350 free_cyc_per_sample=8 -> PASS",
    "@S6.3 ksps=8000 xfer=8000 expect=8000 tol=5 overrun=0 late=0 missed=0 isr=2 half=1 "
    "done=1 brake=0 guard_ok=1 load_max_x10=460 free_cyc_per_sample=6 -> PASS",
    "@S9.1 ksps=8000 xfer=8000 expect=8000 tol=5 overrun=0 late=0 missed=0 isr=2 half=1 "
    "done=1 brake=0 guard_ok=1 load_max_x10=460 free_cyc_per_sample=6 -> PASS",
    "@SUM stages=10 pass=13 fail=0",
    "@END",
]


class ReplayTarget:
    """Stands in for protocol.Target in --selftest: answers like the
    firmware's console would for the commands this runner sends, with
    several injectable faults used to exercise a caller's own handling
    of them - a command that times out once (`timeout_block`), a command
    that NAKs once (`nak_once`), one 'stream grab' that comes back with a
    corrupted CRC (`grab_fault_at`, a (ksps, grab index) pair), a
    "chain all" reply other than the clean default (`chain_all_lines`, for a
    difference at a known stage), and extra "key: value" lines appended to "status" beyond the
    baseline set (`extra_status_fields`, standing in for BR.6's not-yet-named
    fields - present in B, absent in A)."""

    def __init__(self, label, has_route, timeout_block=None, nak_once=None, grab_fault_at=None,
                 chain_all_lines=None, extra_status_fields=None):
        self.label = label
        self.has_route = has_route
        self.timeout_block = timeout_block
        self._timeout_fired = False
        self.nak_once = set(nak_once or ())
        self._nak_fired = set()
        self.grab_fault_at = grab_fault_at
        self.chain_all_lines = chain_all_lines or DEFAULT_CHAIN_ALL_LINES
        self.extra_status_fields = extra_status_fields or {}
        self.port = f"replay-{label}"
        self.chain_on = False
        self.chain_ksps = 0
        self.chain_test = True
        self._grab_i = {}
        self._reset_count = 0

    def close(self):
        pass

    def sync(self, timeout=20.0):
        return True

    def ping(self, n=5, timeout=5.0):
        samples = [12.0 + i for i in range(n)]
        return dict(n=n, min_ms=min(samples), avg_ms=sum(samples) / n, max_ms=max(samples),
                    samples_ms=samples)

    def boot_banner(self):
        """Called once up front (the "power-up" banner) and again after a
        simulated reset, deliberately with a different reset cause the
        second time - so a selftest can tell the two apart."""
        self._reset_count += 1
        cause = "POR BOR EXTR" if self._reset_count == 1 else "EXTR (simulated reset)"
        return [
            "",
            "[boot] uart up on FRC, 115200 8N1",
            f"[boot] adc_dma_40msps replay-selftest git replay-{self.label} (master)",
            f"[boot] reset cause: {cause}",
            f"adc_dma_40msps - ADC at 40 MSPS into RAM via DMA (replay {self.label})",
        ]

    half_len = 1024     # "buf" state, as cli.c's capture_half_len() reports it
    # True: grabs carry half_len samples, as 955c473's firmware does. False: a
    # fixed 512, whatever "buf" said - the pre-955c473 fault R4.gui must catch.
    buf_follows = True
    dac_log = None

    def cmd(self, line, timeout=5.0):
        if self.dac_log is None:
            self.dac_log = []
        if self.timeout_block is not None and line == self.timeout_block and not self._timeout_fired:
            self._timeout_fired = True
            raise TimeoutError(f"replay: simulated hang on {line!r}")
        if line in self.nak_once and line not in self._nak_fired:
            self._nak_fired.add(line)
            return False, [f"NAK: simulated fault on {line!r}"]
        return self._reply(line)

    def _reply(self, line):
        parts = line.split()
        c = parts[0] if parts else ""
        if c == "version":
            return True, [f"[build] adc_dma_40msps replay {self.label}",
                          "[build] board: EV74H48A, dsPIC33AK512MPS512 GP DIM"]
        if c == "help":
            lines = ["Available commands:",
                     "  help - show this help",
                     "  version - build id, git revision, board, configuration",
                     "  status - run state and counters",
                     "  regs - clock, ADC, DMA and UART registers",
                     "  chain all|<n>|from <n>|run <ksps> [s] - the chain test",
                     "  test [all|self|clock|clkoff|bursts|matrix|rate|sweep|dac] [n]",
                     "  stream on <ksps> [core pinsel [samc]]|off|grab - the chain streaming",
                     "  buf [n] - samples per buffer half (16..1024, even)",
                     "  dac <1|2> <on|off> [low] [high] [slpdat] [force] - triangle on DACOUT1/2"]
            if self.has_route:
                lines.append("  route list - the active route(s) and the resource table")
            return True, lines
        if c == "status":
            lines = ["running: " + ("1" if self.chain_on else "0"),
                     "overrun: 0", "late: 0", "missed: 0", "fail_code: 0"]
            lines += [f"{k}: {v}" for k, v in self.extra_status_fields.items()]
            return True, lines
        if c == "regs":
            return True, ["CLK1CON: 0x00001234", "AD5CON1: 0x00005678"]
        if line == "chain all":
            return True, self.chain_all_lines
        if line == "test all":
            return True, ["[test] self: PASS", "[test] clock: PASS", "[test] all: done"]
        if c == "route" and len(parts) > 1 and parts[1] == "list":
            if not self.has_route:
                return False, ["unknown command"]
            # The reply format of P11.5 (5ac4dc1, tests/smoke/expected.log):
            # R6 runs after R5's "stream off", so no route is active.
            return True, ["route: none - no route active",
                          "dma_used: 0", "dma_total: 8", "sccp_used: 0", "sccp_total: 8",
                          "dac_outputs_used: 0", "dac_outputs_total: 2",
                          "uref_used: 0", "uref_total: 1",
                          "ram_used: 0", "ram_budget: 57344"]
        if c == "stream":
            return self._stream_cmd(parts[1:])
        if c == "buf":
            # cli.c's cmd_buf_fn(): refused while streaming
            if len(parts) > 1:
                if self.chain_on:
                    return False, ["buf: stop the stream first, and give an even number"]
                self.half_len = int(parts[1])
            return True, [f"samples per half: {self.half_len}", "maximum: 1024"]
        if c == "dac" and len(parts) >= 3:
            self.dac_log.append(line)
            return True, [f"dac: {parts[1]}", "off" if parts[2] == "off" else "RA8"]
        return False, ["unknown command"]

    def _stream_cmd(self, args):
        if args and args[0] == "on":
            rest = args[1:]
            self.chain_on = True
            self.chain_ksps = int(rest[0])
            self.chain_test = len(rest) <= 1
            self._grab_i[self.chain_ksps] = 0
            if not self.buf_follows:
                self.half_len = 1024          # the pre-955c473 fault: "stream on" undid "buf"
            return True, [f"stream: on - {self.chain_ksps} ksps"]
        if args and args[0] == "off":
            self.chain_on = False
            return True, ["stream: off, boot configuration restored"]
        return False, ["unknown command"]

    def _grab_wire(self):
        """The three raw wire pieces (header text line, payload bytes, tail
        - prompt/CRC line/ACK-or-NAK) one 'stream grab' cycle would put on
        the console, exactly as grab() builds them, split out so a fixture
        that plays this same replay over a REAL socket (a bench_client
        stand-in, tests/host/fake_bench_client.py) can send the actual
        bytes a real Target reads, instead of the (ok, samples, meta) tuple
        grab() decodes them into for the in-process --selftest here."""
        if not self.chain_on:
            header = "GRAB n=0 from=0 ksps=0 ov=0 late=0 missed=0 halves=0 xfer=0 slp=0 dachz=0\r\n"
            crc = protocol.crc16_ccitt_false(b"")
            tail = f"\r\nCRC {crc:04X}\r\n> ".encode("ascii") + protocol.NAK
            return header, b"", tail
        i = self._grab_i.get(self.chain_ksps, 0)
        self._grab_i[self.chain_ksps] = i + 1
        n = self.half_len if self.buf_follows else getattr(self, "_fixed_n", 512)
        if self.chain_test:
            slp = 20
            samples = chain_synth(n, 30.0, phase=float((i * 7) % 60 or 1), seed=i + 1)
        else:
            slp = 0
            samples = [2048 + (i * 37) % 100] * n
        payload = np.asarray(samples, dtype="<u2").tobytes()
        crc = protocol.crc16_ccitt_false(payload)
        if self.grab_fault_at == (self.chain_ksps, i):
            payload = bytes([payload[0] ^ 0xFF]) + payload[1:]
        header = (f"GRAB n={n} from=0 ksps={self.chain_ksps} ov=0 late=0 missed=0 "
                  f"halves=2 xfer={2 * n} slp={slp} dachz=400000000\r\n")
        tail = f"\r\nCRC {crc:04X}\r\n> ".encode("ascii") + protocol.ACK
        return header, payload, tail

    def grab(self, timeout=10.0):
        return protocol.parse_grab_frame(*self._grab_wire())
