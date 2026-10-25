# AGENTS.md

herdr-here: Windows Terminal profiles that direct-attach to one Herdr workspace per directory.

## Commands
- Setup: `mise run install`
- Release: `verkit release <major|minor|patch>` (do not hand-edit `version` in `pyproject.toml`)
- First publish of the current version, with no bump: `verkit tag`

## Rules
- `verkit release` is the only version bump. It edits `pyproject.toml` and `uv.lock`, then tags and pushes. The tag publish workflow uploads to PyPI.
- The bash pane command and `herdr_here.install` read that version. Do not copy it into those files.
- verkit is a dev dependency. The installed tool stays on the Python standard library.
