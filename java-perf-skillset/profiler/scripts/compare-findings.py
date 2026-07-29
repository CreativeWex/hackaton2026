#!/usr/bin/env python3
"""Compare one profiler run's findings against a reference and compute a verdict.

Part of the `profiler` Claude Code skill. Mirrors the shape of
java-performance-measurement's compare_results.py on purpose (same fingerprint
model, same verdict priority order) so behaviour is predictable across both
skills — but compares a *set of findings matched by stable id*, not a single
numeric metric.

Usage:
    compare-findings.py \
        --scenario profiler/scenario.yaml \
        --mode initial|incremental|final \
        --current <analyze-findings.py output.json> \
        [--reference <reference-findings.json>] \
        [--fingerprint-file <fingerprint.json>] \
        [--git-sha <sha>] \
        [--run-id <id>] \
        [--raw-dir <path-recorded-in-output>] \
        --output <findings.json>

Exit codes:
    0 - findings.json written (verdict may still be WORSE/INCONCLUSIVE/...)
    2 - fatal usage / IO / parsing error (verdict FAILED is written when possible)

Requires Python 3.10+. No external dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

VERDICT_PRIORITY = ["FAILED", "NOT_COMPARABLE", "INCONCLUSIVE", "MIXED", "WORSE", "BETTER", "SAME"]

# All finding categories in this skill are "lower magnitude is better"
# (growth MB, thread growth count, GC pause ms, pending-connections count) —
# unlike java-performance-measurement's metrics, findings never have a
# higher_is_better direction, so it is not a per-finding field here.


def _parse_scalar(text: str) -> Any:
    text = text.strip()
    if text == "" or text.lower() in {"null", "~"}:
        return None
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    if (text.startswith('"') and text.endswith('"') and len(text) >= 2) or (
        text.startswith("'") and text.endswith("'") and len(text) >= 2
    ):
        return text[1:-1]
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def _strip_comment(line: str) -> str:
    out = []
    in_s = in_d = False
    for ch in line:
        if ch == "'" and not in_d:
            in_s = not in_s
        elif ch == '"' and not in_s:
            in_d = not in_d
        elif ch == "#" and not in_s and not in_d:
            break
        out.append(ch)
    return "".join(out).rstrip()


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        lines.append((indent, line.strip()))

    pos = 0

    def parse_block(indent: int) -> Any:
        nonlocal pos
        if pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
            items: list[Any] = []
            while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                _, content = lines[pos]
                inner = content[2:].strip()
                if ":" in inner and not inner.startswith(("'", '"')):
                    pos += 1
                    item: dict[str, Any] = {}
                    key, _, val = inner.partition(":")
                    if val.strip():
                        item[key.strip()] = _parse_scalar(val)
                    else:
                        item[key.strip()] = parse_block(indent + 4)
                    while pos < len(lines) and lines[pos][0] > indent and not lines[pos][1].startswith("- "):
                        k_indent, k_content = lines[pos]
                        k, _, v = k_content.partition(":")
                        pos += 1
                        if v.strip():
                            item[k.strip()] = _parse_scalar(v)
                        else:
                            item[k.strip()] = parse_block(k_indent + 2)
                    items.append(item)
                else:
                    pos += 1
                    items.append(_parse_scalar(inner))
            return items
        mapping: dict[str, Any] = {}
        while pos < len(lines) and lines[pos][0] == indent and not lines[pos][1].startswith("- "):
            _, content = lines[pos]
            if ":" not in content:
                raise ValueError(f"Cannot parse YAML line: {content!r}")
            key, _, val = content.partition(":")
            pos += 1
            if val.strip():
                mapping[key.strip()] = _parse_scalar(val)
            else:
                if pos < len(lines) and lines[pos][0] > indent:
                    mapping[key.strip()] = parse_block(lines[pos][0])
                else:
                    mapping[key.strip()] = None
        return mapping

    result = parse_block(0)
    if not isinstance(result, dict):
        raise ValueError("Top-level YAML structure must be a mapping")
    return result


def profile_fingerprint(scenario_path: Path, scenario: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(scenario_path.read_bytes())
    for key in ("load", "snapshots", "thresholds", "commands"):
        h.update(f"{key}={scenario.get(key)}".encode())
    return h.hexdigest()[:16]


def environment_fingerprint(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    env: dict[str, Any] = {
        "os": platform.system(),
        "arch": platform.machine(),
        "cpuCount": os.cpu_count(),
        "javaVersion": (extra or {}).get("javaVersion", "unknown"),
        "jvmOptions": (extra or {}).get("jvmOptions", "unknown"),
        "memoryLimit": (extra or {}).get("memoryLimit", "unknown"),
    }
    digest = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()[:16]
    env["fingerprint"] = digest
    return env


def relative_delta_percent(reference: float, current: float) -> float | None:
    if reference == 0:
        return None if current == 0 else (100.0 if current > 0 else -100.0)
    return (current - reference) / abs(reference) * 100.0


def classify_finding(delta_percent: float | None, noise: float, regression: float, improvement: float) -> str:
    """Lower magnitude is always better for this skill's finding categories."""
    if delta_percent is None:
        return "SAME"
    if abs(delta_percent) <= noise:
        return "SAME"
    if -delta_percent >= improvement:
        return "IMPROVED"
    if delta_percent >= regression:
        return "WORSE"
    return "SAME"


