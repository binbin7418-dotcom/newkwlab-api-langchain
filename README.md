# newkwlab-langchain

LangChain tools for the **NewKwLab API Bundle** gateway — one API key and one
shared credit balance for a suite of data tools, ready to drop into any
LangChain / LangGraph agent.

> **Pre-release.** This package is built and tested locally but not yet
> published to PyPI. Its dependency `newkwlab-api-bundle` (the gateway's
> Python SDK) is not on PyPI yet either — install it from the sibling
> `../python-sdk` directory first (see below).

## Tools

| Tool | What it does | Credits |
|---|---|---|
| `email_check` | Validate an email address: syntax, MX, disposable / role account, typo suggestion, catch-all risk, 0–100 score | 1 |
| `phone_check` | Validate a phone number: format, country, line type | 1 |
| `card_check` | Validate a bank-card number: Luhn, network, type (validation only — never a payment) | 1 |
| `lei_lookup` | Look up a company by Legal Entity Identifier (GLEIF data) | 2, **0 if no record** |
| `airport_lookup` | Airport data by IATA code: name, city, country, coordinates, timezone | 2 |
| `sanctions_screen` | Screen a person/company name against sanctions & watchlists | 2 |

Charging rules come from the gateway and are surfaced on every result:
a result is charged its credit price, a lookup with **no record is free**,
repeating the same call within 24h hits the **cache and is free**, and
upstream errors are never charged.

Every tool returns a compact JSON string for the model:

```json
{"ok":true,"tool":"card_check","credits_charged":1,"credits_balance":999,"cache":"MISS","data":{"valid":true,"network":"Visa"}}
```

Errors come back in the same shape — tools never raise into the agent loop:

```json
{"ok":false,"tool":"card_check","error":{"code":"INSUFFICIENT_CREDITS","status":402,"detail":"..."}}
```

## Install (from this monorepo, pre-release)

```bash
pip install ../python-sdk   # provides newkwlab-api-bundle, the SDK these tools wrap
pip install .               # this package (pulls in langchain-core)
```

## Quick start

```python
import os
from newkwlab_api_bundle import NewKwLabClient
from newkwlab_langchain import create_tools

client = NewKwLabClient(api_key=os.environ["NKW_API_KEY"])  # nkw_live_...
tools = create_tools(client)

# Call a tool directly:
print(tools[2].invoke({"number": "4242424242424242"}))
# {"ok":true,"tool":"card_check","credits_charged":1,...}
```

`create_tools()` can also build the client for you — `create_tools(api_key=...)`
— or read `NKW_API_KEY` / `NKW_BASE_URL` from the environment, exactly like
the SDK.

## Use with a LangChain agent

```python
from langchain.agents import create_agent  # from the `langchain` package
from langchain_openai import ChatOpenAI      # or any chat model you use

from newkwlab_api_bundle import NewKwLabClient
from newkwlab_langchain import create_tools

tools = create_tools(NewKwLabClient())  # key from NKW_API_KEY env var
agent = create_agent(ChatOpenAI(model="gpt-4o-mini"), tools)

result = agent.invoke({
    "messages": [{
        "role": "user",
        "content": "Is alice@example.com a real mailbox, and is the card "
                   "4242 4242 4242 4242 structurally valid?",
    }]
})
```

The agent picks the tools, spends credits from the shared balance, and reads
the JSON results — including `credits_charged` / `credits_balance`, so it can
report what a lookup cost.

## Getting a key

Buy a credit pack on Gumroad (NewKwLab API Bundle), activate the license at
the bundle activation page to receive your `nkw_live_...` key, and keep it in
an environment variable — never in source code.

## Tests

```bash
python3 test_offline.py   # no network: schema/routing/error-shape checks vs a stub client
# test_live.py runs against a gateway instance you point it at:
NKW_BASE_URL=http://127.0.0.1:<port> NKW_API_KEY=<seeded-key> python3 test_live.py
```

## License

MIT
