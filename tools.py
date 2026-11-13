"""LangChain tools for the NewKwLab API Bundle gateway.

Wraps the already-verified Python SDK (``newkwlab_api_bundle.NewKwLabClient``)
as LangChain ``StructuredTool`` objects, so any LangChain / LangGraph agent
can call the gateway's validation, lookup and screening products with the
customer's single aggregate key and shared credit balance.

Design rules:
- No HTTP code lives here — every tool delegates to the Python SDK client.
- Every tool returns a compact JSON *string* for the model:
  success -> {"ok": true, "tool": ..., "credits_charged": ...,
              "credits_balance": ..., "cache": ..., "data": {...}}
  failure -> {"ok": false, "tool": ..., "error": {"code": ..., "status": ...,
              "detail": ...}}
- Tools never raise: gateway errors (``GatewayError``) and local misuse are
  converted into the failure string above, so a bad call cannot crash the
  agent loop. ``credits_charged`` is the amount the gateway actually took
  (not-found results and errors are charged 0 by gateway design).
"""

from __future__ import annotations

import json
from typing import Any, Callable, List, Optional
from urllib.parse import quote

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from newkwlab_api_bundle import CallResult, GatewayError, NewKwLabClient

__all__ = ["create_tools", "TOOL_NAMES"]

TOOL_NAMES = [
    "email_check",
    "phone_check",
    "card_check",
    "lei_lookup",
    "airport_lookup",
    "sanctions_screen",
]


# -- Input schemas -----------------------------------------------------------


class EmailCheckInput(BaseModel):
    email: str = Field(description="The email address to validate, e.g. 'alice@example.com'.")


class PhoneCheckInput(BaseModel):
    phone: str = Field(
        description="The phone number to validate, in international format, e.g. '+14155552671'."
    )


class CardCheckInput(BaseModel):
    number: str = Field(
        description="The bank-card number to validate (digits, spaces/dashes are stripped "
        "by the service). Validation only — this never charges the card."
    )


class LeiLookupInput(BaseModel):
    lei: str = Field(
        description="The 20-character Legal Entity Identifier (LEI) code to look up."
    )


class AirportLookupInput(BaseModel):
    code: str = Field(description="The airport's IATA code, e.g. 'LAX'.")


class SanctionsScreenInput(BaseModel):
    name: str = Field(
        description="The person or company name to screen against sanctions and watchlists."
    )


# -- Result formatting ---------------------------------------------------------


def _success(tool: str, result: CallResult) -> str:
    payload = {
        "ok": True,
        "tool": tool,
        "credits_charged": result.credits_charged,
        "credits_balance": result.credits_balance,
        "cache": result.cache,
        "data": result.data,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _failure(tool: str, code: str, status: Optional[int], detail: Optional[str]) -> str:
    payload = {
        "ok": False,
        "tool": tool,
        "error": {"code": code, "status": status, "detail": detail},
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _guarded(tool: str, fn: Callable[[], CallResult]) -> str:
    """Run one SDK call and format the outcome; never raises."""
    try:
        return _success(tool, fn())
    except GatewayError as e:
        return _failure(tool, e.code, e.status, e.detail)
    except ValueError as e:  # e.g. client built without an API key
        return _failure(tool, "CLIENT_ERROR", None, str(e))
    except Exception as e:  # last resort: keep the agent loop alive
        return _failure(tool, "UNEXPECTED_ERROR", None, f"{type(e).__name__}: {e}")


# -- Tool factory ---------------------------------------------------------------


def create_tools(
    client: Optional[NewKwLabClient] = None,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> List[StructuredTool]:
    """Build the NewKwLab gateway tools for a LangChain agent.

    Pass an existing ``NewKwLabClient`` (recommended when you also use the
    SDK directly), or let one be created from ``api_key`` / ``base_url``
    (falling back to the ``NKW_API_KEY`` / ``NKW_BASE_URL`` env vars and the
    production gateway, exactly like the SDK).
    """
    if client is None:
        client = NewKwLabClient(api_key=api_key, base_url=base_url)

    def email_check(email: str) -> str:
        return _guarded("email_check", lambda: client.email_check(email))

    def phone_check(phone: str) -> str:
        return _guarded("phone_check", lambda: client.phone_check(phone))

    def card_check(number: str) -> str:
        return _guarded("card_check", lambda: client.card_check(number))

    def lei_lookup(lei: str) -> str:
        return _guarded(
            "lei_lookup",
            lambda: client.call("leilookup", f"/lei/{quote(lei, safe='')}"),
        )

    def airport_lookup(code: str) -> str:
        return _guarded(
            "airport_lookup",
            lambda: client.call("airportbase", "/airport", params={"code": code}),
        )

    def sanctions_screen(name: str) -> str:
        return _guarded(
            "sanctions_screen",
            lambda: client.call("sanctionscreen", "/screen", params={"name": name}),
        )

    return [
        StructuredTool.from_function(
            func=email_check,
            name="email_check",
            description=(
                "Validate one email address through the NewKwLab gateway: syntax, MX "
                "records, disposable / role-account detection, typo suggestion, "
                "catch-all risk and a 0-100 score. Costs 1 credit per result; "
                "repeat calls with the same parameters within 24h are cached and free."
            ),
            args_schema=EmailCheckInput,
        ),
        StructuredTool.from_function(
            func=phone_check,
            name="phone_check",
            description=(
                "Validate one phone number through the NewKwLab gateway: format "
                "validity, country and line-type details. Costs 1 credit per result; "
                "repeat calls with the same parameters within 24h are cached and free."
            ),
            args_schema=PhoneCheckInput,
        ),
        StructuredTool.from_function(
            func=card_check,
            name="card_check",
            description=(
                "Validate one bank-card number through the NewKwLab gateway: Luhn "
                "check, card network and type. Validation only — never a payment. "
                "Costs 1 credit per result; repeat calls with the same parameters "
                "within 24h are cached and free."
            ),
            args_schema=CardCheckInput,
        ),
        StructuredTool.from_function(
            func=lei_lookup,
            name="lei_lookup",
            description=(
                "Look up a company by its Legal Entity Identifier (LEI) through the "
                "NewKwLab gateway (GLEIF data): registration status and entity "
                "details. Costs 2 credits when a record is found; a malformed LEI "
                "or a lookup with no record costs 0 credits."
            ),
            args_schema=LeiLookupInput,
        ),
        StructuredTool.from_function(
            func=airport_lookup,
            name="airport_lookup",
            description=(
                "Get airport data by IATA code through the NewKwLab gateway: name, "
                "city, country, coordinates and timezone. Costs 2 credits per result."
            ),
            args_schema=AirportLookupInput,
        ),
        StructuredTool.from_function(
            func=sanctions_screen,
            name="sanctions_screen",
            description=(
                "Screen a person or company name against sanctions and watchlists "
                "through the NewKwLab gateway. Returns match candidates with list "
                "sources and scores — review matches before acting on them. "
                "Costs 2 credits per screening."
            ),
            args_schema=SanctionsScreenInput,
        ),
    ]
