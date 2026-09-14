from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import markdown

from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from news_letter.utils.constants import (
    PROJECT_ROOT,
    PROCESSED_TRANSCRIPT_DIRECTORY,
)
from news_letter.utils.enums import ProcessingStatus
from news_letter.youtube.db import create_session, init_db
from news_letter.youtube.models import Video


NEW_YORK = ZoneInfo("America/New_York")

DEFAULT_LOOKBACK_DAYS = 14

NEWSLETTER_DIRECTORY = PROJECT_ROOT / "data" / "newsletters"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a newsletter from processed YouTube research briefs."
        )
    )

    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help=(
            "Number of days of processed videos to include. "
            f"Default: {DEFAULT_LOOKBACK_DAYS}."
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Optional maximum number of videos to include. "
            "Newest videos are prioritized."
        ),
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=(
            "Override OPENAI_NEWSLETTER_MODEL from .env."
        ),
    )

    return parser.parse_args()


def get_recent_videos(
    session,
    *,
    cutoff_utc: datetime,
    limit: int | None,
) -> list[Video]:
    statement = (
        select(Video)
        .options(selectinload(Video.channel))
        .where(
            Video.transcript_status
            == ProcessingStatus.COMPLETED,
            Video.ai_processing_status
            == ProcessingStatus.COMPLETED,
            Video.published_at.is_not(None),
            Video.published_at >= cutoff_utc,
        )
        .order_by(
            Video.published_at.desc(),
            Video.id.desc(),
        )
    )

    if limit is not None:
        statement = statement.limit(limit)

    return list(session.scalars(statement))


def processed_brief_path(video: Video) -> Path:
    return (
        PROCESSED_TRANSCRIPT_DIRECTORY
        / f"{video.platform_video_id}-processed.md"
    )


def normalize_datetime(value: datetime) -> datetime:
    """
    Return an aware UTC datetime.

    SQLite may return a naive datetime even when the application
    originally stored a timezone-aware value.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def recency_bucket(
    published_at: datetime,
    now_utc: datetime,
) -> str:
    age = now_utc - normalize_datetime(published_at)

    if age <= timedelta(days=3):
        return "NOW — LAST 72 HOURS"

    if age <= timedelta(days=7):
        return "RECENT — LAST 4 TO 7 DAYS"

    return "CONTEXT — DAYS 8 TO 14"


def recency_weight(
    published_at: datetime,
    now_utc: datetime,
) -> int:
    """
    Editorial priority score from 1-10.

    This is intentionally nonlinear so very recent material gets
    substantially more editorial weight.
    """
    age_days = max(
        0.0,
        (
            now_utc - normalize_datetime(published_at)
        ).total_seconds()
        / 86_400,
    )

    if age_days <= 1:
        return 10

    if age_days <= 3:
        return 9

    if age_days <= 5:
        return 7

    if age_days <= 7:
        return 6

    if age_days <= 10:
        return 4

    return 3


def build_source_document(
    videos: list[Video],
    now_utc: datetime,
) -> tuple[str, int]:
    documents: list[str] = []
    included = 0

    # Feed sources oldest -> newest.
    #
    # This makes the chronology visible to the model while the explicit
    # recency weight tells it how much editorial importance to assign.
    videos = sorted(
        videos,
        key=lambda video: normalize_datetime(video.published_at),
    )

    for index, video in enumerate(videos, start=1):
        path = processed_brief_path(video)

        if not path.exists():
            print(
                "Skipping missing processed brief: "
                f"{path}"
            )
            continue

        content = path.read_text(
            encoding="utf-8"
        ).strip()

        if not content:
            print(
                "Skipping empty processed brief: "
                f"{path}"
            )
            continue

        published_utc = normalize_datetime(
            video.published_at
        )

        published_et = published_utc.astimezone(
            NEW_YORK
        )

        creator = (
            video.channel.name
            if video.channel is not None
            else "Unknown"
        )

        bucket = recency_bucket(
            published_utc,
            now_utc,
        )

        weight = recency_weight(
            published_utc,
            now_utc,
        )

        documents.append(
            f"""
