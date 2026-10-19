# herdr-here

One Herdr server, one workspace per directory, opened from Windows Terminal.

Windows Terminal keeps the tabs and panes. Herdr keeps the shells alive after a tab closes. The plain WSL profile stays a normal shell. A second profile, colored `#89b4fa`, runs `herdr-here` and direct-attaches to the workspace for that directory. `herdr` still opens the dashboard.

## Install

From Debian, Ubuntu, or another WSL distro:

```bash
git clone <this-repo> ~/repos/herdr-here
cd ~/repos/herdr-here
python3 install.py
```

`uv run install.py` is the same installer. The script has no third-party dependencies.

`python3 install.py --dry-run` prints what it found and writes nothing. `--no-default` leaves the Terminal default profile alone. `--no-yazi` and `--no-history` skip those optional pieces.

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

Open the `<Distro> Herdr` profile. The tab color is the Herdr marker. From a plain WSL shell:

```bash
cd ~/repos/some-project
herdr-here
```

A Windows path works too: `herdr-here 'C:\Users\me\repos\some-project'`.

Detach with `ctrl+b q`. A literal `ctrl+b` is `ctrl+b ctrl+b`. Closing the tab leaves the shell running. `herdr-here` in that directory attaches to it again.

`herdr-dash` opens the dashboard. After a reboot the server is down. The next `herdr-here` starts it. That launch clears `NO_COLOR` and turns color on, because panes inherit the server environment.

In Yazi, `g` then `r` opens the hovered directory in Herdr. `g` then `h` is still Go home.

## Why these tools

`herdr-here` and `herdr-dash` are bash. They run at the start of a pane, and a package manager there would be another thing that has to work before the shell does.

`install.py` is Python 3, standard library only. It has to edit JSON and ask Windows who you are. Bash can do that, and it gets brittle. A Go or Rust binary would be one file with no Python, and it would be worse to change. Node would also edit JSON, and it would ask every coworker for `npm install`.

There is no pip package. Cloning the repo and running `python3 install.py` is the install. `uv run install.py` works when uv is present because the script declares `requires-python` and an empty dependency list.

## Layout

| Path | Role |
|---|---|
| `share/herdr-here` | Create or resume the workspace and direct-attach |
| `share/herdr-dash` | Open the dashboard in the matching Terminal build |
| `share/yazi-keymap.toml` | Optional `g r` keymap |
| `install.py` | Detect this machine and install the pieces |

The installer copies the scripts to `~/.local/bin`. Pane history is turned on in `~/.config/herdr/config.toml` when that line is absent.
