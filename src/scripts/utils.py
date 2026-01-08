import os
import re
import sys
from pathlib import Path

import dotenv


def add_src_to_system_path() -> None:
    module_path = (Path(__file__).parent.parent).absolute()
    print(module_path)
    sys.path.append(str(module_path))


def load_env():
    dotenv_path = os.path.join(os.getcwd(), ".env")

    try:
        dotenv.load_dotenv(dotenv_path)
    except Exception as e:
        print(f"Failed to load .env: {e}")


def _replace_envs_dict(d: dict, prefix: str | None = None) -> dict:
    for key, value in d.items():
        if isinstance(value, str):
            d[key] = replace_env(value, prefix)
        elif isinstance(value, dict):
            d[key] = _replace_envs_dict(value, prefix)
    return d


def _replace_envs_str(value: str, prefix: str | None = None) -> str:
    """
    Finds all envs that match pattern $env:{env_name} and replaces them with the value of the environment variable
    :param value: string to replace envs in
    :return: string with replaced envs
    """
    pattern = r"\$env:{([^}]*)}"
    matches = re.finditer(pattern, value)

    result = value
    for match in matches:
        full_match = match.group(0)  # The entire match including $env:{}
        env_name = match.group(1)  # Just the variable name
        full_env_name = f"{prefix}{env_name}" if prefix else env_name

        # Get environment variable value, use empty string if not found
        env_value = os.environ.get(full_env_name)
        if env_value is None:
            continue

        # Replace the pattern with the environment variable value
        result = result.replace(full_match, env_value)

    return result


def replace_env(value: str, prefix: str | None = None) -> str:
    """
    Replaces environment variables in a string.
    Replaces patterns like $env:{env_name} with their environment variable values
    :param value: string to replace envs in
    :param prefix: in case prefix is defined only environment variables with this prefix will be replaced; prefix will
    be removed from the variable name
    :return: string with replaced envs
    """
    return _replace_envs_str(value, prefix)