============================================================
SOURCE {index}
============================================================

Creator: {creator}
Video title: {video.title}
YouTube video ID: {video.platform_video_id}
Published: {published_et.isoformat()}
Temporal bucket: {bucket}
Editorial recency weight: {weight}/10

BEGIN PROCESSED RESEARCH BRIEF

{content}

END PROCESSED RESEARCH BRIEF
""".strip()
        )

        included += 1

    return "\n\n".join(documents), included


def render_html(
    *,
    markdown_content: str,
    newsletter_date: datetime,
) -> str:
    body = markdown.markdown(
        markdown_content,
        extensions=[
            "tables",
            "fenced_code",
        ],
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>
        Daily Intelligence Brief —
        {newsletter_date.strftime("%B %d, %Y")}
    </title>

    <style>
        :root {{
            --background: #f5f6f8;
            --surface: #ffffff;
            --text: #18202a;
            --muted: #667085;
            --border: #e4e7ec;
            --heading: #101828;
            --accent: #183b56;
        }}

        * {{
            box-sizing: border-box;
        }}

        body {{
            margin: 0;
            background: var(--background);
            color: var(--text);
            font-family:
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                Roboto,
                Helvetica,
                Arial,
                sans-serif;
            line-height: 1.65;
        }}

        main {{
            max-width: 920px;
            margin: 48px auto;
            background: var(--surface);
            padding: 52px 64px;
            border: 1px solid var(--border);
            border-radius: 12px;
        }}

        h1 {{
            margin-top: 0;
            color: var(--heading);
            font-size: 2.4rem;
            line-height: 1.1;
            letter-spacing: -0.03em;
        }}

        h2 {{
            margin-top: 48px;
            padding-top: 18px;
            border-top: 1px solid var(--border);
            color: var(--accent);
            font-size: 1.55rem;
        }}

        h3 {{
            margin-top: 32px;
            color: var(--heading);
            font-size: 1.2rem;
        }}

        p {{
            margin: 0 0 18px;
        }}

        ul,
        ol {{
            padding-left: 24px;
        }}

        li {{
            margin-bottom: 8px;
        }}

        strong {{
            color: var(--heading);
        }}

        table {{
            width: 100%;
            margin: 24px 0 32px;
            border-collapse: collapse;
            font-size: 0.95rem;
        }}

        th,
        td {{
            padding: 10px 12px;
            border-bottom: 1px solid var(--border);
            text-align: left;
            vertical-align: top;
        }}

        th {{
            background: #f8fafc;
            color: var(--heading);
            font-weight: 600;
        }}

        @media (max-width: 720px) {{
            body {{
                background: white;
            }}

            main {{
                margin: 0;
                padding: 28px 20px;
                border: none;
                border-radius: 0;
            }}

            h1 {{
                font-size: 1.9rem;
            }}

            table {{
                display: block;
                overflow-x: auto;
            }}
        }}
    </style>
</head>

<body>
    <main>
        {body}
    </main>
</body>
</html>
"""


