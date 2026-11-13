#!/usr/bin/env python3
"""Offline smoke test for the NewKwLab LangChain tools — no network.

Drives the six tools against a stub client with the same surface as
``newkwlab_api_bundle.NewKwLabClient`` and asserts:
  * tool names / descriptions / input schemas line up with the SDK methods,
  * each tool routes to the right client method with the right arguments,
  * success returns a compact JSON string carrying data + credit headers,
  * gateway errors come back as an {"ok": false, ...} string — never raised.

Usage:  python3 test_offline.py
Exit:   0 = PASS, 1 = FAIL.
"""

import json
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "../python-sdk/src")

from newkwlab_api_bundle import CallResult, GatewayError, NewKwLabClient  # noqa: E402
from newkwlab_langchain import TOOL_NAMES, create_tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


class StubClient:
    """Same surface as NewKwLabClient; records calls, returns canned results."""

    def __init__(self):
        self.calls = []
        self.raise_with = None

    def _record(self, entry):
        self.calls.append(entry)
        if self.raise_with is not None:
            raise self.raise_with
        return CallResult(
            data={"stub": True, "echo": entry[0]},
            credits_charged=1,
            credits_balance=999,
            cache="MISS",
        )

    def email_check(self, email):
        return self._record(("email_check", email))

    def phone_check(self, phone):
        return self._record(("phone_check", phone))

    def card_check(self, number):
        return self._record(("card_check", number))

    def call(self, product, endpoint, method="GET", params=None, body=None):
        return self._record(("call", product, endpoint, params))


EXPECTED_FIELDS = {
    "email_check": {"email"},
    "phone_check": {"phone"},
    "card_check": {"number"},
    "lei_lookup": {"lei"},
    "airport_lookup": {"code"},
    "sanctions_screen": {"name"},
}

INVOKES = {
    "email_check": {"email": "alice@example.com"},
    "phone_check": {"phone": "+14155552671"},
    "card_check": {"number": "4242424242424242"},
    "lei_lookup": {"lei": "984500ABCDEF12345678"},
    "airport_lookup": {"code": "LAX"},
    "sanctions_screen": {"name": "Test Person"},
}

EXPECTED_ROUTES = {
    "email_check": ("email_check", "alice@example.com"),
    "phone_check": ("phone_check", "+14155552671"),
    "card_check": ("card_check", "4242424242424242"),
    "lei_lookup": ("call", "leilookup", "/lei/984500ABCDEF12345678", None),
    "airport_lookup": ("call", "airportbase", "/airport", {"code": "LAX"}),
    "sanctions_screen": ("call", "sanctionscreen", "/screen", {"name": "Test Person"}),
}


def main():
    # 0. The tools must sit on the real client's surface — not a fantasy API.
    for method in ("email_check", "phone_check", "card_check", "call"):
        check(f"real NewKwLabClient has method {method}()",
              callable(getattr(NewKwLabClient, method, None)))

    stub = StubClient()
    tools = create_tools(stub)
    by_name = {t.name: t for t in tools}

    check("six tools constructed", len(tools) == 6, f"got {len(tools)}")
    check("tool names == TOOL_NAMES", [t.name for t in tools] == TOOL_NAMES,
          ", ".join(t.name for t in tools))
    check("all tools are StructuredTool with callable _run",
          all(callable(getattr(t, "_run", None)) for t in tools))

    for name, fields in EXPECTED_FIELDS.items():
        tool = by_name[name]
        schema_fields = set(tool.args_schema.model_fields)
        check(f"{name}: args schema fields == {sorted(fields)}",
              schema_fields == fields, f"got {sorted(schema_fields)}")
        check(f"{name}: description present and states credit cost",
              bool(tool.description) and "credit" in tool.description.lower())

    # Success path: routing + return shape.
    for name, payload in INVOKES.items():
        stub.calls.clear()
        out = by_name[name].invoke(payload)
        ok_shape = isinstance(out, str)
        parsed = {}
        if ok_shape:
            try:
                parsed = json.loads(out)
            except ValueError:
                ok_shape = False
        check(f"{name}: returns JSON string with ok=true and credit headers",
              ok_shape and parsed.get("ok") is True
              and parsed.get("credits_charged") == 1
              and parsed.get("credits_balance") == 999
              and parsed.get("cache") == "MISS"
              and parsed.get("data", {}).get("stub") is True)
        check(f"{name}: routed to {EXPECTED_ROUTES[name][0]} with right args",
              stub.calls == [EXPECTED_ROUTES[name]],
              f"recorded={stub.calls}")

    # Error path: a GatewayError must come back as a string, not raise.
    stub.raise_with = GatewayError(402, "INSUFFICIENT_CREDITS", "Balance below price.")
    out = by_name["card_check"].invoke({"number": "4242424242424242"})
    parsed = json.loads(out)
    check("gateway error -> ok=false string with code/status, no raise",
          parsed.get("ok") is False
          and parsed["error"]["code"] == "INSUFFICIENT_CREDITS"
          and parsed["error"]["status"] == 402,
          out[:120])

    # Local misuse (client without key) must also be a string, not a raise.
    bare_tools = {t.name: t for t in create_tools(NewKwLabClient(api_key=None))}
    # Force the no-key branch: the SDK raises ValueError before any request.
    out = bare_tools["email_check"].invoke({"email": "a@b.co"})
    parsed = json.loads(out)
    check("missing API key -> ok=false CLIENT_ERROR string, no raise",
          parsed.get("ok") is False and parsed["error"]["code"] == "CLIENT_ERROR",
          out[:120])

    passed = sum(results)
    print(f"\nOFFLINE SMOKE: {'PASS' if passed == len(results) else 'FAIL'} "
          f"({passed}/{len(results)} assertions)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
