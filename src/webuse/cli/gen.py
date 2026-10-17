import argparse
import re
import tomllib
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .utils import print_jsonl
from .project import load_project_config, project_config_path, require_project_dir


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


def _registered_config(
    project_dir: Path, name: str, path: Path, *, force: bool
) -> tuple[Path, str]:
    config_path = project_config_path(project_dir)
    existing = load_project_config(project_dir)
    if name in existing.spiders and not force:
        raise SystemExit(f"spider already registered in project config: {name}")
    relative_path = path.relative_to(project_dir).as_posix()
    if config_path.suffix == ".toml":
        text = config_path.read_text(encoding="utf-8")
        section = f"[spiders.{name}]"
        replacement = f'{section}\npath = "{relative_path}"\n\n'
        if name in existing.spiders:
            pattern = rf"(?ms)^{re.escape(section)}[^\n]*\n.*?(?=^\[|\Z)"
            text, count = re.subn(pattern, lambda match: replacement, text, count=1)
            if count != 1:
                raise SystemExit(
                    f"edit the existing inline TOML spider registration manually: {name}"
                )
        else:
            suffix = "\n" if text.endswith("\n") else "\n\n"
            text = f"{text}{suffix}{replacement}"
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise SystemExit(
                "cannot extend inline TOML spider registrations; "
                "use [spiders.NAME] tables before generating a spider"
            ) from exc
        return config_path, text

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(config, dict):
        raise SystemExit(f"project config must be a mapping: {config_path}")
    spiders = config.setdefault("spiders", {})
    if not isinstance(spiders, dict):
        raise SystemExit("project config spiders must be a mapping")
    if name in spiders and not force:
        raise SystemExit(f"spider already registered in project config: {name}")
    spiders[name] = {"path": relative_path}
    return config_path, yaml.safe_dump(config, sort_keys=False)


def _spider_config_toml(name: str, url: str, *, pipelines: list[dict[str, str]]) -> str:
    parsed = urlparse(url)
    allowed_domains = (
        f'allowed_domains = ["{parsed.netloc}"]\n' if parsed.netloc else ""
    )
    pipeline_config = ""
    if pipelines:
        entries = "\n".join(
            "  { " + ", ".join(f'{key} = "{value}"' for key, value in spec.items()) + " },"
            for spec in pipelines
        )
        pipeline_config = f"pipelines = [\n{entries}\n]\n"
    return f'''name = "{name}"
start_urls = ["{url}"]
{allowed_domains}max_depth = 1
{pipeline_config}

[[pages.default.follow]]
css = "a"
same_domain = true

[pages.default.extract.{_module_name(name)}.fields]
title = "title"
'''


def _spider_config_yaml(name: str, url: str, *, pipelines: list[dict[str, str]]) -> str:
    parsed = urlparse(url)
    allowed_domains = (
        f"allowed_domains:\n  - {parsed.netloc}\n" if parsed.netloc else ""
    )
    pipeline_config = (
        yaml.safe_dump({"pipelines": pipelines}, sort_keys=False)
        if pipelines
        else ""
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
{pipeline_config}"""


def _spider_template(
    name: str,
    url: str,
    *,
    config_suffix: str | None = None,
    asynchronous: bool = False,
) -> str:
    parsed = urlparse(url)
    allowed_domain = parsed.netloc
    class_name = _class_name(name)
    base_class = "AsyncSpider" if asynchronous else "Spider"
    module = _module_name(name)
    definitions = '''import webuse
from pydantic import BaseModel


class Item(BaseModel):
    title: str


class CleanPipeline(webuse.ItemPipeline):
    def process_item(self, item: Item):
        return item


'''
    if config_suffix:
        config_path = f"spiders/{module}{config_suffix}"
        return definitions + f'''class {class_name}(webuse.{base_class}):
    spider_config_path = "{config_path}"
    item_model = Item
'''

    allowed_domains = (
        f'    allowed_domains = {{"{allowed_domain}"}}\n' if allowed_domain else ""
    )
    return definitions + f'''class {class_name}(webuse.{base_class}):
    name = "{name}"
    item_model = Item
    pipelines = [
        CleanPipeline(),
        {{"type": "jsonl", "path": "output.jsonl"}},
    ]
    start_urls = ["{url}"]
{allowed_domains}    max_depth = 1

    follow = [
        webuse.FollowRule(css="a", same_domain=True),
    ]

    extract = {{
        "default": {{
            "{module}": {{
                "fields": {{"title": "title"}},
            }},
        }},
    }}
'''


def gen_command(args: argparse.Namespace) -> int:
    target = Path(args.directory)
    if target.exists() and not target.is_dir():
        raise SystemExit(f"gen target exists and is not a directory: {target}")
    if sum(bool(value) for value in (args.python_only, args.toml, args.yaml)) > 1:
        raise SystemExit("Use only one of --python-only, --toml, or --yaml")

    target = require_project_dir(target)
    module = _module_name(args.name)
    output_dir = target / "spiders"
    path = output_dir / f"{module}.py"
    use_toml = args.toml
    use_yaml = args.yaml or not (args.python_only or args.toml)
    if path.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing file: {path}")

    config_path = None
    config_content = None
    config_suffix = None
    pipelines = [
        {"class": f"spiders.{module}.CleanPipeline"},
        {"type": "jsonl", "path": "output.jsonl"},
    ]
    if use_toml:
        config_path = output_dir / f"{module}.toml"
        config_content = _spider_config_toml(args.name, args.url, pipelines=pipelines)
        config_suffix = ".toml"
    elif use_yaml:
        config_path = output_dir / f"{module}.yaml"
        config_content = _spider_config_yaml(args.name, args.url, pipelines=pipelines)
        config_suffix = ".yaml"
    if config_path is not None and config_path.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing file: {config_path}")

    project_path, project_content = _registered_config(
        target, module, path, force=args.force
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"name": args.name, "url": args.url}
    path.write_text(
        _spider_template(
            args.name,
            args.url,
            config_suffix=config_suffix,
            asynchronous=args.async_spider,
        ),
        encoding="utf-8",
    )
    payload["path"] = str(path)
    if config_path is not None and config_content is not None:
        config_path.write_text(config_content, encoding="utf-8")
        payload["config"] = str(config_path)
    project_path.write_text(project_content, encoding="utf-8")
    print_jsonl([payload])
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    gen_parser = subparsers.add_parser(
        "gen", help="add a spider to an existing project"
    )
    gen_parser.add_argument("name")
    gen_parser.add_argument("url")
    gen_parser.add_argument(
        "--directory", default=".", help="existing project directory"
    )
    gen_parser.add_argument("--force", action="store_true")
    gen_parser.add_argument(
        "--async",
        dest="async_spider",
        action="store_true",
        help="generate an AsyncSpider (works with any output format)",
    )
    gen_parser.add_argument(
        "--python-only",
        action="store_true",
        help="generate a Python-only spider without a separate config file",
    )
    gen_parser.add_argument("--toml", action="store_true")
    gen_parser.add_argument("--yaml", action="store_true")
    gen_parser.set_defaults(func=gen_command)
