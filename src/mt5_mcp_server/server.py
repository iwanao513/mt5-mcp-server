"""FastMCP server: drive the MetaTrader 5 Strategy Tester from Claude Code.

Tools: mt5_info, list_eas, run_backtest, optimize, run_forward_test, full_pipeline.

STDIO RULE: never write to stdout (it corrupts JSON-RPC). All logging goes to stderr.
"""
from __future__ import annotations

import json
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
    qualified_passes: int = Field(description="Passes with Trades >= min_trades (entry-count guarantee)")
    min_trades: int = 0
    best_params: dict[str, Any] | None
    top: list[dict[str, Any]]
    report_path: str


def _pass_trades(p: dict[str, Any]) -> float:
    try:
        return float(str(p.get("Trades")).replace(" ", ""))
    except (TypeError, ValueError):
        return 0.0


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


def _config_auth(cfg: dict, login: str | None = None) -> dict[str, str | None]:
    """Optional headless login from config ([Common] in the .ini). Demo accounts recommended.
    Put login/password/server in config/mt5_config.local.json (gitignored)."""
    lg = login or cfg.get("login")
    pw = cfg.get("password")
    return {
        "login": str(lg) if lg not in (None, "") else None,
        "password": str(pw) if pw not in (None, "") else None,
        "server": cfg.get("server") or None,
    }


def _backtest(*, ea_rel, symbol, from_date, to_date, period, model, deposit, currency,
              leverage, inputs, login, timeout, close_running,
              terminal_path=None) -> BacktestResult:
    cfg = paths.load_config()
    mt5 = paths.resolve_mt5(terminal_path)
    runid = uuid.uuid4().hex[:12]
    report_rel = f"mt5_mcp\\{runid}"
    ini = build_ini(
        expert=ea_rel, symbol=symbol, period=period, from_date=from_date, to_date=to_date,
        report_rel=report_rel, deposit=deposit, currency=currency, leverage=leverage,
        model=model, optimization=0, fixed_inputs=inputs or {}, **_config_auth(cfg, login),
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
    pick which MT5 to drive, or call set_default_terminal to make it the persistent default.
    Without either, tools use the configured/auto-detected terminal.
    """
    return [TerminalInfo(**i) for i in paths.list_mt5_installs()]


@mcp.tool()
def set_default_terminal(terminal_path: str) -> Mt5Info:
    """Persist the default MetaTrader 5 terminal so every tool uses it without passing terminal_path.

    Writes terminal_path to the user config (%APPDATA%\\mt5-mcp-server\\mt5_config.json), which
    overrides auto-detection and survives restarts. Pass a terminal64.exe path (or its folder),
    e.g. one from list_mt5_terminals(). Returns the now-default MT5 info.
    """
    p = os.path.normpath(terminal_path)
    if os.path.isdir(p):
        p = os.path.join(p, "terminal64.exe")
    if not os.path.isfile(p):
        raise FileNotFoundError(
            f"terminal64.exe not found at: {p}. Use a path from list_mt5_terminals()."
        )
    cfg_dir = paths.user_config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "mt5_config.json"
    data: dict = {}
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["terminal_path"] = p
    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("default terminal set to %s (%s)", p, cfg_path)
    return mt5_info(terminal_path=p)


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
    min_trades: int = 0,
    timeout_sec: int | None = None,
    close_running: bool = False,
    terminal_path: str | None = None,
) -> OptimizationResult:
    """Run a genetic optimization (Optimization=2) and return the best passes.

    Args:
        param_ranges: {input_name: [min, max, step]} for each optimized parameter.
        criterion: 0=Balance,1=Bal*PF,2=Bal*ExpPayoff,3=(100%-DD)*Bal,4=Bal*Recovery,5=Bal*Sharpe.
        forward_mode: 0=off,1=1/2,2=1/3,3=1/4,4=custom(forward_date). top_n: best passes to return.
        min_trades: drop passes with fewer than this many trades before ranking
                    (guarantees enough entries; avoids over-fit on a handful of trades).
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
        fixed_inputs=fixed_inputs or {}, range_inputs=param_ranges, **_config_auth(cfg),
    )
    report = run_tester(mt5, ini, report_rel, is_optimization=True,
                        timeout=timeout_sec or cfg.get("optimization_timeout_sec", 7200),
                        close_running=close_running)
    parsed = parse_optimization_xml(report, top_n=10**9)  # all passes, already ranked
    passes = parsed["top"]
    qualified = [p for p in passes if _pass_trades(p) >= min_trades] if min_trades > 0 else passes
    top = qualified[:top_n]
    best = _extract_params(top[0], parsed["columns"]) if top else None
    return OptimizationResult(
        ea=ea_rel, symbol=symbol, period=period.upper(), columns=parsed["columns"],
        total_passes=parsed["total_passes"], qualified_passes=len(qualified),
        min_trades=min_trades, best_params=best, top=top, report_path=report,
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
    min_trades: int = 0,
    close_running: bool = False,
    terminal_path: str | None = None,
) -> dict[str, Any]:
    """Optimize on the in-sample window, then forward-test the best params out-of-sample,
    and report an overfitting check (OOS profit factor / IS profit factor).

    min_trades: require this many trades in-sample (entry-count guarantee) so the chosen
    parameters are not over-fit to a handful of trades.
    """
    opt = optimize(
        ea=ea, symbol=symbol, from_date=in_sample_from, to_date=in_sample_to,
        param_ranges=param_ranges, period=period, model=model, criterion=criterion,
        fixed_inputs=fixed_inputs, top_n=top_n, min_trades=min_trades,
        close_running=close_running, terminal_path=terminal_path,
    )
    if not opt.best_params:
        return {"optimization": opt.model_dump(), "forward": None,
                "note": "optimization produced no passes"}
    fwd = run_forward_test(
        ea=ea, symbol=symbol, from_date=out_of_sample_from, to_date=out_of_sample_to,
        inputs={k: v for k, v in opt.best_params.items() if v is not None},
        period=period, model=model, close_running=close_running, terminal_path=terminal_path,
    )
    best_row = opt.top[0] if opt.top else {}
    is_pf = best_row.get("Profit Factor")
    is_trades = _pass_trades(best_row)
    oos_pf = fwd.metrics.profit_factor
    oos_trades = fwd.metrics.total_trades
    try:
        ratio = float(oos_pf) / float(is_pf) if is_pf and oos_pf else None
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = None
    # overfit if OOS PF collapses vs IS, OOS turns unprofitable, or OOS barely trades
    overfit = bool(
        (ratio is not None and ratio < 0.5)
        or (oos_pf is not None and oos_pf < 1.0 and is_pf and float(is_pf) >= 1.2)
        or (oos_trades is not None and oos_trades < max(10, min_trades / 3))
    )
    return {
        "best_params": opt.best_params,
        "in_sample": {"profit_factor": is_pf, "trades": is_trades,
                      "qualified_passes": opt.qualified_passes, "min_trades": min_trades},
        "out_of_sample": {"profit_factor": oos_pf, "net_profit": fwd.metrics.net_profit,
                          "trades": oos_trades, "win_rate_pct": fwd.metrics.win_rate_pct,
                          "report_path": fwd.report_path},
        "oos_to_is_pf_ratio": ratio,
        "overfit_warning": overfit,
        "verdict": ("過剰最適化の疑い（OOSで崩れる）" if overfit
                    else "OOSでも概ね維持（過剰最適化は低い）"),
        "optimization_report": opt.report_path,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
