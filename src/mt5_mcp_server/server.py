"""FastMCP server: drive the MetaTrader 5 Strategy Tester from Claude Code.

Tools: mt5_info, list_eas, run_backtest, optimize, run_forward_test, full_pipeline.

STDIO RULE: never write to stdout (it corrupts JSON-RPC). All logging goes to stderr.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from . import paths
from .ini_builder import build_ini, normalize_date
from .report_parser import parse_optimization_xml, parse_single_html
from .runner import running_terminals_for, run_tester

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("mt5_mcp")

mcp = FastMCP("mt5-strategy-tester")

# metric columns in the optimization XML; everything else is an EA input parameter
_OPT_METRIC_COLS = {
    "Pass", "Result", "Profit", "Expected Payoff", "Profit Factor", "Recovery Factor",
    "Sharpe Ratio", "Custom", "Equity DD %", "Equity DD", "Trades", "Sortino Ratio",
}


# ---------------------------------------------------------------- models
class Mt5Info(BaseModel):
    terminal_path: str
    install_dir: str
    data_folder: str | None
    build: str | None
    experts_count: int
    is_running: bool = Field(description="True if a terminal is already open on this data folder (blocks backtests)")


class TerminalInfo(BaseModel):
    terminal_path: str = Field(description="Pass this as 'terminal_path' to other tools to target this install")
    install_dir: str
    data_folder: str | None
    build: str | None
    experts_count: int


class EaInfo(BaseModel):
    name: str
    rel_path: str = Field(description="Path to pass as 'ea' to run_backtest/optimize")


class BacktestMetrics(BaseModel):
    net_profit: float | None = None
    gross_profit: float | None = None
    gross_loss: float | None = None
    profit_factor: float | None = None
    expected_payoff: float | None = None
    recovery_factor: float | None = None
    sharpe_ratio: float | None = None
    balance_dd_max_abs: float | None = None
    balance_dd_max_pct: float | None = None
    balance_dd_rel_pct: float | None = None
    total_trades: float | None = None
    win_rate_pct: float | None = None
    history_quality: str | None = None


class BacktestResult(BaseModel):
    ea: str
    symbol: str
    period: str
    from_date: str
    to_date: str
    metrics: BacktestMetrics
    report_path: str
    raw: dict[str, str] = Field(default_factory=dict, description="All label->value pairs parsed from the report")


class OptimizationResult(BaseModel):
    ea: str
    symbol: str
    period: str
    columns: list[str]
    total_passes: int
    best_params: dict[str, Any] | None
    top: list[dict[str, Any]]
    report_path: str


# ---------------------------------------------------------------- helpers
def _resolve_ea(data_folder: str | None, ea: str) -> str:
    """Forgiving resolution of an EA argument to the Expert= rel path (with .ex5)."""
    norm = ea.replace("/", "\\")
    if not data_folder:
        return norm
    experts = paths.list_experts(data_folder)
    low = norm.lower()
    for e in experts:
        if e["rel_path"].lower() == low:
            return e["rel_path"]
    if not low.endswith(".ex5"):
        for e in experts:
            if e["rel_path"].lower() == low + ".ex5":
                return e["rel_path"]
    base = os.path.basename(norm).lower().removesuffix(".ex5")
    matches = [e for e in experts if e["name"].lower() == base]
    if len(matches) == 1:
        return matches[0]["rel_path"]
    return norm  # let MT5 try; error surfaces from the runner


def _extract_params(row: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    return {c: row.get(c) for c in columns if c and c not in _OPT_METRIC_COLS}


def _backtest(*, ea_rel, symbol, from_date, to_date, period, model, deposit, currency,
              leverage, inputs, login, timeout, close_running,
              terminal_path=None) -> BacktestResult:
    mt5 = paths.resolve_mt5(terminal_path)
    runid = uuid.uuid4().hex[:12]
    report_rel = f"mt5_mcp\\{runid}"
    ini = build_ini(
        expert=ea_rel, symbol=symbol, period=period, from_date=from_date, to_date=to_date,
        report_rel=report_rel, deposit=deposit, currency=currency, leverage=leverage,
        model=model, optimization=0, fixed_inputs=inputs or {}, login=login,
    )
    report = run_tester(mt5, ini, report_rel, is_optimization=False,
                        timeout=timeout, close_running=close_running)
    parsed = parse_single_html(report)
    return BacktestResult(
        ea=ea_rel, symbol=symbol, period=period.upper(),
        from_date=normalize_date(from_date), to_date=normalize_date(to_date),
        metrics=BacktestMetrics(**parsed["metrics"]),
        report_path=report, raw=parsed["raw"],
    )


# ---------------------------------------------------------------- tools
@mcp.tool()
def list_mt5_terminals() -> list[TerminalInfo]:
    """List all detected MetaTrader 5 installs (incl. broker builds).

    Use a returned terminal_path as the 'terminal_path' argument of the other tools to
    pick which MT5 to drive. Without it, tools use config/mt5_config.json or auto-detect.
    """
    return [TerminalInfo(**i) for i in paths.list_mt5_installs()]


@mcp.tool()
def mt5_info(terminal_path: str | None = None) -> Mt5Info:
    """Detect the MetaTrader 5 install, data folder, build, and EA count.

    terminal_path: optional terminal64.exe (or its folder) to target a specific install.
    """
    mt5 = paths.resolve_mt5(terminal_path)
    experts = paths.list_experts(mt5.data_folder) if mt5.data_folder else []
    return Mt5Info(
        terminal_path=mt5.terminal_path, install_dir=mt5.install_dir,
        data_folder=mt5.data_folder, build=mt5.build, experts_count=len(experts),
        is_running=bool(running_terminals_for(mt5.install_dir)),
    )


@mcp.tool()
def list_eas(name_filter: str = "", terminal_path: str | None = None) -> list[EaInfo]:
    """List compiled EAs (.ex5) under MQL5/Experts. Use rel_path as the 'ea' argument.

    terminal_path: optional terminal64.exe (or its folder) to target a specific install.
    """
    mt5 = paths.resolve_mt5(terminal_path)
    if not mt5.data_folder:
        return []
    return [EaInfo(name=e["name"], rel_path=e["rel_path"])
            for e in paths.list_experts(mt5.data_folder, name_filter)]


@mcp.tool()
def run_backtest(
    ea: str,
    symbol: str,
    from_date: str,
    to_date: str,
    period: str = "H1",
    model: int = 1,
    deposit: float = 10000,
    currency: str = "USD",
    leverage: str = "1:100",
    inputs: dict[str, Any] | None = None,
    login: str | None = None,
    timeout_sec: int | None = None,
    close_running: bool = False,
    terminal_path: str | None = None,
) -> BacktestResult:
    """Run a single backtest and return parsed metrics.

    Args:
        ea: EA rel_path from list_eas (e.g. 'Examples\\Moving Average\\Moving Average.ex5').
        symbol: e.g. 'EURUSD'. from_date/to_date: 'YYYY.MM.DD' or 'YYYY-MM-DD'.
        period: timeframe (M1..MN1). model: 0=every tick,1=1min OHLC,2=open,4=real ticks.
        inputs: fixed EA inputs {name: value}. close_running: close an open MT5 first.
        terminal_path: optional terminal64.exe (or its folder) to target a specific install
                       (see list_mt5_terminals). Defaults to config/auto-detect.
    """
    cfg = paths.load_config()
    mt5 = paths.resolve_mt5(terminal_path)
    return _backtest(
        ea_rel=_resolve_ea(mt5.data_folder, ea), symbol=symbol, from_date=from_date,
        to_date=to_date, period=period, model=model, deposit=deposit, currency=currency,
        leverage=leverage, inputs=inputs, login=login,
        timeout=timeout_sec or cfg.get("backtest_timeout_sec", 1200),
        close_running=close_running, terminal_path=terminal_path,
    )


@mcp.tool()
def optimize(
    ea: str,
    symbol: str,
    from_date: str,
    to_date: str,
    param_ranges: dict[str, list[float]],
    period: str = "H1",
    model: int = 1,
    criterion: int = 0,
    fixed_inputs: dict[str, Any] | None = None,
    forward_mode: int = 0,
    forward_date: str | None = None,
    top_n: int = 10,
    timeout_sec: int | None = None,
    close_running: bool = False,
    terminal_path: str | None = None,
) -> OptimizationResult:
    """Run a genetic optimization (Optimization=2) and return the best passes.

    Args:
        param_ranges: {input_name: [min, max, step]} for each optimized parameter.
        criterion: 0=Balance,1=Bal*PF,2=Bal*ExpPayoff,3=(100%-DD)*Bal,4=Bal*Recovery,5=Bal*Sharpe.
        forward_mode: 0=off,1=1/2,2=1/3,3=1/4,4=custom(forward_date). top_n: best passes to return.
    """
    cfg = paths.load_config()
    mt5 = paths.resolve_mt5(terminal_path)
    ea_rel = _resolve_ea(mt5.data_folder, ea)
    runid = uuid.uuid4().hex[:12]
    report_rel = f"mt5_mcp\\{runid}"
    ini = build_ini(
        expert=ea_rel, symbol=symbol, period=period, from_date=from_date, to_date=to_date,
        report_rel=report_rel, deposit=cfg.get("default_deposit", 10000),
        currency=cfg.get("default_currency", "USD"), leverage=cfg.get("default_leverage", "1:100"),
        model=model, optimization=2, optimization_criterion=criterion,
        forward_mode=forward_mode, forward_date=forward_date,
        fixed_inputs=fixed_inputs or {}, range_inputs=param_ranges,
    )
    report = run_tester(mt5, ini, report_rel, is_optimization=True,
                        timeout=timeout_sec or cfg.get("optimization_timeout_sec", 7200),
                        close_running=close_running)
    parsed = parse_optimization_xml(report, top_n=top_n)
    best = _extract_params(parsed["top"][0], parsed["columns"]) if parsed["top"] else None
    return OptimizationResult(
        ea=ea_rel, symbol=symbol, period=period.upper(), columns=parsed["columns"],
        total_passes=parsed["total_passes"], best_params=best, top=parsed["top"],
        report_path=report,
    )


@mcp.tool()
def run_forward_test(
    ea: str,
    symbol: str,
    from_date: str,
    to_date: str,
    inputs: dict[str, Any],
    period: str = "H1",
    model: int = 1,
    timeout_sec: int | None = None,
    close_running: bool = False,
    terminal_path: str | None = None,
) -> BacktestResult:
    """Out-of-sample test: a single backtest with fixed `inputs` (e.g. optimize().best_params)."""
    cfg = paths.load_config()
    mt5 = paths.resolve_mt5(terminal_path)
    return _backtest(
        ea_rel=_resolve_ea(mt5.data_folder, ea), symbol=symbol, from_date=from_date,
        to_date=to_date, period=period, model=model,
        deposit=cfg.get("default_deposit", 10000), currency=cfg.get("default_currency", "USD"),
        leverage=cfg.get("default_leverage", "1:100"), inputs=inputs, login=None,
        timeout=timeout_sec or cfg.get("backtest_timeout_sec", 1200),
        close_running=close_running, terminal_path=terminal_path,
    )


@mcp.tool()
def full_pipeline(
    ea: str,
    symbol: str,
    param_ranges: dict[str, list[float]],
    in_sample_from: str,
    in_sample_to: str,
    out_of_sample_from: str,
    out_of_sample_to: str,
    period: str = "H1",
    model: int = 1,
    criterion: int = 0,
    fixed_inputs: dict[str, Any] | None = None,
    top_n: int = 5,
    close_running: bool = False,
    terminal_path: str | None = None,
) -> dict[str, Any]:
    """Optimize on the in-sample window, then forward-test the best params out-of-sample,
    and report an overfitting check (OOS profit factor / IS profit factor)."""
    opt = optimize(
        ea=ea, symbol=symbol, from_date=in_sample_from, to_date=in_sample_to,
        param_ranges=param_ranges, period=period, model=model, criterion=criterion,
        fixed_inputs=fixed_inputs, top_n=top_n, close_running=close_running,
        terminal_path=terminal_path,
    )
    if not opt.best_params:
        return {"optimization": opt.model_dump(), "forward": None,
                "note": "optimization produced no passes"}
    fwd = run_forward_test(
        ea=ea, symbol=symbol, from_date=out_of_sample_from, to_date=out_of_sample_to,
        inputs={k: v for k, v in opt.best_params.items() if v is not None},
        period=period, model=model, close_running=close_running, terminal_path=terminal_path,
    )
    is_pf = None
    for row in opt.top[:1]:
        is_pf = row.get("Profit Factor")
    oos_pf = fwd.metrics.profit_factor
    try:
        ratio = float(oos_pf) / float(is_pf) if is_pf and oos_pf else None
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = None
    return {
        "best_params": opt.best_params,
        "in_sample_profit_factor": is_pf,
        "out_of_sample": fwd.model_dump(),
        "oos_to_is_pf_ratio": ratio,
        "overfit_warning": (ratio is not None and ratio < 0.5),
        "optimization_report": opt.report_path,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
