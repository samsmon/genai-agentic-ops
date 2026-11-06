"""Contract validation tests for genai-agentic-ops JSON schemas.

Validates that all core schemas (config, agent-registry, plan, task,
handoff, result, run) comply with JSON Schema Draft-07 and correctly
accept valid fixtures while rejecting invalid payloads and unauthorized fields.

Run: python -I kit/tests/test_contracts.py
"""
import json
import os
import sys

try:
    import jsonschema
    from jsonschema import Draft7Validator, ValidationError
except ImportError:
    print("FAIL: jsonschema package is required to run contract tests")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CONTRACTS_DIR = os.path.join(REPO_ROOT, "contracts")
FIXTURES_DIR = os.path.join(HERE, "fixtures", "contracts")

SCHEMAS = [
    "config",
    "agent-registry",
    "plan",
    "task",
    "handoff",
    "result",
    "run",
]

fail = 0


def expect(name: str, ok: bool, details: str = ""):
    global fail
    status = "ok   " if ok else "FAIL "
    msg = f"{status}{name}"
    if not ok and details:
        msg += f" - {details}"
    print(msg)
    if not ok:
        fail += 1


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    global fail

    for schema_name in SCHEMAS:
        schema_path = os.path.join(CONTRACTS_DIR, f"{schema_name}.schema.json")
        valid_fixture_path = os.path.join(FIXTURES_DIR, f"{schema_name}.valid.json")
        invalid_fixture_path = os.path.join(FIXTURES_DIR, f"{schema_name}.invalid.json")

        # 1. Check schema file exists
        if not os.path.isfile(schema_path):
            expect(f"{schema_name}: schema file exists", False, f"Missing: {schema_path}")
            continue

        try:
            schema = load_json(schema_path)
            Draft7Validator.check_schema(schema)
            expect(f"{schema_name}: draft-07 meta-schema validation", True)
        except Exception as e:
            expect(f"{schema_name}: draft-07 meta-schema validation", False, str(e))
            continue

        validator = Draft7Validator(schema)

        # 2. Check valid fixture passes
        if not os.path.isfile(valid_fixture_path):
            expect(f"{schema_name}: valid fixture exists", False, f"Missing: {valid_fixture_path}")
        else:
            try:
                valid_data = load_json(valid_fixture_path)
                validator.validate(valid_data)
                expect(f"{schema_name}: valid fixture accepted", True)
            except ValidationError as e:
                expect(f"{schema_name}: valid fixture accepted", False, f"Path {list(e.path)}: {e.message}")

        # 3. Check invalid fixture is rejected
        if not os.path.isfile(invalid_fixture_path):
            expect(f"{schema_name}: invalid fixture exists", False, f"Missing: {invalid_fixture_path}")
        else:
            try:
                invalid_data = load_json(invalid_fixture_path)
                validator.validate(invalid_data)
                expect(f"{schema_name}: invalid fixture rejected", False, "Expected ValidationError but passed")
            except ValidationError:
                expect(f"{schema_name}: invalid fixture rejected", True)

        # 4. Check additionalProperties rejection on top-level
        if os.path.isfile(valid_fixture_path):
            try:
                mutated = load_json(valid_fixture_path)
                mutated["__unauthorized_extra_field__"] = "should_fail"
                validator.validate(mutated)
                expect(f"{schema_name}: additionalProperties rejected", False, "Allowed unauthorized field")
            except ValidationError:
                expect(f"{schema_name}: additionalProperties rejected", True)

    print(f"\n[CONTRACTS] {fail} failure(s)")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
