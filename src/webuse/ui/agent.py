import json
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..config import load_webuse_config
from ..exceptions import ConfigError
from ..llm import create_openai_client, openai_settings_from_config
from ..spider.config import ProjectConfig, SpiderConfig
from ..crawl.utils import follow_rule_from_config


MAX_TOOL_STEPS = 20
MAX_COMMAND_OUTPUT = 24_000
COMMAND_TIMEOUT_SECONDS = 30
SKILL_PACKAGE = "webuse.ui.skills"
SKILL_FILE = "webuse_project.md"
DOC_TOPICS = {
    "layout": "Project Layout",
    "yaml": "YAML Spider Config",
    "follow": "YAML Spider Config",
    "extract": "Extraction",
    "python": "Python Spiders",
    "validation": "Validation And Checks",
}

SYSTEM_PROMPT = """You are the Webuse project assistant.

You work only on the current webuse scraping project.

Rules:
- Use the packaged Webuse Project Skill and current project context.
- Inspect files before making non-trivial edits.
- Use tools to edit files; do not claim edits unless a file tool succeeded.
- Keep project files small and focused.
- Run CLI checks only through run_webuse. Never ask for shell access.
- Use validate_webuse_yaml after editing webuse.yaml.
- Use preview_workflow when reasoning about crawl flow.
- Explain what changed and mention files touched.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_project_docs",
            "description": "Read a focused section from the built-in Webuse Project Skill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "One of: layout, yaml, follow, extract, python, validation.",
                    }
                },
                "required": ["topic"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in the current webuse project.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from the current webuse project.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or replace a text file in the current webuse project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file from the current webuse project.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_webuse_yaml",
            "description": "Parse and validate a webuse YAML spider config in the current project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "YAML file path. Defaults to webuse.yaml.",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_workflow",
            "description": "Return a compact workflow graph for a webuse YAML spider config.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "YAML file path. Defaults to webuse.yaml.",
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_webuse",
            "description": "Run the webuse CLI in the current project workspace. Pass only webuse arguments, not the command name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
                "required": ["args"],
                "additionalProperties": False,
            },
        },
    },
]


def run_project_assistant(
    *,
    project_id: int,
    session_id: int,
    files: list[dict[str, str]],
    selected_path: str | None,
    history: list[dict[str, Any]],
    user_message: str,
    work_dir: Path,
) -> dict[str, Any]:
    normalized_files = _normalize_files(files)
    project_dir = work_dir / "assistant" / str(project_id) / str(session_id) / "project"
    _materialize_files(project_dir, normalized_files)

    messages = _openai_messages(
        history,
        user_message,
        project_context=_project_context(normalized_files, selected_path),
    )
    settings = openai_settings_from_config(load_webuse_config().get("llm"))
    client = create_openai_client(settings=settings)
    model = settings.model or "gpt-4.1-mini"
    tool_results: list[dict[str, Any]] = []
    assistant_message: Any = None

    for _ in range(MAX_TOOL_STEPS):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        assistant_message = response.choices[0].message
        tool_calls = getattr(assistant_message, "tool_calls", None) or []
        if not tool_calls:
            break
        messages.append(_message_to_dict(assistant_message))
        for tool_call in tool_calls:
            try:
                result = _execute_tool(project_dir, tool_call)
                ok = True
            except Exception as exc:
                result = {"error": str(exc)}
                ok = False
            tool_results.append(
                {
                    "name": tool_call.function.name,
                    "ok": ok,
                    "result": result,
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                }
            )

    if assistant_message is None or getattr(assistant_message, "tool_calls", None):
        raise RuntimeError(
            f"LLM did not finish after {MAX_TOOL_STEPS} tool steps. "
            "Increase MAX_TOOL_STEPS in src/webuse/ui/agent.py if this project needs longer assistant runs."
        )

    next_files = _walk_files(project_dir)
    paths = {file["path"] for file in next_files}
    return {
        "content": getattr(assistant_message, "content", None) or "",
        "files": next_files,
        "changedFiles": _changed_paths(normalized_files, next_files),
        "selectedPath": selected_path if selected_path in paths else (next_files[0]["path"] if next_files else ""),
        "toolResults": tool_results,
    }


def _message_to_dict(message: Any) -> dict[str, Any]:
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    if isinstance(message, dict):
        return message
    return {"role": "assistant", "content": getattr(message, "content", "") or ""}


def _openai_messages(
    history: list[dict[str, Any]],
    user_message: str,
    *,
    project_context: str,
) -> list[dict[str, Any]]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": "Built-in Webuse Project Skill:\n\n" + _load_skill_text(),
        },
        {"role": "system", "content": project_context},
    ]
    for message in history:
        if message.get("role") in {"user", "assistant"}:
            messages.append({"role": message["role"], "content": message.get("content", "")})
    messages.append({"role": "user", "content": user_message})
    return messages


def _load_skill_text() -> str:
    return resources.files(SKILL_PACKAGE).joinpath(SKILL_FILE).read_text(encoding="utf-8")


def _read_project_docs(topic: Any) -> dict[str, Any]:
    if not isinstance(topic, str):
        raise ValueError("topic must be a string")
    normalized = topic.strip().lower().replace("_", "-")
    heading = DOC_TOPICS.get(normalized)
    if heading is None:
        return {
            "topic": normalized,
            "availableTopics": sorted(DOC_TOPICS),
            "content": "",
            "error": f"unknown topic: {topic}",
        }
    return {
        "topic": normalized,
        "heading": heading,
        "content": _skill_section(heading),
    }


def _skill_section(heading: str) -> str:
    text = _load_skill_text()
    marker = f"## {heading}"
    start = text.find(marker)
    if start < 0:
        return text
    next_heading = text.find("\n## ", start + len(marker))
    if next_heading < 0:
        return text[start:].strip()
    return text[start:next_heading].strip()


def _project_context(files: list[dict[str, str]], selected_path: str | None) -> str:
    paths = [file["path"] for file in files]
    yaml_file = _find_yaml_file(files)
    python_files = [path for path in paths if path.endswith(".py")]
    mode = "yaml" if yaml_file else "python" if python_files else "empty"
    lines = [
        "Current project context:",
        f"- mode: {mode}",
        f"- selected_path: {selected_path or ''}",
        f"- files: {', '.join(paths) if paths else '(none)'}",
    ]
    if yaml_file:
        lines.extend(_yaml_context_lines(yaml_file["path"], yaml_file["content"]))
    elif python_files:
        lines.append(f"- python_spiders: {', '.join(python_files)}")
    else:
        lines.append("- no webuse.yaml or Python spider detected")
    return "\n".join(lines)


def _find_yaml_file(files: list[dict[str, str]]) -> dict[str, str] | None:
    for name in ("webuse.yaml", "webuse.yml"):
        for file in files:
            if file["path"] == name:
                return file
    for file in files:
        if file["path"].endswith((".yaml", ".yml")):
            return file
    return None


def _yaml_context_lines(path: str, content: str) -> list[str]:
    validation = _validate_yaml_content(path, content)
    lines = [
        f"- yaml_path: {path}",
        f"- yaml_valid: {validation['ok']}",
    ]
    summary = validation.get("summary")
    if isinstance(summary, dict):
        if summary.get("spiders"):
            lines.append(f"- spiders: {', '.join(summary.get('spiders', []))}")
        lines.append(f"- start_urls: {', '.join(summary.get('startUrls', [])) or '(none)'}")
        lines.append(f"- allowed_domains: {', '.join(summary.get('allowedDomains', [])) or '(none)'}")
        lines.append(f"- pages: {', '.join(summary.get('pages', [])) or '(none)'}")
        lines.append(f"- follow_rules: {summary.get('followRuleCount', 0)}")
        lines.append(f"- item_types: {summary.get('itemTypes', {})}")
    errors = validation.get("errors") or []
    if errors:
        lines.append("- yaml_errors: " + "; ".join(str(error) for error in errors[:3]))
    warnings = validation.get("warnings") or []
    if warnings:
        lines.append("- yaml_warnings: " + "; ".join(str(warning) for warning in warnings[:3]))
    return lines


def _sanitize_path(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("path must be a string")
    normalized = value.strip().replace("\\", "/")
    parts = normalized.split("/")
    if not normalized or normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid project file path: {value}")
    return normalized


def _project_path(root: Path, relative_path: Any) -> tuple[str, Path]:
    clean_path = _sanitize_path(relative_path)
    root = root.resolve()
    file_path = (root / clean_path).resolve()
    if root != file_path and root not in file_path.parents:
        raise ValueError(f"invalid project file path: {relative_path}")
    return clean_path, file_path


def _normalize_files(files: Any) -> list[dict[str, str]]:
    if not isinstance(files, list):
        raise ValueError("files must be an array")
    seen: set[str] = set()
    normalized = []
    for file in files:
        if not isinstance(file, dict):
            raise ValueError("file entries must be objects")
        file_path = _sanitize_path(file.get("path"))
        if file_path in seen:
            raise ValueError(f"duplicate file path: {file_path}")
        content = file.get("content")
        if not isinstance(content, str):
            raise ValueError(f"file content must be text: {file_path}")
        seen.add(file_path)
        normalized.append({"path": file_path, "content": content})
    return normalized


def _materialize_files(project_dir: Path, files: list[dict[str, str]]) -> None:
    shutil.rmtree(project_dir, ignore_errors=True)
    project_dir.mkdir(parents=True, exist_ok=True)
    for file in files:
        _, file_path = _project_path(project_dir, file["path"])
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file["content"], encoding="utf-8")


def _walk_files(root: Path) -> list[dict[str, str]]:
    files = []
    if not root.exists():
        return files
    for file_path in sorted(path for path in root.rglob("*") if path.is_file()):
        if any(part in {"__pycache__", ".venv", "node_modules"} for part in file_path.parts):
            continue
        relative = file_path.relative_to(root).as_posix()
        files.append({"path": relative, "content": file_path.read_text(encoding="utf-8")})
    return files


def _changed_paths(before: list[dict[str, str]], after: list[dict[str, str]]) -> list[str]:
    before_map = {file["path"]: file["content"] for file in before}
    after_map = {file["path"]: file["content"] for file in after}
    return sorted(path for path in set(before_map) | set(after_map) if before_map.get(path) != after_map.get(path))


def _validate_webuse_yaml(project_dir: Path, path: Any = None) -> dict[str, Any]:
    clean_path, file_path = _project_path(project_dir, path or "webuse.yaml")
    return _validate_yaml_content(clean_path, file_path.read_text(encoding="utf-8"))


def _validate_yaml_content(path: str, content: str) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        parsed = yaml.safe_load(content) or {}
    except yaml.YAMLError as exc:
        return {
            "ok": False,
            "path": path,
            "errors": [str(exc)],
            "warnings": [],
            "summary": None,
        }
    if not isinstance(parsed, dict):
        return {
            "ok": False,
            "path": path,
            "errors": ["webuse YAML must be a mapping at the top level"],
            "warnings": [],
            "summary": None,
        }

    if Path(path).name in {"webuse.yaml", "webuse.yml", "webuse.toml"}:
        try:
            ProjectConfig.model_validate(parsed)
        except ValidationError as exc:
            errors.append(str(exc))
        spiders = parsed.get("spiders")
        if not isinstance(spiders, dict) or not spiders:
            errors.append("webuse.yaml must define a non-empty spiders mapping")
        elif isinstance(spiders, dict):
            for name, spec in spiders.items():
                if not isinstance(spec, dict):
                    errors.append(f"spiders.{name} must be a mapping")
                    continue
                if any(key in spec for key in ("path", "module", "config")):
                    continue
                try:
                    SpiderConfig.model_validate({**spec, "name": spec.get("name") or str(name)})
                except ValidationError as exc:
                    errors.append(f"spiders.{name}: {exc}")
                if "start_urls" not in spec:
                    warnings.append(f"spiders.{name}.start_urls is not configured")
                if "pages" not in spec:
                    warnings.append(f"spiders.{name}.pages is not configured")
                errors.extend(_validate_pages(spec.get("pages"), f"spiders.{name}.pages"))
    else:
        try:
            SpiderConfig.model_validate(parsed)
        except ValidationError as exc:
            errors.append(str(exc))
        if "start_urls" not in parsed:
            warnings.append("start_urls is not configured")
        if "pages" not in parsed:
            warnings.append("pages is not configured")
        errors.extend(_validate_pages(parsed.get("pages"), "pages"))
    return {
        "ok": not errors,
        "path": path,
        "errors": errors,
        "warnings": warnings,
        "summary": _summarize_yaml(parsed),
    }


def _validate_pages(value: Any, label: str = "pages") -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{label} must be a mapping"]
    errors = []
    for category, page in value.items():
        if not isinstance(page, dict):
            errors.append(f"{label}.{category} must be a mapping")
            continue
        errors.extend(_validate_follow_rules(page.get("follow"), f"{label}.{category}.follow"))
        if "extract" in page:
            errors.extend(_validate_extract_rules(page["extract"], f"{label}.{category}.extract"))
    return errors


def _validate_follow_rules(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    rules = value if isinstance(value, list) else [value]
    errors = []
    for index, rule in enumerate(rules):
        if isinstance(rule, dict) and (
            {"source_category", "from_category", "from", "on"} & set(rule)
        ):
            errors.append(f"{label}[{index}] source category is implied by the page key")
            continue
        try:
            parsed = follow_rule_from_config(rule)
        except (ConfigError, TypeError, ValueError) as exc:
            errors.append(f"{label}[{index}] is invalid: {exc}")
            continue
        if not parsed.css and not parsed.xpath:
            errors.append(f"{label}[{index}] must define css or xpath")
    return errors


def _validate_extract_rules(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{label} must be a mapping"]
    errors = []
    for item_type, spec in value.items():
        if not isinstance(spec, dict):
            errors.append(f"{label}.{item_type} must be a mapping")
            continue
        errors.extend(_validate_single_extract(spec, f"{label}.{item_type}"))
    return errors


def _looks_like_single_extract(value: Any) -> bool:
    return isinstance(value, dict) and (
        "fields" in value
        or "item_css" in value
        or "item_xpath" in value
        or _looks_like_fields(value)
    )


def _looks_like_fields(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    reserved = {"type", "item_type", "item_model"}
    return all(key in reserved or _looks_like_field_rule(rule) for key, rule in value.items())


def _looks_like_field_rule(rule: Any) -> bool:
    if isinstance(rule, str):
        return True
    return isinstance(rule, dict) and any(key in rule for key in ("css", "xpath", "smart"))


def _validate_single_extract(value: dict[str, Any], label: str) -> list[str]:
    errors = []
    if value.get("item_css") and value.get("item_xpath"):
        errors.append(f"{label} cannot define both item_css and item_xpath")
    fields = value.get("fields") if "fields" in value else value
    if not isinstance(fields, dict) or not fields:
        errors.append(f"{label}.fields must be a non-empty mapping")
        return errors
    for field, rule in fields.items():
        if field in {"item_css", "item_xpath", "type", "item_type", "item_model"}:
            continue
        if not _looks_like_field_rule(rule):
            errors.append(f"{label}.fields.{field} must be a CSS/XPath/smart rule")
    return errors


def _validate_named_items(value: Any, label: str) -> list[str]:
    if not isinstance(value, dict) or not value:
        return [f"{label} must be a non-empty mapping"]
    errors = []
    for name, spec in value.items():
        if not isinstance(spec, dict):
            errors.append(f"{label}.{name} must be a mapping")
            continue
        errors.extend(_validate_single_extract(spec, f"{label}.{name}"))
    return errors


def _summarize_yaml(config: dict[str, Any]) -> dict[str, Any]:
    spider_entries = _inline_spider_entries(config)
    start_urls: list[str] = []
    allowed_domains: list[str] = []
    pages: dict[str, Any] = {}
    for spider_name, spider_config in spider_entries:
        start_urls.extend(_string_list(spider_config.get("start_urls")))
        allowed_domains.extend(_string_list(spider_config.get("allowed_domains")))
        spider_pages = spider_config.get("pages")
        if isinstance(spider_pages, dict):
            for page_name, page in spider_pages.items():
                pages[f"{spider_name}.{page_name}"] = page
    follow_rules = [
        rule
        for page in pages.values()
        if isinstance(page, dict)
        for rule in (page.get("follow") if isinstance(page.get("follow"), list) else [page.get("follow")] if page.get("follow") else [])
    ]
    return {
        "name": str(config.get("name") or ""),
        "spiders": [name for name, _ in spider_entries],
        "startUrls": start_urls,
        "allowedDomains": allowed_domains,
        "maxDepth": config.get("max_depth"),
        "pages": sorted(str(key) for key in pages),
        "followRuleCount": len(follow_rules),
        "followRules": _summarize_page_follow_rules(pages),
        "itemTypes": _page_item_types(pages),
    }


def _inline_spider_entries(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    spiders = config.get("spiders")
    if isinstance(spiders, dict):
        return [
            (str(name), spec)
            for name, spec in spiders.items()
            if isinstance(spec, dict)
            and not any(key in spec for key in ("path", "module", "config"))
        ]
    return [("default", config)]


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _summarize_follow_rules(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    rules = value if isinstance(value, list) else [value]
    result = []
    for rule in rules:
        if isinstance(rule, str):
            result.append({"selector": rule, "sourceCategory": "*", "targetCategory": ""})
        elif isinstance(rule, dict):
            result.append(
                {
                    "selector": rule.get("css") or rule.get("xpath") or "",
                    "sourceCategory": "*",
                    "targetCategory": rule.get("category") or "",
                    "attr": rule.get("attr") or "href",
                }
            )
    return result


def _summarize_page_follow_rules(pages: Any) -> list[dict[str, Any]]:
    if not isinstance(pages, dict):
        return []
    rules = []
    for category, page in pages.items():
        if not isinstance(page, dict):
            continue
        for rule in _summarize_follow_rules(page.get("follow")):
            rule["sourceCategory"] = str(category)
            rules.append(rule)
    return rules


def _page_item_types(pages: Any) -> dict[str, list[str]]:
    if not isinstance(pages, dict):
        return {}
    result = {}
    for category, page in pages.items():
        if isinstance(page, dict) and isinstance(page.get("extract"), dict):
            result[str(category)] = sorted(str(name) for name in page["extract"])
    return result


def _field_names(spec: dict[str, Any]) -> list[str]:
    fields = spec.get("fields") if "fields" in spec else spec
    if not isinstance(fields, dict):
        return []
    return sorted(
        str(key)
        for key in fields
        if key not in {"item_css", "item_xpath", "type", "item_type", "item_model"}
    )


def _preview_workflow(project_dir: Path, path: Any = None) -> dict[str, Any]:
    clean_path, file_path = _project_path(project_dir, path or "webuse.yaml")
    content = file_path.read_text(encoding="utf-8")
    validation = _validate_yaml_content(clean_path, content)
    if not validation["ok"]:
        return {"ok": False, "path": clean_path, "validation": validation}
    config = yaml.safe_load(content) or {}
    graph = _workflow_graph(config)
    return {
        "ok": True,
        "path": clean_path,
        "validation": validation,
        "graph": graph,
        "mermaid": _workflow_mermaid(graph),
    }


def _workflow_graph(config: dict[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, str]] = []
    edges: list[dict[str, str]] = []
    page_nodes: set[str] = set()
    for spider_name, spider_config in _inline_spider_entries(config):
        prefix = _node_id(spider_name)
        start_urls = _string_list(spider_config.get("start_urls")) or ["start"]
        for index, url in enumerate(start_urls):
            nodes.append({"id": f"start_{prefix}_{index}", "type": "start", "label": f"Start: {spider_name}", "detail": url})
        pages = spider_config.get("pages") if isinstance(spider_config.get("pages"), dict) else {}
        for category, page in pages.items():
            category_name = str(category)
            if not isinstance(page, dict):
                continue
            page_node_id = f"page_{prefix}_{_node_id(category_name)}"
            sources = [page_node_id]
            if category_name == "default":
                sources = [f"start_{prefix}_{index}" for index, _ in enumerate(start_urls)]
            elif page_node_id not in page_nodes:
                nodes.append({"id": page_node_id, "type": "page", "label": f"Page: {category_name}", "detail": spider_name})
                page_nodes.add(page_node_id)
            for index, rule in enumerate(_summarize_follow_rules(page.get("follow"))):
                follow_id = f"follow_{prefix}_{_node_id(category_name)}_{index}"
                target = str(rule.get("targetCategory") or "page")
                target_page_id = f"page_{prefix}_{_node_id(target)}"
                nodes.append({"id": follow_id, "type": "follow", "label": "Follow", "detail": str(rule.get("selector") or "link rule")})
                if target_page_id not in page_nodes:
                    nodes.append({"id": target_page_id, "type": "page", "label": f"Page: {target}", "detail": spider_name})
                    page_nodes.add(target_page_id)
                for source in sources:
                    edges.append({"from": source, "to": follow_id, "label": ""})
                edges.append({"from": follow_id, "to": target_page_id, "label": str(rule.get("attr") or "href")})
            if isinstance(page.get("extract"), dict):
                for item_type, spec in page["extract"].items():
                    fields = _field_names(spec) if isinstance(spec, dict) else []
                    extract_id = f"extract_{prefix}_{_node_id(category_name)}_{_node_id(str(item_type))}"
                    item_id = f"item_{prefix}_{_node_id(category_name)}_{_node_id(str(item_type))}"
                    nodes.append({"id": extract_id, "type": "extract", "label": f"Extract: {category_name}", "detail": spider_name})
                    nodes.append({"id": item_id, "type": "item", "label": f"Item: {item_type}", "detail": ", ".join(fields)})
                    for source in sources:
                        edges.append({"from": source, "to": extract_id, "label": ""})
                    edges.append({"from": extract_id, "to": item_id, "label": ""})
    nodes.append({"id": "database", "type": "database", "label": "Data", "detail": "pipelines/export"})
    for node in [node for node in nodes if node["type"] == "item"]:
        edges.append({"from": node["id"], "to": "database", "label": ""})
    return {"nodes": nodes, "edges": edges}


def _workflow_mermaid(graph: dict[str, Any]) -> str:
    lines = ["flowchart LR"]
    for node in graph["nodes"]:
        label = node["label"] if not node.get("detail") else f"{node['label']}\\n{node['detail']}"
        lines.append(f"  {node['id']}[{json.dumps(label)}]")
    for edge in graph["edges"]:
        label = edge.get("label")
        if label:
            lines.append(f"  {edge['from']} -->|{label}| {edge['to']}")
        else:
            lines.append(f"  {edge['from']} --> {edge['to']}")
    return "\n".join(lines)


def _node_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value) or "default"


def _execute_tool(project_dir: Path, tool_call: Any) -> dict[str, Any]:
    name = tool_call.function.name
    arguments = json.loads(tool_call.function.arguments or "{}")
    if name == "read_project_docs":
        return _read_project_docs(arguments.get("topic"))
    if name == "list_files":
        return {"files": [file["path"] for file in _walk_files(project_dir)]}
    if name == "read_file":
        clean_path, file_path = _project_path(project_dir, arguments.get("path"))
        return {"path": clean_path, "content": file_path.read_text(encoding="utf-8")}
    if name == "write_file":
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        clean_path, file_path = _project_path(project_dir, arguments.get("path"))
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return {"path": clean_path, "ok": True}
    if name == "delete_file":
        clean_path, file_path = _project_path(project_dir, arguments.get("path"))
        file_path.unlink(missing_ok=True)
        return {"path": clean_path, "ok": True}
    if name == "validate_webuse_yaml":
        return _validate_webuse_yaml(project_dir, arguments.get("path"))
    if name == "preview_workflow":
        return _preview_workflow(project_dir, arguments.get("path"))
    if name == "run_webuse":
        return _run_webuse(project_dir, arguments.get("args"))
    raise ValueError(f"unknown assistant tool: {name}")


def _run_webuse(project_dir: Path, args: Any) -> dict[str, Any]:
    if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
        raise ValueError("args must be an array of strings")
    command = _webuse_command(args)
    try:
        completed = subprocess.run(
            command,
            cwd=project_dir,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
        return {
            "command": " ".join(command),
            "code": completed.returncode,
            "stdout": _trim_output(completed.stdout),
            "stderr": _trim_output(completed.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": " ".join(command),
            "code": None,
            "timedOut": True,
            "stdout": _trim_output(exc.stdout or ""),
            "stderr": _trim_output(exc.stderr or ""),
        }


def _webuse_command(args: list[str]) -> list[str]:
    command = os.environ.get("WEBUSE_WORKER_COMMAND")
    if command:
        prefix = json.loads(os.environ.get("WEBUSE_WORKER_COMMAND_ARGS", "[]"))
        return [command, *prefix, *args]
    return [sys.executable, "-m", "webuse.cli", *args]


def _trim_output(value: str) -> str:
    return value if len(value) <= MAX_COMMAND_OUTPUT else f"{value[:MAX_COMMAND_OUTPUT]}\n...[truncated]"
