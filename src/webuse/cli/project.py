"""Project discovery shared by crawler CLI commands."""

from pathlib import Path

from pydantic import ValidationError

from ..config import load_config_file
from ..spider.config import ProjectConfig


CONFIG_NAMES = ("webuse.toml", "webuse.yaml", "webuse.yml")


def project_config_path(directory: Path) -> Path:
    for name in CONFIG_NAMES:
        path = directory / name
        if path.is_file():
            return path
    raise SystemExit(
        f"cannot find webuse.yaml (or webuse.yml/webuse.toml) in {directory}; "
        "create a project with 'webuse create DIRECTORY'"
    )


def require_project_dir(value: str | Path) -> Path:
    directory = Path(value).resolve()
    if not directory.is_dir():
        raise SystemExit(
            "expected a project directory containing webuse.yaml"
        )
    project_config_path(directory)
    return directory


def load_project_config(directory: Path) -> ProjectConfig:
    path = project_config_path(directory)
    try:
        return ProjectConfig.model_validate(load_config_file(path))
    except ValidationError as exc:
        raise SystemExit(f"invalid project config: {path}: {exc}") from exc