def generate_research_dossier(
    *,
    openai_client: OpenAI,
    model: str,
    source_document: str,
    source_count: int,
    now_et: datetime,
    lookback_days: int,
) -> str:
    period_start = (
        now_et - timedelta(days=lookback_days)
    )

    print("\nMarket researcher is analyzing source material...")

    response = openai_client.responses.create(
        model=model,
        instructions="""
You are the market research lead for a financial intelligence
newsletter.

Your job is exhaustive research synthesis, NOT newsletter writing.

You are given processed research briefs from multiple financial,
economic, geopolitical, and market-focused sources.

Build an editorial research dossier that another senior editor
will use to write the final newsletter.

Your priorities, in order, are:

1. Accuracy to the supplied source material.
2. Capture of material facts, numbers, dates and developments.
3. Understanding chronology and how stories evolved.
4. Determining what matters most NOW.
5. Identifying relationships between stories.
6. Preserving disagreements and uncertainty.
7. Identifying forward-looking catalysts and scenarios.

Do not optimize for elegant prose.
Do not try to sound like a newsletter.
Do not omit an important fact merely because it complicates
the narrative.

TEMPORAL ANALYSIS:

Reconstruct the period as:

EARLIER CONTEXT
- Where conditions stood near the beginning.

TRANSITION
- What materially changed.

CURRENT STATE
- What the newest evidence suggests now.

FORWARD STATE
- Predictions, catalysts, risks and unresolved questions.

Recent information should generally have more weight when it
updates earlier information.

Older information remains important when it explains causality
or establishes what changed.

CRITICAL RULES:

- Do not add outside knowledge.
- Do not independently verify claims.
- Preserve attribution for distinctive claims.
- Separate reported observations from creator interpretation.
- Preserve conflicting evidence.
- Do not manufacture consensus.
- Preserve important numerical values and thresholds.
- Explicitly identify when newer information contradicts or
  supersedes an earlier thesis.
""".strip(),
        input=f"""
Prepare the research dossier for today's newsletter.

CURRENT TIME:
{now_et.strftime("%A, %B %d, %Y at %I:%M %p %Z")}

ANALYSIS WINDOW:
{period_start.strftime("%B %d, %Y")}
through
{now_et.strftime("%B %d, %Y")}

SOURCE COUNT:
{source_count}

Produce the dossier using this structure:

# Research Dossier

## Top Developments

Rank the 5-10 most important developments currently affecting
the market or economic outlook.

For each include:

- Development
- Current state
- What changed during the period
- Why it matters
- Recency
- Important supporting data
- Relevant sources
- Confidence / uncertainty

## Timeline

Reconstruct the most important developments chronologically.

Focus on changes in state rather than listing every video.

## Current Market State

Describe what the newest source material indicates about:

- inflation
- monetary policy
- rates
- Treasuries
- equities
- credit
- commodities
- economic growth
- employment
- geopolitical risk

Only include categories supported by the sources.

## Key Data and Numbers

Capture important:

- prices
- rates
- percentages
- probabilities
- inventories
- spreads
- market levels
- economic releases
- policy amounts
- thresholds

Include source attribution and context.

## Cross-Market Relationships

Identify meaningful causal or claimed causal connections such as:

energy -> inflation
inflation -> Fed
Fed -> Treasury yields
Treasury yields -> housing/equities/credit
shipping -> energy
employment -> Fed expectations

Only include relationships supported by supplied material.

## Consensus

Identify areas where independent sources materially agree.

## Disagreements

Identify meaningful disagreements.

For each:

- Side A
- Side B
- evidence supporting each
- newest evidence
- whether either view has strengthened

## Narrative Changes

Identify earlier theses that were:

- strengthened
- weakened
- contradicted
- superseded
- still unresolved

## Risks

List the most important current risks.

Rank them HIGH / MEDIUM / LOW based on relevance within the
source material, not independent probability.

## Forward Outlook

### Base Case

### Upside Scenarios

### Downside Scenarios

## Catalysts

Capture specific events, releases, thresholds, conditions and
market signals worth monitoring.

## Source Ledger

List the sources that materially contributed to the dossier.

SOURCE MATERIAL:

{source_document}
""".strip(),
    )

    dossier = response.output_text.strip()

    if not dossier:
        raise RuntimeError(
            "Research agent returned an empty dossier."
        )

    return dossier


