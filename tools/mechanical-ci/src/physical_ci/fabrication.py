"""Strict operator observations bound to an independent specimen and part record.

This records declared facts; it never judges fit, strength, or printer readiness.
The artifact digest is a binding string, not verification of CAD/STL bytes.
"""
from decimal import Decimal, DecimalException

from . import __version__
from .errors import InputError
from .inspection import (BindingMismatch, SUBJECT_FIELDS, error_report, load_json,
                         quantity, text, validate_subject, versioned)
from .manifest import keys

PART_FIELDS = ("part_id", "design_revision", "artifact_sha256")
CONDITION_FIELDS = ("printer_ref", "material_ref", "profile_ref", "nozzle_diameter_mm",
                    "layer_height_mm", "orientation")


def load_record(path):
    try:
        return load_json(path)
    except DecimalException as error:
        # Even a short JSON exponent can exceed the Decimal constructor range.
        raise InputError("unsupported fabrication JSON number") from error


def validate_part(data):
    versioned(data, PART_FIELDS, "part")
    for field in PART_FIELDS:
        text(data[field], field)
    digest = data["artifact_sha256"]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise InputError("artifact_sha256 must be lowercase SHA256")


def validate_condition(data, label, kind="text"):
    if not isinstance(data, dict):
        raise InputError(f"{label} must explicitly be known or unknown")
    if data.get("status") == "unknown":
        keys(data, ("status", "reason"), label=label)
        text(data["reason"], f"{label}.reason")
    elif data.get("status") == "known":
        keys(data, ("status", "value"), label=label)
        value = data["value"]
        if kind == "positive_mm":
            if quantity(value, f"{label}.value") <= 0:
                raise InputError(f"{label}.value must be positive")
        elif kind == "orientation":
            keys(value, ("frame", "description"), label=label)
            text(value["frame"], f"{label}.frame")
            text(value["description"], f"{label}.description")
        else:
            text(value, f"{label}.value")
    else:
        raise InputError(f"{label} must explicitly be known or unknown")


def validate_observation(data):
    versioned(data, (*SUBJECT_FIELDS, *PART_FIELDS, "process_state", "source_kind",
                     "print_conditions", "support_removal", "fit_observation"), "fabrication observation")
    for field in (*SUBJECT_FIELDS, "process_state"):
        text(data[field], field)
    validate_part({"schema_version": data["schema_version"], **{k: data[k] for k in PART_FIELDS}})
    if data["source_kind"] not in ("human_observation", "synthetic"):
        raise InputError("source_kind must be human_observation or synthetic")
    conditions = data["print_conditions"]
    keys(conditions, CONDITION_FIELDS, label="print_conditions")
    for field in CONDITION_FIELDS:
        kind = "positive_mm" if field.endswith("_mm") else "orientation" if field == "orientation" else "text"
        validate_condition(conditions[field], f"print_conditions.{field}", kind)
    support = data["support_removal"]
    keys(support, ("status", "description"), label="support_removal")
    if support["status"] not in ("removed", "partial", "not_performed", "unknown"):
        raise InputError("unsupported support_removal status")
    text(support["description"], "support_removal.description")
    fit = data["fit_observation"]
    keys(fit, ("status", "target_ref", "description"), label="fit_observation")
    if fit["status"] not in ("assembled", "interference", "not_tested", "unknown"):
        raise InputError("unsupported fit_observation status")
    validate_condition(fit["target_ref"], "fit_observation.target_ref")
    if fit["status"] in ("assembled", "interference") and fit["target_ref"]["status"] != "known":
        raise InputError("attempted fit requires a declared target_ref")
    text(fit["description"], "fit_observation.description")


def report_observation(value):
    """Keep structured orientation values; report declared mm without rounding."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: str(item) if key == "value" and type(item) in (int, Decimal)
                else report_observation(item) for key, item in value.items()}
    return value


def fabrication_error_report(kind):
    result = error_report(kind)
    result.update(command="record-fabrication", artifact_hash_verification="not_performed")
    return result


def record_fabrication(subject_path, part_path, observation_path):
    subject, subject_digest = load_record(subject_path)
    validate_subject(subject)
    part, part_digest = load_record(part_path)
    validate_part(part)
    observation, observation_digest = load_record(observation_path)
    validate_observation(observation)
    for expected, fields in ((subject, SUBJECT_FIELDS), (part, PART_FIELDS)):
        for field in fields:
            if observation[field] != expected[field]:
                raise BindingMismatch(f"binding mismatch: {field}")
    synthetic = observation["source_kind"] == "synthetic"
    result = {"schema_version": 1, "tool_version": __version__, "command": "record-fabrication",
              "execution_status": "complete", "judgment": "not_applicable", "reason": "observation_recorded",
              "evidence_class": "record" if synthetic else "observation", "synthetic": synthetic,
              "subject": subject, "part": part, "observation": report_observation(observation),
              "input_hashes": {"subject_sha256": subject_digest, "part_sha256": part_digest,
                               "observation_sha256": observation_digest},
              "artifact_hash_verification": "not_performed", "physical_validation": "not_performed",
              "printer_ready": False,
              "unimplemented_gates": {"support_removal": "not_implemented", "physical_safety": "not_implemented"}}
    return result, [subject_path, part_path, observation_path]
