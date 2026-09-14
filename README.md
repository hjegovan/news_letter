# News-Letter

News-Letter is a Python research pipeline that turns long-form YouTube content into a structured financial and macroeconomic intelligence newsletter.

The system discovers videos from selected YouTube channels, downloads transcripts, processes each transcript with OpenAI models, builds a multi-source research dossier, and uses a separate editorial pass to produce a readable daily intelligence brief.

The final newsletter is generated as both Markdown and HTML.

## What It Does

The pipeline is designed around three layers:

1. **Source ingestion**

   * Track selected YouTube channels.
   * Discover new videos.
   * Backfill historical videos.
   * Download available transcripts.
   * Skip or tolerate unavailable and members-only videos.

2. **Per-video research**

   * Break long transcripts into manageable chunks.
   * Extract claims, data, predictions, risks, recommendations, and entities.
   * Consolidate those chunk analyses into a structured research brief for each video.

3. **Newsletter synthesis**

   * Look back across a configurable time window, currently 14 days by default.
   * Give more editorial weight to recent developments.
   * Use a dedicated market-research agent to construct a research dossier.
   * Pass that dossier to a separate editorial agent.
   * Produce a newsletter designed for both quick scanning and deeper analysis.

## Architecture

```text
YouTube Channels
       │
       ▼
Video Discovery
       │
       ▼
Transcript Download
       │
       ▼
Raw Transcript
       │
       ▼
Transcript Processor
  ├── Chunk analysis
  └── Per-video consolidation
       │
       ▼
Processed Research Briefs
       │
       ▼
Market Research Agent
       │
       ▼
Research Dossier
       │
       ▼
Newsletter Editor
       │
       ├── Markdown
       └── HTML
```

The research and editorial stages are intentionally separated.

The **research agent** focuses on completeness, chronology, data, disagreement, causal relationships, and forward-looking risks.

The **editor agent** focuses on information hierarchy, readability, flow, headlines, and making the newsletter useful to both readers who want a 60-second overview and readers who want the full analysis.

## Project Structure

```text
news_letter/
├── data/
│   ├── newsletters/
│   │   ├── YYYY-MM-DD-research.md
│   │   ├── YYYY-MM-DD-newsletter.md
│   │   └── YYYY-MM-DD-newsletter.html
│   │
│   └── transcripts/
│
├── src/
│   └── news_letter/
│       ├── main.py
│       ├── newsletter.py
│       │
│       ├── processing/
│       │   ├── transcript_processor.py
│       │   └── batch_process.py
│       │
│       ├── youtube/
│       │   ├── client.py
│       │   ├── db.py
│       │   ├── ingestion.py
│       │   ├── models.py
│       │   └── services/
│       │
│       └── utils/
│           ├── constants.py
│           └── enums.py
│
├── .env
├── pyproject.toml
├── uv.lock
└── README.md
```

The exact structure may evolve as additional market-data sources are introduced.

## Technology

* Python
* SQLAlchemy
* SQLite
* yt-dlp
* youtube-transcript-api
* OpenAI Responses API
* Webshare rotating proxies
* python-dotenv
* tqdm
* Markdown
* uv

## Installation

Clone the repository:

```bash
git clone <your-repository-url>
cd news_letter
```

Install the project dependencies:

```bash
uv sync
```

If Markdown rendering has not yet been added:

```bash
uv add markdown
```

## Configuration

Create a `.env` file in the project root.

```env
OPENAI_API_KEY=your_openai_api_key

OPENAI_CHUNK_MODEL=gpt-5.6-luna
OPENAI_CONSOLIDATION_MODEL=gpt-5.6-luna

OPENAI_RESEARCH_MODEL=gpt-5.6-sol
OPENAI_EDITOR_MODEL=gpt-5.6-sol

WEBSHARE_PROXY_USERNAME=your_webshare_username
WEBSHARE_PROXY_PASSWORD=your_webshare_password
```
for Webshare proxy please follow the advise provided in the [youtube-transcript-api repo](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception)

Do not commit `.env` to GitHub.

Your `.gitignore` should include at minimum:

