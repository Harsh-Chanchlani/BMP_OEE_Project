"""
OEE Message Schema Validator
==============================
Validates raw Kafka message bytes against the JSON schema defined in
schema/oee_message_schema.json before the producer sends them.

Raises SchemaValidationError (a subclass of Exception) on any failure
so the producer can log and skip the bad message without crashing.
"""

import json
import os

import jsonschema


class SchemaValidationError(Exception):
    """Raised when a message fails JSON schema validation."""

    def __init__(self, message: str, raw: bytes):
        super().__init__(message)
        self.raw = raw


def _load_schema() -> dict:
    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "schema", "oee_message_schema.json"
    )
    with open(schema_path) as f:
        return json.load(f)


# Load once at import time — avoids re-reading the file on every message
_SCHEMA = _load_schema()


def validate_message(raw: bytes) -> dict:
    """
    Decode, parse, and validate a raw Kafka message.

    Parameters
    ----------
    raw : bytes
        The raw Kafka message value.

    Returns
    -------
    dict
        The parsed and validated message as a Python dict.

    Raises
    ------
    SchemaValidationError
        If the bytes cannot be decoded, parsed as JSON, or validated
        against the OEE message schema.
    """
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SchemaValidationError(f"UTF-8 decode error: {exc}", raw)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"JSON parse error: {exc}", raw)

    try:
        jsonschema.validate(instance=parsed, schema=_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(f"Schema violation: {exc.message}", raw)

    return parsed
