# uv run python -m news_letter.processing.process_video VIDEO_ID
from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv
from openai import OpenAI

from news_letter.processing.transcript_processor import (
    TranscriptProcessor,
)
from news_letter.utils.constants import PROJECT_ROOT
from news_letter.youtube.db import create_session, init_db


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize one downloaded YouTube transcript."
        )
    )

    parser.add_argument(
        "video_id",
        help="YouTube video ID stored in the videos table.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate an existing processed summary.",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=20_000,
        help="Approximate characters per transcript chunk.",
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_SUMMARY_MODEL")

    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is missing from .env"
        )

    if not model:
        raise SystemExit(
            "OPENAI_SUMMARY_MODEL is missing from .env"
        )

    init_db()

    client = OpenAI(
        api_key=api_key,
        max_retries=3,
        timeout=300.0,
    )

    with create_session() as session:
        processor = TranscriptProcessor(
            session=session,
            openai_client=client,
            model=model,
            chunk_size=arguments.chunk_size,
        )

        output_path = processor.process_video(
            platform_video_id=arguments.video_id,
            force=arguments.force,
        )

    print(f"\nSummary saved to: {output_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "\nSummarization stopped. "
            "The video was returned to PENDING."
        )