def generate_newsletter(
    *,
    openai_client: OpenAI,
    model: str,
    research_dossier: str,
    now_et: datetime,
    lookback_days: int,
) -> str:
    print("\nSenior editor is writing newsletter...")

    response = openai_client.responses.create(
        model=model,
        instructions="""
You are the senior editor of a premium financial intelligence
newsletter.

A market research analyst has already completed the underlying
research.

Your job is EDITORIAL.

Turn the research dossier into a newsletter that works at two
levels:

LEVEL 1 — THE SKIM
A busy reader should understand the most important developments
and what to watch in approximately 60-90 seconds.

LEVEL 2 — THE DEEP DIVE
A reader who continues should receive the analysis, evidence,
causal relationships, disagreements and forward outlook.

The newsletter should feel like one coherent publication,
not an aggregation of summaries.

EDITORIAL PRINCIPLES:

- Lead with what matters now.
- Make significance obvious.
- Explain why a development matters.
- Use chronology only where it improves understanding.
- Prefer short paragraphs.
- Use bullets where they improve scanning.
- Avoid walls of text.
- Avoid repeating the same argument in multiple sections.
- Do not organize by creator.
- Do not mention every source merely because it exists.
- Preserve meaningful uncertainty.
- Preserve attribution for distinctive claims.
- Never turn source assertions into independently verified facts.
- Do not introduce facts not contained in the dossier.

HEADLINE WRITING:

Section and story headings should communicate information.

Prefer:

"Diesel, Not Crude, Is Becoming the Inflation Risk"

over:

"Energy Markets"

Prefer:

"The Fed Is Being Pulled in Two Directions"

over:

"Monetary Policy"

Readers should learn something simply by scanning the headings.

INFORMATION HIERARCHY:

For major stories use:

WHAT HAPPENED
WHY IT MATTERS
WHAT TO WATCH

But write naturally. Do not mechanically repeat these labels
for every story unless useful.
""".strip(),
        input=f"""
Write today's Daily Intelligence Brief.

DATE:
{now_et.strftime("%B %d, %Y")}

RESEARCH WINDOW:
Previous {lookback_days} days.

Use this structure:

# Daily Intelligence Brief

*{now_et.strftime("%B %d, %Y")}*

## The 60-Second Read

Give 5-7 bullets.

Each bullet should communicate:

- what happened or currently matters
- why it matters

Keep each bullet to roughly 1-3 sentences.

A reader who stops here should still understand today's market
setup.

## What Matters Most

Identify the 3-5 highest-priority stories.

Give each story a descriptive, information-rich heading.

For each story explain concisely:

- what changed
- current state
- why markets/economy care
- what could change the thesis

This is the bridge between the skim and deep dive.

## Market Dashboard

Provide a compact Markdown table of the most useful numerical
signals contained in the research dossier.

Columns:

| Indicator | Current / Cited Level | Why It Matters |

Only include supported numbers.

Prefer roughly 5-10 signals.

## The Big Picture

Write 3-6 concise paragraphs connecting the major stories.

Explain the dominant feedback loops and how the current
environment developed.

This should be the main narrative of the newsletter.

## Deep Dive

Choose the major analytical themes supported by the research.

Use descriptive ### headings.

For each theme provide substantive analysis including:

- context
- newest developments
- relevant numbers
- causal relationships
- disagreements
- uncertainty

The deep dive should contain the valuable research without
repeating the opening sections word-for-word.

## Consensus vs. Debate

### Where the Sources Agree

Use concise bullets.

### Where the Debate Is Still Open

Explain the most consequential disagreements and what evidence
would resolve them.

## What Comes Next

### Base Case

Explain the most supported near-term scenario.

### Upside Case

Explain major positive scenarios.

### Downside Case

Explain major negative scenarios.

Do not assign numerical probabilities unless present in the
research.

## Catalysts to Watch

Use a compact table:

| Catalyst | Why It Matters | What Would Change |

Prioritize upcoming and high-impact items.

## Bottom Line

Write 2-4 strong paragraphs.

Answer:

- Where were we?
- What changed?
- Where are we now?
- What should readers watch next?

Do not merely summarize previous sections.
Provide the editorial synthesis.

## Sources

List only materially used sources.

RESEARCH DOSSIER:

{research_dossier}
""".strip(),
    )

    newsletter = response.output_text.strip()

    if not newsletter:
        raise RuntimeError(
            "Editor returned an empty newsletter."
        )

    return newsletter


