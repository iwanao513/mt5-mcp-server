"""MT5 install / data-folder / EA discovery (Windows).

Ground truth verified on this machine:
- terminal64.exe under "C:\\Program Files\\MetaTrader 5" (registry Uninstall -> InstallLocation)
- data folder = %APPDATA%\\MetaQuotes\\Terminal\\<hash>, mapped via origin.txt (UTF-16LE+BOM)
- EAs live under <data>\\MQL5\\Experts\\**\\*.ex5 (NOT the install dir in non-portable mode)
"""
from __future__ import annotations

import json
import os
import winreg
from dataclasses import dataclass
from pathlib import Path

KNOWN_INSTALL_DIRS = [
    r"C:\Program Files\MetaTrader 5",
]

_UNINSTALL_HIVES = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


@dataclass
class Mt5Paths:
    terminal_path: str
    install_dir: str
    data_folder: str | None
    build: str | None


def config_file() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "mt5_config.json"


def load_config() -> dict:
    p = config_file()
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _iter_uninstall_entries():
    for root, sub in _UNINSTALL_HIVES:
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
        "terminal64.exe not found. Set 'terminal_path' in config/mt5_config.json"
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
