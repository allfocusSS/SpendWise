from pydantic import BaseModel, ConfigDict, model_validator

from app.models import TransactionType
from app.schemas.common import HexColor, NonEmptyStr50


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr50
    type: TransactionType
    color: HexColor = "#64748b"


class CategoryUpdate(BaseModel):
    """All fields optional: only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    name: NonEmptyStr50 | None = None
    type: TransactionType | None = None
    color: HexColor | None = None

    @model_validator(mode="after")
    def _reject_explicit_nulls(self) -> "CategoryUpdate":
        # Leaving a field out means "don't change it"; sending null is a mistake.
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"'{field}' cannot be null")
        return self


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: TransactionType
    color: str
    is_default: bool
