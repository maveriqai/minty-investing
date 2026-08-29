"""Unit tests for engine/kite_gateway_inprocess.py's extract_kite_error_message
— issue #50's follow-up. Live-observed 2026-08-29: mcp/kite_gateway/server.py
wraps every result (success or error) in the same {"source","as_of","data"}
envelope, and on error sets data to {"error": [<content blocks>]} — so a
human-readable message like "Please log in first using the login tool" sat
three JSON layers deep in what holdings_fetch.py/identity_check.py were
forwarding as an "error", rather than the clean message alone.
"""

import json

from engine.kite_gateway_inprocess import extract_kite_error_message


def test_extracts_message_from_the_real_nested_envelope_shape():
    envelope_text = json.dumps(
        {
            "source": "kite",
            "as_of": "2026-08-29 22:10 IST",
            "data": {"error": [{"type": "text", "text": "Please log in first using the login tool"}]},
        },
        indent=2,
    )

    assert extract_kite_error_message(envelope_text) == "Please log in first using the login tool"


def test_falls_back_to_original_text_on_plain_string():
    assert extract_kite_error_message("Please log in first using the login tool") == (
        "Please log in first using the login tool"
    )


def test_falls_back_to_original_text_on_invalid_json():
    assert extract_kite_error_message("{not valid json") == "{not valid json"


def test_falls_back_to_original_text_on_unexpected_shape():
    unexpected = json.dumps({"source": "kite", "as_of": "2026-08-29", "data": "some string, not a dict"})
    assert extract_kite_error_message(unexpected) == unexpected


def test_falls_back_to_original_text_when_error_list_is_empty():
    envelope_text = json.dumps({"source": "kite", "as_of": "2026-08-29", "data": {"error": []}})
    assert extract_kite_error_message(envelope_text) == envelope_text
