"""Pydantic models for API requests and responses."""

from typing import Optional, List
from typing import Literal
from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    content_type: Literal['qa','debate','all'] = 'qa'
    house: Literal['lok_sabha', 'rajya_sabha', 'both'] = 'lok_sabha'
    query: str = Field(..., min_length=1, description="Search query")
    top_k: int = Field(10, ge=1, le=200, description="Number of results")
    lok: Optional[int] = Field(None, description="Filter by Lok Sabha number")
    session: Optional[int] = Field(None, description="Filter by session number")
    ministry: Optional[str] = Field(None, description="Filter by ministry")
    mp_names: Optional[List[str]] = Field(None, description="Filter by MP name(s) — OR logic")

    @field_validator('query', mode='before')
    @classmethod
    def trim_query(cls, value):
        return value.strip() if isinstance(value, str) else value


class EvidenceItemResponse(BaseModel):
    content_type: str = 'qa'
    debate_category: Optional[str] = None
    original_pages: Optional[str] = None
    transcript_status: Optional[str] = None
    document_url: Optional[str] = None
    retrieval_method: str = 'dense'
    house: str = 'lok_sabha'
    date: Optional[str] = None
    source_url: Optional[str] = None
    index: int
    score: float
    chunk_id: str
    question_id: Optional[str] = None
    lok_no: Optional[int]
    session_no: Optional[int]
    ques_no: Optional[int]
    type: Optional[str]  # "Starred" | "Unstarred"
    asked_by: Optional[str]
    ministry: Optional[str]
    subject: Optional[str]
    pdf_filename: Optional[str]
    pdf_url: Optional[str]
    chunk_index: Optional[int]
    text: str
    text_preview: str


class SearchResponse(BaseModel):
    query: str
    results: List[EvidenceItemResponse]
    total: int


class SynthesizeRequest(BaseModel):
    @field_validator('query', mode='before')
    @classmethod
    def trim_query(cls, value):
        return value.strip() if isinstance(value, str) else value

    content_type: Literal['qa','debate','all'] = 'qa'
    house: Literal['lok_sabha', 'rajya_sabha', 'both'] = 'lok_sabha'
    query: str = Field(..., min_length=1, description="Question to answer")
    top_k: int = Field(15, ge=1, le=200, description="M: total chunks to retrieve from Qdrant")
    top_n: Optional[int] = Field(10, ge=1, le=50, description="N: max unique questions to keep")
    chunks_per_question: Optional[int] = Field(2, ge=1, le=10, description="C: evidence chunks per question; Q&A keeps the best match plus opening context")
    top_q: Optional[int] = Field(10, ge=1, le=50, description="Q: recent questions in MP stats summary")
    lok: Optional[int] = Field(None, description="Filter by Lok Sabha number")
    session: Optional[int] = Field(None, description="Filter by session number")
    ministry: Optional[str] = Field(None, description="Filter by ministry")
    mp_names: Optional[List[str]] = Field(None, description="Filter by MP name(s) — OR logic")


class ChunkDetail(BaseModel):
    """Individual chunk within an evidence group."""
    chunk_index: Optional[int]
    score: float
    chunk_id: str
    text: str
    text_preview: str


class EvidenceGroupResponse(BaseModel):
    content_type: str = 'qa'
    debate_category: Optional[str] = None
    original_pages: Optional[str] = None
    transcript_status: Optional[str] = None
    document_url: Optional[str] = None
    retrieval_method: str = 'dense'
    house: str = 'lok_sabha'
    date: Optional[str] = None
    source_url: Optional[str] = None
    """A group of chunks from the same parliamentary question."""
    group_index: int
    question_id: Optional[str] = None
    lok_no: Optional[int]
    session_no: Optional[int]
    ques_no: Optional[int]
    type: Optional[str]  # "Starred" | "Unstarred"
    ministry: Optional[str]
    subject: Optional[str]
    asked_by: Optional[str]
    pdf_url: Optional[str]
    best_score: float
    chunks: List[ChunkDetail]
    total_chunks_available: int = Field(0, description="Total chunks before trimming")


class MpStatsResponse(BaseModel):
    """MP activity statistics from the metadata database."""
    mp_name: str
    total_questions: int
    by_lok: dict
    by_session: dict
    by_type: dict
    top_ministries: List[dict]
    recent_questions: List[dict]


class MinistryStatsResponse(BaseModel):
    """Ministry activity statistics from the metadata database."""
    ministry: str
    total_questions: int
    by_lok: dict
    by_session: dict
    by_type: dict
    top_mps: List[dict]
    recent_questions: List[dict]


class SynthesizeResponse(BaseModel):
    answer_checks: Optional[dict] = None
    period_coverage: Optional[dict] = None
    source_scope: Optional[dict] = None
    query: str
    answer: str
    citations_used: List[int]
    evidence_groups: List[EvidenceGroupResponse]
    total_chunks: int
    mp_stats: Optional[MpStatsResponse] = None
    ministry_stats: Optional[MinistryStatsResponse] = None


# ── Debug / Trace models ──────────────────────────────────────────────


class TraceChunk(BaseModel):
    """Single chunk with full metadata for trace output."""
    chunk_id: str
    question_id: Optional[str] = None
    chunk_index: Optional[int]
    score: float
    lok_no: Optional[int]
    session_no: Optional[int]
    ques_no: Optional[int]
    type: Optional[str]
    ministry: Optional[str]
    asked_by: Optional[str]
    subject: Optional[str]
    pdf_url: Optional[str]
    text: str


class TraceGroup(BaseModel):
    """Question group in trace output."""
    group_key: str
    question_id: Optional[str] = None
    lok_no: Optional[int]
    session_no: Optional[int]
    ques_no: Optional[int]
    type: Optional[str]
    ministry: Optional[str]
    subject: Optional[str]
    asked_by: Optional[str]
    pdf_url: Optional[str]
    best_score: float
    chunk_count: int
    total_chunks_available: int = 0
    chunks: List[TraceChunk]


class TraceResponse(BaseModel):
    """Full pipeline trace — every intermediate stage as JSON."""
    input: dict
    vector_search: dict
    grouping: dict
    c_chunk_fetch: dict
    mp_stats: Optional[dict] = None
    evidence_context: str
    prompt: dict

