"""Install herdr-here for the current WSL user and Windows Terminal.

The shell commands stay bash. This module discovers the machine and writes
the Windows Terminal profiles. It uses the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

SHARE = Path(__file__).resolve().parent / "share"

# Stable ids so a later install updates the same profiles instead of adding more.
HERE_GUID = "{c4e8a1f2-7b63-4d15-9e40-6a2f8c91d0e7}"
DASH_GUID = "{d5f9b203-8c74-4e26-af51-7b309da2e1f8}"
TAB_COLOR = "#89b4fa"

FLAVORS = (
    ("canary", "Microsoft.WindowsTerminalCanary_8wekyb3d8bbwe"),
    ("preview", "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe"),
    ("stable", "Microsoft.WindowsTerminal_8wekyb3d8bbwe"),
)
APPEARANCE = (
    "colorScheme",
    "font",
    "fontSize",
    "icon",
    "opacity",
    "useAcrylic",
    "background",
    "backgroundImage",
    "cursorShape",
    "padding",
    "antialiasingMode",
)


def win_value(name: str) -> str:
    """Read one Windows environment variable. WSL does not share it by default."""
    proc = subprocess.run(
        ["cmd.exe", "/d", "/c", f"echo %{name}%"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"install: cmd.exe could not read %{name}%")
    value = proc.stdout.replace("\r", "").strip().splitlines()
    got = value[-1].strip() if value else ""
    if not got or got == f"%{name}%":
        raise SystemExit(f"install: Windows did not return %{name}%")
    return got


def to_linux(path: str) -> Path:
    proc = subprocess.run(
        ["wslpath", "-u", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(f"install: wslpath could not convert {path}")
    return Path(proc.stdout.strip())


def discover_terminals(local_appdata: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    packages = local_appdata / "Packages"
    for flavor, package in FLAVORS:
        settings = packages / package / "LocalState" / "settings.json"
        if settings.is_file():
            found.append((flavor, settings))
    unpackaged = local_appdata / "Microsoft" / "Windows Terminal" / "settings.json"
    if unpackaged.is_file():
        found.append(("unpackaged", unpackaged))
    return found


def donor_profile(settings: dict, distro: str) -> dict | None:
    """The plain WSL profile whose font and colors the Herdr profiles should follow."""
    custom = []
    generated = []
    for profile in settings.get("profiles", {}).get("list", []):
        command = profile.get("commandline") or ""
        if "herdr-here" in command or "herdr-dash" in command:
            continue
        name = profile.get("name") or ""
        if name == distro and "wsl" in command.lower():
            custom.append(profile)
        elif profile.get("source") in {"Windows.Terminal.Wsl", "Microsoft.WSL"} and name == distro:
            generated.append(profile)
    if custom:
        return custom[0]
    if generated:
        return generated[0]
    return None


def upsert(profiles: list, guid: str, name: str, fields: dict, appearance: dict) -> str:
    for profile in profiles:
        same_guid = str(profile.get("guid", "")).lower() == guid.lower()
        same_name = profile.get("name") == name
        if not same_guid and not same_name:
            continue
        profile["guid"] = guid
        profile["name"] = name
        profile.update(fields)
        return "updated"
    created = {"guid": guid, "name": name, "hidden": False}
    created.update(appearance)
    created.update(fields)
    profiles.append(created)
    return "added"


def load_settings(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"install: {path} is not strict JSON ({exc}). "
            "Windows Terminal settings with comments need to be edited by hand."
        ) from exc


def dump_settings(data: dict) -> str:
    return json.dumps(data, indent=4, ensure_ascii=False) + "\n"


def install_settings(path: Path, flavor: str, distro: str, home: str, here: Path, dash: Path, dry_run: bool) -> None:
    settings, raw = load_settings(path)
    profiles = settings.setdefault("profiles", {}).setdefault("list", [])
    here_name = f"{distro} Herdr"
    donor = donor_profile(settings, distro)
    appearance = {}
    if donor:
        appearance = {key: donor[key] for key in APPEARANCE if key in donor}
        if "pathTranslationStyle" in donor:
            appearance["pathTranslationStyle"] = donor["pathTranslationStyle"]
    # A normal WSL shell, same as the plain distro profile. herdr-here is a
    # command the user runs for an agent chat. A login wrapper here is slow,
    # and launching herdr-here from the profile would attach every split.
    start = donor.get("startingDirectory") if donor and donor.get("startingDirectory") else home
    here_fields = {
        "hidden": False,
        "commandline": f"wsl.exe -d {distro}",
        "startingDirectory": start,
        "tabTitle": here_name,
        "tabColor": TAB_COLOR,
        "pathTranslationStyle": appearance.get("pathTranslationStyle", "wsl"),
    }
    dash_fields = {
        "hidden": False,
        "commandline": f"wsl.exe -d {distro} -- env HERDR_DASH=1 HERDR_WT={flavor} {dash}",
        "startingDirectory": home,
        "tabTitle": "Herdr",
        "pathTranslationStyle": appearance.get("pathTranslationStyle", "wsl"),
    }
    here_action = upsert(profiles, HERE_GUID, here_name, here_fields, appearance)
    dash_action = upsert(profiles, DASH_GUID, "Herdr", dash_fields, appearance)
    # The Herdr profile is a normal shell plus a tab title and color. It is
    # for the one tab that runs herdr-here. A new tab should keep the plain
    # distro profile. If an older install made this the default, give it back.
    if str(settings.get("defaultProfile", "")).lower() == HERE_GUID.lower():
        donor_guid = donor.get("guid") if donor else None
        if donor_guid:
            settings["defaultProfile"] = donor_guid
    text = dump_settings(settings)
    changed = text != raw
    print(f"  {flavor}: {here_name} {here_action}, Herdr {dash_action}, write={changed}")
    if dry_run or not changed:
        return
    backup = path.with_name(path.name + ".herdr-here.bak")
    if not backup.exists():
        backup.write_text(raw, encoding="utf-8")
        print(f"  backup: {backup}")
    path.write_text(text, encoding="utf-8")


def install_scripts(bin_dir: Path, dry_run: bool) -> dict[str, Path]:
    """Return the script paths Windows Terminal should call.

    A uv tool install already symlinks these into the bin directory.
    Leave that symlink alone so `uv tool upgrade` keeps working.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name in ("herdr-here", "herdr-dash"):
        src = SHARE / name
        dest = bin_dir / name
        if dest.is_symlink():
            print(f"  script: {dest} provided by uv")
            paths[name] = dest
            continue
        found = shutil.which(name)
        if found:
            resolved = Path(found).resolve()
            if "uv/tools/herdr-here" in resolved.as_posix() and resolved != dest.resolve():
                print(f"  script: using {found}")
                paths[name] = Path(found)
                continue
        same = dest.is_file() and not dest.is_symlink() and dest.read_bytes() == src.read_bytes()
        print(f"  script: {dest} ({'current' if same else 'install'})")
        paths[name] = dest
        if dry_run or same:
            continue
        shutil.copyfile(src, dest)
        dest.chmod(0o755)
    return paths


