---
title: "Package Release"
description: "Build and verify Webuse Python release artifacts with the bundled UI."
---

This guide is for maintainers building the Webuse Python package. To deploy your
spiders with Docker, Compose, or Kubernetes, see
[Deployment](../../user-guide/deployment/).

## Building Python Releases

From the repository root, with Node.js 22.19+ and npm available:

```bash
uv build
```

The release hook runs `npm ci` and `npm run build` using the Node server
preset. It copies the compiled server and public assets into `webuse/_ui` and
includes them in both the source distribution and wheel under `dist/`.
SQLite uses Node's built-in module, keeping the bundle free of native Node addons.
The generated `src/webuse/_ui/` directory must not be committed.

Installing a released wheel, or building a wheel from its source distribution,
does not require npm or recompiling the frontend. Node.js 22.19+ is required only
when running the UI. Editable source installs skip the frontend build.

## Verifying Release Artifacts

Verify the wheel independently of the checkout:

```bash
uv venv /tmp/webuse-release
uv pip install --python /tmp/webuse-release/bin/python dist/*.whl
/tmp/webuse-release/bin/python scripts/smoke_ui.py
```

The smoke test starts the installed UI in a temporary data directory, checks
compiled assets, and runs a crawler against a local fixture page. CI performs
this check before uploading build artifacts; it does not publish a release.
