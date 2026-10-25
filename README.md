# herdr-here

One Herdr server, one workspace per directory, opened from Windows Terminal.

Windows Terminal keeps the tabs and panes. Herdr keeps the shells alive after a tab closes. A new tab stays the plain WSL profile. A second profile, colored `#89b4fa`, is the same shell with a Herdr tab title. Run `herdr-here` in that tab when a pane is an agent chat. `herdr` still opens the dashboard.

## Install

From Debian, Ubuntu, or another WSL distro, after this package is on PyPI:

```bash
uv tool install herdr-here
```

That puts `herdr-here`, `herdr-dash`, and `herdr-here-install` on `PATH`. `uv` installs those commands and does not run them, so it cannot see your Windows user or edit Windows Terminal by itself. The first `herdr-here` runs `herdr-here-install`, writes the profiles, and then attaches. Run `herdr-here-install` on its own when you want the profiles before you attach.

Until the package is published, install this checkout:

```bash
uv tool install --from ~/repos/herdr-here herdr-here
```

`herdr-here-install --dry-run` prints what it found and writes nothing. `--no-yazi` and `--no-history` skip those optional pieces. A checkout can still run `python3 install.py`. The installer does not make the Herdr profile the Terminal default. If an older install did, the next run puts the default back on the plain distro profile.

Herdr itself is separate. Install it before opening the new profile: <https://herdr.dev>.

## What the installer detects

It does not assume the Windows username matches the Linux username.

- Linux user and home come from the account running the installer.
- The distro name comes from `WSL_DISTRO_NAME`.
- The Windows username, profile, and `%LOCALAPPDATA%` come from `cmd.exe`.
- It looks for Windows Terminal settings in the Canary, Preview, and Stable store packages, and in the unpackaged `%LOCALAPPDATA%\Microsoft\Windows Terminal\settings.json`.
- If a plain profile for this distro already exists, the new profiles copy its font, color scheme, and icon.
- The profile `startingDirectory` is the Linux home (`/home/<user>`). A Windows path in that field is passed to `wsl.exe --cd` and fails when the path is not a Windows directory.

Re-running the installer updates the same two profiles. Their ids stay `{c4e8a1f2-7b63-4d15-9e40-6a2f8c91d0e7}` and `{d5f9b203-8c74-4e26-af51-7b309da2e1f8}`. The first settings change keeps a `settings.json.herdr-here.bak` beside the original.

## Daily use

Open the `<Distro> Herdr` profile, or split a pane. That pane is a normal shell in the directory it was split from. It does not start Herdr.

Run `herdr-here` in a pane when that pane is an agent chat. Yazi, LazyGit, and ordinary commands stay ordinary shells. A split of a Herdr pane is another shell in that directory, not another attach to the workspace.

From a pane that is already attached, `herdr-here` in another directory moves that pane to the workspace for the new directory.

A Windows path works too: `herdr-here 'C:\Users\me\repos\some-project'`.

Detach with `ctrl+b q`. A literal `ctrl+b` is `ctrl+b ctrl+b`. Closing the tab leaves the shell running. `herdr-here` in that directory attaches to it again.

`herdr-dash` opens a full-pane dashboard showing all workspaces, git branch and sync statuses, live agent states, and whether each workspace is currently attached to a Windows Terminal pane. Press Enter to attach the current terminal pane, or `t` to open a new tab.

In Yazi, `g` then `r` opens the hovered directory in Herdr. `g` then `h` is still Go home.

## Why these tools

`herdr-here` is bash. It runs at the start of a pane, and a package manager there would be another thing that has to work before the shell does.

`herdr-dash` and `herdr-here-install` are Python 3, standard library only (using curses, json, fcntl, and subprocess). They require zero external dependencies. Publishing entry points is what makes `uv tool install herdr-here` work.

## Release

Versioning goes through [verkit](https://github.com/bizkite-co/verkit). The version string lives in `pyproject.toml`. `verkit release` bumps it, commits, tags `vX.Y.Z`, and pushes. Pushing that tag runs `.github/workflows/publish.yml`, which builds the package and uploads it to PyPI with trusted publishing.

```bash
mise run install
mise run release patch   # or minor / major
```

`verkit tag` tags the version already committed, without bumping it. Use that for the first upload of `0.1.0`. Later uploads use `verkit release`.

PyPI still needs a trusted publisher for this GitHub repository: project `herdr-here`, workflow `publish.yml`, and the `id-token: write` permission already in that file. This checkout has no `origin` remote yet.

## Layout

| Path | Role |
|---|---|
| `src/herdr_here/share/herdr-here` | Create or resume the workspace and direct-attach |
| `src/herdr_here/share/herdr-dash` | Open the dashboard in the matching Terminal build |
| `src/herdr_here/share/yazi-keymap.toml` | Optional `g r` keymap |
| `src/herdr_here/install.py` | Detect this machine and write the Terminal profiles |
| `pyproject.toml` | Package metadata. verkit bumps `version` here |
| `mise.toml` | `mise run release` calls `verkit release` |
| `.github/workflows/publish.yml` | Publishes a `v*` tag to PyPI |

The installer copies the scripts to `~/.local/bin`. Pane history is turned on in `~/.config/herdr/config.toml` when that line is absent.
