import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

MAX_DOWNLOAD_WORKERS = int(os.getenv('DOWNLOAD_WORKERS', 6))
MAX_EMBED_WORKERS = int(os.getenv('EMBED_WORKERS', 4))
DEFAULT_OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
RESOLUTION = os.getenv('RESOLUTION', '720')
AUDIO_TYPE = os.getenv('AUDIO_TYPE', 'sub')
SUBTITLE_LANG = os.getenv('SUBTITLE_LANG', 'en')
DOWNLOAD_DELAY = float(os.getenv('DOWNLOAD_DELAY', 2))
DOWNLOAD_TIMEOUT = int(os.getenv('DOWNLOAD_TIMEOUT', 3600))
EMBED_TIMEOUT = int(os.getenv('EMBED_TIMEOUT', 600))

DOWNLOAD_ALL = os.getenv('DOWNLOAD_ALL', 'true').lower() in ('true', '1', 'yes')
VERBOSE = os.getenv('VERBOSE', 'true').lower() in ('true', '1', 'yes')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
LOG_TIMESTAMPS = os.getenv('LOG_TIMESTAMPS', 'true').lower() in ('true', '1', 'yes')
NO_SUBTITLES = os.getenv('NO_SUBTITLES', 'false').lower() in ('true', '1', 'yes')
EMBED_CHAPTERS = os.getenv('EMBED_CHAPTERS', 'true').lower() in ('true', '1', 'yes')
DEFAULT_SEASON = int(os.getenv('DEFAULT_SEASON', 0))
FILENAME_FORMAT = os.getenv('FILENAME_FORMAT', 'standard').lower()



def parse_anime_urls() -> List[str]:
    urls_raw = os.getenv('ANIME_URLS', '')
    if not urls_raw:
        single_url = os.getenv('ANIME_URL', '')
        return [single_url] if single_url else []

    urls = []
    for part in urls_raw.replace('\n', ',').split(','):
        url = part.strip()
        if url:
            urls.append(url)
    return urls


ANIME_URL_QUEUE = parse_anime_urls()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
    "Connection": "keep-alive",
}


def print_config():
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
    print(f"  Embed Chapters: {EMBED_CHAPTERS}")
    print(f"  Verbose: {VERBOSE}")

    print(f"  Log Level: {LOG_LEVEL}")
    print(f"  Log Timestamps: {LOG_TIMESTAMPS}")
    if ANIME_URL_QUEUE:
        print(f"  URLs in Queue: {len(ANIME_URL_QUEUE)}")
    print()