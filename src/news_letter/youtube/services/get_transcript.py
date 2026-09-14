# uv run python -m news_letter.youtube.services.get_transcript w4UXf9lI_SE
from __future__ import annotations

import argparse
import os

from sqlalchemy import select

from news_letter.utils.constants import TRANSCRIPT_DIRECTORY
from news_letter.youtube.client import YouTubeRepository
from news_letter.youtube.db import create_session, init_db
from news_letter.youtube.models import Video
from dotenv import load_dotenv
from news_letter.utils.constants import PROJECT_ROOT
load_dotenv(PROJECT_ROOT / ".env")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch the transcript for one video in the database."
    )

    parser.add_argument(
        "video_id",
        help="YouTube video ID stored in the videos table.",
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    init_db()

    with create_session() as session:
        video = session.scalar(
            select(Video).where(
                Video.platform_video_id == arguments.video_id
            )
        )

        if video is None:
            raise SystemExit(
                f"No video found with ID: {arguments.video_id}"
            )

        repository = YouTubeRepository(
            session=session,
            transcript_directory=TRANSCRIPT_DIRECTORY,
            proxy_username=os.getenv("WEBSHARE_PROXY_USERNAME"),
            proxy_password=os.getenv("WEBSHARE_PROXY_PASSWORD"),
        )

        print(f"Fetching transcript: {video.title}")
        print(f"Video ID: {video.platform_video_id}")

        transcript_path = repository.fetch_transcript(video)

        if transcript_path is None:
            raise SystemExit(
                f"Transcript fetch failed: {video.last_error}"
            )

        print(f"Transcript saved: {transcript_path}")


if __name__ == "__main__":
    main()
