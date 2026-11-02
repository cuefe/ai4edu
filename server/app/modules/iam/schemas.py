import uuid

from pydantic import BaseModel, Field


class PhoneLoginIn(BaseModel):
    phone: str = Field(min_length=11, max_length=20)
    password: str = Field(min_length=1, max_length=64)


class StudentLoginIn(BaseModel):
    tenant_code: str = Field(min_length=1, max_length=32)
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=64)


class SmsSendIn(BaseModel):
    phone: str = Field(min_length=11, max_length=20)


class SmsLoginIn(BaseModel):
    phone: str = Field(min_length=11, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class RefreshIn(BaseModel):
    refresh_token: str


class ChangePasswordIn(BaseModel):
    old_password: str = Field(min_length=1, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


class TenantBrief(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str


class MeOut(BaseModel):
    id: uuid.UUID
    name: str
    roles: list[str]
    username: str | None = None
    phone_masked: str | None = None
    must_change_password: bool
    tenant: TenantBrief | None = None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: MeOut


class OkOut(BaseModel):
    ok: bool = True
