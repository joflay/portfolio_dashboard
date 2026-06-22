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
        {"symbol": "SPY", "date": "2026-01-01", "close": 100},
        {"symbol": "ABC", "date": "2026-01-02", "close": 12},
        {"symbol": "SPY", "date": "2026-01-02", "close": 102},
        {"symbol": "ABC", "date": "2026-01-03", "close": 9},
        {"symbol": "SPY", "date": "2026-01-03", "close": 101},
    ]

    result = build_performance(positions, orders, prices)

    assert result["strategy"] == "Vol_Factor"
    assert result["summary"]["latest_equity"] == -10
    assert result["summary"]["net_exposure"] == 90
    assert result["summary"]["gross_exposure"] == 90
    assert result["summary"]["net_aum"] == 90
    assert result["summary"]["daily_pnl"] == -30
    assert result["summary"]["daily_return"] == -0.33333333
    assert result["summary"]["total_return"] == -0.22222222
    assert result["summary"]["spy_daily_return"] == -0.00980392
    assert result["summary"]["spy_total_return"] == 0.01
    assert result["summary"]["daily_return_over_spy"] == -0.32352941
    assert result["summary"]["total_return_over_spy"] == -0.23222222
    assert result["summary"]["max_drawdown"] == -1.5
    assert result["summary"]["trade_count"] == 1
    assert result["holdings"][0]["symbol"] == "ABC"
    assert result["holdings"][0]["return"] == -0.1


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


def test_broker_position_pnl_overrides_synthetic_summary_pnl() -> None:
    result = build_performance(
        [
            {
                "symbol": "ABC",
                "quantity": 2,
                "avg_price": 5,
                "day_profit_loss": "1.25",
                "unrealized_profit_loss": "3.50",
            },
            {
                "symbol": "XYZ",
                "quantity": 1,
                "avg_price": 10,
                "day_profit_loss": "-0.25",
                "unrealized_profit_loss": "2.00",
            },
        ],
        [],
        [
            {"symbol": "ABC", "date": "2026-01-01", "close": 5},
            {"symbol": "XYZ", "date": "2026-01-01", "close": 10},
            {"symbol": "ABC", "date": "2026-01-02", "close": 8},
            {"symbol": "XYZ", "date": "2026-01-02", "close": 12},
        ],
    )

    assert result["summary"]["latest_equity"] == 5.5
    assert result["summary"]["total_pnl"] == 5.5
    assert result["summary"]["daily_pnl"] == 1.0


def test_latest_daily_row_uses_broker_return_over_gross_exposure() -> None:
    result = build_performance(
        [
            {
                "symbol": "ABC",
                "quantity": 100,
                "avg_price": 10,
                "day_profit_loss": "10.00",
                "unrealized_profit_loss": "20.00",
            }
        ],
        [
            {
                "order_id": "1",
                "symbol": "ABC",
                "side": "BUY",
                "quantity": 1,
                "filled_quantity": 1,
                "avg_price": 98,
                "status": "FILLED",
                "placed_at": "2026-01-01",
            }
        ],
        [
            {"symbol": "ABC", "date": "2026-01-01", "close": 100},
            {"symbol": "ABC", "date": "2026-01-02", "close": 110},
        ],
    )

    latest = result["equity_curve"][-1]
    assert latest["equity"] == 20
    assert latest["daily_pnl"] == 10
    assert latest["daily_return"] == 0.00090909


def test_daily_spy_comparison_requires_matching_benchmark_dates() -> None:
    result = build_performance(
        [{"symbol": "ABC", "quantity": 1, "avg_price": 10}],
        [
            {
                "order_id": "1",
                "symbol": "ABC",
                "side": "BUY",
                "quantity": 1,
                "filled_quantity": 1,
                "avg_price": 10,
                "status": "FILLED",
                "placed_at": "2026-06-12",
            }
        ],
        [
            {"symbol": "ABC", "date": "2026-06-12", "close": 10},
            {"symbol": "SPY", "date": "2026-06-12", "close": 100},
            {"symbol": "ABC", "date": "2026-06-15", "close": 11},
            {"symbol": "ABC", "date": "2026-06-16", "close": 12},
            {"symbol": "SPY", "date": "2026-06-16", "close": 101},
        ],
    )

    assert result["summary"]["daily_return"] == 0.09090909
    assert result["summary"]["spy_daily_return"] is None
    assert result["summary"]["daily_return_over_spy"] is None


def test_returns_use_gross_exposure_for_short_positions() -> None:
    result = build_performance(
        [
            {"symbol": "LONG", "quantity": 2, "avg_price": 10},
            {"symbol": "SHORT", "quantity": -1, "avg_price": 30},
        ],
        [],
        [
            {"symbol": "LONG", "date": "2026-01-01", "close": 10},
            {"symbol": "SHORT", "date": "2026-01-01", "close": 30},
            {"symbol": "LONG", "date": "2026-01-02", "close": 12},
            {"symbol": "SHORT", "date": "2026-01-02", "close": 24},
        ],
    )

    assert result["summary"]["net_exposure"] == 0
    assert result["summary"]["gross_exposure"] == 48
    assert result["summary"]["daily_pnl"] == 10
    assert result["summary"]["daily_return"] == 0.20833333
    assert result["holdings"][1]["return"] == 0.2


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
