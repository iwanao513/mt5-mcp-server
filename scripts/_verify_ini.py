"""Print sample generated .ini files to eyeball correctness."""
from mt5_mcp_server.ini_builder import build_ini

print("===== SINGLE BACKTEST =====")
print(build_ini(
    expert=r"Examples\Moving Average\Moving Average.ex5",
    symbol="EURUSD", period="H1", from_date="2024-01-01", to_date="2024-06-30",
    report_rel=r"mt5_mcp\abc123", deposit=10000, currency="USD", leverage="1:100",
    model=1, optimization=0,
    fixed_inputs={"Lots": 0.1, "MaximumRisk": 0.02, "MovingPeriod": 12},
))

print("\n===== GENETIC OPTIMIZATION + FORWARD =====")
print(build_ini(
    expert=r"Examples\Moving Average\Moving Average.ex5",
    symbol="EURUSD", period="H1", from_date="2023.01.01", to_date="2024.12.31",
    report_rel=r"mt5_mcp\opt456", model=2, optimization=2, optimization_criterion=0,
    forward_mode=4, forward_date="2024.07.01",
    fixed_inputs={"Lots": 0.1},
    range_inputs={"MovingPeriod": [10, 40, 2], "MaximumRisk": [0.01, 0.05, 0.01]},
))
