#!/usr/bin/env python3
"""Live-chain test for the NewKwLab LangChain tools.

Runs the tools against a gateway instance given by env vars (the test
harness points this at a LOCAL instance of the production gateway code with
a throwaway ledger — never at the production ledger):

  NKW_BASE_URL      gateway base, e.g. http://127.0.0.1:<port>
  NKW_API_KEY       trial key seeded with 1,000 credits
  NKW_API_KEY_LOW   (optional) key for a customer seeded with exactly
                    1 credit — used to capture the real INSUFFICIENT_CREDITS
                    shape on the second charged call

Asserts the full chain through the tools: card_check charges exactly 1
credit, a not-found LEI lookup charges 0, and the /v1/usage ledger agrees
with both. Usage rows are a LIST of {product_id, calls, charged, ...}.

Usage:  NKW_BASE_URL=... NKW_API_KEY=... python3 test_live.py
Exit:   0 = PASS, 1 = FAIL.
"""

import json
import os
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "../python-sdk/src")

from newkwlab_api_bundle import NewKwLabClient  # noqa: E402
from newkwlab_langchain import create_tools  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail else ""))


def row(usage, product_id):
    rows = usage.get("usage_by_product")
    if isinstance(rows, list):
        return next((r for r in rows if r.get("product_id") == product_id), None)
    return None


def main():
    base = os.environ["NKW_BASE_URL"]
    client = NewKwLabClient(api_key=os.environ["NKW_API_KEY"], base_url=base)
    tools = {t.name: t for t in create_tools(client)}

    u0 = client.usage()
    check("usage (before) balance = 1000", u0.get("balance") == 1000,
          f"balance={u0.get('balance')}")

    # 1. card_check through the tool: real verdict, exactly 1 credit.
    out = json.loads(tools["card_check"].invoke({"number": "4242424242424242"}))
    check("tool card_check -> ok, valid=true, charged 1, balance 999",
          out.get("ok") is True and out.get("data", {}).get("valid") is True
          and out.get("credits_charged") == 1 and out.get("credits_balance") == 999,
          json.dumps(out)[:200])

    # 2. lei_lookup with a malformed LEI: not-found signal, 0 credits.
    out = json.loads(tools["lei_lookup"].invoke({"lei": "984500ABCDEF12345678"}))
    check("tool lei_lookup (fake LEI) -> ok, status=invalid_format, charged 0",
          out.get("ok") is True and out.get("data", {}).get("status") == "invalid_format"
          and out.get("credits_charged") == 0,
          json.dumps(out)[:200])

    # 3. Ledger agrees: balance 999, per-product rows match the two calls.
    u1 = client.usage()
    card_row, lei_row = row(u1, "cardcheck"), row(u1, "leilookup")
    check("usage (after card+lei) balance = 999, rows aligned",
          u1.get("balance") == 999
          and card_row is not None and card_row.get("calls") == 1 and card_row.get("charged") == 1
          and lei_row is not None and lei_row.get("calls") == 1
          and lei_row.get("charged") == 0 and lei_row.get("not_found") == 1,
          f"balance={u1.get('balance')}, card={card_row}, lei={lei_row}")

    # 4. email_check through the tool (anchor route): verdict + 1 credit.
    out = json.loads(tools["email_check"].invoke({"email": "alice@gmail.com"}))
    check("tool email_check -> ok, valid=true, charged 1, balance 998",
          out.get("ok") is True and out.get("data", {}).get("valid") is True
          and out.get("credits_charged") == 1 and out.get("credits_balance") == 998,
          json.dumps(out)[:200])
    u2 = client.usage()
    email_row = row(u2, "emailcheck")
    check("usage (final) balance = 998, emailcheck row charged 1",
          u2.get("balance") == 998 and email_row is not None
          and email_row.get("charged") == 1,
          f"balance={u2.get('balance')}, email={email_row}")

    # 5. Low-balance customer: 1 credit, two differently-numbered card calls.
    low_key = os.environ.get("NKW_API_KEY_LOW")
    if low_key:
        low_client = NewKwLabClient(api_key=low_key, base_url=base)
        low_tools = {t.name: t for t in create_tools(low_client)}
        check("low-balance usage (before) = 1", low_client.usage().get("balance") == 1)
        out1 = json.loads(low_tools["card_check"].invoke({"number": "4242424242424242"}))
        check("low-balance card_check #1 -> charged 1, balance 0",
              out1.get("ok") is True and out1.get("credits_charged") == 1
              and out1.get("credits_balance") == 0,
              json.dumps(out1)[:200])
        out2 = json.loads(low_tools["card_check"].invoke({"number": "5555555555554444"}))
        err = out2.get("error", {})
        print(f"INSUFFICIENT_PROBE raw: ok={out2.get('ok')} status={err.get('status')} "
              f"code={err.get('code')} detail={err.get('detail')}")
        check("low-balance card_check #2 -> ok=false INSUFFICIENT_CREDITS (402)",
              out2.get("ok") is False and err.get("code") == "INSUFFICIENT_CREDITS"
              and err.get("status") == 402,
              f"actual status={err.get('status')} code={err.get('code')}")
        check("low-balance usage (after) still 0 — nothing charged on refusal",
              low_client.usage().get("balance") == 0)
    else:
        print("SKIP  low-balance INSUFFICIENT_CREDITS probe (NKW_API_KEY_LOW not set)")

    passed = sum(1 for _, ok in results if ok)
    print(f"\nLIVE TEST: {'PASS' if passed == len(results) else 'FAIL'} "
          f"({passed}/{len(results)} assertions)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
