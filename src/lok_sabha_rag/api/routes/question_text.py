"""Question text endpoint — fetch absolute leading C chunks for a specific question."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator, field_validator

from lok_sabha_rag.core.retriever import Retriever

router = APIRouter()

# Shared retriever instance (reuses same Qdrant connection + URL cache as other routes)
_retriever = Retriever()


class QuestionTextRequest(BaseModel):
    question_id: str | None = Field(None, description="Stable composite key (preferred)")
    lok_no: int | None = Field(None, ge=1)
    session_no: int | None = Field(None, ge=1)
    ques_no: int | None = Field(None, ge=1)
    type: str | None = Field(None, description="'Starred' or 'Unstarred' — disambiguates overlapping ques_no ranges")
    c: int = Field(1, ge=1, le=10, description="Number of leading chunks to fetch (chunk_index 0..c-1)")

    @field_validator('question_id', mode='before')
    @classmethod
    def trim_identity(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError('question_id must not be blank')
        return value

    @field_validator('type', mode='before')
    @classmethod
    def normalize_type(cls, value):
        if value is None:
            return value
        if not isinstance(value, str) or value.strip().upper() not in ('STARRED', 'UNSTARRED'):
            raise ValueError('type must be STARRED or UNSTARRED')
        return value.strip().upper()

    @model_validator(mode='after')
    def require_identity(self):
        if not self.question_id and any(v is None for v in (self.lok_no, self.session_no, self.ques_no, self.type)):
            raise ValueError('Provide question_id, or lok_no, session_no, ques_no and type to identify one question')
        return self


class QuestionTextResponse(BaseModel):
    text: str


@router.post("/question-text", response_model=QuestionTextResponse)
def question_text(req: QuestionTextRequest) -> QuestionTextResponse:
    """Fetch the absolute first C chunks (chunk_index 0..c-1) for a specific question.

    Uses Qdrant metadata scroll — not vector search — so the returned chunks are
    always the true document-order leading chunks, regardless of what was retrieved
    during the original search.

    Accepts either question_id (preferred) or the legacy lok_no/session_no/ques_no fields.
    """
    chunks = _retriever._fetch_leading_chunks(
        c=req.c,
        question_id=req.question_id,
        lok_no=req.lok_no,
        session_no=req.session_no,
        ques_no=req.ques_no,
        qtype=req.type,
    )

    if not chunks:
        detail = f"No chunks found for question_id={req.question_id}" if req.question_id else (
            f"No chunks found for Lok {req.lok_no} Session {req.session_no} Q{req.ques_no}"
        )
        raise HTTPException(status_code=404, detail=detail)

    # Join chunk texts — body only (no header to strip since chunks are pure body now)
    parts = [chunk.text or "" for chunk in chunks]

    return QuestionTextResponse(text="\n\n".join(parts))
