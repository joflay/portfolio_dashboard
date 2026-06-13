from portfolio_dashboard.webull import WebullClient, _flatten_order_history, generate_signature


class _Settings:
    def __init__(self, token_file):
        self.token_file = token_file


def test_read_token_uses_first_non_empty_line(tmp_path) -> None:
    token_file = tmp_path / "token.txt"
    token_file.write_text("\naccess-token\n1782250690617\nNORMAL\n")

    assert WebullClient(_Settings(token_file))._read_token() == "access-token"


def test_generate_signature_matches_webull_doc_example() -> None:
    signature = generate_signature(
        path="/trade/place_order",
        query_params={"a1": "webull", "a2": "123", "a3": "xxx", "q1": "yyy"},
        body_string='{"k1":123,"k2":"this is the api request body","k3":true,"k4":{"foo":[1,2]}}',
        app_key="776da210ab4a452795d74e726ebd74b6",
        app_secret="0f50a2e853334a9aae1a783bee120c1f",
        host="api.webull.com",
        timestamp="2022-01-04T03:55:31Z",
        nonce="48ef5afed43d4d91ae514aaeafbc29ba",
    )

    assert signature == "kvlS6opdZDhEBo5jq40nHYXaLvM="


def test_flatten_order_history_group_rows() -> None:
    payload = [
        {
            "combo_order_id": "combo",
            "combo_type": "NORMAL",
            "orders": [{"order_id": "order", "symbol": "AAPL"}],
        }
    ]

    assert _flatten_order_history(payload) == [
        {"order_id": "order", "symbol": "AAPL", "combo_order_id": "combo", "combo_type": "NORMAL"}
    ]
