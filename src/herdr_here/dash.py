"""Herdr Dashboard: A standalone full-pane TUI for monitoring workspaces,

git branch status, agent activity, and attached Windows Terminal panes.
Organized vertically with related data nested under each workspace,
matching the Herdr sidebar.
"""

from __future__ import annotations

import curses
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WorkspaceItem:
    number: int
    workspace_id: str
    label: str
    root: str
    branch: str
    dirty: bool
    ahead: int
    behind: int
    agents: list[tuple[str, str]]
    attached: bool
    terminal_ids: list[str]


def find_herdr() -> str | None:
    env_bin = os.environ.get("HERDR")
    if env_bin and os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
        return env_bin
    which = shutil.which("herdr")
    if which:
        return which
    candidates = [
        Path.home() / ".local/bin/herdr",
        Path.home() / ".local/share/mise/installs/herdr/latest/herdr",
        Path.home() / ".cargo/bin/herdr",
        Path("/usr/local/bin/herdr"),
        Path("/usr/bin/herdr"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def find_herdr_here() -> str | None:
    which = shutil.which("herdr-here")
    if which:
        return which
    candidates = [
        Path.home() / ".local/bin/herdr-here",
        Path(__file__).resolve().parent / "share/herdr-here",
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def win_value(var_name: str) -> str:
    try:
        proc = subprocess.run(
            ["cmd.exe", "/d", "/c", f"echo %{var_name}%"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        if proc.returncode == 0:
            lines = [line.strip() for line in proc.stdout.replace("\r", "").splitlines() if line.strip()]
            if lines and lines[-1] != f"%{var_name}%":
                return lines[-1]
    except Exception:
        pass
    return ""


def find_wt() -> str | None:
    which = shutil.which("wt.exe") or shutil.which("wt")
    if which:
        return which
    flavor = os.environ.get("HERDR_WT", "")
    pkg = ""
    if flavor == "canary":
        pkg = "Microsoft.WindowsTerminalCanary_8wekyb3d8bbwe"
    elif flavor == "preview":
        pkg = "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe"
    elif flavor == "stable":
        pkg = "Microsoft.WindowsTerminal_8wekyb3d8bbwe"

    username = win_value("USERNAME")
    if username:
        if pkg:
            p = Path(f"/mnt/c/Users/{username}/AppData/Local/Microsoft/WindowsApps/{pkg}/wt.exe")
            if p.is_file():
                return str(p)
        for cand_pkg in [
            "Microsoft.WindowsTerminal_8wekyb3d8bbwe",
            "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe",
            "Microsoft.WindowsTerminalCanary_8wekyb3d8bbwe",
        ]:
            p = Path(f"/mnt/c/Users/{username}/AppData/Local/Microsoft/WindowsApps/{cand_pkg}/wt.exe")
            if p.is_file():
                return str(p)
    return None


def is_terminal_attached(lock_dir: Path, terminal_id: str) -> bool:
    lock_file = lock_dir / f"{terminal_id}.lock"
    if not lock_file.is_file():
        return False
    try:
        with open(lock_file, "r+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return False
            except (BlockingIOError, OSError):
                return True
    except Exception:
        return False


def get_git_info(cwd: str) -> tuple[str, bool, int, int]:
    if not cwd or not os.path.isdir(cwd):
        return ("", False, 0, 0)
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
        if proc.returncode != 0:
            return ("", False, 0, 0)
        branch = proc.stdout.strip()
        if branch == "HEAD":
            res = subprocess.run(
                ["git", "-C", cwd, "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=1,
            )
            branch = f":{res.stdout.strip()}"

        proc = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain=v1"],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
        dirty = bool(proc.stdout.strip())

        ahead, behind = 0, 0
        if branch and not branch.startswith(":"):
            proc = subprocess.run(
                ["git", "-C", cwd, "rev-list", "--left-right", "--count", f"{branch}...@{{upstream}}"],
                capture_output=True,
                text=True,
                check=False,
                timeout=1,
            )
            if proc.returncode == 0:
                parts = proc.stdout.strip().split()
                if len(parts) == 2:
                    ahead, behind = int(parts[0]), int(parts[1])

        return (branch, dirty, ahead, behind)
    except Exception:
        return ("", False, 0, 0)


def load_workspaces(herdr_bin: str) -> list[WorkspaceItem]:
    try:
        proc = subprocess.run(
            [herdr_bin, "api", "snapshot"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        text = proc.stdout or ""
        start = text.find("{")
        if start < 0:
            return []
        data = json.loads(text[start:])
    except Exception:
        return []

    snap = data.get("result", {}).get("snapshot", {})
    workspaces_raw = snap.get("workspaces", [])
    agents_raw = snap.get("agents", [])
    panes_raw = snap.get("panes", [])

    lock_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "herdr" / "wt-attach"
    roots_dir = lock_dir / "roots"

    agents_by_ws: dict[str, list[dict]] = {}
    for a in agents_raw:
        ws_id = a.get("workspace_id")
        if ws_id:
            agents_by_ws.setdefault(ws_id, []).append(a)

    panes_by_ws: dict[str, list[dict]] = {}
    for p in panes_raw:
        ws_id = p.get("workspace_id")
        if ws_id:
            panes_by_ws.setdefault(ws_id, []).append(p)

    items: list[WorkspaceItem] = []
    for w in workspaces_raw:
        ws_id = w.get("workspace_id", "")
        num = w.get("number", len(items) + 1)
        label = w.get("label") or ws_id

        root = ""
        root_file = roots_dir / ws_id
        if root_file.is_file():
            try:
                root = root_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        if not root and ws_id in panes_by_ws:
            for p in panes_by_ws[ws_id]:
                cwd = p.get("cwd") or p.get("foreground_cwd")
                if cwd:
                    root = cwd
                    break

        agents_list: list[tuple[str, str]] = []
        if ws_id in agents_by_ws:
            for ag_info in agents_by_ws[ws_id]:
                name = ag_info.get("agent") or ""
                st = ag_info.get("agent_status") or ""
                if name or st:
                    agents_list.append((name, st))
        elif ws_id in panes_by_ws:
            for p in panes_by_ws[ws_id]:
                if p.get("agent") or (p.get("agent_status") and p.get("agent_status") != "unknown"):
                    name = p.get("agent") or ""
                    st = p.get("agent_status") or ""
                    agents_list.append((name, st))

        if not agents_list and w.get("agent_status") and w.get("agent_status") != "unknown":
            agents_list.append(("", w.get("agent_status", "")))

        terminal_ids: list[str] = []
        attached = False
        for p in panes_by_ws.get(ws_id, []):
            t_id = p.get("terminal_id")
            if t_id:
                terminal_ids.append(t_id)
                if is_terminal_attached(lock_dir, t_id):
                    attached = True

        branch, dirty, ahead, behind = get_git_info(root)

        items.append(
            WorkspaceItem(
                number=num,
                workspace_id=ws_id,
                label=label,
                root=root,
                branch=branch,
                dirty=dirty,
                ahead=ahead,
                behind=behind,
                agents=agents_list,
                attached=attached,
                terminal_ids=terminal_ids,
            )
        )

    items.sort(key=lambda x: x.number)
    return items


def shorten_path(path: str) -> str:
    if not path:
        return ""
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def run_tui(stdscr: curses.window) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Enable mouse events
    curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_DOUBLE_CLICKED)

    # Color pairs
    # 1: Yellow (blocked / dirty / attention)
    curses.init_pair(1, curses.COLOR_YELLOW, -1)
    # 2: Green (working / done / attached)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    # 3: Cyan (workspace label / agent name)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    # 4: Red (behind / error)
    curses.init_pair(4, curses.COLOR_RED, -1)
    # 5: Dim / White (labels, paths, frame)
    curses.init_pair(5, curses.COLOR_WHITE, -1)
    # 6: Selection highlight (Cyan background)
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_CYAN)

    herdr_bin = find_herdr()
    if not herdr_bin:
        stdscr.addstr(0, 0, "Error: herdr executable not found. Press 'q' to exit.", curses.A_BOLD)
        stdscr.refresh()
        while True:
            k = stdscr.getch()
            if k in (ord("q"), ord("Q"), 27):
                return

    selected = 0
    scroll_offset = 0
    show_help = False
    message = ""
    message_time = 0.0

    items: list[WorkspaceItem] = []
    last_refresh = 0.0

    # Non-blocking input with 1-second timeout for responsive refresh
    stdscr.timeout(1000)

    while True:
        now = time.time()
        if now - last_refresh >= 2.0 or not items:
            items = load_workspaces(herdr_bin)
            last_refresh = now
            if selected >= len(items):
                selected = max(0, len(items) - 1)

        # Clear message after 3 seconds
        if message and now - message_time > 3.0:
            message = ""

        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        if max_y < 8 or max_x < 24:
            stdscr.addstr(0, 0, "Terminal window too small.")
            stdscr.refresh()
            k = stdscr.getch()
            if k in (ord("q"), ord("Q"), 27):
                return
            continue

        # Header
        title = "HERDR SIDEBAR"
        right_info = f"{len(items)} ws" if max_x < 50 else f"{len(items)} workspaces (r: refresh, ?: help, q: quit)"
        try:
            stdscr.addstr(0, 0, "─" * max_x, curses.color_pair(5) | curses.A_DIM)
        except curses.error:
            pass
        stdscr.addstr(0, 0, title, curses.A_BOLD)
        if len(right_info) < max_x - len(title) - 1:
            try:
                stdscr.addstr(0, max_x - len(right_info), right_info, curses.color_pair(5) | curses.A_DIM)
            except curses.error:
                pass

        content_start_y = 2
        avail_rows = max_y - content_start_y - 2  # leave room for header & footer

        # Build vertical block lines for each workspace
        # Each item has:
        #  - Header: marker + number + status-bullet + label + attached-badge
        #  - Nested branch line
        #  - Nested agent line(s)
        #  - Nested path line
        #  - Trailing blank separator line
        type_line_tuples: list[tuple[int, str, list[tuple[str, int]]]] = []
        # format: (item_index, line_type, [(text, attr), ...])
        block_spans: list[tuple[int, int]] = []

        curr_virtual_line = 0
        for idx, item in enumerate(items):
            block_start = curr_virtual_line
            is_sel = idx == selected

            # Overall status bullet
            bullet = "○"
            bullet_attr = curses.color_pair(5) | curses.A_DIM
            any_blocked = any("block" in st.lower() or "wait" in st.lower() for _, st in item.agents)
            any_working = any("work" in st.lower() or "run" in st.lower() for _, st in item.agents)
            any_done = any("done" in st.lower() for _, st in item.agents)
            any_idle = any("idle" in st.lower() for _, st in item.agents)

            if any_blocked:
                bullet = "●"
                bullet_attr = curses.color_pair(1) | curses.A_BOLD
            elif any_working:
                bullet = "●"
                bullet_attr = curses.color_pair(2) | curses.A_BOLD
            elif any_done:
                bullet = "✔"
                bullet_attr = curses.color_pair(2) | curses.A_BOLD
            elif any_idle:
                bullet = "●"
                bullet_attr = curses.color_pair(3)

            hdr_spans: list[tuple[str, int]] = []
            if is_sel:
                hdr_spans.append((f"{item.number:d} ", curses.A_BOLD))
                hdr_spans.append((f"{bullet} ", bullet_attr))
                hdr_spans.append((f"{item.label} ", curses.color_pair(3) | curses.A_BOLD))
            else:
                hdr_spans.append((f"{item.number:d} ", curses.color_pair(5) | curses.A_BOLD))
                hdr_spans.append((f"{bullet} ", bullet_attr))
                hdr_spans.append((f"{item.label} ", curses.A_BOLD))

            att_str = "[attached]" if item.attached else "[detached]"
            att_attr = (curses.color_pair(2) | curses.A_BOLD) if item.attached else (curses.color_pair(5) | curses.A_DIM)
            hdr_spans.append((f" {att_str}", att_attr))
            type_line_tuples.append((idx, "header", hdr_spans))
            curr_virtual_line += 1

            # Tree connector prefix
            prefix = "  "

            # Branch line
            br_spans: list[tuple[str, int]] = [
                (prefix + "branch: ", curses.color_pair(5) | curses.A_DIM),
            ]
            if item.branch:
                br_spans.append((item.branch, curses.color_pair(5)))
                if item.dirty:
                    br_spans.append(("*", curses.color_pair(1) | curses.A_BOLD))
                if item.ahead > 0:
                    br_spans.append((f" ↑{item.ahead}", curses.color_pair(2) | curses.A_BOLD))
                if item.behind > 0:
                    br_spans.append((f" ↓{item.behind}", curses.color_pair(4) | curses.A_BOLD))
            else:
                br_spans.append(("-", curses.color_pair(5) | curses.A_DIM))
            type_line_tuples.append((idx, "branch", br_spans))
            curr_virtual_line += 1

            # Agent line(s)
            if item.agents:
                for ag_name, ag_st in item.agents:
                    ag_spans: list[tuple[str, int]] = [
                        (prefix + "agent:  ", curses.color_pair(5) | curses.A_DIM),
                    ]
                    if ag_name:
                        ag_spans.append((f"{ag_name} ", curses.color_pair(3)))
                    st_lower = ag_st.lower()
                    if "block" in st_lower or "wait" in st_lower:
                        st_attr = curses.color_pair(1) | curses.A_BOLD
                    elif "work" in st_lower or "run" in st_lower or "done" in st_lower:
                        st_attr = curses.color_pair(2) | curses.A_BOLD
                    elif "idle" in st_lower:
                        st_attr = curses.color_pair(3)
                    else:
                        st_attr = curses.color_pair(5)
                    ag_spans.append((f"({ag_st})", st_attr))
                    type_line_tuples.append((idx, "agent", ag_spans))
                    curr_virtual_line += 1
            else:
                ag_spans = [
                    (prefix + "agent:  ", curses.color_pair(5) | curses.A_DIM),
                    ("none", curses.color_pair(5) | curses.A_DIM),
                ]
                type_line_tuples.append((idx, "agent", ag_spans))
                curr_virtual_line += 1

            # Path line
            short_p = shorten_path(item.root) or "-"
            p_spans: list[tuple[str, int]] = [
                (prefix + "path:   ", curses.color_pair(5) | curses.A_DIM),
                (short_p, curses.color_pair(5) | curses.A_DIM),
            ]
            type_line_tuples.append((idx, "path", p_spans))
            curr_virtual_line += 1

            # Empty separator line
            type_line_tuples.append((idx, "separator", [("", curses.A_NORMAL)]))
            curr_virtual_line += 1

            block_spans.append((block_start, curr_virtual_line))

        # Adjust scroll offset so selected block is visible
        if 0 <= selected < len(block_spans):
            sel_start, sel_end = block_spans[selected]
            # Ensure the top of the selected item is at least visible
            if sel_start < scroll_offset:
                scroll_offset = sel_start
            elif sel_end > scroll_offset + avail_rows:
                # If block exceeds available height, align to start of block
                if sel_end - sel_start >= avail_rows:
                    scroll_offset = sel_start
                else:
                    scroll_offset = sel_end - avail_rows
        scroll_offset = max(0, scroll_offset)

        # Render visible lines
        visible_lines = type_line_tuples[scroll_offset : scroll_offset + avail_rows]
        for row_i, (item_idx, ltype, spans) in enumerate(visible_lines):
            y = content_start_y + row_i
            x = 0
            is_sel = item_idx == selected

            if ltype == "header" and is_sel:
                # Highlight background for the selected header line across full width
                try:
                    stdscr.addstr(y, 0, " " * max_x, curses.color_pair(6))
                except curses.error:
                    pass

            for text, attr in spans:
                if x >= max_x:
                    break
                slice_len = min(len(text), max_x - x)
                t_slice = text[:slice_len]
                # If header is selected, retain highlight styling
                draw_attr = attr
                if ltype == "header" and is_sel:
                    draw_attr = curses.color_pair(6) | curses.A_BOLD

                try:
                    stdscr.addstr(y, x, t_slice, draw_attr)
                except curses.error:
                    pass
                x += slice_len

        # Footer
        footer_y = max_y - 2
        try:
            stdscr.addstr(footer_y, 0, "─" * max_x, curses.color_pair(5) | curses.A_DIM)
        except curses.error:
            pass

        if message:
            try:
                stdscr.addstr(max_y - 1, 0, message[:max_x], curses.color_pair(1) | curses.A_BOLD)
            except curses.error:
                pass
        else:
            if max_x >= 55:
                shortcuts = "[Enter] Attach  [t] Tab  [r] Refresh  [q] Quit  [?] Help"
            elif max_x >= 40:
                shortcuts = "[Enter] Attach  [t] Tab  [r] Ref  [q] Quit"
            else:
                shortcuts = "Enter:Attach t:Tab q:Quit"
            try:
                stdscr.addstr(max_y - 1, 0, shortcuts[:max_x], curses.color_pair(5))
            except curses.error:
                pass

        # Help popup overlay
        if show_help:
            box_w = min(66, max_x - 4)
            box_h = min(14, max_y - 4)
            start_x = (max_x - box_w) // 2
            start_y = (max_y - box_h) // 2

            for hy in range(box_h):
                stdscr.addstr(start_y + hy, start_x, " " * box_w, curses.A_REVERSE)

            help_lines = [
                "HERDR SIDEBAR HELP",
                "──────────────────────────────────────────────────────────",
                "  Enter / dbl-click  Attach current pane to this workspace",
                "  t                  Open a new Windows Terminal tab",
                "  j / k or Up / Down Navigate workspaces",
                "  g / G              Jump to Top / Bottom",
                "  r                  Refresh status immediately",
                "  q / Esc            Quit sidebar",
                "  ?                  Close this help overlay",
                "──────────────────────────────────────────────────────────",
                "Tip: WT tab titles reflect workspace names dynamically.",
            ]
            for idx, hl in enumerate(help_lines):
                if idx < box_h:
                    stdscr.addstr(start_y + idx + 1, start_x + 2, hl[: box_w - 4], curses.A_REVERSE | (curses.A_BOLD if idx == 0 else curses.A_NORMAL))

        stdscr.refresh()

        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            return

        if key == curses.ERR:
            continue

        if show_help:
            if key in (ord("?"), ord("q"), ord("Q"), 27, ord("\n"), ord("\r")):
                show_help = False
            continue

        if key in (ord("q"), ord("Q"), 27):
            return

        elif key == ord("?"):
            show_help = True

        elif key in (curses.KEY_UP, ord("k"), ord("K")):
            if selected > 0:
                selected -= 1

        elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
            if selected < len(items) - 1:
                selected += 1

        elif key in (curses.KEY_HOME, ord("g")):
            selected = 0

        elif key in (curses.KEY_END, ord("G")):
            if items:
                selected = len(items) - 1

        elif key in (ord("r"), ord("R")):
            items = load_workspaces(herdr_bin)
            last_refresh = time.time()
            message = "Refreshed."
            message_time = time.time()

        elif key in (ord("\n"), ord("\r"), curses.KEY_ENTER):
            if items and 0 <= selected < len(items):
                target = items[selected]
                if target.root:
                    curses.endwin()
                    herdr_here = find_herdr_here()
                    if herdr_here:
                        os.execvp(herdr_here, [herdr_here, target.root])
                    else:
                        print(f"Error: herdr-here command not found to attach {target.root}", file=sys.stderr)
                        sys.exit(1)

        elif key in (ord("t"), ord("T")):
            if items and 0 <= selected < len(items):
                target = items[selected]
                wt = find_wt()
                if not wt:
                    message = "Error: Windows Terminal (wt.exe) not found."
                    message_time = time.time()
                elif not target.root:
                    message = f"Error: no root path for workspace {target.label}."
                    message_time = time.time()
                else:
                    distro = os.environ.get("WSL_DISTRO_NAME", "Debian")
                    cmd = [
                        wt,
                        "-w",
                        "0",
                        "new-tab",
                        "--title",
                        target.label,
                        "wsl.exe",
                        "-d",
                        distro,
                        "--cd",
                        target.root,
                        "bash",
                        "-lc",
                        f"herdr-here '{target.root}'",
                    ]
                    try:
                        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        message = f"Opened new tab for {target.label}"
                        message_time = time.time()
                    except Exception as e:
                        message = f"Failed to open tab: {e}"
                        message_time = time.time()

        elif key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
                if content_start_y <= my < content_start_y + avail_rows:
                    clicked_line = scroll_offset + (my - content_start_y)
                    for idx, (b_start, b_end) in enumerate(block_spans):
                        if b_start <= clicked_line < b_end:
                            selected = idx
                            if bstate & curses.BUTTON1_DOUBLE_CLICKED:
                                target = items[selected]
                                if target.root:
                                    curses.endwin()
                                    herdr_here = find_herdr_here()
                                    if herdr_here:
                                        os.execvp(herdr_here, [herdr_here, target.root])
                            break
            except curses.error:
                pass


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        print(
            "Usage: herdr-dash [OPTIONS]\n\n"
            "Open the Herdr sidebar dashboard in the current terminal.\n\n"
            "Options:\n"
            "  -h, --help    Show this help message and exit\n"
        )
        return 0

    try:
        curses.wrapper(run_tui)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
