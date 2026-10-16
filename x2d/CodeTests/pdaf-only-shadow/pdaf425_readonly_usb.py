"""Narrow read-only USB reader for the X2D 4.2.0 PDAF experiment records.

This module exposes typed reads only. Its internal factory requests are
restricted to version checks, bounded process-memory reads, stock AF log
capture under one owned temporary directory, and removal of that directory.
It has no public arbitrary-shell, parameter-write, file-upload, or AF-control
method.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import secrets
import struct
import time


USB_VID = 0x2756
USB_PID = 0x0009
USB_INTERFACE = 3
USB_ALTSETTING = 0
USB_OUT = 0x04
USB_IN = 0x85
USB_TIMEOUT_MS = 4000
MAX_TRANSFER = 1024
MAX_REPLY_CHARS = 8192

_ALLOWED_PARAMETER_IDS = {2, 27, 28}
_READ_REQUEST_PREFIX = bytes((0x04, 0x00, 0x08, 0x05, 0x05))
_REPLY_ROUTE_PREFIXES = {
    bytes((0x03, 0x00, 0x05, 0x08, 0x0C)),
    bytes((0x03, 0x00, 0x05, 0x08, 0x05)),
}

_FACTORY_REQUEST_HEADER = struct.pack("<HBBB", 0x000A, 8, 5, 0xFC)
_FACTORY_REPLY_HEADER = struct.pack("<HBBB", 0x0009, 5, 8, 0xFC)
_FACTORY_FRAME_SIZE = 257
_FACTORY_COMMAND_SIZE = 252
_FACTORY_COMMAND_DATA_SIZE = 232
_FACTORY_HBL_SHELL = 65
_FACTORY_NOTIFICATION = 4
_CAPTURE_SECONDS = 30
_CAPTURE_PATTERN = "pdaf_type3|_exec_pdaf_afs_process|StateSequenceAF|StateAfSingle"
_LOG_PATTERNS = {
    "all": "target_pos=|align lens_pos=|StateSequenceAF|StateAfSingle::handleAfResult|pdaf_type3",
    "state": "StateSequenceAF|StateAfSingle::handleAfResult",
    "target": "target_pos=",
    "zone": "zone\\[|pdaf type3 output",
}


class ReadOnlyUsbError(RuntimeError):
    """A bounded USB read or protocol validation failed."""


@dataclass(frozen=True)
class ParameterResponse:
    parameter_id: int
    sequence: int
    value: bytes


@dataclass(frozen=True)
class FactoryResponse:
    command_id: int
    function: int
    cookie: int
    status: int
    text: str


def _crc16_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def _read_parameter_request(parameter_id: int, sequence: int) -> bytes:
    if parameter_id not in _ALLOWED_PARAMETER_IDS or not 0 <= sequence <= 255:
        raise ReadOnlyUsbError("unsupported read-only parameter request")
    return _READ_REQUEST_PREFIX + bytes((sequence, 0, 2)) + struct.pack("<H", parameter_id)


def _logical_parameter_length(data: bytes, parameter_id: int) -> int | None:
    if len(data) < 8:
        return None
    offset = 8
    payload = data[offset:]
    if len(payload) >= 2 and struct.unpack_from("<H", payload)[0] == parameter_id:
        offset += 2
        payload = payload[2:]
    if parameter_id == 27:
        end = payload.find(b"\0")
        return offset + end + 1 if end >= 0 else None
    if parameter_id in (2, 28) and payload.startswith(b"i"):
        end = 1
        if end < len(payload) and payload[end] in (ord("+"), ord("-")):
            end += 1
        start = end
        while end < len(payload) and 48 <= payload[end] <= 57:
            end += 1
        if end > start and (end == len(payload) or payload[end] == 0):
            return offset + end + (end < len(payload))
    return None


def _parse_parameter(data: bytes, parameter_id: int, sequence: int) -> ParameterResponse:
    if len(data) < 10 or data[:5] not in _REPLY_ROUTE_PREFIXES:
        raise ReadOnlyUsbError("invalid camera parameter reply")
    if data[5] != sequence or data[6] != 0 or data[7] != 0x82:
        raise ReadOnlyUsbError("camera parameter reply did not match its request")
    logical = _logical_parameter_length(data, parameter_id)
    frame = data[:logical] if logical else data.rstrip(b"\0")
    payload = frame[8:]
    if len(payload) >= 2 and struct.unpack_from("<H", payload)[0] == parameter_id:
        payload = payload[2:]
    return ParameterResponse(parameter_id, sequence, payload.split(b"\0", 1)[0])


def _factory_request(command: str, cookie: int) -> bytes:
    encoded = command.encode("ascii")
    if not 0 < len(encoded) < _FACTORY_COMMAND_DATA_SIZE:
        raise ReadOnlyUsbError("bounded read request is too long")
    payload = bytearray(_FACTORY_COMMAND_SIZE)
    struct.pack_into("<III", payload, 0, _FACTORY_HBL_SHELL, 0, cookie)
    struct.pack_into("<I", payload, 0x10, 10)
    payload[0x14:0x14 + len(encoded)] = encoded
    struct.pack_into("<I", payload, 0x0C, _crc16_xmodem(payload[0x10:0xFC]))
    return _FACTORY_REQUEST_HEADER + bytes(payload)


def _extract_factory_frames(buffer: bytearray) -> list[bytes]:
    frames = []
    while True:
        start = buffer.find(_FACTORY_REPLY_HEADER)
        if start < 0:
            if len(buffer) > 4:
                del buffer[:-4]
            break
        if start:
            del buffer[:start]
        if len(buffer) < _FACTORY_FRAME_SIZE:
            break
        candidate = bytes(buffer[:_FACTORY_FRAME_SIZE])
        payload = candidate[5:]
        stored = struct.unpack_from("<I", payload, 0x0C)[0]
        if stored != _crc16_xmodem(payload[0x10:0xFC]):
            del buffer[0]
            continue
        frames.append(candidate)
        del buffer[:_FACTORY_FRAME_SIZE]
    return frames


def _parse_factory_frame(frame: bytes) -> FactoryResponse:
    if len(frame) != _FACTORY_FRAME_SIZE or frame[:5] != _FACTORY_REPLY_HEADER:
        raise ReadOnlyUsbError("invalid bounded factory response")
    payload = frame[5:]
    command_id, function, cookie = struct.unpack_from("<III", payload, 0)
    status = struct.unpack_from("<I", payload, 0x10)[0]
    text = payload[0x14:].split(b"\0", 1)[0].decode("utf-8", errors="replace")
    return FactoryResponse(command_id, function, cookie, status, text)


def _capture_path(token: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{16}", token):
        raise ReadOnlyUsbError("invalid temporary capture identifier")
    return "/tmp/pdafsh-" + token


def _allowed_read_command(command: str) -> bool:
    """Fail closed: only the fixed observations used by this module pass."""
    exact = {
        "getprop ro.product.device",
        "cat /proc/sys/kernel/random/boot_id",
        "date +%s.%N",
        "sha256sum /system/lib64/libaaa.so",
    }
    if command in exact:
        return True
    patterns = (
        r"pidof camera-service",
        r"grep libaaa\.so /proc/[1-9][0-9]*/maps",
        r"awk '\{print \$22\}' /proc/[1-9][0-9]*/stat",
        r"awk -v c=[0-9]+ -v n=[1-9][0-9]* '\$2~/\^r/\{split\(\$1,a,\"-\"\); if\(\(\"0x\" a\[1\]\)\+0<=c && \(\"0x\" a\[2\]\)\+0>=c\+n\) print \"MATCH\"\}' /proc/[1-9][0-9]*/maps",
        r"dd if=/proc/[1-9][0-9]*/mem bs=1 skip=[0-9]+ count=[1-9][0-9]* 2>/dev/null \| od -An -v -tx1",
        r"dd if=/proc/[1-9][0-9]*/mem bs=1 skip=[0-9]+ count=[1-9][0-9]* 2>/dev/null \| sha256sum",
        r"umask 077; mkdir /tmp/pdafsh-[0-9a-f]{16} && echo READY",
        r"printf '%s' '[1-9][0-9]*\|[0-9]{10}\.[0-9]{1,9}' >/tmp/pdafsh-[0-9a-f]{16}/owner",
        r"test -f /tmp/pdafsh-[0-9a-f]{16}/log && echo READY",
        r"cat /tmp/pdafsh-[0-9a-f]{16}/owner",
        r"test ! -d /proc/[1-9][0-9]* && echo STOPPED",
        r"ls /tmp/pdafsh-[0-9a-f]{16}/log\*",
        r"sha256sum /tmp/pdafsh-[0-9a-f]{16}/log",
        r"wc -l </tmp/pdafsh-[0-9a-f]{16}/log",
        r"sed -n '[1-9][0-9]*,[1-9][0-9]*p' /tmp/pdafsh-[0-9a-f]{16}/log",
        r"if test -r /proc/[1-9][0-9]*/cmdline; then tr '\\000' ' ' </proc/[1-9][0-9]*/cmdline; fi",
        r"kill -TERM [1-9][0-9]*",
        r"rm -f /tmp/pdafsh-[0-9a-f]{16}/log /tmp/pdafsh-[0-9a-f]{16}/log\.1 /tmp/pdafsh-[0-9a-f]{16}/owner",
        r"rmdir /tmp/pdafsh-[0-9a-f]{16}",
    )
    if any(re.fullmatch(pattern, command) for pattern in patterns):
        return True
    if any(command == f"logcat -d -v epoch --pid={pid} | grep -E '{pattern}' | tail -n 24"
           for pid in re.findall(r"--pid=([1-9][0-9]*)", command)
           for pattern in _LOG_PATTERNS.values()):
        return True
    capture = re.fullmatch(
        r"busybox timeout -t 30 logcat -b main -v epoch --pid=([1-9][0-9]*) "
        r"-e 'pdaf_type3\|_exec_pdaf_afs_process\|StateSequenceAF\|StateAfSingle' "
        r"-f (/tmp/pdafsh-[0-9a-f]{16})/log >/dev/null 2>&1 & echo \$!",
        command,
    )
    return capture is not None


class ReadOnlyCamera:
    """Typed USB observations with a closed set of remote read commands."""

    def __init__(self, timeout_ms: int = USB_TIMEOUT_MS):
        if not 1000 <= timeout_ms <= 15000:
            raise ReadOnlyUsbError("USB timeout must be 1000–15000 ms")
        self.timeout_ms = timeout_ms
        self.device = None
        self.out_ep = None
        self.in_ep = None
        self._usb_util = None

    def __enter__(self) -> "ReadOnlyCamera":
        try:
            import usb.core
            import usb.util
            devices = list(usb.core.find(find_all=True, idVendor=USB_VID, idProduct=USB_PID) or [])
        except Exception as error:
            raise ReadOnlyUsbError("PyUSB/libusb could not open the camera interface") from error
        if len(devices) != 1:
            raise ReadOnlyUsbError("connect one supported camera over USB")
        self.device = devices[0]
        self._usb_util = usb.util
        try:
            self.device.set_configuration()
        except Exception:
            pass
        try:
            usb.util.claim_interface(self.device, USB_INTERFACE)
            self.device.set_interface_altsetting(interface=USB_INTERFACE, alternate_setting=USB_ALTSETTING)
            config = self.device.get_active_configuration()
            interface = usb.util.find_descriptor(config, bInterfaceNumber=USB_INTERFACE,
                                                  bAlternateSetting=USB_ALTSETTING)
            if interface is None:
                raise ReadOnlyUsbError("required camera interface is unavailable")
            self.out_ep = usb.util.find_descriptor(interface, bEndpointAddress=USB_OUT)
            self.in_ep = usb.util.find_descriptor(interface, bEndpointAddress=USB_IN)
            if self.out_ep is None or self.in_ep is None:
                raise ReadOnlyUsbError("required camera endpoints are unavailable")
        except Exception:
            self.close()
            raise ReadOnlyUsbError("could not claim the supported camera interface")
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        device = self.device
        self.device = self.out_ep = self.in_ep = None
        if device is not None and self._usb_util is not None:
            try:
                self._usb_util.dispose_resources(device)
            except Exception:
                pass

    @staticmethod
    def _is_timeout(error: BaseException) -> bool:
        return getattr(error, "errno", None) in (60, 110) or "timed out" in str(error).lower()

    def _drain(self, timeout_ms: int = 100) -> None:
        if self.in_ep is None:
            raise ReadOnlyUsbError("camera USB interface is closed")
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                self.in_ep.read(MAX_TRANSFER, timeout=max(1, int((deadline - time.monotonic()) * 1000)))
            except Exception as error:
                if self._is_timeout(error):
                    return
                raise ReadOnlyUsbError("camera USB read failed") from error

    def _write_request(self, request: bytes) -> None:
        if self.out_ep is None:
            raise ReadOnlyUsbError("camera USB interface is closed")
        try:
            if self.out_ep.write(request, timeout=self.timeout_ms) != len(request):
                raise ReadOnlyUsbError("camera USB request was incomplete")
        except ReadOnlyUsbError:
            raise
        except Exception as error:
            raise ReadOnlyUsbError("camera USB request failed") from error

    def read_parameter(self, parameter_id: int, sequence: int = 1) -> ParameterResponse:
        self._drain(50)
        request = _read_parameter_request(parameter_id, sequence)
        self._write_request(request)
        if self.in_ep is None:
            raise ReadOnlyUsbError("camera USB interface is closed")
        chunks = bytearray()
        deadline = time.monotonic() + self.timeout_ms / 1000
        while len(chunks) < MAX_TRANSFER:
            try:
                chunk = bytes(self.in_ep.read(MAX_TRANSFER - len(chunks),
                                              timeout=max(1, int((deadline - time.monotonic()) * 1000))))
            except Exception as error:
                if chunks and self._is_timeout(error):
                    break
                raise ReadOnlyUsbError("camera parameter read failed") from error
            if not chunk:
                break
            chunks.extend(chunk)
            logical = _logical_parameter_length(bytes(chunks), parameter_id)
            if logical is not None:
                break
            if time.monotonic() >= deadline:
                break
        return _parse_parameter(bytes(chunks), parameter_id, sequence)

    def _run_fixed_read(self, command: str, capture_ms: int = 3000) -> str:
        if not _allowed_read_command(command):
            raise ReadOnlyUsbError("refusing a command outside the fixed read-only allowlist")
        if not 100 <= capture_ms <= 15000:
            raise ReadOnlyUsbError("bounded read timeout is outside its allowed range")
        cookie = secrets.randbits(32) or 1
        request = _factory_request(command, cookie)
        self._drain(50)
        self._write_request(request)
        if self.in_ep is None:
            raise ReadOnlyUsbError("camera USB interface is closed")
        deadline = time.monotonic() + capture_ms / 1000
        buffer = bytearray()
        output = []
        while time.monotonic() < deadline:
            try:
                chunk = bytes(self.in_ep.read(MAX_TRANSFER,
                                              timeout=min(self.timeout_ms, max(1, int((deadline-time.monotonic())*1000)))))
            except Exception as error:
                if self._is_timeout(error):
                    continue
                raise ReadOnlyUsbError("bounded camera read failed") from error
            if not chunk:
                continue
            buffer.extend(chunk)
            for frame in _extract_factory_frames(buffer):
                response = _parse_factory_frame(frame)
                if response.command_id != _FACTORY_HBL_SHELL or response.cookie != cookie:
                    continue
                if response.function == _FACTORY_NOTIFICATION:
                    output.append(response.text)
                    continue
                if response.status != 0:
                    raise ReadOnlyUsbError("fixed camera read request was rejected")
                result = "".join(output).rstrip("\0")
                if len(result) > MAX_REPLY_CHARS:
                    raise ReadOnlyUsbError("camera reply exceeded the bounded output size")
                return result.strip()
        raise ReadOnlyUsbError("timed out waiting for the bounded camera read")

    def device_model(self) -> str:
        return self._run_fixed_read("getprop ro.product.device")

    def camera_pid(self) -> int:
        text = self._run_fixed_read("pidof camera-service")
        match = re.fullmatch(r"([1-9][0-9]*)", text)
        if not match:
            raise ReadOnlyUsbError("camera service was not found")
        return int(match.group(1))

    def library_maps(self, pid: int) -> list[tuple[int, int, str]]:
        text = self._run_fixed_read(f"grep libaaa.so /proc/{pid}/maps")
        maps = _parse_maps(text)
        if not maps:
            raise ReadOnlyUsbError("stock AF library mapping was not found")
        return maps

    def process_start(self, pid: int) -> int:
        text = self._run_fixed_read(f"awk '{{print $22}}' /proc/{pid}/stat")
        if not re.fullmatch(r"[0-9]+", text):
            raise ReadOnlyUsbError("camera service identity could not be checked")
        return int(text)

    def boot_id(self) -> str:
        text = self._run_fixed_read("cat /proc/sys/kernel/random/boot_id")
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", text):
            raise ReadOnlyUsbError("camera boot identity could not be checked")
        return text

    def identity(self, pid: int) -> tuple[int, str]:
        return self.process_start(pid), self.boot_id()

    def read_memory(self, pid: int, address: int, length: int) -> bytes:
        if not 1 <= length <= 1024 or address < 0:
            raise ReadOnlyUsbError("memory read is outside the bounded range")
        if not self.mapping_contains(pid, address, length):
            raise ReadOnlyUsbError("memory range was not confirmed readable")
        command = (f"dd if=/proc/{pid}/mem bs=1 skip={address} count={length} 2>/dev/null "
                   "| od -An -v -tx1")
        text = self._run_fixed_read(command)
        tokens = text.split()
        if len(tokens) != length or any(not re.fullmatch(r"[0-9a-fA-F]{2}", token) for token in tokens):
            raise ReadOnlyUsbError("incomplete bounded memory read")
        return bytes(int(token, 16) for token in tokens)

    def memory_hash(self, pid: int, address: int, length: int) -> str:
        if not 1 <= length <= 4096 or address < 0:
            raise ReadOnlyUsbError("memory hash range is outside the bounded range")
        if not self.mapping_contains(pid, address, length):
            raise ReadOnlyUsbError("memory hash range was not confirmed readable")
        command = (f"dd if=/proc/{pid}/mem bs=1 skip={address} count={length} 2>/dev/null "
                   "| sha256sum")
        digest = self._run_fixed_read(command).split()[0]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReadOnlyUsbError("incomplete bounded memory hash")
        return digest

    def mapping_contains(self, pid: int, address: int, length: int) -> bool:
        if pid <= 0 or address < 0 or not 1 <= length <= 4096:
            raise ReadOnlyUsbError("invalid memory mapping check")
        command = (f"awk -v c={address} -v n={length} '$2~/^r/"
                   f"{{split($1,a,\"-\"); if((\"0x\" a[1])+0<=c && (\"0x\" a[2])+0>=c+n) "
                   f"print \"MATCH\"}}' /proc/{pid}/maps")
        if not _allowed_read_command(command):
            raise ReadOnlyUsbError("memory mapping query is outside the read-only allowlist")
        return self._run_fixed_read(command) == "MATCH"

    def device_library_hash(self) -> str:
        digest = self._run_fixed_read("sha256sum /system/lib64/libaaa.so").split()[0]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReadOnlyUsbError("stock AF library hash could not be read")
        return digest

    def timestamp(self) -> float:
        text = self._run_fixed_read("date +%s.%N")
        if not re.fullmatch(r"[0-9]{10}\.([0-9]{1,9})", text):
            raise ReadOnlyUsbError("camera clock marker is invalid")
        return float(text)

    def recent_logs(self, pid: int, kind: str = "all") -> str:
        if kind not in _LOG_PATTERNS:
            raise ReadOnlyUsbError("unsupported log category")
        command = f"logcat -d -v epoch --pid={pid} | grep -E '{_LOG_PATTERNS[kind]}' | tail -n 24"
        return self._run_fixed_read(command, capture_ms=8000)

    def start_capture(self, pid: int) -> str:
        token = secrets.token_hex(8)
        path = _capture_path(token)
        if self._run_fixed_read(f"umask 077; mkdir {path} && echo READY") != "READY":
            raise ReadOnlyUsbError("private temporary capture directory could not be created")
        command = (f"busybox timeout -t {_CAPTURE_SECONDS} logcat -b main -v epoch --pid={pid} "
                   f"-e '{_CAPTURE_PATTERN}' -f {path}/log >/dev/null 2>&1 & echo $!")
        owner = self._run_fixed_read(command, capture_ms=10000)
        if not re.fullmatch(r"[1-9][0-9]*", owner):
            raise ReadOnlyUsbError("bounded capture start was not confirmed")
        marker = f"{self.timestamp():.9f}"
        self._run_fixed_read(f"printf '%s' '{owner}|{marker}' >{path}/owner")
        if self._run_fixed_read(f"test -f {path}/log && echo READY") != "READY":
            raise ReadOnlyUsbError("bounded capture file was not created")
        return token

    def read_capture(self, token: str, max_lines: int = 2048) -> tuple[list[str], float]:
        path = _capture_path(token)
        if not 1 <= max_lines <= 4096:
            raise ReadOnlyUsbError("capture export limits are invalid")
        owner_record = self._run_fixed_read(f"cat {path}/owner")
        match = re.fullmatch(r"([1-9][0-9]*)\|([0-9]{10}\.[0-9]{1,9})", owner_record)
        if not match:
            raise ReadOnlyUsbError("capture owner record is invalid")
        owner, marker = match.group(1), float(match.group(2))
        if self._run_fixed_read(f"test ! -d /proc/{owner} && echo STOPPED") != "STOPPED":
            raise ReadOnlyUsbError("wait for the bounded logger to stop before export")
        if self._run_fixed_read(f"ls {path}/log*") != f"{path}/log":
            raise ReadOnlyUsbError("capture rotated or contains unexpected files")
        before_hash = self._run_fixed_read(f"sha256sum {path}/log").split()[0]
        count_text = self._run_fixed_read(f"wc -l <{path}/log")
        if not re.fullmatch(r"[0-9]+", count_text):
            raise ReadOnlyUsbError("capture line count is invalid")
        count = int(count_text)
        if count > max_lines:
            raise ReadOnlyUsbError("capture exceeds the requested line limit")
        lines = []
        for start in range(1, count + 1, 8):
            end = min(start + 7, count)
            page = self._run_fixed_read(f"sed -n '{start},{end}p' {path}/log", capture_ms=8000).splitlines()
            if len(page) != end - start + 1:
                raise ReadOnlyUsbError("capture page was incomplete")
            lines.extend(page)
        if (self._run_fixed_read(f"wc -l <{path}/log") != count_text or
                self._run_fixed_read(f"sha256sum {path}/log").split()[0] != before_hash):
            raise ReadOnlyUsbError("capture changed during export")
        return [line for line in lines if _epoch(line) is None or _epoch(line) >= marker], marker

    def cleanup_capture(self, token: str) -> None:
        path = _capture_path(token)
        owner_record = self._run_fixed_read(f"cat {path}/owner")
        match = re.fullmatch(r"([1-9][0-9]*)\|([0-9]{10}\.[0-9]{1,9})", owner_record)
        if match:
            owner = match.group(1)
            command = (f"if test -r /proc/{owner}/cmdline; then tr '\\000' ' ' "
                       f"</proc/{owner}/cmdline; fi")
            cmdline = self._run_fixed_read(command)
            if f"{path}/log" in cmdline and "logcat" in cmdline:
                self._run_fixed_read(f"kill -TERM {owner}")
        self._run_fixed_read(f"rm -f {path}/log {path}/log.1 {path}/owner")
        self._run_fixed_read(f"rmdir {path}")


def _parse_maps(text: str) -> list[tuple[int, int, str]]:
    result = []
    for line in text.splitlines():
        match = re.match(r"^([0-9a-f]+)-([0-9a-f]+) ([rwxps-]{4}) ", line)
        if match:
            result.append((int(match.group(1), 16), int(match.group(2), 16), match.group(3)))
    return result


def _epoch(line: str) -> float | None:
    match = re.match(r"^\s*(\d{10}(?:\.\d+)?)\s", line)
    return float(match.group(1)) if match else None
