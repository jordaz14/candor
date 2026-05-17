"""Document-structure-aware chunking for filings, transcripts, and reviews.

Tokenization uses tiktoken's cl100k_base (the encoder behind text-embedding-3-small).
Counting tokens is much more reliable than counting characters or words for embedding cost
and context-window decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


@dataclass
class Chunk:
    text: str
    token_count: int
    # Optional positional metadata the caller will merge into the row's metadata JSONB
    chunk_index: int
    

def count_tokens(text: str) -> int:
    return len(_ENC.encode(text))


DEFAULT_TARGET_TOKENS = 800
DEFAULT_OVERLAP_TOKENS = 80


def chunk_section(
    text: str,
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[Chunk]:
    """Split a single section's text into retrieval-friendly chunks."""
    if not text: return []
    sub_chunks = []
    sub_chunk, sub_chunk_idx = "", 0

    text_blocks = text.split("\n\n") 
    for block in text_blocks:
        if not sub_chunk or count_tokens(block + sub_chunk) <= target_tokens:
            sub_chunk = f"{sub_chunk}\n\n{block}" if sub_chunk else block
        else:
            sub_chunks.append(Chunk(text=sub_chunk, token_count=count_tokens(sub_chunk), chunk_index=sub_chunk_idx))
            tail_ids = _ENC.encode(sub_chunk)[-overlap_tokens:]
            tail = _ENC.decode(tail_ids)
            sub_chunk = f"{tail}\n\n{block}" if tail else block
            sub_chunk_idx += 1

    sub_chunks.append(Chunk(text=sub_chunk, token_count=count_tokens(sub_chunk), chunk_index=sub_chunk_idx))

    return sub_chunks


# ---------------------------------------------------------------------------
# Speaker-turn chunking for earnings call transcripts.
# Each "turn" is one contiguous block of speech from a single speaker.
# Strategy: emit one chunk per turn, but if a turn exceeds 2x target size,
# fall back to chunk_section() on that turn's text.
# ---------------------------------------------------------------------------

@dataclass
class SpeakerTurn:
    speaker: str
    speaker_role: str  # "CEO" | "CFO" | "Analyst" | "Operator" | "Other"
    text: str


def chunk_transcript(
    turns: Iterable[SpeakerTurn],
    *,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> list[tuple[SpeakerTurn, Chunk]]:
    """Yield (turn, chunk) pairs. Long turns are sub-chunked via chunk_section()."""
    out: list[tuple[SpeakerTurn, Chunk]] = []
    idx = 0
    for turn in turns:
        token_count = count_tokens(turn.text)
        if token_count <= target_tokens * 2:
            out.append((turn, Chunk(text=turn.text, token_count=token_count, chunk_index=idx)))
            idx += 1
        else:
            for sub in chunk_section(turn.text, target_tokens=target_tokens):
                out.append(
                    (turn, Chunk(text=sub.text, token_count=sub.token_count, chunk_index=idx))
                )
                idx += 1
    return out


# ---------------------------------------------------------------------------
# Glassdoor reviews are already short (typically 50-300 tokens per pro/con).
# We emit one chunk per individual pro or con, no further splitting.
# ---------------------------------------------------------------------------

def chunk_review_text(text: str) -> Chunk:
    return Chunk(text=text.strip(), token_count=count_tokens(text), chunk_index=0)
