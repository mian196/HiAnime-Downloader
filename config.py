"""
Configuration module for HiAnime Downloader.

Loads settings from environment variables and .env file.
"""

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)


# =============================================================================
# DOWNLOAD SETTINGS
# =============================================================================

# Number of parallel download workers
MAX_DOWNLOAD_WORKERS = int(os.getenv('DOWNLOAD_WORKERS', 6))

# Number of parallel FFmpeg embed workers
MAX_EMBED_WORKERS = int(os.getenv('EMBED_WORKERS', 4))

# Default output directory
DEFAULT_OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')

# Video resolution (720, 1080, etc.)
RESOLUTION = os.getenv('RESOLUTION', '720')

# Audio type: 'sub' for Japanese audio, 'dub' for English audio
AUDIO_TYPE = os.getenv('AUDIO_TYPE', 'sub')

# Subtitle language
SUBTITLE_LANG = os.getenv('SUBTITLE_LANG', 'en')

# Delay between starting downloads (rate limit protection)
DOWNLOAD_DELAY = float(os.getenv('DOWNLOAD_DELAY', 2))

# Download timeout in seconds
DOWNLOAD_TIMEOUT = int(os.getenv('DOWNLOAD_TIMEOUT', 3600))

# FFmpeg embed timeout in seconds
EMBED_TIMEOUT = int(os.getenv('EMBED_TIMEOUT', 600))


# =============================================================================
# BEHAVIOR SETTINGS
# =============================================================================

# Download all episodes by default (skip episode range prompt)
DOWNLOAD_ALL = os.getenv('DOWNLOAD_ALL', 'true').lower() in ('true', '1', 'yes')

# Show yt-dlp output (verbose mode)
VERBOSE = os.getenv('VERBOSE', 'true').lower() in ('true', '1', 'yes')

# Logging level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# Include timestamps in log output
LOG_TIMESTAMPS = os.getenv('LOG_TIMESTAMPS', 'true').lower() in ('true', '1', 'yes')

# Skip subtitle download
NO_SUBTITLES = os.getenv('NO_SUBTITLES', 'false').lower() in ('true', '1', 'yes')

# Default season number (0 = prompt user)
DEFAULT_SEASON = int(os.getenv('DEFAULT_SEASON', 0))

# Filename format options:
# 'full'     = Title + Season + Episode + Episode Title: "Bleach TYBW The Conflict - S01E02 - Kill The King.mkv"
# 'standard' = Title + Season + Episode (no title):      "Bleach TYBW The Conflict - S01E02.mkv"
# 'short'    = First word + Season + Episode:            "Bleach - S01E02.mkv"
# 'season'   = Season + Episode only:                    "S01E02.mkv"
# 'episode'  = Episode only:                             "E02.mkv"
FILENAME_FORMAT = os.getenv('FILENAME_FORMAT', 'standard').lower()


# =============================================================================
# ANIME URL QUEUE
# =============================================================================

def parse_anime_urls() -> List[str]:
    """Parse ANIME_URLS from env, supporting comma or newline separation."""
    urls_raw = os.getenv('ANIME_URLS', '')
    if not urls_raw:
        # Fallback to single ANIME_URL for backwards compatibility
        single_url = os.getenv('ANIME_URL', '')
        return [single_url] if single_url else []

    # Split by comma or newline, strip whitespace, filter empty
    urls = []
    for part in urls_raw.replace('\n', ',').split(','):
        url = part.strip()
        if url:
            urls.append(url)
    return urls


ANIME_URL_QUEUE = parse_anime_urls()


# =============================================================================
# HTTP HEADERS
# =============================================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
    "Connection": "keep-alive",
}


# =============================================================================
# PRINT CURRENT CONFIG (for debugging)
# =============================================================================

def print_config():
    """Print current configuration for debugging."""
    from colorama import Fore, Style

    print(f"\n{Fore.CYAN}Current Configuration:{Style.RESET_ALL}")
    print(f"  Download Workers: {MAX_DOWNLOAD_WORKERS}")
    print(f"  Embed Workers: {MAX_EMBED_WORKERS}")
    print(f"  Output Dir: {DEFAULT_OUTPUT_DIR}")
    print(f"  Resolution: {RESOLUTION}p")
    print(f"  Audio Type: {AUDIO_TYPE}")
    print(f"  Subtitle Lang: {SUBTITLE_LANG}")
    print(f"  Download Delay: {DOWNLOAD_DELAY}s")
    print(f"  Download All: {DOWNLOAD_ALL}")
    print(f"  Verbose: {VERBOSE}")
    print(f"  Log Level: {LOG_LEVEL}")
    print(f"  Log Timestamps: {LOG_TIMESTAMPS}")
    if ANIME_URL_QUEUE:
        print(f"  URLs in Queue: {len(ANIME_URL_QUEUE)}")
    print()
