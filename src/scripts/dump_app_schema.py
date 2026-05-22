# CLI Script that dumps application schema to the specified output file.
# Usage example:
# python dump_app_schema.py output_schema.json
# python dump_app_schema.py output_schema.json --check

if __name__ == '__main__':
    import os

    from utils import add_src_to_system_path, load_env

    add_src_to_system_path()
    load_env()
    # Keep the committed schema baseline independent of a developer's local default.
    # The env value is a per-deployment operator choice; it must not bake into the
    # checked-in schema that `make lint` validates against.
    os.environ.pop("DEFAULT_ORCHESTRATOR_DEPLOYMENT_ID", None)

import json

from quickapp.common.dial_schema import DialJSONSchemaExtensions
from quickapp.config.application import ApplicationConfig

DIAL_SCHEMA_PROPERTIES = {
    DialJSONSchemaExtensions.COMPLETION_ENDPOINT: "<quickapps_base_url>/openai/deployments/quick_apps/chat/completions",
    DialJSONSchemaExtensions.CONFIGURATION_ENDPOINT: "<quickapps_base_url>/openai/deployments/quick_apps/configuration",
}


def add_dial_properties(schema: dict) -> dict:
    """
    Adds DIAL-specific properties to the schema.
    Args:
        schema (dict): The original schema to which DIAL properties will be added.
    Returns:
        dict: The updated schema with DIAL properties added.
    """

    return {
        **DIAL_SCHEMA_PROPERTIES,
        **schema,
    }


def get_quickapp_schema() -> dict:
    """
    Retrieves the Quick App schema with DIAL properties added.

    Returns:
        dict: The Quick App schema with DIAL properties.
    """

    schema = ApplicationConfig.model_json_schema()
    schema = add_dial_properties(schema)
    return schema


def dump_app_schema(output_file: str) -> None:
    """
    Dumps the application schema to the specified output file.

    Args:
        output_file (str): The path to the output file where the schema will be dumped.
    """

    schema = get_quickapp_schema()

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print(f"Application schema dumped to {output_file}")


def check_app_schema(output_file: str) -> None:
    """
    Checks that the committed schema file matches the current generated schema.
    Exits with non-zero code if they differ.

    Args:
        output_file (str): The path to the schema file to check against.
    """
    import sys

    schema = get_quickapp_schema()
    generated = json.dumps(schema, ensure_ascii=False, indent=2) + '\n'

    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            existing = f.read()
    except FileNotFoundError:
        print(f"ERROR: Schema file '{output_file}' not found. Run 'make format' to generate it.")
        sys.exit(1)

    if generated != existing:
        print(
            f"ERROR: Schema file '{output_file}' is out of date. "
            f"Run 'make format' to regenerate it."
        )
        sys.exit(1)

    print(f"Schema file '{output_file}' is up to date.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dump application schema to a file.")
    parser.add_argument("output_file", type=str, help="The output file path to dump the schema.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that the schema file is up to date instead of overwriting it.",
    )
    args = parser.parse_args()

    if args.check:
        check_app_schema(args.output_file)
    else:
        dump_app_schema(args.output_file)