def compare(
    current_findings: list[dict[str, Any]],
    reference_findings: list[dict[str, Any]] | None,
    noise: float,
    regression: float,
    improvement: float,
) -> tuple[dict[str, Any], list[str]]:
    """Returns (comparison-by-id, list of per-finding verdicts actually observed)."""
    comparison: dict[str, Any] = {}
    verdicts: list[str] = []

    current_by_id = {f["id"]: f for f in current_findings}
    reference_by_id = {f["id"]: f for f in (reference_findings or [])}

    all_ids = set(current_by_id) | set(reference_by_id)
    for fid in sorted(all_ids):
        cur = current_by_id.get(fid)
        ref = reference_by_id.get(fid)

        if cur is not None and ref is None:
            comparison[fid] = {
                "category": cur["category"], "severity": cur["severity"],
                "reference": None, "current": cur.get("magnitude"), "deltaPercent": None,
                "verdict": "NEW",
            }
            verdicts.append("NEW")
            continue

        if cur is None and ref is not None:
            comparison[fid] = {
                "category": ref["category"], "severity": ref.get("severity"),
                "reference": ref.get("magnitude"), "current": None, "deltaPercent": None,
                "verdict": "RESOLVED",
            }
            verdicts.append("RESOLVED")
            continue

        # Present in both.
        cur_mag = cur.get("magnitude")
        ref_mag = ref.get("magnitude")
        if cur_mag is None or ref_mag is None:
            # e.g. deadlock: no magnitude, presence in both = still broken.
            verdict = "SAME"
            delta = None
        else:
            delta = relative_delta_percent(float(ref_mag), float(cur_mag))
            verdict = classify_finding(delta, noise, regression, improvement)
        comparison[fid] = {
            "category": cur["category"], "severity": cur["severity"],
            "reference": ref_mag, "current": cur_mag,
            "deltaPercent": round(delta, 4) if delta is not None else None,
            "verdict": verdict,
        }
        verdicts.append(verdict)

    return comparison, verdicts


