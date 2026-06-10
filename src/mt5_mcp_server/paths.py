"""MT5 install / data-folder / EA discovery (Windows).

Ground truth verified on this machine:
- terminal64.exe under "C:\\Program Files\\MetaTrader 5" (registry Uninstall -> InstallLocation)
- data folder = %APPDATA%\\MetaQuotes\\Terminal\\<hash>, mapped via origin.txt (UTF-16LE+BOM)
- EAs live under <data>\\MQL5\\Experts\\**\\*.ex5 (NOT the install dir in non-portable mode)
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import winreg  # Windows only (the MT5 Strategy Tester is Windows-only)
except ImportError:
    winreg = None  # type: ignore

KNOWN_INSTALL_DIRS = [
    r"C:\Program Files\MetaTrader 5",
]

DEFAULT_CONFIG = {
    "terminal_path": None,
    "data_folder": None,
    "default_deposit": 10000,
    "default_currency": "USD",
    "default_leverage": "1:100",
    "default_model": 1,
    "backtest_timeout_sec": 1200,
    "optimization_timeout_sec": 7200,
}


@dataclass
class Mt5Paths:
    terminal_path: str
    install_dir: str
    data_folder: str | None
    build: str | None


def _uninstall_hives():
    if winreg is None:
        return []
    return [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]


def user_config_dir() -> Path:
    """Per-user config dir: %APPDATA%\\mt5-mcp-server (works after pip install)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "mt5-mcp-server"


def _config_locations() -> list[Path]:
    """Config files in priority order (later wins): repo (dev) -> user dir -> $MT5_MCP_CONFIG."""
    locs: list[Path] = []
    repo = Path(__file__).resolve().parents[2] / "config"
    locs += [repo / "mt5_config.json", repo / "mt5_config.local.json"]
    ud = user_config_dir()
    locs += [ud / "mt5_config.json", ud / "mt5_config.local.json"]
    env = os.environ.get("MT5_MCP_CONFIG")
    if env:
        locs.append(Path(env))
    return locs


def load_config() -> dict:
    """Built-in defaults, then merge each config file found (later wins).

    Installed users put overrides in %APPDATA%\\mt5-mcp-server\\mt5_config.json (or .local.json),
    or set $MT5_MCP_CONFIG to a file path. Missing config is fine — sane defaults apply.
    """
    cfg: dict = dict(DEFAULT_CONFIG)
    for p in _config_locations():
        try:
            if p.is_file():
                cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            print(f"[mt5-mcp] failed to read config {p}: {e}", file=sys.stderr)
    return cfg


def _iter_uninstall_entries():
    for root, sub in _uninstall_hives():
        try:
            key = winreg.OpenKey(root, sub)
        except OSError:
            continue
        count = winreg.QueryInfoKey(key)[0]
        for i in range(count):
            try:
                sk = winreg.OpenKey(key, winreg.EnumKey(key, i))
            except OSError:
                continue
            entry = {}
            for name in ("DisplayName", "InstallLocation", "DisplayVersion"):
                try:
                    entry[name] = winreg.QueryValueEx(sk, name)[0]
                except OSError:
                    entry[name] = None
            yield entry


def registry_installs() -> list[str]:
    """All terminal64.exe paths found via the registry (incl. broker builds)."""
    out: list[str] = []
    for e in _iter_uninstall_entries():
        loc = e.get("InstallLocation")
        if not loc:
            continue
        exe = os.path.join(loc, "terminal64.exe")
        if os.path.isfile(exe) and exe not in out:
            out.append(exe)
    return out


def registry_version(install_dir: str) -> str | None:
    target = os.path.normcase(os.path.normpath(install_dir))
    for e in _iter_uninstall_entries():
        loc = e.get("InstallLocation")
        if loc and os.path.normcase(os.path.normpath(loc)) == target:
            return e.get("DisplayVersion")
    return None


