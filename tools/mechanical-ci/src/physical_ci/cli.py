import argparse
import hashlib
import json
import sys
from pathlib import Path

from . import __version__
from .errors import BackendError, InputError
from .gcode import extract
from .geometry import check_path
from .manifest import load_manifest, sha256
from .slicer import run_slicer
from .support import load_regions, screen_support


def ensure_output(path, protected=()):
    requested = Path(path)
    target = requested.resolve()
    if requested.exists() or requested.is_symlink():
        raise InputError("output already exists; choose a fresh output path")
    if target in {Path(p).resolve() for p in protected}:
        raise InputError("output must not overwrite an input or another output")
    return target


def write_json(path, data, protected=()):
    target = ensure_output(path, protected)
    try:
        payload = json.dumps(data, indent=2, allow_nan=False) + "\n"
    except (ValueError, OverflowError) as error:
        raise InputError("result cannot be represented as finite JSON") from error
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(payload)


def write_segments(path, segments, protected=()):
    target = ensure_output(path, protected)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        for segment in segments:
            stream.write(json.dumps(segment, allow_nan=False) + "\n")


def parser():
    command = argparse.ArgumentParser(description="Bounded headless mechanical checks; no physical certification")
    command.add_argument("--version", action="version", version=__version__)
    sub = command.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate manifest and artifact hashes")
    validate.add_argument("manifest")
    path = sub.add_parser("check-path", help="sample one translation path against frozen STEP")
    path.add_argument("manifest")
    path.add_argument("--output", required=True)
    analyze = sub.add_parser("analyze-gcode", help="extract supported linear extrusion paths")
    analyze.add_argument("input")
    analyze.add_argument("--output", required=True)
    analyze.add_argument("--segments", help="optional segment JSONL output")
    support = sub.add_parser("screen-support", help="screen nominal support extrusion against machine-frame ROI AABBs")
    support.add_argument("input", help="supported linear G-code")
    support.add_argument("--roi", required=True, help="strict, hash-bound ROI JSON")
    support.add_argument("--output", required=True)
    slicing = sub.add_parser("slice", help="run a local pinned PrusaSlicer, then analyze output")
    slicing.add_argument("manifest")
    slicing.add_argument("--slicer", default="prusa-slicer")
    slicing.add_argument("--output-dir", required=True)
    slicing.add_argument("--segments", action="store_true")
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "screen-support":
            source = Path(args.input)
            protected = [source, args.roi]
            ensure_output(args.output, protected)
            if source.stat().st_size > 64 * 1024 * 1024:
                raise InputError("G-code exceeds this prototype's 64 MiB limit")
            gcode_digest = sha256(source)
            regions, roi_digest = load_regions(args.roi, gcode_digest)
            stationary = []
            with source.open("rb") as stream:
                raw_gcode = stream.read(64 * 1024 * 1024 + 1)
            if len(raw_gcode) > 64 * 1024 * 1024:
                raise InputError("G-code exceeds this prototype's 64 MiB limit")
            if hashlib.sha256(raw_gcode).hexdigest() != gcode_digest:
                raise InputError("G-code changed while being read")
            summary, segments = extract(raw_gcode.decode("utf-8"), stationary_events=stationary)
            if sha256(source) != gcode_digest:
                raise InputError("G-code changed while being read")
            result = screen_support(summary, segments, stationary, regions)
            result.update({"gcode_sha256": gcode_digest, "roi_sha256": roi_digest})
            write_json(args.output, result, protected)
            print(json.dumps({"observed_hits": len(result["observed_hits"]),
                              "coverage_complete": result["coverage_complete"], "printer_ready": False}))
            return 0
        if args.command == "analyze-gcode":
            source = Path(args.input)
            if source.stat().st_size > 64 * 1024 * 1024:
                raise InputError("G-code exceeds this prototype's 64 MiB limit")
            protected = [source]
            if args.segments and Path(args.segments).resolve() == Path(args.output).resolve():
                raise InputError("summary and segment paths must be different")
            ensure_output(args.output, protected)
            if args.segments:
                ensure_output(args.segments, protected + [args.output])
            summary, segments = extract(source.read_text(encoding="utf-8"))
            summary["gcode_sha256"] = sha256(source)
            write_json(args.output, summary, protected)
            if args.segments:
                write_segments(args.segments, segments, protected + [args.output])
            print(json.dumps({"extrusion_segments": summary["extrusion_segments"], "physical_validation": "not_performed"}))
            return 0
        manifest, paths, digest = load_manifest(args.manifest)
        protected = list(paths.values()) + [args.manifest]
        if args.command == "validate":
            print(json.dumps({"manifest_valid": True, "artifact_hashes_verified": len(paths), "schema_version": 1,
                              "manifest_sha256": digest, "physical_validation": "not_performed"}))
            return 0
        if args.command == "check-path":
            ensure_output(args.output, protected)
            result = check_path(manifest, paths, digest)
            write_json(args.output, result, protected)
            print(json.dumps({key: result[key] for key in ("outcome", "regression_passed", "sample_count")}))
            return 3 if result["regression_passed"] is False else 0
        result, segments = run_slicer(manifest, paths, digest, args.slicer, args.output_dir)
        output = Path(args.output_dir)
        write_json(output / "summary.json", result, protected)
        if args.segments:
            write_segments(output / "segments.jsonl", segments, protected + [output / "summary.json"])
        print(json.dumps({"extrusion_segments": result["extrusion_segments"], "printer_ready": False}))
        return 0
    except InputError as error:
        print(f"input error: {error}", file=sys.stderr)
        return 2
    except (BackendError, OSError, UnicodeError) as error:
        print(f"execution error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
