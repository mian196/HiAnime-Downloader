# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

KickAssAnime Downloader is a Python CLI tool for downloading anime from kaa.lt with automatic subtitle embedding. It uses a parallel pipeline: scraping → downloading (yt-dlp) → subtitle embedding (FFmpeg).

## Commands

```bash
# Run interactive mode
python main.py

# Search by name
python main.py -s "anime name"

# Direct URL download
python main.py -u "https://kaa.lt/anime-slug"

# Fetch episode list only (no download)
python main.py -u "URL" --fetch-only

# Download from previously saved CSV
python main.py --from-csv "path/to/file.csv"

# Syntax check
python -m py_compile main.py
```

## Architecture

## Three-Stage Pipeline
```
Scraper Thread → Download Queue → Download Workers (yt-dlp)
                                        ↓
                     Embed Queue → Embed Workers (FFmpeg) → .mkv files
```

### Core Components

- **main.py**: Entry point, CLI parsing, parallel worker orchestration, signal handling for graceful shutdown
- **config.py**: Loads `.env` settings (worker counts, resolution, timeouts, filename format)
- **extractors/kickassanime.py**: `KickAssAnimeExtractor` class - search, URL parsing, API calls to fetch episode lists and dynamic media resolution
- **tools/thread_logger.py**: Thread-aware colored logging with worker prefixes (W1-W6, E1-E4, SCRAPER, MAIN)
- **tools/functions.py**: Utilities for filename sanitization, user prompts, colored output

### Key Data Classes (in `extractors/hianime.py`)

- `Anime`: name, url, sub_episodes, dub_episodes, download_type, season_number
- `Episode`: number, url, title, filename, video_path, subtitle_path, status, error

### Threading Model

- 1 scraper thread fetches episode URLs
- N download workers (default 6) run yt-dlp in parallel
- M embed workers (default 4) run FFmpeg in parallel
- Thread-safe queues connect stages; locks protect shared state
- `shutdown_event` enables graceful Ctrl+C handling

## Configuration

Settings loaded from `.env` file. Key options:
- `DOWNLOAD_WORKERS`, `EMBED_WORKERS`: Parallelism controls
- `RESOLUTION`: 720 or 1080
- `AUDIO_TYPE`: sub or dub
- `FILENAME_FORMAT`: episode, season, short, standard, full
- `DOWNLOAD_DELAY`: Rate limiting between downloads (seconds)
- `ANIME_URLS`: Comma-separated URLs for queue processing

## External Dependencies

**Required system tools**: yt-dlp, FFmpeg (must be in PATH)

**Python packages**: beautifulsoup4, requests, colorama, python-dotenv, yt-dlp

**Optional**: selenium, selenium-wire, selenium-stealth (for m3u8 capture fallback)

## Output Structure

```
output/
└── Anime Name (Sub)/
    ├── Anime Name_episodes.csv
    ├── Anime Name_metadata.json
    └── Anime Name - S01E01.mkv
```

## Platform Notes

- Windows-specific subprocess flags used (`CREATE_NEW_PROCESS_GROUP`)
- Selenium config uses mobile emulation with stealth mode for anti-bot bypass
- Single-episode content (movies/OVAs) uses anime name only without episode numbering
