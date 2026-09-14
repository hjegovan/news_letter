# uv run python -m news_letter.youtube.services.remove_creator UCGy7SkBjcIAgTiwkXEtPnYg
import sys

from sqlalchemy import select

from news_letter.youtube.models import Channel
from news_letter.youtube.db import create_session


def delete_channel(platform_channel_id: str) -> bool:
    with create_session() as session:
        channel = session.scalar(
            select(Channel).where(
                Channel.platform_channel_id == platform_channel_id
            )
        )

        if channel is None:
            print(f"Channel not found: {platform_channel_id}")
            return False

        print(
            f"Deleting channel: {channel.name} "
            f"({channel.platform_channel_id})"
        )

        session.delete(channel)
        session.commit()

        print("Channel deleted.")
        return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "Usage: uv run python -m "
            "news_letter.youtube.services.remove_creator "
            "<platform_channel_id>"
        )
        sys.exit(1)

    platform_channel_id = sys.argv[1]
    delete_channel(platform_channel_id)
