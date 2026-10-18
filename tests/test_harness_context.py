"""Ensure parity normalization permits fixture paths, not context differences."""

import copy
import json
from pathlib import Path
import runpy

import pytest


smoke = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/smoke_ui.py"))


def snapshot(root):
    workspace = {"directory": f"{root}/project", "skill": f"{root}/skills/SKILL.md"}
    initial = {
        "model": "test-model",
        "messages": [
            {
                "role": "system",
                "content": f"Work in {workspace['directory']}; read {workspace['skill']}.",
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "parameters": {"type": "object", "required": ["path"]},
                },
            }
        ],
    }
    after_docs = copy.deepcopy(initial)
    after_docs["messages"].extend(
        [
            {
                "role": "tool",
                "content": json.dumps(
                    {
                        **workspace,
                        "framework": {
                            "python": "/installed/bin/python",
                            "docs": "/installed/docs",
                        },
                    }
                ),
            },
            {"role": "tool", "content": "Skill contents"},
            {"role": "tool", "content": "Documentation contents"},
        ]
    )
    return smoke["context_snapshot"]([initial, {}, {}, after_docs], workspace)


@pytest.mark.parametrize(
    "roots", [("/tmp/first", "/tmp/second"), (r"C:\first", r"C:\second")]
)
def test_only_fixture_paths_are_normalized(roots):
    smoke["assert_context_parity"](snapshot(roots[0]), snapshot(roots[1]))


@pytest.mark.parametrize("change", ["prompt", "tool", "skill", "docs", "runtime"])
def test_context_drift_fails_with_a_readable_diff(change):
    packaged, development = snapshot("/tmp/first"), snapshot("/tmp/second")
    if change == "prompt":
        development["initial"]["messages"][0]["content"] += " Different instructions."
    elif change == "tool":
        development["initial"]["tools"][0]["function"]["parameters"]["required"] = []
    else:
        index = {"runtime": 1, "skill": 2, "docs": 3}[change]
        development["after_docs"]["messages"][index]["content"] += " changed"
    with pytest.raises(AssertionError, match="Harness context differs") as error:
        smoke["assert_context_parity"](packaged, development)
    assert "--- packaged Harness context" in str(error.value)
    assert "+++ development Harness context" in str(error.value)
