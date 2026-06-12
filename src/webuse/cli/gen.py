import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .common import print_jsonl

_CONFIG_NAMES = ("webuse.toml", "webuse.yaml", "webuse.yml")


def _module_name(value: str) -> str:
    module = re.sub(r"\W+", "_", value.strip().lower()).strip("_")
    if not module:
        raise SystemExit("gen requires a non-empty name")
    if module[0].isdigit():
        module = f"_{module}"
    return module


def _class_name(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    if not words:
        raise SystemExit("gen requires a non-empty name")
    name = "".join(word[:1].upper() + word[1:] for word in words)
    if name[0].isdigit():
        name = f"Spider{name}"
    if name == "Spider":
        return "GeneratedSpider"
    if not name.endswith("Spider"):
        name = f"{name}Spider"
    return name


def _is_project_dir(path: Path) -> bool:
    return any((path / name).exists() for name in _CONFIG_NAMES)


def _project_config_file(path: Path) -> Path:
    for name in _CONFIG_NAMES:
        candidate = path / name
        if candidate.exists():
            return candidate
    raise SystemExit(f"cannot find project config in {path}")


def _register_spider(project_dir: Path, name: str, path: Path, *, force: bool) -> None:
    config_path = _project_config_file(project_dir)
    relative_path = path.relative_to(project_dir).as_posix()
    if config_path.suffix == ".toml":
        text = config_path.read_text(encoding="utf-8")
        section = f"[spiders.{name}]"
        if section in text and not force:
            raise SystemExit(f"spider already registered in project config: {name}")
        if section in text:
            return
        suffix = "\n" if text.endswith("\n") else "\n\n"
        config_path.write_text(
            f'{text}{suffix}{section}\npath = "{relative_path}"\n',
            encoding="utf-8",
        )
        return

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise SystemExit(f"project config must be a mapping: {config_path}")
    spiders = config.setdefault("spiders", {})
    if not isinstance(spiders, dict):
        raise SystemExit("project config spiders must be a mapping")
    if name in spiders and not force:
        raise SystemExit(f"spider already registered in project config: {name}")
    spiders[name] = {"path": relative_path}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def _spider_config_toml(name: str, url: str) -> str:
    parsed = urlparse(url)
    allowed_domains = (
        f'allowed_domains = ["{parsed.netloc}"]\n' if parsed.netloc else ""
    )
    return f'''name = "{name}"
start_urls = ["{url}"]
{allowed_domains}max_depth = 1

[[pages.default.follow]]
css = "a"
same_domain = true

[pages.default.extract.{_module_name(name)}.fields]
title = "title"
'''


def _spider_config_yaml(name: str, url: str) -> str:
    parsed = urlparse(url)
    allowed_domains = (
        f"allowed_domains:\n  - {parsed.netloc}\n" if parsed.netloc else ""
    )
    return f"""name: {name}
start_urls:
  - {url}
{allowed_domains}max_depth: 1
pages:
  default:
    follow:
      - css: a
        same_domain: true
    extract:
      {_module_name(name)}:
        fields:
          title: title
"""


def _spider_template(
    name: str,
    url: str,
    *,
    config_suffix: str | None = None,
    project_mode: bool = False,
) -> str:
    parsed = urlparse(url)
    allowed_domain = parsed.netloc
    class_name = _class_name(name)
    module = _module_name(name)
    if config_suffix:
        config_path = (
            f"spiders/{module}{config_suffix}"
            if project_mode
            else f"{module}{config_suffix}"
        )
        item_model = '    item_model = "items.BookItem"\n' if project_mode else ""
        return f"""import webuse


class {class_name}(webuse.Spider):
    spider_config_path = "{config_path}"
{item_model}

def main():
    {class_name}().run()


if __name__ == "__main__":
    main()
"""

    allowed_domains = (
        f'    allowed_domains = {{"{allowed_domain}"}}\n' if allowed_domain else ""
    )
    item_model = '    item_model = "items.BookItem"\n' if project_mode else ""
    return f'''import webuse


class {class_name}(webuse.Spider):
    name = "{name}"
{item_model}    start_urls = ["{url}"]
{allowed_domains}    max_depth = 1

    follow = [
        webuse.FollowRule(css="a", same_domain=True),
    ]

    extract = {{
        "fields": {{
            "title": "title",
        }},
    }}


def main():
    {class_name}().run()


if __name__ == "__main__":
    main()
'''


def gen_command(args: argparse.Namespace) -> int:
    target = Path(args.directory)
    if target.exists() and not target.is_dir():
        raise SystemExit(f"gen target exists and is not a directory: {target}")
    if sum(bool(value) for value in (args.python, args.toml, args.yaml)) > 1:
        raise SystemExit("Use only one of --python, --toml, or --yaml")

    project_mode = target.exists() and _is_project_dir(target)
    module = _module_name(args.name)
    output_dir = target / "spiders" if project_mode else target
    path = output_dir / f"{module}.py"
    use_python = args.python
    use_toml = args.toml
    use_yaml = args.yaml or not (args.python or args.toml)
    standalone_config_only = not project_mode and not use_python
    if not standalone_config_only and path.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing file: {path}")

    config_path = None
    config_content = None
    config_suffix = None
    if use_toml:
        config_path = output_dir / f"{module}.toml"
        config_content = _spider_config_toml(args.name, args.url)
        config_suffix = ".toml"
    elif use_yaml:
        config_path = output_dir / f"{module}.yaml"
        config_content = _spider_config_yaml(args.name, args.url)
        config_suffix = ".yaml"
    if config_path is not None and config_path.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing file: {config_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"name": args.name, "url": args.url}
    if not standalone_config_only:
        path.write_text(
            _spider_template(
                args.name,
                args.url,
                config_suffix=config_suffix,
                project_mode=project_mode,
            ),
            encoding="utf-8",
        )
        payload["path"] = str(path)
    if config_path is not None and config_content is not None:
        config_path.write_text(config_content, encoding="utf-8")
        payload["config"] = str(config_path)
    if project_mode:
        _register_spider(target, module, path, force=args.force)
    print_jsonl([payload])
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    gen_parser = subparsers.add_parser("gen")
    gen_parser.add_argument("name")
    gen_parser.add_argument("url")
    gen_parser.add_argument("--directory", default=".")
    gen_parser.add_argument("--force", action="store_true")
    gen_parser.add_argument("--python", action="store_true")
    gen_parser.add_argument("--toml", action="store_true")
    gen_parser.add_argument("--yaml", action="store_true")
    gen_parser.set_defaults(func=gen_command)
