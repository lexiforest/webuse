# Webuse documentation

This directory contains an [Astro](https://astro.build/) site using
[Starlight](https://starlight.astro.build/). It requires Node.js 22.19+ and npm.

Run these commands from this directory:

```bash
npm ci
npm run dev
```

The development server defaults to `http://localhost:4321/`.

Build and preview the static site:

```bash
npm run build
npm run preview
```

The generated site is in `dist/`. No Python environment is needed to build it.

Edit the plain Markdown pages in `src/content/docs/`. Each page has a `title`
in its YAML frontmatter. Navigation is configured in `astro.config.mjs`.
Use fenced code blocks, Markdown tables, and HTML `details` elements for examples.

The source folders follow the site's navigation:

```text
src/content/docs/
  index.md
  user-guide/
  references/
  advanced/
```

Page URLs follow these folders. A folder's `index.md` is its overview page.
Page links are relative to the rendered URL: use `../cli/` from another reference
page or `./references/cli/` from the homepage. A user guide or advanced page links
to that reference with `../../references/cli/`. Relative links also work when
hosted at a subpath.

Set `DOCS_SITE` to the full public URL when deploying, for example
`https://example.com/webuse/`. Its path is used as Astro's base path;
`DOCS_BASE` can override that path. Read the Docs builds automatically use
`READTHEDOCS_CANONICAL_URL`, including its version path.

The repository's Read the Docs configuration installs locked npm dependencies,
builds the site, and copies `dist/` to the hosting output directory. CI also
builds the site. The `reference/HUMAN.md` download is generated from the repository
original, so no duplicate source file is maintained.