def find_terminal(hint: str | None = None) -> str:
    """Locate terminal64.exe: hint/config -> known dirs -> registry."""
    cfg = load_config()
    cand = hint or cfg.get("terminal_path")
    if cand:
        cand = os.path.normpath(cand)
        if os.path.isdir(cand):
            cand = os.path.join(cand, "terminal64.exe")
        if os.path.isfile(cand):
            return cand
    for d in KNOWN_INSTALL_DIRS:
        exe = os.path.join(d, "terminal64.exe")
        if os.path.isfile(exe):
            return exe
    installs = registry_installs()
    # Prefer the vanilla "Program Files\MetaTrader 5" install over broker builds.
    installs.sort(key=lambda e: (os.path.join("Program Files", "MetaTrader 5") not in e, e))
    if installs:
        return installs[0]
    raise FileNotFoundError(
        "MetaTrader 5 (terminal64.exe) not found. Searched known dirs ("
        + ", ".join(KNOWN_INSTALL_DIRS)
        + ") and the Windows registry (incl. broker builds). "
        "Run list_mt5_terminals() to see detected installs, or set 'terminal_path' to your "
        "terminal64.exe in %APPDATA%\\mt5-mcp-server\\mt5_config.json (or $MT5_MCP_CONFIG)."
    )


def data_folder_for(install_dir: str) -> str | None:
    """Reverse-map an install dir to its %APPDATA% data folder via origin.txt."""
    base = os.path.join(os.environ.get("APPDATA", ""), "MetaQuotes", "Terminal")
    if not os.path.isdir(base):
        return None
    target = os.path.normcase(os.path.normpath(install_dir))
    for d in os.listdir(base):
        o = os.path.join(base, d, "origin.txt")
        if not os.path.isfile(o):
            continue
        try:
            with open(o, encoding="utf-16") as f:  # UTF-16LE + BOM
                p = f.read().strip()
        except Exception:
            continue
        if p and os.path.normcase(os.path.normpath(p)) == target:
            return os.path.join(base, d)
    return None


def resolve_mt5(terminal_hint: str | None = None) -> Mt5Paths:
    cfg = load_config()
    terminal = find_terminal(terminal_hint)
    install = os.path.dirname(terminal)
    data = cfg.get("data_folder") or data_folder_for(install)
    return Mt5Paths(
        terminal_path=terminal,
        install_dir=install,
        data_folder=data,
        build=registry_version(install),
    )


def list_mt5_installs() -> list[dict]:
    """All detected MT5 installs (known dirs + registry, incl. broker builds)."""
    found: list[str] = []
    for d in KNOWN_INSTALL_DIRS:
        exe = os.path.join(d, "terminal64.exe")
        if os.path.isfile(exe):
            found.append(exe)
    found += registry_installs()

    out: list[dict] = []
    seen: set[str] = set()
    for exe in found:
        key = os.path.normcase(exe)
        if key in seen:
            continue
        seen.add(key)
        install = os.path.dirname(exe)
        data = data_folder_for(install)
        out.append({
            "terminal_path": exe,
            "install_dir": install,
            "data_folder": data,
            "build": registry_version(install),
            "experts_count": len(list_experts(data)) if data else 0,
        })
    return out


def experts_dir(data_folder: str) -> str:
    return os.path.join(data_folder, "MQL5", "Experts")


def list_experts(data_folder: str, name_filter: str = "") -> list[dict]:
    """List compiled EAs (.ex5) under <data>/MQL5/Experts as paths relative to Experts."""
    root = experts_dir(data_folder)
    out: list[dict] = []
    if not os.path.isdir(root):
        return out
    nf = name_filter.lower()
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(".ex5"):
                continue
            abspath = os.path.join(dirpath, fn)
            rel = os.path.relpath(abspath, root).replace("/", "\\")
            name = os.path.splitext(fn)[0]
            if nf and nf not in rel.lower():
                continue
            out.append({"name": name, "rel_path": rel, "abs_path": abspath})
    out.sort(key=lambda e: e["rel_path"].lower())
    return out
