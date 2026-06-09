"""Launch terminal64.exe for a Strategy Tester run and detect completion.

Completion signal: ShutdownTerminal=1 makes MT5 exit when the test finishes, so
subprocess.wait() returning is the 'done' event. We corroborate with the report file.

MT5 enforces single-instance PER DATA FOLDER: if a terminal bound to the target install
is already running, a /config launch may be ignored. We detect that and refuse (or, with
close_running=True, terminate it first).
"""
from __future__ import annotations

import logging
import os
import subprocess
import time

import psutil

from .ini_builder import write_ini
from .paths import Mt5Paths

log = logging.getLogger("mt5_mcp.runner")

_SIBLING_EXTS = (".htm", ".html", ".xml", ".png", ".xlsx")


def running_terminals_for(install_dir: str) -> list[psutil.Process]:
    target = os.path.normcase(os.path.join(install_dir, "terminal64.exe"))
    out: list[psutil.Process] = []
    for p in psutil.process_iter(["name", "exe"]):
        try:
            if (p.info["name"] or "").lower() != "terminal64.exe":
                continue
            exe = p.info["exe"]
            if exe and os.path.normcase(exe) == target:
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


def _kill(procs: list[psutil.Process]) -> None:
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=5)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass


def _kill_metatester() -> None:
    procs = [p for p in psutil.process_iter(["name"])
             if (p.info["name"] or "").lower() == "metatester64.exe"]
    _kill(procs)


def run_tester(
    mt5: Mt5Paths,
    ini_text: str,
    report_rel: str,
    *,
    is_optimization: bool = False,
    timeout: int = 1200,
    close_running: bool = False,
) -> str:
    """Write the config, launch the tester, wait, and return the report file path.

    report_rel: path relative to the data folder root, backslash-separated, no extension
                (e.g. 'mt5_mcp\\\\<runid>'). The .ini is written next to it.
    """
    if not mt5.data_folder:
        raise RuntimeError(
            "MT5 data folder not found. Open MT5 once, or set 'data_folder' in config/mt5_config.json"
        )

    base = os.path.join(mt5.data_folder, report_rel)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    ini_path = base + ".ini"
    write_ini(ini_path, ini_text)

    # clear stale outputs so we never read a previous run
    for ext in _SIBLING_EXTS:
        try:
            os.remove(base + ext)
        except FileNotFoundError:
            pass

    running = running_terminals_for(mt5.install_dir)
    if running:
        if close_running:
            log.info("closing %d running terminal(s) for %s", len(running), mt5.install_dir)
            _kill(running)
            time.sleep(2)
        else:
            raise RuntimeError(
                f"MetaTrader 5 is already running for {mt5.install_dir}. "
                "A backtest cannot run while that instance is open (MT5 is single-instance "
                "per data folder). Close it, or call again with close_running=true."
            )

    launched = time.time()
    log.info("launching tester: %s /config:%s", mt5.terminal_path, ini_path)
    proc = subprocess.Popen([mt5.terminal_path, f"/config:{ini_path}"])
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        _kill_metatester()
        raise RuntimeError(f"tester timed out after {timeout}s")

    # resolve produced report (single test: .htm/.html; optimization: .xml)
    candidates = [base + ".xml"] if is_optimization else [base + ".htm", base + ".html"]
    for c in candidates:
        if os.path.isfile(c) and os.path.getmtime(c) >= launched - 5:
            return c
    raise RuntimeError(
        "no report produced. Likely causes: the EA/symbol needs history downloaded "
        "(open MT5 and log into an account with the symbol once), the EA name is wrong, "
        "or the symbol is unavailable. Checked: " + ", ".join(candidates)
    )
