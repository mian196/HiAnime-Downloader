# ⚡ KAA Downloader (KickAssAnime)

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.8+">
  <img src="https://img.shields.io/badge/FFmpeg-Supported-green?style=for-the-badge&logo=ffmpeg&logoColor=white" alt="FFmpeg">
  <img src="https://img.shields.io/badge/yt--dlp-Supported-red?style=for-the-badge&logo=youtube&logoColor=white" alt="yt-dlp">
  <img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="MIT License">
</p>

A state-of-the-art, high-performance parallel downloader for **kaa.lt** (KickAssAnime) with automatic subtitle conversion and lossy-free chapter skip-time embedding.

---

## ✨ Features

- **🚀 3-Stage Parallel Pipeline** — Scraping, downloading, and embedding run concurrently on separate workers.
- **⏱️ Dynamic Chapter Skip Times** — Integrates Jikan & AniSkip APIs to automatically embed `Opening` and `Ending` timestamps as chapters into the final video (compatible with VLC, MPV, MPC-HC, etc.).
- **💬 Auto Subtitle Embedding** — Subtitles are downloaded as `.vtt`, natively converted to `.srt`, and multiplexed into the `.mkv` file with `default+forced` flags.
- **🔍 Interactive Search & Range Selection** — Search for anime by name directly in the terminal, and choose custom download ranges (e.g. single episode, starting from episode X, or range X to Y).
- **🎛️ Configurable Filenames** — Choose from 5 different naming conventions (`standard`, `full`, `short`, `season`, `episode`) to match your media server structure (e.g. Plex, Jellyfin).
- **🚦 Smart Rate Limiting & Timeouts** — Configurable request delays and HLS fragment socket timeouts to prevent rate limits and terminal hangs.
- **🛡️ Graceful Interrupts** — Responds to `Ctrl+C` by finishing current downloads before exiting safely.

---

## 📐 Pipeline Architecture

```text
  ┌─────────────────────────────────────────────────────────────┐
  │                    PARALLEL EXECUTION MODEL                 │
  ├─────────────────────────────────────────────────────────────┤
  │                                                             │
  │  [SCRAPER THREAD]     [DOWNLOAD WORKERS]    [EMBED WORKERS] │
  │        │                      │                     │       │
  │  Scrapes URLs  ───▶  [Download Queue]               │       │
  │  (Details API)                │                     │       │
  │                        Worker 1 (yt-dlp)            │       │
  │                        Worker 2 (yt-dlp) ──▶  [Embed Queue] │
  │                               ▼                     │       │
  │                        (Raw MP4 Streams)       Worker 1     │
  │                                                Worker 2     │
  │                                                     ▼       │
  │                                              (FFmpeg Muxing)│
  │                                                     ▼       │
  │                                              (Final .mkv)   │
  └─────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Quick Start

### 1. Install System Dependencies (Windows)

```powershell
# Install Python 3.13
winget install Python.Python.3.13

# Install FFmpeg (required for muxing and chapters)
winget install Gyan.FFmpeg
```

### 2. Set Up Virtual Environment & Dependencies

```bash
# Clone the repository
git clone git@github.com:mian196/KAA-Downloader.git
cd KAA-Downloader

# Create and activate venv
python -m venv .venv
.venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 3. Initialize Configuration

Copy the example configuration to create your local `.env`:
```bash
cp .env.example .env
```

---

## 🚀 Usage Guide

### 📱 Interactive Command Center
Simply launch the program without arguments to search for anime or enter custom URLs:
```bash
python main.py
```

### 🔍 Search by Name
```bash
python main.py -s "Horimiya"
```

### 🔗 Direct URL Download
```bash
python main.py -u "https://kaa.lt/horimiya-1e9c"
```

### 📋 Scrape URLs Only (CSV Export)
```bash
python main.py -u "https://kaa.lt/horimiya-1e9c" --fetch-only
```

### 📂 Resume Download from CSV
```bash
python main.py --from-csv "output/Horimiya (Sub)/Horimiya_episodes.csv"
```

---

## ⚙️ Configuration Options (`.env`)

Every aspect of the downloader is customizable via settings inside the `.env` file:

| Parameter | Default | Description |
| :--- | :--- | :--- |
| **ANIME_URL** | `None` | If set, skips the interactive input and starts downloads immediately. |
| **ANIME_URLS** | `None` | Comma-separated list of URLs to process sequentially in queue mode. |
| **DOWNLOAD_WORKERS** | `6` | Number of concurrent `yt-dlp` download processes. |
| **EMBED_WORKERS** | `4` | Number of concurrent `FFmpeg` subtitle/chapter muxers. |
| **OUTPUT_DIR** | `output` | Directory where downloaded anime folders are stored. |
| **DOWNLOAD_ALL** | `false` | If `false`, prompts you for custom episode ranges (all, single, start X, range X-Y). |
| **VERBOSE** | `true` | Outputs real-time progress and logs from `yt-dlp`. |
| **LOG_LEVEL** | `INFO` | Level of terminal verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| **RESOLUTION** | `720` | Desired video quality (`720`, `1080`). |
| **AUDIO_TYPE** | `sub` | Language track to extract (`sub` for Japanese, `dub` for English). |
| **EMBED_CHAPTERS** | `true` | Enables AniSkip skip-time chapter embedding in output video files. |
| **FILENAME_FORMAT** | `standard` | Template for output files (`standard`, `full`, `short`, `season`, `episode`). |
| **DOWNLOAD_DELAY** | `2` | Delay in seconds between starting downloads (prevents server throttling). |
| **DOWNLOAD_TIMEOUT**| `3600` | Max seconds allowed for downloading a single episode stream. |

---

## 🗂️ Filename Formats

| Format | Naming Pattern | Example Output |
| :--- | :--- | :--- |
| `episode` | `E{ep}` | `E02.mkv` |
| `season` | `S{season}E{ep}` | `S01E02.mkv` |
| `short` | `{ShortTitle} - S{season}E{ep}` | `Bleach - S01E02.mkv` |
| `standard` | `{CleanTitle} - S{season}E{ep}` | `Bleach TYBW The Conflict - S01E02.mkv` |
| `full` | `{CleanTitle} - S{season}E{ep} - {EpTitle}` | `Bleach TYBW The Conflict - S01E02 - Kill The King.mkv` |

---

## 📁 Repository Structure

```text
KAA-Downloader/
├── main.py               # Main pipeline manager & worker threads
├── config.py             # Parses settings from .env
├── requirements.txt      # Python dependencies
├── .env.example          # Template configuration
│
├── extractors/           # Extraction logic
│   ├── __init__.py
│   ├── hianime.py        # Base extractor & model dataclasses
│   └── kickassanime.py   # KAA-specific API parsing & decoders
│
└── tools/                # Utilities
    ├── __init__.py
    ├── functions.py      # Console input handlers & file operations
    └── thread_logger.py  # Synchronized console logging
```

---

## 🤝 Acknowledgements

Special thanks to the original creators whose repositories laid the foundation for this fork:
*   **Base Codebase**: [HianimeDownloader](https://github.com/gheatherington/HianimeDownloader) by [@gheatherington](https://github.com/gheatherington)
*   **yt-dlp Plugin**: [yt-dlp-hianime](https://github.com/pratikpatel8982/yt-dlp-hianime) by [@pratikpatel8982](https://github.com/pratikpatel8982)