def install_yazi(home: Path, dry_run: bool) -> None:
    if shutil.which("yazi") is None and not (home / ".config" / "yazi").is_dir():
        print("  yazi: not installed, keymap left alone")
        return
    keymap = home / ".config" / "yazi" / "keymap.toml"
    snippet = (SHARE / "yazi-keymap.toml").read_text(encoding="utf-8").rstrip() + "\n\n"
    current = keymap.read_text(encoding="utf-8") if keymap.is_file() else ""
    if "herdr-here" in current:
        print(f"  yazi: {keymap} already opens Herdr")
        return
    print(f"  yazi: prepend g r to {keymap}")
    if dry_run:
        return
    keymap.parent.mkdir(parents=True, exist_ok=True)
    keymap.write_text(snippet + current, encoding="utf-8")


def install_history(home: Path, dry_run: bool) -> None:
    path = home / ".config" / "herdr" / "config.toml"
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    if "pane_history" in current:
        print(f"  herdr: pane history already set in {path}")
        return
    print(f"  herdr: enable pane history in {path}")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if not current:
        path.write_text("[experimental]\npane_history = true\n", encoding="utf-8")
        return
    if "[experimental]" in current:
        lines = current.splitlines()
        out = []
        inserted = False
        for line in lines:
            out.append(line)
            if not inserted and line.strip() == "[experimental]":
                out.append("pane_history = true")
                inserted = True
        path.write_text("\n".join(out) + ("\n" if current.endswith("\n") else ""), encoding="utf-8")
        return
    path.write_text(current.rstrip() + "\n\n[experimental]\npane_history = true\n", encoding="utf-8")


