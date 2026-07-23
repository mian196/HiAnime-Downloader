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
- **📦 Global Pip Executable** — Install as a system CLI tool and run `kaa` from any directory.
- **⚙️ YAML Configuration System** — OS-aware configuration file management (`config.yaml`) with CLI subcommands (`kaa config`).
- **⏱️ Dynamic Chapter Skip Times** — Integrates Jikan & AniSkip APIs to automatically embed `Opening` and `Ending` timestamps as chapters into the final video (compatible with VLC, MPV, MPC-HC, etc.).
- **💬 Auto Subtitle Embedding** — Subtitles are downloaded as `.vtt`, natively converted to `.srt`, and multiplexed into the `.mkv` file with `default+forced` flags.
- **🔍 Interactive Search & Range Selection** — Search for anime by name directly in the terminal, or download from custom URL batch files.
- **🎛️ Configurable Filenames** — Choose from 5 different naming conventions (`standard`, `full`, `short`, `season`, `episode`) to match media servers (Plex, Jellyfin).
- **🚦 Smart Rate Limiting & Timeouts** — Configurable request delays and socket timeouts to prevent rate limits.
- **🛡️ Graceful Interrupts** — Responds to `Ctrl+C` by finishing current downloads before exiting safely.

---

## 🛠️ Installation

### 1. Install System Dependencies (Windows)

```powershell
# Install Python 3.8+
winget install Python.Python.3.13

# Install FFmpeg (required for muxing and chapters)
winget install Gyan.FFmpeg
```

### 2. Install via Pip (Global CLI Tool)

Install directly from GitHub as a global executable:

```bash
pip install git+https://github.com/mian196/KAA-Downloader.git
```

Once installed, you can run `kaa` or `kaa-downloader` from any terminal prompt!

---

## ⚙️ Configuration Management (`config.yaml`)

The downloader automatically resolves configuration using a **5-tier priority hierarchy**:

```text
High Priority
  ├── 1. Command-Line Arguments  (e.g., --workers 8 --resolution 1080)
  ├── 2. Environment Variables   (e.g., KAA_DOWNLOAD_WORKERS=8)
  ├── 3. Local Config File       (./config.yaml in current working directory)
  ├── 4. Global User Config      (OS-standard path via platformdirs)
  └── 5. Built-in Defaults       (Hardcoded fallback values)
Low Priority
```

### 📍 OS Global Config Paths
- **Windows**: `%APPDATA%\kaa-downloader\config.yaml`
- **Linux / macOS**: `~/.config/kaa-downloader/config.yaml`

### 🎛️ CLI Config Management Subcommands

```bash
# Initialize or reset the global config.yaml file
kaa config --init

# Show active global & local configuration file paths
kaa config --path

# Display active resolved configuration settings
kaa config --show
```

### 📄 `config.yaml` Example Schema

```yaml
download:
  download_workers: 6      # Parallel download threads
  embed_workers: 4         # Parallel FFmpeg subtitle embedding processes
  resolution: "720"        # Video resolution (720, 1080)
  audio_type: "sub"        # Audio format (sub, dub)
  subtitle_lang: "en"      # Subtitle language code
  download_delay: 2.0      # Throttle delay between downloads in seconds
  download_timeout: 3600   # Max download timeout per episode in seconds
  embed_timeout: 600       # Max embed timeout per episode in seconds
  download_all: true       # Download all episodes by default
  no_subtitles: false      # Disable subtitle extraction/embedding
  embed_chapters: true     # Embed skip-time chapters into MKV container

output:
  output_dir: "output"     # Default directory for saved videos
  filename_format: "standard" # Options: episode, season, short, standard, full

logging:
  verbose: true            # Show detailed worker logs
  log_level: "INFO"        # Options: DEBUG, INFO, WARNING, ERROR
  log_timestamps: true     # Include timestamps in console log output
```

---

## 🚀 Usage Guide

### 📱 Interactive Command Center
Simply launch the program without arguments to search for anime or enter custom URLs:
```bash
kaa
```

### 🔍 Search by Name
```bash
kaa -s "Horimiya"
```

### 🔗 Direct URL Download
```bash
kaa -u "https://kaa.lt/horimiya-1e9c" --resolution 1080 --audio-type sub
```

### 📄 Download from URL Batch File
```bash
kaa --url-file urls.txt
```

### 📋 Scrape URLs Only (CSV Export)
```bash
kaa -u "https://kaa.lt/horimiya-1e9c" --fetch-only
```

### 📂 Resume Download from CSV
```bash
kaa --from-csv "output/Horimiya (Sub)/Horimiya_episodes.csv"
```

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
├── main.py               # CLI entrypoint & parallel pipeline manager
├── config.py             # YAML & env config resolver with OS platformdirs
├── pyproject.toml        # Pip package build & executable specification
├── config.yaml           # Default configuration settings
├── config.yaml.example   # Config template reference
├── requirements.txt      # Python package dependencies
│
├── extractors/           # Scrapers & data models
│   ├── __init__.py
│   ├── models.py         # Anime & Episode dataclasses
│   └── kickassanime.py   # KAA API scraping & decoders
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
