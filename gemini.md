# GEMINI.md

This file provides guidance to Google Gemini when working with code in this repository.

---

## Repository Origin

> [!IMPORTANT]
> This project is a **refactored fork** of [HianimeDownloader](https://github.com/gheatherington/HianimeDownloader) by [@gheatherington](https://github.com/gheatherington).

**Key Differences from Source:**

- Focuses exclusively on HiAnime (removed multi-platform support)
- Uses [yt-dlp-hianime](https://github.com/pratikpatel8982/yt-dlp-hianime) plugin instead of Selenium-based m3u8 capture
- Implements a parallel 3-stage pipeline (Scrape → Download → Embed)
- Adds comprehensive `.env` configuration system
- Provides thread-aware colored logging

---

## External Dependencies

### Core Tools (Must be in PATH)

| Tool | Purpose | Install |
|------|---------|---------|
| `yt-dlp` | Video downloading engine | `pip install yt-dlp` |
| `FFmpeg` | Subtitle embedding, video processing | `winget install Gyan.FFmpeg` |

### Required Plugin

| Plugin | Repository | Install |
|--------|------------|---------|
| `yt-dlp-hianime` | [pratikpatel8982/yt-dlp-hianime](https://github.com/pratikpatel8982/yt-dlp-hianime) | `pip install -U https://github.com/pratikpatel8982/yt-dlp-hianime/archive/master.zip` |

> [!NOTE]
> The plugin is **external code I do not modify**. If yt-dlp or the plugin introduces breaking changes, identify them and update this context accordingly.

### Python Packages

**Required:** `beautifulsoup4`, `requests`, `colorama`, `python-dotenv`, `yt-dlp`

**Optional:** `selenium`, `selenium-wire`, `selenium-stealth`, `langdetect` (for fallback m3u8 capture and language detection)

---

## Project Overview

HiAnime Downloader is a Python CLI tool for downloading anime from hianime.to with automatic subtitle embedding. It uses a parallel pipeline: **Scraping → Downloading (yt-dlp) → Subtitle Embedding (FFmpeg)**.

---

## Commands

```bash
# Run interactive mode
python main.py

# Search by name
python main.py -s "anime name"

# Direct URL download
python main.py -u "https://hianime.to/watch/anime-slug"

# Fetch episode list only (no download)
python main.py -u "URL" --fetch-only

# Download from previously saved CSV
python main.py --from-csv "path/to/file.csv"

# Syntax check
python -m py_compile main.py
```

---

## Architecture

### Three-Stage Parallel Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                     PARALLEL PIPELINE                        │
├─────────────────────────────────────────────────────────────┤
│  SCRAPER              DOWNLOADERS           EMBEDDERS        │
│  ───────              ───────────           ─────────        │
│  EP1 found ────────▶  [Download Queue] ──▶ [Embed Queue]    │
│  EP2 found ────────▶       ▼                   ▼            │
│  EP3 found ────────▶    Worker 1 ─────────▶ Worker 1        │
│  ...                    Worker 2 ─────────▶ Worker 2        │
│                       (yt-dlp downloads)   (FFmpeg embed)    │
└─────────────────────────────────────────────────────────────┘
```

### Core Components

| File | Purpose |
|------|---------|
| `main.py` | Entry point, CLI parsing, parallel worker orchestration, signal handling |
| `config.py` | Loads `.env` settings (worker counts, resolution, timeouts, filename format) |
| `extractors/hianime.py` | `HianimeExtractor` class - search, URL parsing, AJAX API calls |
| `tools/thread_logger.py` | Thread-aware colored logging with worker prefixes (W1-W6, E1-E4) |
| `tools/functions.py` | Utilities for filename sanitization, user prompts, colored output |

### Key Data Classes (`extractors/hianime.py`)

- **`Anime`**: `name`, `url`, `sub_episodes`, `dub_episodes`, `download_type`, `season_number`
- **`Episode`**: `number`, `url`, `title`, `filename`, `video_path`, `subtitle_path`, `status`, `error`

### Threading Model

- 1 scraper thread fetches episode URLs
- N download workers (default 6) run yt-dlp in parallel
- M embed workers (default 4) run FFmpeg in parallel
- Thread-safe queues connect stages; locks protect shared state
- `shutdown_event` enables graceful Ctrl+C handling

---

## Configuration

Settings loaded from `.env` file:

| Setting | Default | Description |
|---------|---------|-------------|
| `DOWNLOAD_WORKERS` | 6 | Parallel download threads |
| `EMBED_WORKERS` | 4 | Parallel FFmpeg processes |
| `RESOLUTION` | 720 | Video resolution (720 or 1080) |
| `AUDIO_TYPE` | sub | Audio type (sub or dub) |
| `FILENAME_FORMAT` | standard | episode, season, short, standard, full |
| `DOWNLOAD_DELAY` | 2 | Rate limiting between downloads (seconds) |
| `DOWNLOAD_TIMEOUT` | 3600 | Max seconds per download |
| `ANIME_URLS` | - | Comma-separated URLs for queue processing |

---

## Feature Comparison: Source vs My Tool

| Feature | HianimeDownloader (Source) | HiAnime Downloader (This Fork) |
|---------|----------------------------|--------------------------------|
| **Platforms** | HiAnime + TikTok + YouTube + Instagram | HiAnime only |
| **Download Method** | Chrome/Selenium m3u8 capture | yt-dlp with hianime plugin |
| **Parallelism** | Sequential downloads | 3-stage parallel pipeline |
| **Configuration** | CLI args only | `.env` file + CLI args |
| **Logging** | Basic colored output | Thread-aware logging with worker IDs |
| **Queue Mode** | No | Yes (multiple URLs in `.env`) |
| **CSV Export** | No | Yes (fetch-only mode) |
| **Metadata Export** | No | Yes (JSON) |
| **Subtitle Handling** | Downloads VTT, no embedding | Auto-embeds into MKV |
| **Server Selection** | Manual via prompt | Not needed (plugin handles) |
| **`--aria` option** | Yes (untested) | Removed |
| **`--server` option** | Yes | Removed (plugin auto-selects) |
| **Multi-extractor** | `GeneralExtractor`, `InstagramExtractor` | Removed |
| **Filename Formats** | Fixed naming | 5 configurable formats |
| **Rate Limiting** | No | Yes (configurable delay) |
| **Graceful Shutdown** | No | Yes (Ctrl+C waits for current downloads) |

### What Was Kept

- Core search functionality
- Episode URL scraping via AJAX API
- Basic HiAnime extractor structure

### What Was Removed

- Multi-platform support (TikTok, YouTube, Instagram extractors)
- Chrome/Selenium-based m3u8 capture (replaced with yt-dlp plugin)
- `--aria` and `--server` CLI options

### Custom Additions

- Parallel 3-stage download pipeline
- `.env` configuration system
- Thread-aware colored logging
- Queue mode for batch processing
- CSV/JSON export capabilities
- Automatic subtitle embedding
- Multiple filename format options
- Graceful shutdown handling
- Rate limiting between downloads

---

## Upstream Update Workflow

### Protocol

When checking for updates from the source repositories:

1. **Clone/Update References in `scripts/`**
   ```bash
   cd scripts/
   git clone https://github.com/gheatherington/HianimeDownloader.git
   # For plugin reference:
   git clone https://github.com/pratikpatel8982/yt-dlp-hianime.git
   ```

2. **The `scripts/` folder is `.gitignore`'d** - use it strictly for reading/referencing code, not deployment.

### Integration Rules

> [!CAUTION]
> When integrating features from the source tool:

1. **Read the code in `scripts/`** - Understand the upstream implementation thoroughly
2. **Adapt to existing architecture** - Fit new features into my parallel pipeline design
3. **Safety Check** - STRICTLY ensure importing a new feature does not break existing code
4. **No blind copy-paste** - My tool does not implement every source feature; do not add missing logic unless explicitly requested
5. **Test thoroughly** - Verify the feature works within my threading model

### Reference URLs

- **Base Repository:** https://github.com/gheatherington/HianimeDownloader
- **yt-dlp Plugin:** https://github.com/pratikpatel8982/yt-dlp-hianime
- **yt-dlp Documentation:** https://github.com/yt-dlp/yt-dlp

---

## Output Structure

```
output/
└── Anime Name (Sub)/
    ├── Anime Name_episodes.csv    # Episode list
    ├── Anime Name_metadata.json   # Anime metadata
    ├── Anime Name - S01E01.mkv    # Video with embedded subs
    └── ...
```

---

## Platform Notes

- Windows-specific subprocess flags used (`CREATE_NEW_PROCESS_GROUP`)
- Selenium config uses mobile emulation with stealth mode (fallback only)
- Single-episode content (movies/OVAs) uses anime name only without episode numbering
