"""Build MetaTrader 5 Strategy Tester /config .ini files.

Key facts (verified):
- Sections: [Common] (login, optional for local backtest), [Tester], [TesterInputs].
- Expert= is relative to <data>/MQL5/Experts, backslash-separated, WITH .ex5 (GUI form).
- [TesterInputs] line: Name=value||start||step||stop||Y/N  (Y=optimize, N=fixed). Separator '||'.
- Dates are YYYY.MM.DD (dots). Currency = 3-letter code. Single test always emits .htm.
- Write the file as UTF-16 or MT5 may misparse keys.
"""
from __future__ import annotations

import os
from pathlib import Path

PERIODS = {"M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
           "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D1", "W1", "MN1"}


def normalize_date(s: str) -> str:
    """Accept YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD -> YYYY.MM.DD."""
    s = str(s).strip().replace("-", ".").replace("/", ".")
    parts = s.split(".")
    if len(parts) != 3:
        raise ValueError(f"invalid date '{s}', expected YYYY.MM.DD")
    y, m, d = parts
    return f"{int(y):04d}.{int(m):02d}.{int(d):02d}"


def normalize_leverage(lev: str | int) -> int:
    """'1:100' or '100' or 100 -> 100 (MT5 tester .ini wants the integer)."""
    s = str(lev)
    if ":" in s:
        s = s.split(":")[-1]
    return int(float(s))


def _fmt_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def build_tester_inputs(fixed: dict | None = None, ranges: dict | None = None) -> str:
    """Build the [TesterInputs] body.

    fixed:  {name: value}                 -> name=value||value||0||0||N
    ranges: {name: [min, max, step]}      -> name=min||min||step||max||Y
            (also accepts {name: {"min","max","step"}})
    """
    lines: list[str] = []
    for name, value in (fixed or {}).items():
        v = _fmt_value(value)
        lines.append(f"{name}={v}||{v}||0||0||N")
    for name, spec in (ranges or {}).items():
        if isinstance(spec, dict):
            lo, hi, step = spec.get("min"), spec.get("max"), spec.get("step")
        else:
            lo, hi, step = spec[0], spec[1], spec[2]
        lo, hi, step = _fmt_value(lo), _fmt_value(hi), _fmt_value(step)
        lines.append(f"{name}={lo}||{lo}||{step}||{hi}||Y")
    return "\n".join(lines)


def build_ini(
    *,
    expert: str,
    symbol: str,
    period: str,
    from_date: str,
    to_date: str,
    report_rel: str,
    deposit: float = 10000,
    currency: str = "USD",
    leverage: str | int = "1:100",
    model: int = 1,
    optimization: int = 0,
    optimization_criterion: int = 0,
    forward_mode: int = 0,
    forward_date: str | None = None,
    fixed_inputs: dict | None = None,
    range_inputs: dict | None = None,
    login: str | None = None,
    password: str | None = None,
    server: str | None = None,
    visual: int = 0,
    shutdown: int = 1,
) -> str:
    period = period.upper()
    if period not in PERIODS:
        raise ValueError(f"invalid period '{period}'")
    if len(currency) != 3:
        raise ValueError(f"currency must be a 3-letter code, got '{currency}'")

    lines: list[str] = []

    if login or server:
        lines.append("[Common]")
        if login:
            lines.append(f"Login={login}")
        if password is not None:
            lines.append(f"Password={password}")
        if server:
            lines.append(f"Server={server}")
        lines.append("")

    lines.append("[Tester]")
    lines.append(f"Expert={expert}")
    lines.append(f"Symbol={symbol}")
    lines.append(f"Period={period}")
    lines.append(f"Model={model}")
    lines.append(f"Optimization={optimization}")
    if optimization:
        lines.append(f"OptimizationCriterion={optimization_criterion}")
    lines.append(f"FromDate={normalize_date(from_date)}")
    lines.append(f"ToDate={normalize_date(to_date)}")
    lines.append(f"ForwardMode={forward_mode}")
    if forward_mode == 4 and forward_date:
        lines.append(f"ForwardDate={normalize_date(forward_date)}")
    if login:
        lines.append(f"Login={login}")
    lines.append(f"Deposit={int(deposit)}")
    lines.append(f"Currency={currency.upper()}")
    lines.append(f"Leverage={normalize_leverage(leverage)}")
    lines.append(f"Report={report_rel}")
    lines.append("ReplaceReport=1")
    lines.append(f"ShutdownTerminal={shutdown}")
    lines.append("UseLocal=1")
    lines.append("UseRemote=0")
    lines.append("UseCloud=0")
    lines.append(f"Visual={visual}")
    lines.append("")

    inputs_body = build_tester_inputs(fixed_inputs, range_inputs)
    if inputs_body:
        lines.append("[TesterInputs]")
        lines.append(inputs_body)
        lines.append("")

    return "\n".join(lines)


def write_ini(path: str, text: str) -> None:
    """MT5 expects the /config .ini as UTF-16."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(text, encoding="utf-16")
