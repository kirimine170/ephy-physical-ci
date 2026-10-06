"""One human-recorded length against an independent, version-bound requirement.

This module judges declared evidence, not measurement authenticity or safety.
Decimal JSON tokens are compared as exact rational numbers, without an epsilon.
"""
import hashlib
import json
from decimal import Decimal
from fractions import Fraction
from pathlib import Path, PurePosixPath

from . import __version__
from .errors import InputError
from .manifest import keys

MAX_JSON_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
SUBJECT_FIELDS = ("sample_id", "design_job_ref", "manufacturing_job_ref")
MATCH_FIELDS = ("feature_id", "requirement_revision", "unit", "process_state", "measurement_method")


class BindingMismatch(InputError):
    reason_code = "binding_mismatch"


def text(value, label):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise InputError(f"{label} must be a nonblank string without outer whitespace")
    return value


def quantity(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise InputError(f"{label} must be a finite JSON number")
    decimal = Decimal(value)
    if not decimal.is_finite() or decimal < 0:
        raise InputError(f"{label} must be finite and nonnegative")
    if decimal and not -100 <= decimal.adjusted() <= 100:
        raise InputError(f"{label} exceeds the supported decimal magnitude")
    return Fraction(decimal)


def json_number(token):
    if len(token) > 128:
        raise InputError("JSON number exceeds 128 characters")
    value = Decimal(token)
    if not value.is_finite() or abs(value.as_tuple().exponent) > 100:
        raise InputError("JSON number has a nonfinite or unsupported exponent")
    return value


def json_integer(token):
    if len(token) > 128:
        raise InputError("JSON integer exceeds 128 characters")
    return int(token)


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise InputError("duplicate inspection JSON key")
        result[name] = value
    return result


def reject_constant(token):
    raise InputError("nonfinite inspection JSON constant")


def load_json(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise InputError("inspection JSON exceeds 64 KiB")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_float=json_number, parse_int=json_integer,
                          parse_constant=reject_constant)
    except (ValueError, UnicodeError, RecursionError, OverflowError) as error:
        raise InputError("invalid inspection JSON") from error
    return data, hashlib.sha256(raw).hexdigest()


def versioned(data, required, label):
    keys(data, ("schema_version", *required), label=label)
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise InputError(f"{label} schema_version must be integer 1")


def validate_subject(data):
    versioned(data, SUBJECT_FIELDS, "subject")
    for field in SUBJECT_FIELDS:
        text(data[field], field)


def validate_requirement(data):
    versioned(data, (*MATCH_FIELDS, "tolerance", "judgment_policy"), "requirement")
    for field in MATCH_FIELDS:
        text(data[field], field)
    if data["unit"] != "mm":
        raise InputError("inspect-length supports only explicit mm; no unit conversion")
    keys(data["tolerance"], ("lower", "upper"), label="tolerance")
    lower = quantity(data["tolerance"]["lower"], "tolerance.lower")
    upper = quantity(data["tolerance"]["upper"], "tolerance.upper")
    if lower > upper:
        raise InputError("tolerance.lower must not exceed tolerance.upper")
    policy = data["judgment_policy"]
    keys(policy, ("name", "unevaluated_uncertainty"), label="judgment_policy")
    if policy["name"] not in ("simple_acceptance_v1", "interval_containment_v1"):
        raise InputError("unsupported judgment policy")
    if policy["unevaluated_uncertainty"] not in ("indeterminate", "ignore"):
        raise InputError("explicit unevaluated uncertainty policy is required")
    if policy["name"] == "interval_containment_v1" and policy["unevaluated_uncertainty"] != "indeterminate":
        raise InputError("interval_containment_v1 requires evaluated uncertainty")


def validate_measurement(data):
    versioned(data, (*SUBJECT_FIELDS, *MATCH_FIELDS, "value", "source_kind",
                     "uncertainty", "evidence_refs"), "measurement")
    for field in (*SUBJECT_FIELDS, *MATCH_FIELDS):
        text(data[field], field)
    if data["unit"] != "mm":
        raise InputError("inspect-length supports only explicit mm; no unit conversion")
    quantity(data["value"], "value")
    if data["source_kind"] not in ("human_measurement", "synthetic"):
        raise InputError("source_kind must be human_measurement or synthetic")
    uncertainty = data["uncertainty"]
    if not isinstance(uncertainty, dict):
        raise InputError("uncertainty must explicitly be evaluated or unevaluated")
    if uncertainty.get("status") == "evaluated":
        keys(uncertainty, ("status", "value", "unit", "basis"), label="uncertainty")
        quantity(uncertainty["value"], "uncertainty.value")
        if uncertainty["unit"] != data["unit"]:
            raise InputError("uncertainty unit mismatch; no conversion")
        text(uncertainty["basis"], "uncertainty.basis")
    elif uncertainty.get("status") == "unevaluated":
        keys(uncertainty, ("status", "reason"), label="uncertainty")
        text(uncertainty["reason"], "uncertainty.reason")
    else:
        raise InputError("uncertainty must explicitly be evaluated or unevaluated")
    if not isinstance(data["evidence_refs"], list) or len(data["evidence_refs"]) > 16:
        raise InputError("evidence_refs must be a list of at most 16 local hash-bound records")
    for reference in data["evidence_refs"]:
        keys(reference, ("path", "sha256"), label="evidence reference")
        name = text(reference["path"], "evidence path")
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise InputError("evidence path must be relative POSIX and stay in the measurement directory")
        digest = reference["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise InputError("evidence reference requires lowercase SHA256")


def verify_evidence(measurement, measurement_path, protected):
    """Hash the bounded bytes read; a reference alone cannot establish evidence."""
    root = Path(measurement_path).resolve().parent
    digests = []
    missing = not measurement["evidence_refs"]
    for reference in measurement["evidence_refs"]:
        source = (root / reference["path"]).resolve()
        if not source.is_relative_to(root):
            raise InputError("evidence path resolves outside the measurement directory")
        protected.append(source)
        try:
            with source.open("rb") as stream:
                raw = stream.read(MAX_EVIDENCE_BYTES + 1)
        except FileNotFoundError:
            missing = True
            continue
        if len(raw) > MAX_EVIDENCE_BYTES:
            raise InputError("evidence exceeds 64 MiB")
        if not raw:
            missing = True
            continue
        digest = hashlib.sha256(raw).hexdigest()
        if digest != reference["sha256"]:
            raise InputError("evidence SHA256 mismatch")
        digests.append(digest)
    return digests, missing


def report_values(value):
    """Report all quantities as decimal strings to avoid binary rounding."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: str(item) if key in ("value", "lower", "upper") else report_values(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [report_values(item) for item in value]
    return value


def error_report(kind):
    return {"schema_version": 1, "tool_version": __version__, "command": "inspect-length",
            "execution_status": "error", "judgment": "not_applicable", "reason": kind,
            "evidence_class": "record", "physical_validation": "not_performed", "printer_ready": False}


def inspect_length(subject_path, requirement_path=None, measurement_path=None):
    subject, subject_digest = load_json(subject_path)
    validate_subject(subject)
    protected = [subject_path]
    requirement = measurement = None
    hashes = {"subject_sha256": subject_digest, "requirement_sha256": None, "measurement_sha256": None}
    if requirement_path:
        requirement, hashes["requirement_sha256"] = load_json(requirement_path)
        validate_requirement(requirement)
        protected.append(requirement_path)
    if measurement_path:
        measurement, hashes["measurement_sha256"] = load_json(measurement_path)
        validate_measurement(measurement)
        protected.append(measurement_path)
        for field in SUBJECT_FIELDS:
            if measurement[field] != subject[field]:
                raise BindingMismatch(f"binding mismatch: {field}")
        if requirement:
            for field in MATCH_FIELDS:
                if measurement[field] != requirement[field]:
                    raise BindingMismatch(f"binding mismatch: {field}")
    synthetic = measurement is not None and measurement["source_kind"] == "synthetic"
    result = {"schema_version": 1, "tool_version": __version__, "command": "inspect-length",
              "execution_status": "not_run", "judgment": "indeterminate", "reason": "missing_requirement",
              "evidence_class": "measurement" if measurement and not synthetic else "record",
              "synthetic": synthetic, "subject": subject, "input_hashes": hashes,
              "requirement": report_values(requirement),
              "measurement": report_values({k: v for k, v in measurement.items() if k != "evidence_refs"}) if measurement else None,
              "verified_evidence_sha256": [], "physical_validation": "not_performed", "printer_ready": False,
              "unimplemented_gates": {"support_removal": "not_implemented", "physical_safety": "not_implemented"}}
    if requirement is None:
        return result, protected
    if measurement is None:
        result["reason"] = "missing_measurement"
        return result, protected
    digests, missing = verify_evidence(measurement, measurement_path, protected)
    result["verified_evidence_sha256"] = digests
    if missing:
        result["reason"] = "missing_evidence"
        return result, protected
    result["execution_status"] = "complete"
    policy = requirement["judgment_policy"]
    uncertainty = measurement["uncertainty"]
    if uncertainty["status"] == "unevaluated" and policy["unevaluated_uncertainty"] == "indeterminate":
        result["reason"] = "uncertainty_unevaluated"
        return result, protected
    lower = quantity(requirement["tolerance"]["lower"], "lower")
    upper = quantity(requirement["tolerance"]["upper"], "upper")
    value = quantity(measurement["value"], "value")
    if policy["name"] == "simple_acceptance_v1":
        result["judgment"] = "pass" if lower <= value <= upper else "fail"
        result["reason"] = "point_within_closed_bounds" if result["judgment"] == "pass" else "point_outside_closed_bounds"
    else:
        radius = quantity(uncertainty["value"], "uncertainty.value")
        low, high = value - radius, value + radius
        if lower <= low and high <= upper:
            result.update(judgment="pass", reason="interval_within_closed_bounds")
        elif high < lower or low > upper:
            result.update(judgment="fail", reason="interval_disjoint_from_closed_bounds")
        else:
            result["reason"] = "interval_overlaps_tolerance_boundary"
    return result, protected
