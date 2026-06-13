from portfolio_dashboard.analytics import build_performance


def test_strategy_performance_metrics_from_fills_and_marks() -> None:
    positions = [{"symbol": "ABC", "quantity": 10, "avg_price": 10}]
    orders = [
        {
            "order_id": "1",
            "symbol": "ABC",
            "side": "BUY",
            "quantity": 10,
            "filled_quantity": 10,
            "avg_price": 10,
            "status": "FILLED",
            "placed_at": "2026-01-01",
        }
    ]
    prices = [
        {"symbol": "ABC", "date": "2026-01-01", "close": 10},
        {"symbol": "ABC", "date": "2026-01-02", "close": 12},
        {"symbol": "ABC", "date": "2026-01-03", "close": 9},
    ]

    result = build_performance(positions, orders, prices)

    assert result["strategy"] == "Vol_Factor"
    assert result["summary"]["latest_equity"] == -10
    assert result["summary"]["net_exposure"] == 90
    assert result["summary"]["net_aum"] == 90
    assert result["summary"]["daily_pnl"] == -30
    assert result["summary"]["max_drawdown"] == -1.5
    assert result["summary"]["trade_count"] == 1
    assert result["holdings"][0]["symbol"] == "ABC"


def test_positions_only_fallback_builds_history() -> None:
    result = build_performance(
        [{"symbol": "XYZ", "quantity": 2, "avg_price": 5}],
        [],
        [
            {"symbol": "XYZ", "date": "2026-01-01", "close": 5},
            {"symbol": "XYZ", "date": "2026-01-02", "close": 6},
        ],
    )

    assert result["summary"]["latest_equity"] == 12
    assert result["summary"]["open_positions"] == 1


def test_sharpe_uses_daily_excess_returns() -> None:
    positions = [{"symbol": "ABC", "quantity": 10, "avg_price": 10}]
    orders = [
        {
            "order_id": "1",
            "symbol": "ABC",
            "side": "BUY",
            "quantity": 10,
            "filled_quantity": 10,
            "avg_price": 10,
            "status": "FILLED",
            "placed_at": "2026-06-12",
        }
    ]
    prices = [
        {"symbol": "ABC", "date": "2026-06-12", "close": 10},
        {"symbol": "ABC", "date": "2026-06-15", "close": 11},
        {"symbol": "ABC", "date": "2026-06-16", "close": 12},
    ]

    without_rf = build_performance(positions, orders, prices)
    with_rf = build_performance(
        positions,
        orders,
        prices,
        {"2026-06-12": 0.05, "2026-06-15": 0.05, "2026-06-16": 0.05},
    )

    assert with_rf["summary"]["risk_free_rate"] == 0.05
    assert with_rf["summary"]["sharpe"] != without_rf["summary"]["sharpe"]
