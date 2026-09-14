from __future__ import annotations

import os
import sys

from news_letter.youtube.client import YouTubeRepository
from news_letter.youtube.db import create_session, init_db
from news_letter.utils.constants import TRANSCRIPT_DIRECTORY


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: uv run python "
            "-m news_letter.youtube.services.add_creator "
            "<youtube-handle-or-url>"
        )

    creator_identifier = sys.argv[1]

    init_db()

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

        channel = repository.add_channel(
            channel_handle=creator_identifier,
            backfill_limit=1,
        )

        print(
            f"Added creator: {channel.name}\n"
            f"Channel ID: {channel.platform_channel_id}\n"
            f"Backfill status: {channel.backfill_status.value}"
        )


if __name__ == "__main__":
    main()