def main() -> None:
    arguments = parse_arguments()

    if arguments.days <= 0:
        raise SystemExit(
            "--days must be greater than zero."
        )

    if (
        arguments.limit is not None
        and arguments.limit <= 0
    ):
        raise SystemExit(
            "--limit must be greater than zero."
        )

    load_dotenv(PROJECT_ROOT / ".env")

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise SystemExit(
            "OPENAI_API_KEY is missing from the .env file."
        )

    research_model = os.getenv(
        "OPENAI_RESEARCH_MODEL",
        "gpt-5.6-sol",
    )

    editor_model = os.getenv(
        "OPENAI_EDITOR_MODEL",
        "gpt-5.6-sol",
    )

    now_et = datetime.now(NEW_YORK)
    now_utc = now_et.astimezone(timezone.utc)

    cutoff_utc = (
        now_utc - timedelta(days=arguments.days)
    )

    print("\nNewsletter generation")

    print(
        "Models: "
        f"research={research_model}, "
        f"editor={editor_model}"
    )

    print(
        "Period: "
        f"{cutoff_utc.astimezone(NEW_YORK).strftime('%Y-%m-%d')} "
        "through "
        f"{now_et.strftime('%Y-%m-%d')}"
    )

    init_db()

    with create_session() as session:
        videos = get_recent_videos(
            session=session,
            cutoff_utc=cutoff_utc,
            limit=arguments.limit,
        )

        if not videos:
            raise SystemExit(
                "No completed processed videos were found "
                "inside the requested period."
            )

        print(
            f"Found {len(videos)} eligible video(s)."
        )

        source_document, included_count = (
            build_source_document(
                videos=videos,
                now_utc=now_utc,
            )
        )

        if included_count == 0:
            raise SystemExit(
                "No processed transcript files could be loaded."
            )

        print(
            f"Loaded {included_count} processed research brief(s)."
        )

        openai_client = OpenAI(
            api_key=api_key,
            max_retries=3,
            timeout=600.0,
        )

        # ---------------------------------------------
        # Agent 1: Market Researcher
        # ---------------------------------------------

        research_dossier = generate_research_dossier(
            openai_client=openai_client,
            model=research_model,
            source_document=source_document,
            source_count=included_count,
            now_et=now_et,
            lookback_days=arguments.days,
        )

        # ---------------------------------------------
        # Agent 2: Newsletter Editor
        # ---------------------------------------------

        newsletter = generate_newsletter(
            openai_client=openai_client,
            model=editor_model,
            research_dossier=research_dossier,
            now_et=now_et,
            lookback_days=arguments.days,
        )

    # -------------------------------------------------
    # Save outputs
    # -------------------------------------------------

    NEWSLETTER_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    date_prefix = now_et.strftime("%Y-%m-%d")

    research_path = (
        NEWSLETTER_DIRECTORY
        / f"{date_prefix}-research.md"
    )

    markdown_path = (
        NEWSLETTER_DIRECTORY
        / f"{date_prefix}-newsletter.md"
    )

    html_path = (
        NEWSLETTER_DIRECTORY
        / f"{date_prefix}-newsletter.html"
    )

    research_path.write_text(
        research_dossier.strip() + "\n",
        encoding="utf-8",
    )

    markdown_path.write_text(
        newsletter.strip() + "\n",
        encoding="utf-8",
    )

    html_content = render_html(
        markdown_content=newsletter,
        newsletter_date=now_et,
    )

    html_path.write_text(
        html_content,
        encoding="utf-8",
    )

    print("\nNewsletter generation complete:")
    print(f"Research: {research_path}")
    print(f"Markdown: {markdown_path}")
    print(f"HTML:     {html_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(
            "\nNewsletter generation stopped."
        )
