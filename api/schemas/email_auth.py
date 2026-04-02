"""Email authentication (DKIM/SPF/DMARC) schemas."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class EmailAuthStatus(BaseModel):
    domain: str
    spf: str = Field(description="'ok', 'missing', or 'invalid'")
    dkim: str = Field(description="'ok', 'missing', or 'invalid'")
    dmarc: str = Field(description="'ok', 'missing', or 'invalid'")


class DKIMSetupResponse(BaseModel):
    domain: str
    dkim_selector: str = "default"
    public_key: str = ""
    dns_record: str = Field(
        description="Full TXT record to add to DNS"
    )
    private_key_path: str = ""


class DNSRecordEntry(BaseModel):
    type: str = "TXT"
    name: str
    value: str
    description: str = ""


class EmailDNSRecords(BaseModel):
    domain: str
    records: list[DNSRecordEntry] = []


class SPFRecord(BaseModel):
    domain: str
    record: str
    includes: list[str] = []


class DMARCRecord(BaseModel):
    domain: str
    record: str
    policy: str = "quarantine"


class EmailVerifyResponse(BaseModel):
    domain: str
    spf: str
    dkim: str
    dmarc: str
    all_ok: bool
    details: dict[str, str] = {}
