"""Domain models describing Windows desktop windows and captures."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WindowInfo(BaseModel):
    """A snapshot of a top-level window identified by its HWND."""

    model_config = ConfigDict(frozen=True)

    hwnd: int = Field(gt=0)
    title: str = Field(min_length=1)
    pid: int = Field(ge=0)
    left: int
    top: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class CaptureMetadata(BaseModel):
    """Identity, dimensions, and time associated with a captured frame."""

    model_config = ConfigDict(frozen=True)

    hwnd: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    timestamp: datetime
