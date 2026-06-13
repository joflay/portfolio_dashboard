from portfolio_dashboard.db import Database
from portfolio_dashboard.sync import _load_local_accounts


class _Settings:
    def __init__(self, account_info_file):
        self.account_info_file = account_info_file


def test_all_activity_defaults_to_vol_factor(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    db.initialize()

    db.upsert_positions(
        "Vol_Factor",
        "acct",
        [{"symbol": "abc", "quantity": "3", "avgPrice": "10"}],
    )
    db.upsert_orders(
        "Vol_Factor",
        "acct",
        [{"orderId": "o1", "symbol": "abc", "side": "BUY", "filledQty": "3", "avgPrice": "10"}],
    )

    assert db.fetch_positions("Vol_Factor")[0]["symbol"] == "ABC"
    assert db.fetch_orders("Vol_Factor")[0]["strategy"] == "Vol_Factor"


def test_load_local_account_info_file(tmp_path) -> None:
    path = tmp_path / "accouninfo.txt"
    path.write_text('{"account_id": "abc", "account_label": "Individual Margin"}')

    accounts = _load_local_accounts(_Settings(path))

    assert accounts == [{"account_id": "abc", "account_label": "Individual Margin"}]
