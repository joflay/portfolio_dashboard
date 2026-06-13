from portfolio_dashboard.risk_free import latest_rate_on_or_before, load_risk_free_rates


def test_load_risk_free_rates_uses_decimal_rate(tmp_path) -> None:
    path = tmp_path / "DGS3MO_risk_free_rate.csv"
    path.write_text(
        "Date,risk_free_rate_percent,risk_free_rate,series_id,source\n"
        "2026-06-12,3.78,0.0378,DGS3MO,fred\n"
    )

    assert load_risk_free_rates(path) == {"2026-06-12": 0.0378}


def test_load_risk_free_rates_falls_back_to_percent(tmp_path) -> None:
    path = tmp_path / "DGS3MO_risk_free_rate.csv"
    path.write_text(
        "Date,risk_free_rate_percent,risk_free_rate,series_id,source\n"
        "2026-06-12,3.78,,DGS3MO,fred\n"
    )

    assert load_risk_free_rates(path) == {"2026-06-12": 0.0378}


def test_latest_rate_on_or_before_carries_forward() -> None:
    rates = {"2026-06-10": 0.03, "2026-06-12": 0.04}

    assert latest_rate_on_or_before(rates, "2026-06-11") == 0.03
    assert latest_rate_on_or_before(rates, "2026-06-12") == 0.04
