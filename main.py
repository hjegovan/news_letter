from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from news_letter.processing.transcript_processor import TranscriptProcessor
from news_letter.youtube.client import YouTubeRepository
from news_letter.youtube.db import create_session, init_db
from news_letter.youtube.ingestion import TranscriptIngestionService
from news_letter.youtube.models import Video
from news_letter.utils.constants import (
    PROJECT_ROOT,
    TRANSCRIPT_DIRECTORY,
)
from news_letter.utils.enums import ProcessingStatus

load_dotenv(PROJECT_ROOT / ".env")


def main() -> None:
    init_db()

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is missing from the .env file."
        )

    chunk_model = os.getenv(
        "OPENAI_CHUNK_MODEL",
        "gpt-5.6-luna",
    )

    consolidation_model = os.getenv(
        "OPENAI_CONSOLIDATION_MODEL",
        "gpt-5.6-luna",
    )

    openai_client = OpenAI(
        api_key=api_key,
        max_retries=3,
        timeout=300.0,
    )

    with create_session() as session:
        repository = YouTubeRepository(
            session=session,
            transcript_directory=TRANSCRIPT_DIRECTORY,
            proxy_username=os.getenv(
                "WEBSHARE_PROXY_USERNAME"
            ),
            proxy_password=os.getenv(
                "WEBSHARE_PROXY_PASSWORD"
            ),
        )

        ingestion_service = TranscriptIngestionService(
            session=session,
            youtube_repository=repository,
        )

        ingestion_service.run(
            backfill_limit=15,
            latest_video_limit=10,
            transcript_limit=200,
        )

        # -----------------------------------
        # Process downloaded transcripts
        # -----------------------------------

        processor = TranscriptProcessor(
            session=session,
            openai_client=openai_client,
            chunk_model=chunk_model,
            consolidation_model=consolidation_model,
        )

        statement = (
            select(Video)
            .options(selectinload(Video.channel))
            .where(
                Video.transcript_status
                == ProcessingStatus.COMPLETED,
                Video.ai_processing_status
                == ProcessingStatus.PENDING,
            )
            .order_by(
                Video.published_at.desc(),
                Video.id.desc(),
            )
        )

        videos = list(session.scalars(statement))

        if not videos:
            print("\nNo transcripts require AI processing.")
            return

        print(
            f"\nProcessing {len(videos)} transcript(s) "
            f"with {chunk_model}."
        )

        successful = 0
        failed = 0

        for video in videos:
            creator = (
                video.channel.name
                if video.channel is not None
                else "Unknown"
            )

            print(
                f"\nProcessing: {creator} — {video.title}"
            )

            try:
                output_path = processor.process_video(
                    platform_video_id=video.platform_video_id,
                )

                successful += 1
                print(f"Saved: {output_path}")

            except KeyboardInterrupt:
                raise

            except Exception as exc:
                failed += 1

                print(
                    f"Failed: {video.platform_video_id}"
                )
                print(
                    f"Reason: {str(exc)[:500]}"
                )

        print(
            "\nAI processing complete: "
            f"{successful} successful, "
            f"{failed} failed."
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "\nPipeline stopped. "
            "Incomplete work will be retried."
        )
