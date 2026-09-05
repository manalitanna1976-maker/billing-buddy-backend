"""Lenient Pydantic models for Meta's WhatsApp Cloud API webhook payload.

These exist only to give the router typed, defensive access into a payload
whose exact shape Meta does not guarantee down to every optional field.
``extra="ignore"`` everywhere, and every field the router doesn't strictly
need is optional -- a malformed or partially-shaped payload must never 500;
the router treats unexpected shapes as "nothing to do here" and acks 200.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Text(BaseModel):
    model_config = ConfigDict(extra="ignore")

    body: str | None = None


class ButtonReply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    title: str | None = None


class Interactive(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    button_reply: ButtonReply | None = None


class Button(BaseModel):
    model_config = ConfigDict(extra="ignore")

    payload: str | None = None
    text: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    from_: str | None = Field(default=None, alias="from")
    type: str | None = None
    text: Text | None = None
    interactive: Interactive | None = None
    button: Button | None = None


class Metadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    phone_number_id: str | None = None


class Value(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metadata: Metadata | None = None
    messages: list[Message] | None = None
    statuses: list[dict] | None = None


class Change(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: Value | None = None
    field: str | None = None


class Entry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    changes: list[Change] | None = None


class WebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object: str | None = None
    entry: list[Entry] | None = None
