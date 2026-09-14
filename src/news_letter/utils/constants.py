from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DATA_DIRECTORY = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIRECTORY / "news_letter.db"

TRANSCRIPT_DIRECTORY = DATA_DIRECTORY / "transcripts"
PROCESSED_TRANSCRIPT_DIRECTORY = DATA_DIRECTORY / "processed_transcripts"
