# uv run python -m news_letter.youtube.services.add_creators
from __future__ import annotations

import os

from news_letter.utils.constants import TRANSCRIPT_DIRECTORY
from news_letter.youtube.client import YouTubeRepository
from news_letter.youtube.db import create_session, init_db


CREATORS = [
    "@eurodollaruniversity",
    "@Monetary-Matters",
    "@fxevolutionvideo",
    "@StockedUp",
    "@PBoyle",
    "@CasuallyFinance",
    "@AndreiJikh",
    "@clearvaluetax9382",
    "@HeresyFinancial",
]


def main() -> None:
    init_db()

    successful = 0
    failed = 0

    with create_session() as session:
        repository = YouTubeRepository(
            session=session,
            transcript_directory=TRANSCRIPT_DIRECTORY,
            proxy_username=os.getenv("WEBSHARE_PROXY_USERNAME"),
            proxy_password=os.getenv("WEBSHARE_PROXY_PASSWORD"),
        )

        for creator_handle in CREATORS:
            print(f"Adding creator: {creator_handle}")

            try:
                channel = repository.add_channel(
                    channel_handle=creator_handle,
                    backfill_limit=1,
                )

                print(
                    f"Added: {channel.name} "
                    f"({channel.platform_channel_id})\n"
                )
                successful += 1

            except Exception as exc:
                session.rollback()

                print(
                    f"Failed to add {creator_handle}: {exc}"
                )
                failed += 1

    print(
        "\nCreator import complete: "
        f"{successful} successful, {failed} failed."
    )


if __name__ == "__main__":
    main()
