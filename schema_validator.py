import json
import jsonschema
import os

class SchemaValidationError(Exception):
    def __init__(self, message, raw):
        super().__init__(message)
        self.raw = raw

def load_schema():
    schema_path = os.path.join(os.path.dirname(__file__), "schema", "oee_message_schema.json")
    with open(schema_path, "r") as f:
        return json.load(f)

# Cache the schema at module level
SCHEMA = load_schema()

def validate_message(raw: bytes) -> dict:
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SchemaValidationError(f"Decode error: {str(e)}", raw)

    try:
        parsed = json.loads(decoded)
    except json.JSONDecodeError as e:
        raise SchemaValidationError(f"JSON parse error: {str(e)}", raw)

    try:
        jsonschema.validate(instance=parsed, schema=SCHEMA)
    except jsonschema.ValidationError as e:
        raise SchemaValidationError(f"Schema violation: {e.message}", raw)

    return parsed
