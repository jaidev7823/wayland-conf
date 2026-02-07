#!/usr/bin/env python3
import argparse
import curses
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

DATA_DIR = Path.home() / ".local/share/waybar-todo"
DATA_FILE = DATA_DIR / "tasks.json"
ROTATION_INTERVAL =2# Seconds per task display

DEFAULT_TASKS = [
    {
        "id": "seed-quickstart",
        "title": "Part 6",
        "priority": 1,
        "done": False,
        "created": datetime.now().isoformat(),
    },
    {
        "id": "seed-manage",
        "title": "Right click to edit or add",
        "priority": 3,
        "done": False,
        "created": datetime.now().isoformat(),
    },
]


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> Dict[str, Any]:
    ensure_data_dir()
    if not DATA_FILE.exists():
        state = {"tasks": DEFAULT_TASKS, "show_index": 0}
        save_state(state)
        return state

    try:
        raw = json.loads(DATA_FILE.read_text())
        if not isinstance(raw, dict):
            raise ValueError("state not a dict")
        raw.setdefault("tasks", [])
        raw.setdefault("show_index", 0)
        return raw
    except Exception:
        backup = DATA_FILE.with_suffix(DATA_FILE.suffix + ".bak")
        DATA_FILE.rename(backup)
        state = {"tasks": DEFAULT_TASKS, "show_index": 0}
        save_state(state)
        return state


def save_state(state: Dict[str, Any]) -> None:
    ensure_data_dir()
    # Atomic write to prevent file corruption
    tmp_file = DATA_FILE.with_suffix(".tmp")
    with tmp_file.open("w") as f:
        json.dump(state, f, indent=2)
    tmp_file.replace(DATA_FILE)


def sorted_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        tasks,
        key=lambda t: (
            t.get("priority", 3),
            t.get("created", ""),
            t.get("title", ""),
        ),
    )


