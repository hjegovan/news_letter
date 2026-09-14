# uv run python -m news_letter.processing.batch_process 50
from __future__ import annotations
import argparse
import os
from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from tqdm import tqdm
from news_letter.processing.transcript_processor import (
    TranscriptProcessor,
)
from news_letter.utils.constants import PROJECT_ROOT
from news_letter.utils.enums import ProcessingStatus
from news_letter.youtube.db import create_session, init_db
from news_letter.youtube.models import Video
from openai import RateLimitError


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize a batch of downloaded YouTube transcripts."
        )
    )

    parser.add_argument(
        "limit",
        type=int,
        help="Maximum number of transcripts to process.",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=20_000,
        help=(
            "Approximate number of characters per transcript chunk. "
            "Default: 20000."
        ),
    )

    parser.add_argument(
        "--include-failed",
        action="store_true",
        help=(
            "Retry videos whose AI processing status is FAILED."
        ),
    )

    parser.add_argument(
        "--oldest-first",
        action="store_true",
        help=(
            "Process the oldest videos first instead of the newest."
        ),
    )

    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help=(
            "Stop the batch when one transcript fails. "
            "By default, failures are logged and processing continues."
        ),
    )

    return parser.parse_args()


def get_unprocessed_videos(
    session,
    limit: int,
    include_failed: bool,
    oldest_first: bool,
) -> list[Video]:
    allowed_statuses = [ProcessingStatus.PENDING]

    if include_failed:
        allowed_statuses.append(ProcessingStatus.FAILED)

    order_column = (
        Video.published_at.asc()
        if oldest_first
        else Video.published_at.desc()
    )

    statement = (
        select(Video)
        .options(selectinload(Video.channel))
        .where(
            Video.transcript_status
            == ProcessingStatus.COMPLETED,
            Video.ai_processing_status.in_(allowed_statuses),
        )
        .order_by(
            order_column,
            Video.id.asc() if oldest_first else Video.id.desc(),
        )
        .limit(limit)
    )

    return list(session.scalars(statement))


def reset_interrupted_ai_jobs(session) -> int:
    statement = select(Video).where(
        Video.ai_processing_status
        == ProcessingStatus.IN_PROGRESS
    )

    interrupted_videos = list(
        session.scalars(statement)
    )

    for video in interrupted_videos:
        video.ai_processing_status = ProcessingStatus.PENDING
        video.last_error = None

    session.commit()

    return len(interrupted_videos)


def main() -> None:
    arguments = parse_arguments()

    if arguments.limit <= 0:
        raise SystemExit("The batch limit must be greater than zero.")

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    chunk_model = os.getenv(
        "OPENAI_CHUNK_MODEL",
        "gpt-5.6-luna",
    )

    consolidation_model = os.getenv(
        "OPENAI_CONSOLIDATION_MODEL",
        "gpt-5.6-luna",
    )

    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is missing from the .env file."
        )

    init_db()

    openai_client = OpenAI(
        api_key=api_key,
        max_retries=3,
        timeout=300.0,
    )

    with create_session() as session:
        reset_count = reset_interrupted_ai_jobs(session)

        if reset_count:
            print(
                f"Reset {reset_count} interrupted AI processing job(s)."
            )

        videos = get_unprocessed_videos(
            session=session,
            limit=arguments.limit,
            include_failed=arguments.include_failed,
            oldest_first=arguments.oldest_first,
        )

        if not videos:
            print("No unprocessed transcripts were found.")
            return

        processor = TranscriptProcessor(
            session=session,
            openai_client=openai_client,
            chunk_model=chunk_model,
            consolidation_model=consolidation_model,
            chunk_size=arguments.chunk_size,
        )

        successful = 0
        failed = 0

        print(
            f"Starting AI summarization for "
            f"{len(videos)} transcript(s)."
        )

        progress_bar = tqdm(
            videos,
            total=len(videos),
            desc="Summaries",
            unit="video",
            dynamic_ncols=True,
        )

        for video in progress_bar:
            creator_name = (
                video.channel.name
                if video.channel is not None
                else "Unknown"
            )

            progress_bar.set_postfix(
                success=successful,
                failed=failed,
                video=video.platform_video_id,
            )

            tqdm.write(
                "\nProcessing: "
                f"{creator_name} — {video.title}"
            )

            try:
                output_path = processor.process_video(
                    platform_video_id=video.platform_video_id,
                    force=(
                        video.ai_processing_status
                        == ProcessingStatus.FAILED
                    ),
                )

                successful += 1

                tqdm.write(
                    f"Saved: {output_path}"
                )

            except KeyboardInterrupt:
                tqdm.write(
                    "\nBatch interrupted. "
                    "Incomplete work will be retried."
                )
                raise

            except RateLimitError as exc:
                error_text = str(exc)

                if "credit_balance_exhausted" in error_text:
                    tqdm.write(
                        "\nOpenAI API credits are exhausted. "
                        "Stopping batch."
                    )
                    raise SystemExit(
                        "Add API credits before retrying."
                    )

                failed += 1

                tqdm.write(
                    f"Failed: {video.platform_video_id}"
                )
                tqdm.write(
                    f"Reason: {error_text[:500]}"
                )

                if arguments.stop_on_error:
                    raise

            except Exception as exc:
                failed += 1

                tqdm.write(
                    f"Failed: {video.platform_video_id}"
                )
                tqdm.write(
                    f"Reason: {str(exc)[:500]}"
                )

                if arguments.stop_on_error:
                    raise

            progress_bar.set_postfix(
                success=successful,
                failed=failed,
            )

        print(
            "\nBatch summarization complete: "
            f"{successful} successful, "
            f"{failed} failed, "
            f"{len(videos)} attempted."
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "\nSummarization stopped. "
            "The current video will be returned to PENDING."
        )