```gitignore
.env
.venv/
__pycache__/
*.pyc
.DS_Store
```

Depending on whether you want generated research artifacts stored in Git, you may also want:

```gitignore
data/transcripts/
data/newsletters/
```

## Running the Main Ingestion Pipeline

The main pipeline discovers videos, backfills channels, checks existing channels for new content, and downloads transcripts.

```bash
uv run python -m news_letter.main
```

The current configuration can control values such as:

```python
ingestion_service.run(
    backfill_limit=15,
    latest_video_limit=10,
    transcript_limit=200,
)
```

### Backfill behavior

Channel backfills use flat playlist extraction so inaccessible members-only videos do not prevent public videos from being discovered.

The goal is:

```text
Channel
├── Public video        -> ingest
├── Public video        -> ingest
├── Members-only video  -> skip/fail individually
├── Public video        -> ingest
└── Public video        -> ingest
```

A single inaccessible video should not invalidate an entire channel.

## Processing Transcripts

Downloaded transcripts can be processed in batches:

```bash
uv run python -m news_letter.processing.batch_process 50
```

This processes up to 50 transcripts.

Additional options include:

```bash
uv run python -m news_letter.processing.batch_process 50 --include-failed
```

Retry previously failed AI processing jobs.

```bash
uv run python -m news_letter.processing.batch_process 50 --oldest-first
```

Process older videos first.

```bash
uv run python -m news_letter.processing.batch_process 50 --stop-on-error
```

Stop when the first transcript-processing error occurs.

### Transcript processing strategy

Long transcripts are split into chunks.

Each chunk is analyzed for:

* Main arguments and claims
* Important numbers and dates
* Economic and financial relationships
* Predictions
* Risks
* Recommendations
* Companies, institutions, assets, and indicators
* Caveats and uncertainty
* Topics relevant to other videos

The chunk analyses are then consolidated into a single per-video research brief.

The inexpensive model handles the high-volume transcript workload:

```env
OPENAI_CHUNK_MODEL=gpt-5.6-luna
OPENAI_CONSOLIDATION_MODEL=gpt-5.6-luna
```

## Generating the Newsletter

Generate the current newsletter with:

```bash
uv run python -m news_letter.newsletter
```

The default lookback period is 14 days.

To change it:

```bash
uv run python -m news_letter.newsletter --days 7
```

You can also restrict how many recent videos are considered:

```bash
uv run python -m news_letter.newsletter --days 14 --limit 100
```

## Newsletter Research Process

The newsletter pipeline uses two distinct AI roles.

### 1. Market Research Agent

The research agent consumes all processed video briefs within the requested period.

Its responsibility is to capture:

* Major developments
* Chronology
* Current market state
* Important prices and economic data
* Cross-market relationships
* Areas of consensus
* Meaningful disagreements
* Narrative changes
* Risks
* Forward scenarios
* Upcoming catalysts
* Source attribution

It is optimized for completeness rather than polished writing.

### 2. Newsletter Editor

The editor receives the research dossier instead of the original transcripts.

Its job is to turn the research into a reader-first publication.

The newsletter is organized around two levels of consumption.

### Quick read

A reader should be able to understand the most important developments in roughly 60–90 seconds.

Sections include:

```text
The 60-Second Read
What Matters Most
Market Dashboard
```

### Deep dive

Readers who want more detail can continue into:

```text
The Big Picture
Deep Dive
Consensus vs. Debate
What Comes Next
Catalysts to Watch
Bottom Line
Sources
```

This prevents the newsletter from becoming a wall of research while retaining the underlying analytical depth.

## Recency Weighting

The newsletter does not treat every video in the analysis window equally.

Newer information receives more editorial weight when it materially updates older information.

Conceptually:

```text
Last 24 hours      -> highest relevance
Last 72 hours      -> very high relevance
Days 4–7           -> recent transition
Days 8–14          -> historical context
```

Older information remains important when it explains how the current environment developed.

The model is instructed not to treat recency as proof of accuracy. Newer claims only supersede older claims when the newer evidence meaningfully updates the story.

## Generated Files

Newsletter generation produces three files:

