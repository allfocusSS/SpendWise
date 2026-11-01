from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# Length only, no composition rules (NIST SP 800-63B). The upper bound keeps hashing cheap to
# reject; Argon2 itself has no length limit.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=254)
    # repr=False: the password never appears in a repr, log line or traceback of this model.
    password: str = Field(
        min_length=PASSWORD_MIN_LENGTH,
        max_length=PASSWORD_MAX_LENGTH,
        repr=False,
        json_schema_extra={"format": "password"},
    )


class LoginRequest(BaseModel):
    """No format or policy checks: a wrong email or password is simply "invalid" (401)."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=254)
    password: str = Field(
        min_length=1,
        max_length=PASSWORD_MAX_LENGTH,
        repr=False,
        json_schema_extra={"format": "password"},
    )


class UserRead(BaseModel):
    """The signed-in user. Never includes the password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime
