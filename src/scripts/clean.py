import glob
import os
import shutil


def remove_dir(directory_path: str):
    if os.path.exists(directory_path):
        shutil.rmtree(directory_path)
        print("Removed: " + directory_path)


def remove_recursively(pattern: str, exclude_dirs: list[str] | None = None):
    if exclude_dirs is None:
        exclude_dirs = []

    files = glob.glob(f"**/{pattern}", recursive=True)

    def is_excluded(file_path: str) -> bool:
        return any(dir_str in file_path for dir_str in exclude_dirs)

    for file in files:
        if not is_excluded(file):
            remove_dir(file)


def main():
    remove_dir("dist")
    remove_recursively("__pycache__", exclude_dirs=[".venv"])
    remove_recursively(".pytest_cache", exclude_dirs=[".venv"])


if __name__ == "__main__":
    main()
