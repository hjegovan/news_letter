# uv run python -m news_letter.youtube.services.reset_blocked_transcripts --dry-run
from __future__ import annotations
import argparse
from sqlalchemy import select
from news_letter.utils.enums import ProcessingStatus
from news_letter.youtube.db import create_session, init_db
from news_letter.youtube.models import Video

IP_BLOCK_ERROR_MARKERS = (
    "YouTube is blocking requests from your IP",
    "RequestBlocked",
    "IpBlocked",
)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reset transcript jobs that failed because YouTube "
            "blocked the request IP."
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show matching videos without updating the database."
        ),
    )

    return parser.parse_args()


def is_ip_block_error(error: str | None) -> bool:
    if not error:
        return False

    return any(
        marker.lower() in error.lower()
        for marker in IP_BLOCK_ERROR_MARKERS
    )


def main() -> None:
    arguments = parse_arguments()

    init_db()

    with create_session() as session:
        statement = (
            select(Video)
            .where(
                Video.transcript_status
                == ProcessingStatus.FAILED
            )
            .order_by(Video.ingested_at)
        )

        failed_videos = list(
            session.scalars(statement)
        )

        matching_videos = [
            video
            for video in failed_videos
            if is_ip_block_error(video.last_error)
        ]

        if not matching_videos:
            print(
                "No IP-blocked transcript jobs were found."
            )
            return

        print(
            f"Found {len(matching_videos)} "
            "IP-blocked transcript job(s)."
        )

        for video in matching_videos:
            print(
                f"- {video.platform_video_id}: "
                f"{video.title}"
            )

            if arguments.dry_run:
                continue

            video.transcript_status = (
                ProcessingStatus.PENDING
            )
            video.last_error = None

        if arguments.dry_run:
            print(
                "\nDry run complete. "
                "No database rows were changed."
            )
            return

        session.commit()

        print(
            "\nReset complete: "
            f"{len(matching_videos)} job(s) changed "
            "from FAILED to PENDING."
        )


if __name__ == "__main__":
    main()
