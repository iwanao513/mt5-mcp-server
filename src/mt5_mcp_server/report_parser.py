"""Parse MT5 Strategy Tester results.

- Single backtest -> HTML (.htm), even if you name it .xml. Labels are localized to the
  terminal UI language (Japanese on this machine), so we match EN + JA aliases and also
  keep the full raw label->value map so nothing is lost.
- Optimization -> Excel-2003 SpreadsheetML (.xml).
Encoding is not fixed: sniff BOM, then utf-8 -> cp932/cp1252 -> latin-1.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup
from lxml import etree

SS = "{urn:schemas-microsoft-com:office:spreadsheet}"

# canonical metric -> label variants (English both layouts + Japanese)
ALIASES: dict[str, list[str]] = {
    "net_profit": ["Total Net Profit", "Total net profit", "総損益", "純益", "総純益"],
    "gross_profit": ["Gross Profit", "Gross profit", "総利益", "粗利益"],
    "gross_loss": ["Gross Loss", "Gross loss", "総損失", "粗損失"],
    "profit_factor": ["Profit Factor", "Profit factor", "プロフィットファクター", "プロフィットファクタ"],
    "expected_payoff": ["Expected Payoff", "Expected payoff", "期待利得", "期待ペイオフ"],
    "recovery_factor": ["Recovery Factor", "Recovery factor", "リカバリーファクター", "リカバリファクター"],
    "sharpe_ratio": ["Sharpe Ratio", "シャープレシオ"],
    "balance_dd_max": ["Balance Drawdown Maximal", "Maximal drawdown", "残高最大ドローダウン",
                        "最大ドローダウン", "最大ドローダウン(残高)"],
    "balance_dd_rel": ["Balance Drawdown Relative", "Relative drawdown", "残高相対ドローダウン",
                        "相対ドローダウン"],
    "total_trades": ["Total Trades", "Total trades", "総取引数", "取引数", "総取引"],
    "total_deals": ["Total Deals", "約定数", "総約定数", "約定総数"],
    "profit_trades": ["Profit Trades (% of total)", "Profit trades (% of total)",
                       "勝ちトレード (勝率 %)", "勝ちトレード（合計に対する％）", "勝ちトレード"],
    "loss_trades": ["Loss Trades (% of total)", "Loss trades (% of total)",
                     "負けトレード (負率 %)", "負けトレード（合計に対する％）", "負けトレード"],
    "bars": ["Bars", "バー"],
    "ticks": ["Ticks", "ティック"],
    "history_quality": ["History Quality", "ヒストリー品質", "履歴の質"],
}

_GRAPH_MARKERS = ("StrategyTester.gif", "report_by_ticktester.png", "<img")


def read_report(path: str) -> str:
    raw = open(path, "rb").read()
    if raw[:2] == b"\xff\xfe":
        return raw.decode("utf-16-le")
    if raw[:2] == b"\xfe\xff":
        return raw.decode("utf-16-be")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig")
    for enc in ("utf-8", "cp1252", "cp932", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def _truncate_summary(html: str) -> str:
    """Cut the huge per-deal ledger that follows the summary graph image."""
    for marker in _GRAPH_MARKERS:
        i = html.find(marker)
        if i > 0:
            return html[:i]
    return html


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    m = re.search(r"-?\d[\d ]*\.?\d*", s.replace(",", ""))
    return float(m.group().replace(" ", "")) if m else None


def _two(s: str | None) -> tuple[float | None, float | None]:
    """'1169.32 (1.17%)' -> (abs, pct); '1.17% (1169.32)' -> (abs, pct)."""
    if not s:
        return (None, None)
    nums = re.findall(r"-?\d[\d ]*\.?\d*", s.replace(",", ""))
    vals = [float(x.replace(" ", "")) for x in nums]
    if not vals:
        return (None, None)
    pct_first = "%" in s and (s.index("%") < (s.find("(") if "(" in s else len(s)))
    if pct_first:
        return (vals[1] if len(vals) > 1 else None, vals[0])
    return (vals[0], vals[1] if len(vals) > 1 else None)


def _known_labels() -> set[str]:
    out: set[str] = set()
    for variants in ALIASES.values():
        for v in variants:
            out.add(v.lower())
    return out


def parse_single_html(path: str) -> dict:
    html = _truncate_summary(read_report(path))
    soup = BeautifulSoup(html, "lxml")
    cells = [c.get_text(" ", strip=True) for c in soup.find_all(["td", "th"])]
    n = len(cells)
    known = _known_labels()

    pairs: dict[str, str] = {}  # lowercased label -> value
    for i, c in enumerate(cells):
        if not c:
            continue
        key = c.rstrip(":：").strip()
        kl = key.lower()
        if not key:
            continue
        is_label = c.endswith(":") or c.endswith("：") or kl in known
        if is_label:
            for j in range(i + 1, min(i + 3, n)):
                if cells[j].strip():
                    pairs.setdefault(kl, cells[j].strip())
                    break

    def pick(metric: str) -> str | None:
        for v in ALIASES.get(metric, []):
            val = pairs.get(v.lower())
            if val is not None:
                return val
        return None

    dd_max = pick("balance_dd_max")
    dd_rel = pick("balance_dd_rel")
    pt = pick("profit_trades")

    metrics = {
        "net_profit": _num(pick("net_profit")),
        "gross_profit": _num(pick("gross_profit")),
        "gross_loss": _num(pick("gross_loss")),
        "profit_factor": _num(pick("profit_factor")),
        "expected_payoff": _num(pick("expected_payoff")),
        "recovery_factor": _num(pick("recovery_factor")),
        "sharpe_ratio": _num(pick("sharpe_ratio")),
        "balance_dd_max_abs": _two(dd_max)[0],
        "balance_dd_max_pct": _two(dd_max)[1],
        "balance_dd_rel_pct": _two(dd_rel)[1],
        "total_trades": _num(pick("total_trades")),
        "profit_trades": pt,
        "win_rate_pct": _two(pt)[1] if pt else None,
        "history_quality": pick("history_quality"),
    }
    return {"report_path": path, "metrics": metrics, "raw": pairs}


def parse_optimization_xml(path: str, top_n: int = 10) -> dict:
    tree = etree.parse(path)
    header: list[str] | None = None
    passes: list[dict] = []
    for row in tree.iter(f"{SS}Row"):
        vals: dict[int, str | None] = {}
        idx = 1
        for cell in row.iter(f"{SS}Cell"):
            ci = cell.get(f"{SS}Index")
            if ci:
                idx = int(ci)
            data = cell.find(f"{SS}Data")
            vals[idx] = data.text if data is not None else None
            idx += 1
        ordered = [vals.get(k) for k in range(1, (max(vals) if vals else 0) + 1)]
        if header is None:
            header = [h or f"col{i}" for i, h in enumerate(ordered)]
        else:
            passes.append(dict(zip(header, ordered)))

    def fnum(d: dict, key: str) -> float | None:
        return _num(d.get(key)) if key in d else None

    # rank by 'Result' (optimization criterion) desc, then Profit
    def sort_key(p: dict):
        return (fnum(p, "Result") or float("-inf"), fnum(p, "Profit") or float("-inf"))

    passes.sort(key=sort_key, reverse=True)
    return {
        "report_path": path,
        "columns": header or [],
        "total_passes": len(passes),
        "top": passes[:top_n],
    }
