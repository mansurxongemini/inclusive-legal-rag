"""Pydantic schemas for the editorial (Tahririyat) module."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class CuratedAnswerCreate(BaseModel):
    question: str = Field(..., min_length=5, max_length=2000)
    alt_questions: List[str] = Field(default_factory=list, max_length=20)
    answer_md: str = Field(..., min_length=10, max_length=20000)
    language: str = Field(default="uz", max_length=8)
    category: str = Field(default="general", max_length=64)
    author: str = Field(default="", max_length=128)


class CuratedAnswerUpdate(BaseModel):
    question: Optional[str] = Field(default=None, min_length=5, max_length=2000)
    alt_questions: Optional[List[str]] = Field(default=None, max_length=20)
    answer_md: Optional[str] = Field(default=None, min_length=10, max_length=20000)
    language: Optional[str] = Field(default=None, max_length=8)
    category: Optional[str] = Field(default=None, max_length=64)


class LegalLinkCreate(BaseModel):
    canonical_id: str = Field(..., min_length=1, max_length=256)
    note: str = Field(default="", max_length=1000)


class NotificationResolve(BaseModel):
    action: Literal["keep", "edited", "unpublish", "delete"] = Field(...)
    note: str = Field(default="", max_length=2000)