def pending_tasks(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [t for t in state.get("tasks", []) if not t.get("done")]


def next_display_pool(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    pool = sorted_tasks(pending_tasks(state))
    if pool:
        return pool
    return sorted_tasks(state.get("tasks", []))


def render_tooltip(state: Dict[str, Any]) -> str:
    lines: List[str] = []
    tasks = sorted_tasks(state.get("tasks", []))
    if not tasks:
        lines.append("No todos yet. Right click to add one.")
    else:
        for task in tasks:
            mark = "☑" if task.get("done") else "☐"
            pr = task.get("priority", "?")
            lines.append(f"{mark} P{pr} {task.get('title', '')}")
    lines.append("")
    lines.append("Left click: cycle | Right click: manage | Middle click: reset view")
    return "\n".join(lines)


def render_tasks_line(state: Dict[str, Any]) -> str:
    pool = next_display_pool(state)
    if not pool:
        return " No todos"
    
    parts = []
    for task in pool:
        pr = task.get("priority", "?")
        parts.append(f"P{pr} {task.get('title', '')}")
    
    return " " + " | ".join(parts)


def get_display_task(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pool = sorted_tasks(pending_tasks(state))
    if not pool:
        return None
    # Rotate based on time
    idx = int(time.time() / ROTATION_INTERVAL) % len(pool)
    return pool[idx]


def render_tasks_line(state: Dict[str, Any]) -> str:
    task = get_display_task(state)
    if not task:
        return " No todos"
    
    pr = task.get("priority", "?")
    done = "☑" if task.get("done") else "☐"
    # Show only the current rotated task
    return f" P{pr} {task.get('title', '')}"


def print_status(state: Dict[str, Any]) -> None:
    text = render_tasks_line(state)
    payload = {
        "text": text,
        "tooltip": render_tooltip(state),
        "class": "todo",
    }
    json.dump(payload, sys.stdout)


def toggle_current_display_task(state: Dict[str, Any]) -> bool:
    """Marks the currently displayed task as done/undone."""
    task = get_display_task(state)
    if not task:
        return False
    return toggle_task(state, task["id"])


def cycle_task(state: Dict[str, Any]) -> None:
    pool = next_display_pool(state)
    if not pool:
        state["show_index"] = 0
        return
    state["show_index"] = (state.get("show_index", 0) + 1) % len(pool)


def reset_cycle(state: Dict[str, Any]) -> None:
    state["show_index"] = 0


def toggle_task(state: Dict[str, Any], task_id: str) -> bool:
    for task in state.get("tasks", []):
        if task.get("id") == task_id:
            task["done"] = not task.get("done")
            return True
    return False


def add_task(state: Dict[str, Any], title: str, priority: int = 3) -> None:
    state.setdefault("tasks", []).append(
        {
            "id": uuid4().hex[:10],
            "title": title.strip(),
            "priority": max(1, min(priority, 5)),
            "done": False,
            "created": datetime.now().isoformat(),
        }
    )


def clear_completed(state: Dict[str, Any]) -> None:
    state["tasks"] = [t for t in state.get("tasks", []) if not t.get("done")]


def send_signal(signal: Optional[int]) -> None:
    if signal is None:
        return
    try:
        subprocess.run(["pkill", f"-RTMIN+{signal}", "waybar"], check=True)
    except subprocess.CalledProcessError:
        pass


def detect_menu() -> Optional[str]:
    for candidate in ("wofi", "rofi"):
        if shutil.which(candidate):
            return candidate
    return None


def run_menu(options: List[str], prompt: str) -> Optional[str]:
    chooser = detect_menu()
    if chooser is None:
        return None

    if chooser == "wofi":
        cmd = ["wofi", "--dmenu", "--prompt", prompt]
    else:
        cmd = ["rofi", "-dmenu", "-p", prompt]

    joined = "\n".join(options)
    proc = subprocess.run(cmd, input=joined.encode(), capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode().strip()


def prompt_input(prompt: str) -> Optional[str]:
    chooser = detect_menu()
    cmd: Optional[List[str]] = None
    if chooser == "wofi":
        cmd = ["wofi", "--dmenu", "--prompt", prompt]
    elif chooser == "rofi":
        cmd = ["rofi", "-dmenu", "-p", prompt]

    if cmd:
        proc = subprocess.run(cmd, input=b"", capture_output=True)
        if proc.returncode != 0:
            return None
        return proc.stdout.decode().strip()

    try:
        return input(f"{prompt}: ").strip()
    except EOFError:
        return None


def manage_menu(state: Dict[str, Any]) -> bool:
    tasks = sorted_tasks(state.get("tasks", []))
    options: List[str] = []
    for task in tasks:
        mark = "[x]" if task.get("done") else "[ ]"
        pr = task.get("priority", "?")
        short_id = task.get("id", "")[:6]
        options.append(f"{mark} P{pr} {task.get('title', '')}  #{short_id}")

    if options:
        options.append("---")
    options.extend([
        "[+] Add task",
        "[!] Clear completed",
        "[0] Reset view",
    ])

    choice = run_menu(options, prompt="Todo")
    if not choice:
        return False

    if choice.startswith("[+]"):
        title = prompt_input("New todo")
        if title:
            raw_priority = prompt_input("Priority 1-5 (1=high)")
            priority = int(raw_priority) if raw_priority and raw_priority.isdigit() else 3
            add_task(state, title, priority)
            return True
        return False

    if choice.startswith("[!]"):
        clear_completed(state)
        reset_cycle(state)
        return True

    if choice.startswith("[0]"):
        reset_cycle(state)
        return True

    if choice.startswith("[") and "#" in choice:
        task_id = choice.rsplit("#", 1)[-1].strip()
        toggled = toggle_task(state, task_id)
        if toggled:
            reset_cycle(state)
        return toggled

def tui_loop(stdscr: Any, state: Dict[str, Any]) -> bool:
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)
    curses.start_color()
    curses.use_default_colors()
    
    # Define colors
    curses.init_pair(1, curses.COLOR_GREEN, -1)   # Done
    curses.init_pair(2, curses.COLOR_RED, -1)     # High Priority (1-2)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Med Priority (3)
    curses.init_pair(4, curses.COLOR_BLUE, -1)    # Low Priority (4-5)
    curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_WHITE) # Selected

    current_idx = 0
    changed = False

    def delete_task(state: Dict[str, Any], task_id: str) -> bool:
        tasks = state.get("tasks", [])
        initial_len = len(tasks)
        state["tasks"] = [t for t in tasks if t.get("id") != task_id]
        return len(state["tasks"]) < initial_len

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # Header
        header = "Todo List"
        header_x = (width - len(header)) // 2
        header_x = max(0, header_x)
        stdscr.addstr(0, header_x, header, curses.A_BOLD | curses.A_UNDERLINE)

        # Footer / Controls
        footer = "[A] Add  [E] Edit  [Space] Toggle  [D] Trash  [C] Clear Done  [Q] Quit"
        stdscr.addstr(height-1, 0, footer[:width], curses.A_REVERSE)

        # Content
        tasks = sorted_tasks(state.get("tasks", []))
        visible_count = min(len(tasks), height - 3) # Header + Footer + padding
        
        # Adjust scroll if needed (simple scrolling)
        if current_idx >= len(tasks):
            current_idx = min(max(0, len(tasks) - 1), len(tasks))
        if current_idx < 0:
            current_idx = 0

        start_row = 0
        list_height = height - 2
        
        if current_idx >= list_height:
            start_row = current_idx - list_height + 1
            
        render_tasks = tasks[start_row : start_row + list_height]
        
        for i, task in enumerate(render_tasks):
            actual_idx = start_row + i
            row = i + 1
            
            if row >= height - 1: # Avoid overwriting footer
                break

            # Selection highlight
            style = curses.A_NORMAL
            if actual_idx == current_idx:
                style = curses.color_pair(5)

            # Task status
            done = task.get("done", False)
            mark = "[x]" if done else "[ ]"
            
            # Priority color
            prio = task.get("priority", 3)
            p_color = curses.A_NORMAL
            if not done:
                if prio <= 2: p_color = curses.color_pair(2)
                elif prio == 3: p_color = curses.color_pair(3)
                else: p_color = curses.color_pair(4)
            elif done:
                p_color = curses.color_pair(1)

            line_str = f"{mark} P{prio} {task.get('title', '')}"[:width-1]
            
            if actual_idx == current_idx:
                stdscr.addstr(row, 0, line_str, style)
            else:
                stdscr.addstr(row, 0, mark, p_color)
                stdscr.addstr(row, 4, f"P{prio}", p_color | curses.A_BOLD)
                stdscr.addstr(row, 7, line_str[7:], curses.A_NORMAL if not done else curses.color_pair(1))

        stdscr.refresh()

        key = stdscr.getch()

        if key in (ord('q'), 27): # q or esc
            break
        elif key in (ord('j'), curses.KEY_DOWN):
            if current_idx < len(tasks) - 1:
                current_idx += 1
        elif key in (ord('k'), curses.KEY_UP):
            if current_idx > 0:
                current_idx -= 1
        elif key == ord(' '):
            if tasks:
                task = tasks[current_idx]
                toggle_task(state, task["id"])
                changed = True
        elif key in (ord('d'), curses.KEY_DC, 127, 8): # d, delete, backspace
            if tasks:
                task = tasks[current_idx]
                if delete_task(state, task["id"]):
                    changed = True
                    # Fix index after delete
                    if current_idx >= len(state.get("tasks", [])):
                        current_idx = max(0, len(state.get("tasks", [])) - 1)
        elif key in (ord('c'), ord('C')):
            if tasks:
                clear_completed(state)
                current_idx = 0
                changed = True
        elif key in (ord('a'), ord('A')):
            # Simple input capture
            curses.echo()
            curses.curs_set(1)
            
            # Clear footer line for input
            stdscr.move(height-1, 0)
            stdscr.clrtoeol()
            stdscr.addstr(height-1, 0, "New task: ")
            
            # Read title
            title_bytes = stdscr.getstr(height-1, 10)
            title = title_bytes.decode('utf-8').strip()
            
            if title:
                stdscr.move(height-1, 0)
                stdscr.clrtoeol()
                stdscr.addstr(height-1, 0, f"Priority (1-5) [3]: ")
                prio_bytes = stdscr.getstr(height-1, 20)
                prio_str = prio_bytes.decode('utf-8').strip()
                prio = int(prio_str) if prio_str.isdigit() else 3
                
                add_task(state, title, prio)
                changed = True
            
            curses.noecho()
            curses.curs_set(0)
        elif key in (ord('e'), ord('E')):
            if tasks:
                task = tasks[current_idx]
                curses.echo()
                curses.curs_set(1)
                
                # Clear footer line for input
                stdscr.move(height-1, 0)
                stdscr.clrtoeol()
                stdscr.addstr(height-1, 0, f"Edit title [{task.get('title')}]: ")
                
                # Read title
                try:
                    title_bytes = stdscr.getstr(height-1, len(f"Edit title [{task.get('title')}]: "))
                    new_title = title_bytes.decode('utf-8').strip()
                    if new_title:
                        task["title"] = new_title
                        changed = True
                except:
                    pass

                stdscr.move(height-1, 0)
                stdscr.clrtoeol()
                stdscr.addstr(height-1, 0, f"Priority [{task.get('priority')}]: ")
                
                try:
                    prio_bytes = stdscr.getstr(height-1, len(f"Priority [{task.get('priority')}]: "))
                    prio_str = prio_bytes.decode('utf-8').strip()
                    
                    if prio_str:
                        new_prio = int(prio_str) if prio_str.isdigit() else task.get('priority')
                        task["priority"] = max(1, min(new_prio, 5))
                        changed = True
                except:
                    pass

                curses.noecho()
                curses.curs_set(0)
        if changed:
            save_state(state) # Autosave immediately
            # We don't signal waybar here to avoid spamming updates during edits,
            # but we could if needed. Let's rely on loop exit or natural refresh.
            
    return changed


def print_status(state: Dict[str, Any]) -> None:
    text = render_tasks_line(state)
    payload = {
        "text": text,
        "tooltip": render_tooltip(state),
        "class": "todo",
    }
    json.dump(payload, sys.stdout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Waybar todo helper")
    parser.add_argument(
        "action",
        choices=["status", "cycle", "toggle-top", "menu", "tui", "toggle", "add", "reset"],
        nargs="?",
        default="status",
    )
    parser.add_argument("--id", help="Task id for toggle")
    parser.add_argument("--title", help="Title for add")
    parser.add_argument("--priority", type=int, default=3, help="Priority 1-5")
    parser.add_argument("--signal", type=int, help="Waybar signal number to refresh")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = load_state()

    changed = False

    if args.action == "cycle":
        # Cycle is now redundant with time-based rotation, but could force a refresh
        changed = True
    elif args.action == "toggle-current":
        changed = toggle_current_display_task(state)
    elif args.action == "toggle-top":
        # Legacy support or if user wants top priority specifically
        # Re-implemented locally if needed, but let's point to toggle_current or just keep old name for CLI
        changed = toggle_current_display_task(state) 
    elif args.action == "menu":
        changed = manage_menu(state)
    elif args.action == "tui":
        try:
            changed = curses.wrapper(lambda stdscr: tui_loop(stdscr, state))
        except curses.error:
            # Fallback if tui fails
            print("Error initializing TUI", file=sys.stderr)
    elif args.action == "toggle" and args.id:
        changed = toggle_task(state, args.id)
    elif args.action == "add" and args.title:
        add_task(state, args.title, args.priority)
        changed = True
    elif args.action == "reset":
        reset_cycle(state)
        changed = True

    if changed:
        save_state(state)
        send_signal(args.signal)

    if args.action in {"status", "cycle", "reset"}:
        print_status(state)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