def package_version() -> str:
    """Version verkit writes into pyproject.toml.

    A checkout reads that file. An installed copy reads the package metadata,
    so a release does not have to edit this module.
    """
    root = Path(__file__).resolve().parents[2]
    pyproject = root / "pyproject.toml"
    if pyproject.is_file() and (root / "src" / "herdr_here" / "install.py").is_file():
        match = re.search(
            r'(?m)^version\s*=\s*"([^"]+)"',
            pyproject.read_text(encoding="utf-8"),
        )
        if match:
            return match.group(1)
    from importlib.metadata import version

    return version("herdr-here")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install herdr-here into WSL and Windows Terminal.")
    parser.add_argument("--version", action="store_true", help="print the package version and exit")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    parser.add_argument("--no-yazi", action="store_true", help="do not add the Yazi g r keymap")
    parser.add_argument("--no-history", action="store_true", help="do not turn on Herdr pane history")
    parser.add_argument("--bin-dir", type=Path, default=Path.home() / ".local" / "bin")
    args = parser.parse_args(argv)
    if args.version:
        print(package_version())
        return 0

    if not SHARE.joinpath("herdr-here").is_file():
        raise SystemExit(f"install: missing {SHARE / 'herdr-here'}")

    linux_user = os.environ.get("USER") or os.getlogin()
    linux_home = Path.home()
    distro = os.environ.get("WSL_DISTRO_NAME") or ""
    if not distro:
        raise SystemExit("install: WSL_DISTRO_NAME is unset. Run this inside WSL.")
    windows_user = win_value("USERNAME")
    user_profile = win_value("USERPROFILE")
    local_appdata = to_linux(win_value("LOCALAPPDATA"))
    terminals = discover_terminals(local_appdata)

    print(f"linux user:   {linux_user}  ({linux_home})")
    print(f"windows user: {windows_user}  ({user_profile})")
    print(f"wsl distro:   {distro}")
    print(f"localappdata: {local_appdata}")
    if shutil.which("herdr"):
        print(f"herdr:        {shutil.which('herdr')}")
    else:
        print("herdr:        not on PATH yet. Install Herdr before opening the new profile.")
    if not terminals:
        print("terminal:     no Windows Terminal settings.json found")
    for flavor, path in terminals:
        print(f"terminal:     {flavor}  {path}")

    print("scripts:")
    scripts = install_scripts(args.bin_dir, args.dry_run)
    print("windows terminal:")
    if not terminals:
        print("  skipped")
    for flavor, path in terminals:
        install_settings(
            path,
            flavor,
            distro,
            str(linux_home),
            scripts["herdr-here"],
            scripts["herdr-dash"],
            dry_run=args.dry_run,
        )
    if not args.no_yazi:
        install_yazi(linux_home, args.dry_run)
    if not args.no_history:
        install_history(linux_home, args.dry_run)
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    stamp = linux_home / ".config" / "herdr" / "herdr-here-setup"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(package_version() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