def combine_verdicts(verdicts: list[str]) -> str:
    better_class = {"RESOLVED", "IMPROVED"}
    worse_class = {"NEW", "WORSE"}
    has_better = any(v in better_class for v in verdicts)
    has_worse = any(v in worse_class for v in verdicts)
    if has_better and has_worse:
        return "MIXED"
    if has_worse:
        return "WORSE"
    if has_better:
        return "BETTER"
    return "SAME"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scenario", required=True, type=Path)
    ap.add_argument("--mode", required=True, choices=["initial", "incremental", "final"])
    ap.add_argument("--current", required=True, type=Path, help="analyze-findings.py output for this run")
    ap.add_argument("--reference", type=Path, default=None)
    ap.add_argument("--fingerprint-file", type=Path, default=None)
    ap.add_argument("--git-sha", default="unknown")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--raw-dir", default=None)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    def write_result(payload: dict[str, Any]) -> None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(str(args.output))

    run_id = args.run_id or re.sub(
        r"[:+]", "-",
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"),
    )

    base: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "mode": args.mode,
        "runId": run_id,
        "gitSha": args.git_sha,
        "rawArtifacts": args.raw_dir,
    }

    try:
        scenario = parse_simple_yaml(args.scenario.read_text(encoding="utf-8"))
        current_doc = json.loads(args.current.read_text(encoding="utf-8"))
        current_findings = current_doc.get("findings", [])
        run_meta = current_doc.get("meta", {})

        extra = {}
        if args.fingerprint_file and args.fingerprint_file.is_file():
            extra = json.loads(args.fingerprint_file.read_text(encoding="utf-8"))
        env = environment_fingerprint(extra)
        prof_fp = profile_fingerprint(args.scenario, scenario)

        comparison_cfg = scenario.get("comparison") or {}
        noise = float(comparison_cfg.get("magnitudeNoisePercent", 10))
        regression = float(comparison_cfg.get("magnitudeRegressionPercent", 20))
        improvement = float(comparison_cfg.get("magnitudeImprovementPercent", 20))

        base.update({
            "scenarioId": current_doc.get("scenarioId", "unknown"),
            "findings": current_findings,
            "meta": run_meta,
            "profileFingerprint": prof_fp,
            "environment": env,
        })

        expected = run_meta.get("expectedSnapshotCount")
        actual = run_meta.get("snapshotCount")
        incomplete = expected is not None and actual is not None and actual < expected

        if args.mode == "initial":
            if incomplete:
                base.update({
                    "verdict": "INCONCLUSIVE",
                    "explanation": f"Only {actual}/{expected} snapshots captured; baseline not reliable",
                })
            else:
                base.update({
                    "verdict": "BASELINE_CREATED",
                    "explanation": "Initial findings baseline created successfully",
                })
            write_result(base)
            return 0

        if args.reference is None or not args.reference.is_file():
            base.update({
                "verdict": "FAILED",
                "explanation": f"Reference findings.json is required for mode '{args.mode}' "
                                "but was not found. Run 'initial' first.",
            })
            write_result(base)
            return 2

        reference = json.loads(args.reference.read_text(encoding="utf-8"))
        base["referenceRun"] = {
            "path": str(args.reference), "runId": reference.get("runId"), "gitSha": reference.get("gitSha"),
        }

        ref_prof_fp = reference.get("profileFingerprint")
        ref_env_fp = (reference.get("environment") or {}).get("fingerprint")
        if ref_prof_fp != prof_fp or ref_env_fp != env["fingerprint"]:
            detail = []
            if ref_prof_fp != prof_fp:
                detail.append(f"profile fingerprint {ref_prof_fp} != {prof_fp}")
            if ref_env_fp != env["fingerprint"]:
                detail.append(f"environment fingerprint {ref_env_fp} != {env['fingerprint']}")
            base.update({"verdict": "NOT_COMPARABLE", "explanation": "; ".join(detail)})
            write_result(base)
            return 0

        if incomplete:
            base.update({
                "verdict": "INCONCLUSIVE",
                "explanation": f"Only {actual}/{expected} snapshots captured in this run",
            })
            write_result(base)
            return 0

        reference_findings = reference.get("findings", [])
        comparison, verdicts = compare(current_findings, reference_findings, noise, regression, improvement)
        overall = combine_verdicts(verdicts)
        explanations = {
            "SAME": "No findings changed beyond the noise threshold",
            "BETTER": "At least one finding resolved or improved, none regressed or appeared new",
            "WORSE": "At least one finding regressed or is new, with no offsetting improvement",
            "MIXED": "Both improvement (resolved/improved) and regression (new/worse) findings present",
        }
        base.update({
            "comparison": comparison,
            "verdict": overall,
            "explanation": explanations[overall],
        })
        write_result(base)
        return 0
    except Exception as exc:  # noqa: BLE001
        base.update({"verdict": "FAILED", "explanation": f"{type(exc).__name__}: {exc}"})
        try:
            write_result(base)
        except OSError:
            print(f"FATAL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
