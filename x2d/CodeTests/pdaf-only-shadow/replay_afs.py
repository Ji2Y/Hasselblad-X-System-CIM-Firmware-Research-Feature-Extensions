"""Offline AF-S log inspection and matched-threshold temporal comparisons.

Only reads a local UTF-8 log and writes a local JSON report. No USB, firmware
loading, memory hooks or lens commands. Logged peak units remain uncalibrated.
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import statistics


EPOCH = re.compile(r"^\s*(\d{10}(?:\.\d+)?|t\+\d+(?:\.\d+)?s)\s")
FIELD = re.compile(r"\b(cur_pos|peak|target_pos|conf|frame_id|rlt|blend_defocus)\s*=\s*"
                   r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)(?![\w.])")
START = re.compile(r"(?:enter(?:ing)?\s+state.*StateSequenceAF|StateSequenceAF.*(?:onHblEntry|FindFocusStart))", re.I)
FINISH = re.compile(r"StateAfSingle::handleAfResult.*\b(Success|Failed|Failure|Cancelled)\b", re.I)


@dataclass(frozen=True)
class Sample:
    timestamp: float
    current_position: float
    logged_peak: float
    raw_confidence: float
    logged_target_position: float | None
    native_frame_id: int | None
    session: int | None
    native_result_class: int | None = None
    native_blend_defocus: int | None = None


@dataclass(frozen=True)
class Config:
    min_raw_confidence: float
    window: int
    max_raw_peak_spread: float
    max_gap_ms: float
    ema_alpha: float
    kalman_process_variance_per_second: float
    kalman_measurement_variance: float

    def validate(self):
        numeric = (self.min_raw_confidence, self.max_raw_peak_spread,
                   self.max_gap_ms, self.ema_alpha,
                   self.kalman_process_variance_per_second,
                   self.kalman_measurement_variance)
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in numeric):
            raise ValueError("config values must be finite numbers")
        if (type(self.window) is not int or not 3 <= self.window <= 32
                or self.min_raw_confidence <= 0 or self.max_raw_peak_spread < 0
                or self.max_gap_ms <= 0 or not 0 < self.ema_alpha <= 1
                or self.kalman_process_variance_per_second < 0
                or self.kalman_measurement_variance <= 0):
            raise ValueError("invalid comparison configuration")


def parse_log(text: str):
    events = []
    seen = set()
    rejected = 0
    for line in text.splitlines():
        timestamp = EPOCH.match(line)
        if timestamp is None or line in seen:
            continue
        seen.add(line)
        token = timestamp.group(1)
        t = float(token[2:-1]) if token.startswith("t+") else float(token)
        fields = {k: float(v) for k, v in FIELD.findall(line)}
        if {"cur_pos", "peak", "conf"}.issubset(fields):
            if any(not math.isfinite(v) or (v < 0 and k != "blend_defocus")
                   for k, v in fields.items()):
                rejected += 1
                continue
            frame = fields.get("frame_id")
            if frame is not None and not frame.is_integer():
                rejected += 1
                continue
            result = fields.get("rlt")
            defocus = fields.get("blend_defocus")
            if ((result is not None and (not result.is_integer() or not 0 <= result <= 3))
                    or (defocus is not None and not defocus.is_integer())):
                rejected += 1
                continue
            events.append((t, 1, fields))
        if START.search(line):
            events.append((t, 0, None))
        finish = FINISH.search(line)
        if finish:
            events.append((t, 2, finish.group(1).lower()))
    origin = min((event[0] for event in events), default=0.0)
    events = [(t - origin, kind, payload) for t, kind, payload in events]
    samples = []
    sessions = []
    active = None
    for t, kind, payload in sorted(events, key=lambda event: (event[0], event[1])):
        if kind == 0:
            active = len(sessions)
            sessions.append({"session": active, "start": t, "end": None,
                             "result": None, "elapsed_ms": None})
        elif kind == 2:
            if active is not None:
                session = sessions[active]
                session.update(end=t, result=payload,
                               elapsed_ms=1000 * (t - session["start"]))
            active = None
        else:
            samples.append(Sample(t, payload["cur_pos"], payload["peak"],
                                  payload["conf"], payload.get("target_pos"),
                                  int(payload["frame_id"]) if "frame_id" in payload else None,
                                  active, int(payload["rlt"]) if "rlt" in payload else None,
                                  int(payload["blend_defocus"]) if "blend_defocus" in payload else None))
    return samples, sessions, rejected


def reversal_count(values):
    signs = [(b > a) - (b < a) for a, b in zip(values, values[1:]) if b != a]
    return sum(a != b for a, b in zip(signs, signs[1:]))


def inspect(samples, sessions, rejected):
    durations = [s["elapsed_ms"] for s in sessions
                 if s["result"] == "success" and s["elapsed_ms"] is not None]
    groups = {}
    for item in samples:
        groups.setdefault(item.session, []).append(item)
    return {
        "model": "X2D 100C first generation", "firmware": "4.2.0", "lens": "55V",
        "verification": "local log analysis only; device identity not verified by this parser",
        "time_units": "seconds relative to the first parsed event",
        "control_allowed": False, "position_units": "raw logged values, uncalibrated",
        "complete_log_export_marker": "not checked by parser; see capture output",
        "sample_count": len(samples), "rejected_sample_lines": rejected,
        "samples_with_native_frame_id": sum(x.native_frame_id is not None for x in samples),
        "samples_with_session_boundary": sum(x.session is not None for x in samples),
        "native_result_class_counts": {str(i): sum(x.native_result_class == i for x in samples)
                                        for i in range(4)},
        "samples_missing_native_result_class": sum(x.native_result_class is None for x in samples),
        "sessions": sessions,
        "observed_stock_success_median_ms": statistics.median(durations) if durations else None,
        "trajectory_groups": [{"session": key, "samples": len(values),
                               "logged_peak_spread": max(x.logged_peak for x in values) - min(x.logged_peak for x in values),
                               "logged_peak_reversals": reversal_count([x.logged_peak for x in values]),
                               "logged_target_reversals": reversal_count([x.logged_target_position for x in values
                                                                          if x.logged_target_position is not None])}
                              for key, values in groups.items()],
        "limitations": ["No simulated speedup is inferred from a fixed stock trajectory.",
                        "Logged target_pos is not treated as the final focus position.",
                        "rlt is the logged downstream class; conf alone does not establish this class.",
                        "blend_defocus is signed and is not a calibrated per-zone metric.",
                        "No images or sharpness ground truth are present.",
                        "Missing frame IDs do not count as consecutive sensor frames."]}


def compare(samples, config):
    """Static-position scalar Kalman, EMA and median share one confidence gate.

    This adapts temporal fusion to AF-S. No velocity extrapolation across shots.
    Every output remains a diagnostic estimate of the *logged peak*.
    """
    config.validate()
    history = deque(maxlen=config.window)
    ema = kalman = variance = None
    previous = None
    rows = []
    for sample in samples:
        gap = sample.timestamp - previous.timestamp if previous else None
        reset = (previous is None or sample.session != previous.session
                 or gap <= 0 or 1000 * gap > config.max_gap_ms)
        if reset:
            history.clear()
            ema = kalman = variance = None
        trusted = sample.raw_confidence >= config.min_raw_confidence
        if variance is not None:
            variance += config.kalman_process_variance_per_second * gap
        if trusted:
            history.append(sample)
            # Confidence scale is deliberately not normalized to the sim's 0..1.
            ratio = min(sample.raw_confidence / config.min_raw_confidence, 10.0)
            noise = config.kalman_measurement_variance / ratio
            if ema is None:
                ema = kalman = sample.logged_peak
                variance = noise
            else:
                ema += config.ema_alpha * (sample.logged_peak - ema)
                gain = variance / (variance + noise)
                kalman += gain * (sample.logged_peak - kalman)
                variance *= 1 - gain
        else:
            # A confidence dropout breaks the consecutive valid window.
            history.clear()
        native_ids = [s.native_frame_id for s in history]
        if sample.session is None:
            reason = "unknown_afs_session"
        elif not trusted:
            reason = "low_confidence"
        elif len(history) < config.window:
            reason = "insufficient_valid_samples"
        elif any(frame is None for frame in native_ids):
            reason = "native_frame_ids_missing"
        elif any(b != a + 1 for a, b in zip(native_ids, native_ids[1:])):
            reason = "nonconsecutive_native_frames"
        elif max(s.logged_peak for s in history) - min(s.logged_peak for s in history) > config.max_raw_peak_spread:
            reason = "unstable_logged_peak"
        else:
            reason = "consistent_logged_peak_only"
        rows.append({**asdict(sample), "same_threshold_single_sample": sample.logged_peak if trusted else None,
                     "median": statistics.median(s.logged_peak for s in history) if history else None,
                     "ema": ema, "static_kalman": kalman, "confidence_gate_pass": trusted,
                     "temporal_gate": reason, "filter_reset": reset,
                     "control_allowed": False})
        previous = sample
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "compare"))
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve() or (args.config and args.config.resolve() == args.output.resolve()):
        parser.error("output must not overwrite input/config")
    raw_input = args.input.read_text(encoding="utf-8")
    if raw_input.lstrip().startswith("{"):
        try:
            capture = json.loads(raw_input)
        except json.JSONDecodeError as error:
            parser.error(f"invalid capture JSON: {error}")
        records = capture.get("records") if isinstance(capture, dict) else None
        if not isinstance(records, list) or any(not isinstance(line, str) for line in records):
            parser.error("capture JSON must contain a string records array")
        raw_input = "\n".join(records)
    samples, sessions, rejected = parse_log(raw_input)
    if not samples:
        parser.error("no epoch-stamped cur_pos/peak/conf records; no report generated")
    report = inspect(samples, sessions, rejected)
    if args.mode == "compare":
        if args.config is None:
            parser.error("compare requires an explicit --config; no camera thresholds are supplied")
        try:
            config = Config(**json.loads(args.config.read_text(encoding="utf-8")))
            report["comparisons"] = compare(samples, config)
            report["comparison_config"] = asdict(config)
        except (TypeError, ValueError) as error:
            parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"{len(samples)} log samples, {len(sessions)} identified AF-S sessions; offline report: {args.output}")
    print("Lens control unavailable; no AF-S performance improvement has been measured.")


if __name__ == "__main__":
    main()
