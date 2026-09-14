from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from news_letter.utils.constants import (
    PROCESSED_TRANSCRIPT_DIRECTORY,
    TRANSCRIPT_DIRECTORY,
)
from news_letter.utils.enums import ProcessingStatus
from news_letter.youtube.models import Video
import os

from dotenv import load_dotenv
from news_letter.utils.constants import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")


class TranscriptProcessor:
    def __init__(
        self,
        session: Session,
        openai_client: OpenAI,
        chunk_model: str = os.getenv("OPENAI_CHUNK_MODEL"),
        consolidation_model: str = os.getenv("OPENAI_CONSOLIDATION_MODEL"),
        transcript_directory: Path = TRANSCRIPT_DIRECTORY,
        processed_directory: Path = PROCESSED_TRANSCRIPT_DIRECTORY,
        chunk_size: int = 20_000,
        chunk_overlap: int = 500,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")

        if chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative")

        if chunk_overlap >= chunk_size:
            raise ValueError(
                "chunk_overlap must be smaller than chunk_size"
            )

        self.session = session
        self.openai_client = openai_client

        self.chunk_model = chunk_model
        self.consolidation_model = consolidation_model

        self.transcript_directory = transcript_directory
        self.processed_directory = processed_directory
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self.processed_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    def process_video(
        self,
        platform_video_id: str,
        force: bool = False,
    ) -> Path:
        video = self._get_video(platform_video_id)

        self._validate_video(
            video=video,
            force=force,
        )

        video.ai_processing_status = (
            ProcessingStatus.IN_PROGRESS
        )
        video.last_error = None
        self.session.commit()

        try:
            transcript_path = self._raw_transcript_path(
                video.platform_video_id
            )

            transcript = transcript_path.read_text(
                encoding="utf-8",
            ).strip()

            if not transcript:
                raise ValueError(
                    f"Transcript is empty: {transcript_path}"
                )

            chunks = self.chunk_transcript(transcript)

            chunk_summaries: list[str] = []

            for index, chunk in enumerate(
                chunks,
                start=1,
            ):
                print(
                    f"Summarizing chunk {index}/{len(chunks)} "
                    f"for {video.platform_video_id}"
                )

                chunk_summary = self._summarize_chunk(
                    video=video,
                    chunk=chunk,
                    chunk_number=index,
                    total_chunks=len(chunks),
                )

                chunk_summaries.append(chunk_summary)

            print(
                f"Consolidating {len(chunk_summaries)} "
                f"chunk summaries..."
            )

            final_markdown = self._consolidate_summaries(
                video=video,
                chunk_summaries=chunk_summaries,
            )

            output_path = self._processed_transcript_path(
                video.platform_video_id
            )

            output_path.write_text(
                final_markdown.strip() + "\n",
                encoding="utf-8",
            )

            video.ai_processing_status = (
                ProcessingStatus.COMPLETED
            )
            video.processed_at = datetime.now(timezone.utc)
            video.last_error = None

            self.session.commit()

            return output_path

        except KeyboardInterrupt:
            self.session.rollback()

            interrupted_video = self.session.get(
                Video,
                video.id,
            )

            if interrupted_video is not None:
                interrupted_video.ai_processing_status = (
                    ProcessingStatus.PENDING
                )
                interrupted_video.last_error = None
                self.session.commit()

            raise

        except Exception as exc:
            self.session.rollback()

            failed_video = self.session.get(
                Video,
                video.id,
            )

            if failed_video is not None:
                failed_video.ai_processing_status = (
                    ProcessingStatus.FAILED
                )
                failed_video.last_error = str(exc)[:2_000]
                self.session.commit()

            raise

    def chunk_transcript(
        self,
        transcript: str,
    ) -> list[str]:
        chunks: list[str] = []
        start = 0
        transcript_length = len(transcript)

        while start < transcript_length:
            proposed_end = min(
                start + self.chunk_size,
                transcript_length,
            )

            end = self._find_chunk_boundary(
                transcript=transcript,
                start=start,
                proposed_end=proposed_end,
            )

            chunk = transcript[start:end].strip()

            if chunk:
                chunks.append(chunk)

            if end >= transcript_length:
                break

            next_start = end - self.chunk_overlap

            if next_start <= start:
                next_start = end

            start = next_start

        return chunks

    def _summarize_chunk(
        self,
        video: Video,
        chunk: str,
        chunk_number: int,
        total_chunks: int,
    ) -> str:
        response = self.openai_client.responses.create(
            model=self.chunk_model,
            instructions=(
                "You are a research analyst extracting substantive "
                "information from financial and economic video "
                "transcripts. Preserve distinctions between facts, "
                "creator opinions, predictions, and speculation. "
                "Do not add outside knowledge."
            ),
            input=f"""
Analyze chunk {chunk_number} of {total_chunks} from this video.

Video title: {video.title}
Creator: {video.channel.name if video.channel else "Unknown"}
YouTube video ID: {video.platform_video_id}

Extract the following from this chunk:

1. Main arguments and claims
2. Important facts, numbers, dates, and data
3. Economic or financial causal relationships
4. Predictions and expected time horizons
5. Risks and warnings
6. Recommendations or suggested actions
7. Important people, institutions, companies, assets, and indicators
8. Caveats, uncertainty, and conditions
9. Topics that could connect with other videos

Rules:

- Use concise Markdown.
- Exclude advertisements, sponsorships, greetings, and calls to subscribe.
- Do not treat a creator's assertion as an independently verified fact.
- Do not invent missing context.
- Preserve numerical units and time periods.
- Do not produce a full-video conclusion because this is only one chunk.

Transcript chunk:

{chunk}
""".strip(),
        )

        summary = response.output_text.strip()

        if not summary:
            raise RuntimeError(
                f"OpenAI returned no text for chunk {chunk_number}"
            )

        return summary

    def _consolidate_summaries(
        self,
        video: Video,
        chunk_summaries: list[str],
    ) -> str:
        combined_summaries = "\n\n".join(
            (
                f"## Source Chunk {index}\n\n"
                f"{summary}"
            )
            for index, summary in enumerate(
                chunk_summaries,
                start=1,
            )
        )

        response = self.openai_client.responses.create(
            model=self.consolidation_model,
            instructions=(
                "You are an editorial research analyst. Consolidate "
                "partial transcript analyses into one accurate Markdown "
                "research brief. Remove repetition while preserving "
                "important disagreements, qualifications, numerical "
                "details, and distinctions between fact and opinion."
            ),
            input=f"""
Create the final structured Markdown summary for this video.

Video title: {video.title}
Creator: {video.channel.name if video.channel else "Unknown"}
YouTube video ID: {video.platform_video_id}
Published at: {video.published_at or "Unknown"}

Use exactly this document structure:

# {video.title}

## Metadata

- Creator:
- YouTube Video ID:
- Published:
- Model:

## Executive Summary

Write 3-6 concise sentences explaining the overall video.

## Central Thesis

State the creator's principal argument.

## Key Points

Use concise bullets for the major supporting ideas.

## Important Facts and Data

Capture important figures, dates, rates, percentages, market levels,
historical comparisons, and policy details. Attribute claims where needed.

## Predictions and Outlook

For each prediction, include:

- Prediction
- Time horizon, when available
- Creator's reasoning
- Expressed confidence or uncertainty

## Causal Claims

List important claimed cause-and-effect relationships. Do not present
unverified causal assertions as proven facts.

## Risks and Warnings

List material risks identified in the video.

## Recommendations

List explicit or implied recommendations made by the creator. Do not
turn them into your own financial advice.

## Important Entities

List important people, institutions, companies, countries, currencies,
assets, policies, and economic indicators.

## Caveats and Uncertainty

Preserve material qualifications, dependencies, and uncertainty.

## Newsletter-Worthy Takeaways

Provide 3-5 concise takeaways useful to someone who did not watch the
video.

## Topic Tags

Return 3-8 lowercase kebab-case tags.

Rules:

- Remove duplicated points across chunks.
- Do not add outside information.
- Do not claim to have verified the creator's statements.
- Preserve conflicting or qualified statements.
- Produce only the final Markdown document.
- Set the Model metadata value to {self.consolidation_model}.

Chunk analyses:

{combined_summaries}
""".strip(),
        )

        markdown = response.output_text.strip()

        if not markdown:
            raise RuntimeError(
                "OpenAI returned an empty consolidated summary"
            )

        return markdown

    def _get_video(
        self,
        platform_video_id: str,
    ) -> Video:
        statement = select(Video).where(
            Video.platform_video_id
            == platform_video_id
        )

        video = self.session.scalar(statement)

        if video is None:
            raise LookupError(
                f"No database video found for {platform_video_id}"
            )

        return video

    @staticmethod
    def _validate_video(
        video: Video,
        force: bool,
    ) -> None:
        if (
            video.transcript_status
            != ProcessingStatus.COMPLETED
        ):
            raise ValueError(
                "Transcript has not been downloaded successfully. "
                f"Current status: {video.transcript_status.value}"
            )

        if (
            video.ai_processing_status
            == ProcessingStatus.COMPLETED
            and not force
        ):
            raise ValueError(
                "Video has already been summarized. "
                "Use force=True to regenerate it."
            )

    def _raw_transcript_path(
        self,
        platform_video_id: str,
    ) -> Path:
        path = (
            self.transcript_directory
            / f"{platform_video_id}-raw.txt"
        )

        if not path.exists():
            raise FileNotFoundError(
                f"Raw transcript file does not exist: {path}"
            )

        return path

    def _processed_transcript_path(
        self,
        platform_video_id: str,
    ) -> Path:
        return (
            self.processed_directory
            / f"{platform_video_id}-processed.md"
        )

    @staticmethod
    def _find_chunk_boundary(
        transcript: str,
        start: int,
        proposed_end: int,
    ) -> int:
        if proposed_end >= len(transcript):
            return len(transcript)

        minimum_boundary = start + (
            (proposed_end - start) // 2
        )

        candidates = [
            transcript.rfind(
                "\n\n",
                minimum_boundary,
                proposed_end,
            ),
            transcript.rfind(
                "\n",
                minimum_boundary,
                proposed_end,
            ),
            transcript.rfind(
                ". ",
                minimum_boundary,
                proposed_end,
            ),
            transcript.rfind(
                "? ",
                minimum_boundary,
                proposed_end,
            ),
            transcript.rfind(
                "! ",
                minimum_boundary,
                proposed_end,
            ),
        ]

        boundary = max(candidates)

        if boundary == -1:
            return proposed_end

        return boundary + 1
