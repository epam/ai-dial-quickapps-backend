# CLI Script that dumps application schema to the specified output file.
# Usage example:
# python dump_app_schema.py output_schema.json

if __name__ == '__main__':
    from utils import add_src_to_system_path, load_env

    add_src_to_system_path()
    load_env()

import json

from quickapp.config.application import ApplicationConfig

DIAL_SCHEMA_PROPERTIES = {
    "dial:applicationTypeCompletionEndpoint": "http://<app-host>/openai/deployments/quick_apps/chat/completions",
    "dial:applicationTypeConfigurationEndpoint": "http://<app-host>/openai/deployments/quick_apps/configuration",
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

    print(f"Application schema dumped to {output_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Dump application schema to a file.")
    parser.add_argument("output_file", type=str, help="The output file path to dump the schema.")
    args = parser.parse_args()

    dump_app_schema(args.output_file)