```text
data/newsletters/
├── YYYY-MM-DD-research.md
├── YYYY-MM-DD-newsletter.md
└── YYYY-MM-DD-newsletter.html
```

### Research dossier

```text
YYYY-MM-DD-research.md
```

Contains the full output of the market-research agent.

This provides an audit trail and makes it easier to determine whether information was missed during research or removed later by the editor.

### Markdown newsletter

```text
YYYY-MM-DD-newsletter.md
```

The canonical newsletter document.

### HTML newsletter

```text
YYYY-MM-DD-newsletter.html
```

Rendered deterministically from the Markdown output.

The HTML version includes responsive styling and is suitable for browser viewing or as the basis for future email/web publishing.

## Database

The project currently uses SQLite with SQLAlchemy.

Primary entities include:

### Channel

Tracks:

* YouTube channel ID
* Channel name
* Backfill status
* Last checked timestamp

### Video

Tracks:

* Channel
* YouTube video ID
* Title
* Publication timestamp
* Transcript processing status
* AI processing status
* Processing timestamp
* Last error

Processing statuses are persisted so interrupted runs can safely resume.

## Failure Recovery

The pipeline is designed to tolerate partial failures.

Interrupted backfills can return to a retryable state.

Interrupted transcript downloads can be reset.

Interrupted AI-processing jobs can be returned to `PENDING`.

Individual transcript failures do not need to terminate an entire batch.

Members-only, private, or otherwise unavailable YouTube videos should not prevent public videos from the same channel from being processed.

## External Market Context

The next stage of the project is to supplement creator research with structured external financial data.

The goal is to combine three different classes of information:

```text
YouTube creators
    -> narratives, interpretations and forecasts

Official / market data
    -> measurable current state

Market sentiment / positioning
    -> expectations and risk appetite

Research Agent
    -> reconcile all three
```

Potential data sources include:

* CNN Fear & Greed Index
* U.S. Treasury yield curve
* CME FedWatch
* Cboe VIX and volatility indices
* Federal Reserve Economic Data (FRED)
* Bureau of Labor Statistics
* Bureau of Economic Analysis
* U.S. Energy Information Administration
* SEC EDGAR
* CFTC Commitments of Traders
* Credit-spread data

Webshare proxy support can be reused where direct HTTP access is appropriate.

Where structured APIs or official feeds exist, those should generally be preferred over HTML scraping.

A future structure may look like:

```text
src/news_letter/external/
├── sentiment/
│   └── cnn_fear_greed.py
│
├── rates/
│   ├── treasury_curve.py
│   └── cme_fedwatch.py
│
├── macro/
│   ├── fred.py
│   ├── bls.py
│   └── bea.py
│
├── energy/
│   └── eia.py
│
├── credit/
│   └── credit_spreads.py
│
└── positioning/
    └── cftc_cot.py
```

## Design Philosophy

The system intentionally separates collection, research, and editorial judgment.

```text
Raw information
      ↓
Structured extraction
      ↓
Research synthesis
      ↓
Editorial synthesis
      ↓
Readable intelligence
```

The objective is not to automatically repeat what individual creators say.

The objective is to understand:

* Where the narrative started
* What changed
* What the newest evidence says
* Where credible sources disagree
* Which numbers actually matter
* What could change the current outlook
* What readers should monitor next

## Roadmap

Planned improvements include:

* External market-data ingestion
* CNN Fear & Greed history and components
* Treasury yield-curve monitoring
* Fed probability monitoring
* Energy inventory and refinery data
* VIX and volatility context
* Automatic market-context snapshots
* Historical newsletter comparison
* Narrative tracking across multiple newsletters
* Structured citation management
* Newsletter web publishing
* Email distribution
* Scheduled daily generation
* Better source-quality and confidence scoring

## Disclaimer

This project is intended for research and informational purposes.

Content generated by the system may include opinions, predictions, claims, or data reported by third-party sources. The pipeline does not automatically verify every underlying claim.

Nothing generated by this project should be interpreted as investment, financial, legal, or tax advice.

## License

Add the license appropriate for your project before distributing or accepting outside contributions.
