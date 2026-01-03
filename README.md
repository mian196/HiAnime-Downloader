# Parallel Anime Downloader

A simple, multi-threaded anime downloader for Hianime.to.

## Quick Start

### Step 1: Install Python
Download and install Python from the [official website](https://www.python.org/downloads/) or use winget:
```bash
winget install Python.Python.3.13
```

### Step 2: Install FFmpeg
Download FFmpeg from [ffmpeg.org](https://ffmpeg.org/download.html) and add it to your PATH, or use winget:
```bash
winget install Gyan.FFmpeg
```

### Step 3: Install yt-dlp
```bash
python3 -m pip install -U "yt-dlp[default]"
```

### Step 4: Install yt-dlp Hianime Plugin
```bash
python -m pip install -U https://github.com/pratikpatel8982/yt-dlp-hianime/archive/master.zip
```
Plugin source: https://github.com/pratikpatel8982/yt-dlp-hianime

### Step 5: Install Python Dependencies
```bash
cd parallel_downloader
pip install -r requirements.txt
```

### Step 6: Run the Downloader
```bash
python main.py
```

---

## Features

This tool:

1. **Generates** episode URLs based on the sequential `?ep=` pattern
2. **Saves** episode list to CSV with proper filenames (`Anime Title - EP01`)
3. **Downloads** using yt-dlp (with hianime plugin) in parallel
4. **Embeds** subtitles with FFmpeg - subtitles are **enabled by default**
5. **Cleans up** separate SRT files after embedding

## Requirements

- Python 3.8+
- yt-dlp with hianime extractor plugin
- FFmpeg (must be in PATH)

## Installation

```bash
cd parallel_downloader

# Install Python dependencies
pip install -r requirements.txt

# Make sure yt-dlp is installed
pip install yt-dlp

# Make sure ffmpeg is in your PATH
```

## Usage

### Interactive Mode
```bash
python main.py
```

### With URL
```bash
python main.py -u "https://hianime.to/watch/bleach-806?ep=13793"
```

### Generate CSV Only (no download)
```bash
python main.py --csv-only
```

### Custom Worker Counts
```bash
python main.py --download-workers 8 --embed-workers 6
```

## How It Works

1. You provide a URL with the **first episode** (e.g., `?ep=13793`)
2. The tool uses the sequential pattern to generate all episode URLs:
   - EP1: `?ep=13793`
   - EP2: `?ep=13794`
   - EP3: `?ep=13795`
   - etc.
3. Saves the list to CSV
4. Downloads in parallel using your yt-dlp command:
   ```
   yt-dlp -S "res:720" -f b[format_id*=sub] --write-subs --sub-lang en --convert-subs srt [URL]
   ```
5. Embeds subtitles with FFmpeg (default disposition so they play automatically)
6. Removes the separate .srt files

## Output

```
output/
└── Anime Name/
    ├── Anime Name_episodes.csv
    ├── Anime Name - EP01.mp4
    ├── Anime Name - EP02.mp4
    └── ...
```

## Configuration

Default settings (in main.py):
- `MAX_DOWNLOAD_WORKERS = 6` - concurrent yt-dlp processes
- `MAX_EMBED_WORKERS = 4` - concurrent FFmpeg processes
- Resolution: 720p
- Format: subbed version
- Output: MP4 (falls back to MKV if needed)

## Notes

- The `?ep=` IDs are sequential for most anime on hianime
- Subtitles are embedded with `disposition:default` so they auto-play
- If MP4 subtitle embedding fails, it falls back to MKV format
