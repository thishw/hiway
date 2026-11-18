---
title: "Code navigation and project setup in hiway-kit"
date: 2026-11-18
description: "What the Oh My OpenAgent evaluation brought to hiway-kit and what's planned for project-wide C/C++ navigation and project setup."
tags: ["code intelligence", "release notes"]
translationKey: code-navigation-and-project-setup
---

We evaluated Oh My OpenAgent (OMO) to see which code exploration tools would help hiway-kit users. In the repository release available on November 18, v5.7.1, `code-intel` can search by code structure, test matching rules and preview changes with an installed ast-grep. It can also query a supported language server on demand. `session-history` can find decisions in selected local Codex and Claude Code session logs.

## Planned for v5.8.0

**C/C++ definitions and references across source files.** When the kit uses its clangd helper with a supported compilation database (`compile_commands.json`), it will build an index automatically. Each query starts a short-lived server and can reuse the index stored in a private cache outside the project. If the helper cannot verify index coverage or finish the query within its limits, it returns the results it has and marks them as partial.

**Keep the project's existing layout and tools.** The planner will use the location your project already specifies or ask before creating a plan folder. Test and documentation agents will follow the project's existing layout. Verification will use your project's commands and installed tools, and report missing dependencies. Formatters will follow project configuration, and the installer will ask before setting a global Git template.

As of this note, v5.8.0 is awaiting release. The repository marketplace serves v5.7.1. Anthropic's Claude Code directory serves v5.5.1 while its v5.7.1 update is under review. For Codex, use the repository marketplace installation path in the [getting-started guide](/docs/getting-started/#codex). Check the [changelog](/changelog/) for the current repository release.
