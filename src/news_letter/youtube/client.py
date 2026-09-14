# src/news_letter/youtube_client.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from random import uniform
from time import sleep
from typing import Any

import yt_dlp
from sqlalchemy import select
from sqlalchemy.orm import Session
from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import WebshareProxyConfig

from .models import Channel, Video
from ..utils.enums import BackfillStatus, ProcessingStatus


class YouTubeRepository:
    def __init__(
        self,
        session: Session,
        transcript_directory: Path,
        proxy_username: str | None = None,
        proxy_password: str | None = None,
    ) -> None:
        self.session = session
        self.transcript_directory = transcript_directory
        self.transcript_directory.mkdir(parents=True, exist_ok=True)

        self.transcript_api = self._build_transcript_api(
            proxy_username=proxy_username,
            proxy_password=proxy_password,
        )

    @staticmethod
    def _build_transcript_api(
        proxy_username: str | None,
        proxy_password: str | None,
    ) -> YouTubeTranscriptApi:
        if proxy_username and proxy_password:
            return YouTubeTranscriptApi(
                proxy_config=WebshareProxyConfig(
                    proxy_username=proxy_username,
                    proxy_password=proxy_password,
                )
            )

        return YouTubeTranscriptApi()

    def add_channel(
        self,
        channel_handle: str,
        backfill_limit: int = 20,
    ) -> Channel:
        """
        Resolve a YouTube handle, create or update the channel, and discover
        its initial videos.
        """
        channel_info = self._extract_channel(
            channel_handle=channel_handle,
            video_limit=backfill_limit,
        )

        platform_channel_id = channel_info.get("channel_id")

        if not platform_channel_id:
            raise ValueError(
                f"Could not resolve channel ID for {channel_handle}"
            )

        channel = self._upsert_channel(
            platform_channel_id=platform_channel_id,
            name=(
                channel_info.get("channel")
                or channel_info.get("uploader")
                or channel_handle
            ),
        )

        self._upsert_video_entries(
            channel=channel,
            entries=channel_info.get("entries") or [],
        )

        self.session.commit()
        return channel

    def backfill_channel(
        self,
        channel: Channel,
        video_limit: int = 100,
    ) -> int:
        channel_id = channel.id

        channel.backfill_status = BackfillStatus.IN_PROGRESS
        channel.last_error = None
        self.session.commit()

        try:
            channel_info = self._extract_channel(
                channel_handle=channel.platform_channel_id,
                video_limit=video_limit,
            )

            inserted_count = self._upsert_video_entries(
                channel=channel,
                entries=channel_info.get("entries") or [],
            )

            channel.backfill_status = BackfillStatus.COMPLETED
            channel.last_checked_at = datetime.now(timezone.utc)

            self.session.commit()
            return inserted_count

        except KeyboardInterrupt:
            self.session.rollback()

            interrupted_channel = self.session.get(
                Channel,
                channel_id,
            )

            if interrupted_channel is not None:
                interrupted_channel.backfill_status = (
                    BackfillStatus.NOT_STARTED
                )
                self.session.commit()

            raise

        except Exception:
            self.session.rollback()

            failed_channel = self.session.get(
                Channel,
                channel_id,
            )

            if failed_channel is not None:
                failed_channel.backfill_status = (
                    BackfillStatus.FAILED
                )
                self.session.commit()

            raise

    def reset_interrupted_backfills(self) -> int:
        statement = select(Channel).where(
            Channel.backfill_status
            == BackfillStatus.IN_PROGRESS
        )

        interrupted_channels = list(
            self.session.scalars(statement)
        )

        for channel in interrupted_channels:
            channel.backfill_status = (
                BackfillStatus.NOT_STARTED
            )

        self.session.commit()

        return len(interrupted_channels)

    def reset_interrupted_transcripts(self) -> int:
        statement = select(Video).where(
            Video.transcript_status
            == ProcessingStatus.IN_PROGRESS
        )

        interrupted_videos = list(
            self.session.scalars(statement)
        )

        for video in interrupted_videos:
            video.transcript_status = (
                ProcessingStatus.PENDING
            )

        self.session.commit()

        return len(interrupted_videos)

    def check_for_new_videos(
        self,
        channel: Channel,
        video_limit: int = 10,
    ) -> int:
        """
        Check the latest channel entries and insert videos not already stored.
        """
        channel_info = self._extract_channel(
            channel_handle=channel.platform_channel_id,
            video_limit=video_limit,
        )

        inserted_count = self._upsert_video_entries(
            channel=channel,
            entries=channel_info.get("entries") or [],
        )

        channel.last_checked_at = datetime.now(timezone.utc)
        self.session.commit()

        return inserted_count

    def fetch_transcript(self, video: Video) -> Path | None:
        """
        Fetch and save one transcript.

        Returns the written file path on success, otherwise None.
        """
        video.transcript_status = ProcessingStatus.IN_PROGRESS
        video.last_error = None
        self.session.commit()

        sleep(uniform(2, 3))

        try:
            fetched_transcript = self.transcript_api.fetch(
                video.platform_video_id
            )

            transcript_text = "\n".join(
                snippet.text
                for snippet in fetched_transcript.snippets
            )

            transcript_file = self.raw_transcript_path(
                video.platform_video_id
            )

            transcript_file.write_text(
                transcript_text,
                encoding="utf-8",
            )

            video.transcript_status = ProcessingStatus.COMPLETED
            video.last_error = None
            self.session.commit()

            return transcript_file

        except (
            TranscriptsDisabled,
            NoTranscriptFound,
            CouldNotRetrieveTranscript,
        ) as exc:
            self._mark_transcript_failed(video, exc)
            return None

        except Exception as exc:
            self._mark_transcript_failed(video, exc)
            return None

    def fetch_pending_transcripts(
        self,
        limit: int | None = None,
    ) -> tuple[int, int]:
        """
        Fetch transcripts for videos currently marked PENDING.

        Returns:
            A tuple of (successful_count, failed_count).
        """
        statement = (
            select(Video)
            .where(
                Video.transcript_status
                == ProcessingStatus.PENDING
            )
            .order_by(Video.published_at.desc())
        )

        if limit is not None:
            statement = statement.limit(limit)

        videos = list(
            self.session.scalars(statement)
        )

        successful = 0
        failed = 0

        for video in videos:
            result = self.fetch_transcript(video)

            if result is None:
                failed += 1
            else:
                successful += 1

        return successful, failed

    def get_channels_requiring_backfill(self) -> list[Channel]:
        statement = (
            select(Channel)
            .where(
                Channel.backfill_status.in_(
                    [
                        BackfillStatus.NOT_STARTED,
                        BackfillStatus.FAILED,
                    ]
                )
            )
            .order_by(Channel.added_at)
        )

        return list(self.session.scalars(statement))

    def get_initialized_channels(self) -> list[Channel]:
        statement = (
            select(Channel)
            .where(
                Channel.backfill_status
                == BackfillStatus.COMPLETED
            )
            .order_by(Channel.name)
        )

        return list(self.session.scalars(statement))

    def raw_transcript_path(self, video_id: str) -> Path:
        return self.transcript_directory / f"{video_id}-raw.txt"

    def processed_transcript_path(self, video_id: str) -> Path:
        return self.transcript_directory / f"{video_id}-processed.txt"

    def _extract_channel(
        self,
        channel_handle: str,
        video_limit: int,
    ) -> dict[str, Any]:
        channel_url = self._build_channel_url(channel_handle)

        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "ignoreerrors": True,
            "playlistend": video_limit,
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            result = ydl.extract_info(
                channel_url,
                download=False,
            )

        if not isinstance(result, dict):
            raise ValueError(
                f"Unexpected yt-dlp response for {channel_url}"
            )

        return result

    @staticmethod
    def _build_channel_url(channel_identifier: str) -> str:
        if channel_identifier.startswith("http"):
            return channel_identifier.rstrip("/") + "/videos"

        if channel_identifier.startswith("UC"):
            return (
                "https://www.youtube.com/channel/"
                f"{channel_identifier}/videos"
            )

        handle = channel_identifier.lstrip("@")
        return f"https://www.youtube.com/@{handle}/videos"

    def _upsert_channel(
        self,
        platform_channel_id: str,
        name: str,
    ) -> Channel:
        statement = select(Channel).where(
            Channel.platform_channel_id == platform_channel_id
        )

        channel = self.session.scalar(statement)

        if channel is None:
            channel = Channel(
                platform_channel_id=platform_channel_id,
                name=name,
                backfill_status=BackfillStatus.NOT_STARTED,
            )
            self.session.add(channel)
            self.session.flush()
        else:
            channel.name = name

        return channel

    def _upsert_video_entries(
        self,
        channel: Channel,
        entries: list[dict[str, Any]],
    ) -> int:
        inserted_count = 0

        for entry in entries:
            if not entry:
                continue

            platform_video_id = entry.get("id")
            title = entry.get("title")

            if not platform_video_id or not title:
                continue

            existing_video = self.session.scalar(
                select(Video).where(
                    Video.platform_video_id
                    == platform_video_id
                )
            )

            if existing_video is not None:
                continue

            video = Video(
                channel_id=channel.id,
                platform_video_id=platform_video_id,
                title=title,
                published_at=self._parse_upload_date(
                    entry.get("upload_date")
                ),
                transcript_status=ProcessingStatus.PENDING,
                ai_processing_status=ProcessingStatus.PENDING,
            )

            self.session.add(video)
            inserted_count += 1

        self.session.flush()
        return inserted_count

    def _mark_transcript_failed(
        self,
        video: Video,
        error: Exception,
    ) -> None:
        video.transcript_status = ProcessingStatus.FAILED
        video.last_error = str(error)[:2_000]
        self.session.commit()

    def get_pending_transcripts(
        self,
        limit: int | None = None,
    ) -> list[Video]:
        statement = (
            select(Video)
            .where(
                Video.transcript_status
                == ProcessingStatus.PENDING
            )
            .order_by(
                Video.published_at.desc(),
                Video.id.desc(),
            )
        )

        if limit is not None:
            statement = statement.limit(limit)

        return list(self.session.scalars(statement))

    @staticmethod
    def _parse_upload_date(
        upload_date: str | None,
    ) -> datetime | None:
        if not upload_date:
            return None

        try:
            parsed = datetime.strptime(
                upload_date,
                "%Y%m%d",
            )
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
