# src/news_letter/ingestion.py
from __future__ import annotations
from sqlalchemy.orm import Session
from tqdm import tqdm
from .client import YouTubeRepository


class TranscriptIngestionService:
    def __init__(
        self,
        session: Session,
        youtube_repository: YouTubeRepository,
    ) -> None:
        self.session = session
        self.youtube_repository = youtube_repository

    def run(
        self,
        backfill_limit: int = 100,
        latest_video_limit: int = 10,
        transcript_limit: int | None = None,
    ) -> None:
        self._recover_interrupted_jobs()

        self._backfill_channels(
            video_limit=backfill_limit,
        )

        self._check_initialized_channels(
            video_limit=latest_video_limit,
        )

        successful, failed = self._fetch_transcripts(
            limit=transcript_limit,
        )

        print(
            "\nTranscript session complete: "
            f"{successful} successful, "
            f"{failed} failed."
        )

    def _recover_interrupted_jobs(self) -> None:
        backfill_reset_count = (
            self.youtube_repository
            .reset_interrupted_backfills()
        )

        transcript_reset_count = (
            self.youtube_repository
            .reset_interrupted_transcripts()
        )

        if backfill_reset_count:
            print(
                f"Reset {backfill_reset_count} "
                "interrupted backfill job(s)."
            )

        if transcript_reset_count:
            print(
                f"Reset {transcript_reset_count} "
                "interrupted transcript job(s)."
            )

    def _fetch_transcripts(
        self,
        limit: int | None,
    ) -> tuple[int, int]:
        videos = (
            self.youtube_repository
            .get_pending_transcripts(limit=limit)
        )

        total = len(videos)

        if total == 0:
            print("No pending transcripts to fetch.")
            return 0, 0

        print(
            f"\nFetching {total} transcript(s) "
            "in this session."
        )

        successful = 0
        failed = 0

        progress_bar = tqdm(
            videos,
            total=total,
            desc="Transcripts",
            unit="video",
            dynamic_ncols=True,
        )

        for video in progress_bar:
            progress_bar.set_postfix(
                success=successful,
                failed=failed,
                current=video.platform_video_id,
            )

            transcript_path = (
                self.youtube_repository
                .fetch_transcript(video)
            )

            if transcript_path is None:
                failed += 1

                tqdm.write(
                    "Failed: "
                    f"{video.platform_video_id} — "
                    f"{video.title}"
                )

                if video.last_error:
                    tqdm.write(
                        f"Reason: {video.last_error[:300]}"
                    )
            else:
                successful += 1

            progress_bar.set_postfix(
                success=successful,
                failed=failed,
            )

        return successful, failed

    def _backfill_channels(
        self,
        video_limit: int,
    ) -> None:
        channels = (
            self.youtube_repository
            .get_channels_requiring_backfill()
        )

        if not channels:
            print("No channels require backfilling.")
            return

        for channel in channels:
            print(f"Backfilling channel: {channel.name}")

            try:
                inserted_count = (
                    self.youtube_repository
                    .backfill_channel(
                        channel=channel,
                        video_limit=video_limit,
                    )
                )

                print(
                    f"Discovered {inserted_count} new videos "
                    f"for {channel.name}."
                )

            except KeyboardInterrupt:
                raise

            except Exception as exc:
                print(
                    f"Backfill failed for {channel.name}: "
                    f"{exc}"
                )

    def _check_initialized_channels(
        self,
        video_limit: int,
    ) -> None:
        channels = (
            self.youtube_repository
            .get_initialized_channels()
        )

        if not channels:
            print("No initialized channels to check.")
            return

        for channel in channels:
            print(
                "Checking channel for new videos: "
                f"{channel.name}"
            )

            try:
                inserted_count = (
                    self.youtube_repository
                    .check_for_new_videos(
                        channel=channel,
                        video_limit=video_limit,
                    )
                )

                print(
                    f"Discovered {inserted_count} new videos "
                    f"for {channel.name}."
                )

            except KeyboardInterrupt:
                raise

            except Exception as exc:
                print(
                    f"Channel check failed for "
                    f"{channel.name}: {exc}"
                )
