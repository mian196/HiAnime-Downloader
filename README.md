# HiAnime Downloader

A parallel anime downloader for hianime.to with automatic subtitle embedding.

## Features

- **Parallel scraping + downloading** - Downloads start as soon as URLs are found
- **Handles non-sequential episode IDs** - Scrapes actual URLs from the page
- **Search by name** - Find anime without knowing the URL
- **Sub/Dub selection** - Choose Japanese or English audio
- **Season number support** - Proper naming (S01E05 format)
- **Auto subtitle embedding** - Subtitles enabled by default in video player
- **Queue mode** - Download multiple anime in sequence
- **CSV export** - Save episode list for later download
- **Thread-aware logging** - Color-coded output with timestamps
- **Configurable filename formats** - Multiple naming conventions available

## Requirements

- Python 3.8+
- yt-dlp with [hianime plugin](https://github.com/pratikpatel8982/yt-dlp-hianime)
- FFmpeg (must be in PATH)

## Quick Start

### 1. Install Python

```bash
winget install Python.Python.3.13
```

### 2. Install FFmpeg

```bash
winget install Gyan.FFmpeg
```

### 3. Install yt-dlp with HiAnime plugin

```bash
pip install yt-dlp
pip install -U https://github.com/pratikpatel8982/yt-dlp-hianime/archive/master.zip
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure (optional)

```bash
cp .env.example .env
# Edit .env with your settings
```

### 6. Run

```bash
python main.py
```

## Usage

### Interactive Mode

```bash
python main.py
```

### Search by Name

```bash
python main.py -s "bleach"
```

### Direct URL

```bash
python main.py -u "https://hianime.to/watch/bleach-806"
```

### Fetch Only (no download)

```bash
python main.py -u "URL" --fetch-only
# Creates CSV with episode URLs for later download
```

### Download from CSV

```bash
python main.py --from-csv "output/AnimeName/AnimeName_episodes.csv"
```

### Command Line Options

```text
Options:
  -u, --url             Anime URL
  -s, --search          Search anime by name
  -o, --output          Output directory (default: output)
  --from-csv            Download from existing CSV file
  --fetch-only          Only scrape URLs to CSV, no download
  --download-workers    Number of parallel downloads (default: 6)
  --embed-workers       Number of parallel FFmpeg processes (default: 4)
  --resolution          Video resolution: 720, 1080 (default: 720)
  --audio-type          Audio: sub or dub (default: sub)
  --season              Season number (default: 1)
```

## How It Works

```text
┌─────────────────────────────────────────────────────────────┐
│                     PARALLEL PIPELINE                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  SCRAPER              DOWNLOADERS           EMBEDDERS        │
│  ───────              ───────────           ─────────        │
│                                                              │
│  EP1 found ────────▶  [Download Queue] ──▶ [Embed Queue]    │
│  EP2 found ────────▶       ▼                   ▼            │
│  EP3 found ────────▶    Worker 1 ─────────▶ Worker 1        │
│  ...                    Worker 2 ─────────▶ Worker 2        │
│                                                              │
│  (scraping URLs)     (yt-dlp downloads)   (FFmpeg embed)    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

1. **Scrape** - Fetches episode URLs from anime page via AJAX API
2. **Queue** - Each URL is immediately added to download queue
3. **Download** - Parallel yt-dlp workers download videos + subtitles
4. **Embed** - Parallel FFmpeg workers embed subtitles into MKV
5. **Cleanup** - Removes separate .srt files after embedding

## Configuration (.env)

```bash
# Anime URL (optional - for single anime)
ANIME_URL=https://hianime.to/watch/bleach-806

# Multiple URLs (queue mode - comma separated)
ANIME_URLS=url1,url2,url3

# Workers
DOWNLOAD_WORKERS=6      # Parallel download threads
EMBED_WORKERS=4         # Parallel FFmpeg processes

# Video settings
RESOLUTION=720          # 720 or 1080
AUDIO_TYPE=sub          # sub or dub
SUBTITLE_LANG=en        # Subtitle language code

# Behavior
DOWNLOAD_ALL=true       # Download all episodes without prompting
VERBOSE=true            # Show yt-dlp output
DEFAULT_SEASON=0        # 0 = prompt user, 1+ = use that season
NO_SUBTITLES=false      # Skip subtitle download/embedding

# Filename format: episode, season, short, standard, full
FILENAME_FORMAT=standard

# Logging
LOG_LEVEL=INFO          # DEBUG, INFO, WARNING, ERROR
LOG_TIMESTAMPS=true     # Include timestamps in log output

# Rate limiting
DOWNLOAD_DELAY=2        # Seconds between starting downloads
DOWNLOAD_TIMEOUT=3600   # Max seconds per download (1 hour)
EMBED_TIMEOUT=600       # Max seconds per embed (10 minutes)
```

### Filename Formats

| Format     | Example Output                                       |
| ---------- | ---------------------------------------------------- |
| `episode`  | `E02`                                                |
| `season`   | `S01E02`                                             |
| `short`    | `Bleach - S01E02`                                    |
| `standard` | `Bleach TYBW The Conflict - S01E02`                  |
| `full`     | `Bleach TYBW The Conflict - S01E02 - Kill The King`  |

## Project Structure

```text
HiAnime-Downloader/
├── main.py              # Entry point and download pipeline
├── config.py            # Settings loader from .env
├── .env                 # Your configuration
├── .env.example         # Example configuration
├── requirements.txt     # Python dependencies
│
├── extractors/          # Site extractors
│   ├── __init__.py
│   └── hianime.py       # HiAnime scraper and data classes
│
└── tools/               # Utilities
    ├── __init__.py
    ├── functions.py     # Helper functions (input, file ops)
    ├── logger.py        # yt-dlp output logger
    └── thread_logger.py # Thread-aware logging system
```

## Output Structure

```text
output/
└── Anime Name (Sub)/
    ├── Anime Name_episodes.csv    # Episode list
    ├── Anime Name_metadata.json   # Anime metadata
    ├── Anime Name - S01E01.mkv    # Video with embedded subs
    ├── Anime Name - S01E02.mkv
    └── ...
```

## Notes

- Episode IDs are scraped from the page, not generated sequentially
- Subtitles are embedded with `default+forced` disposition (auto-play in players)
- Output format is MKV for subtitle compatibility
- Use `--fetch-only` to just get episode URLs without downloading
- Graceful shutdown on Ctrl+C - waits for current downloads to complete
- Single-episode content (movies/OVAs) automatically skips episode numbering

## Acknowledgements

Special thanks to the original creators whose work this project is based on:

- **Main Codebase**: [HianimeDownloader](https://github.com/gheatherington/HianimeDownloader) by [@gheatherington](https://github.com/gheatherington)
- **yt-dlp Plugin**: [yt-dlp-hianime](https://github.com/pratikpatel8982/yt-dlp-hianime) by [@pratikpatel8982](https://github.com/pratikpatel8982)
