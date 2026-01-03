"""
HiAnime Downloader - Parallel Anime Downloader for hianime.to

Features:
- Scraping and downloading happen IN PARALLEL
- As soon as an episode URL is found, it starts downloading
- No need to wait for all URLs to be scraped first

Modes:
1. FULL MODE: Scrape + Download simultaneously (default)
2. FETCH ONLY: Just scrape URLs to CSV (--fetch-only)
3. FROM CSV: Download from existing CSV (--from-csv)

Usage:
    python main.py                          # Interactive: scrape + download in parallel
    python main.py -s "bleach"              # Search + scrape + download
    python main.py -u "URL"                 # URL + scrape + download
    python main.py --fetch-only             # Only scrape URLs to CSV (no download)
    python main.py --from-csv "file.csv"   # Download from existing CSV file
"""

import os
import sys
import time
import signal
import subprocess
import threading
import argparse
import csv
import logging
from queue import Queue, Empty
from typing import List

from colorama import init, Fore, Style

init()

from config import (
    MAX_DOWNLOAD_WORKERS,
    MAX_EMBED_WORKERS,
    DEFAULT_OUTPUT_DIR,
    RESOLUTION,
    AUDIO_TYPE,
    SUBTITLE_LANG,
    DOWNLOAD_DELAY,
    DOWNLOAD_TIMEOUT,
    EMBED_TIMEOUT,
    DOWNLOAD_ALL,
    VERBOSE,
    NO_SUBTITLES,
    DEFAULT_SEASON,
    FILENAME_FORMAT,
    ANIME_URL_QUEUE,
    LOG_LEVEL,
    LOG_TIMESTAMPS,
)
from tools.thread_logger import (
    ThreadLogger,
    get_worker_logger,
    get_scraper_logger,
    get_main_logger,
)
from extractors import HianimeExtractor
from extractors.hianime import Episode, Anime
from tools.functions import (
    get_confirmation,
    get_int_in_range,
    safe_remove,
    sanitize_filename,
    print_info,
    print_success,
    print_error,
    print_warning,
)


# =============================================================================
# GLOBAL STATE
# =============================================================================

shutdown_event = threading.Event()
active_processes: List[subprocess.Popen] = []
processes_lock = threading.Lock()
download_throttle_lock = threading.Lock()
last_download_time = 0.0
print_lock = threading.Lock()

# Initialize logging system
LOG_LEVEL_MAP = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
}

ThreadLogger.initialize(
    level=LOG_LEVEL_MAP.get(LOG_LEVEL, logging.INFO),
    include_timestamp=LOG_TIMESTAMPS
)


# =============================================================================
# SIGNAL HANDLER
# =============================================================================

def signal_handler(signum, frame):
    print_warning("\n\nShutting down...")
    shutdown_event.set()
    with processes_lock:
        for proc in active_processes:
            try:
                proc.terminate()
            except:
                pass
        active_processes.clear()
    sys.exit(1)


# =============================================================================
# SUBPROCESS
# =============================================================================

def run_subprocess(cmd: List[str], timeout: int, prefix: str = "") -> subprocess.CompletedProcess:
    if shutdown_event.is_set():
        raise InterruptedError("Shutdown requested")

    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=creationflags)

    with processes_lock:
        active_processes.append(proc)

    stderr_lines, stdout_lines = [], []

    def read_stderr():
        try:
            for line in proc.stderr:
                stderr_lines.append(line)
                if VERBOSE and prefix and any(x in line for x in ['[download]', '[hlsnative]', '[info]', 'Destination:']):
                    with print_lock:
                        print(f"{Fore.YELLOW}[{prefix}]{Style.RESET_ALL} {line.rstrip()}")
        except:
            pass

    def read_stdout():
        try:
            for line in proc.stdout:
                stdout_lines.append(line)
        except:
            pass

    t1 = threading.Thread(target=read_stderr, daemon=True)
    t2 = threading.Thread(target=read_stdout, daemon=True)
    t1.start()
    t2.start()

    try:
        start = time.time()
        while True:
            if shutdown_event.is_set():
                proc.terminate()
                raise InterruptedError()
            if proc.poll() is not None:
                t1.join(timeout=2)
                t2.join(timeout=2)
                return subprocess.CompletedProcess(cmd, proc.returncode, ''.join(stdout_lines), ''.join(stderr_lines))
            if time.time() - start > timeout:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, timeout)
            time.sleep(0.5)
    finally:
        with processes_lock:
            if proc in active_processes:
                active_processes.remove(proc)


# =============================================================================
# CSV FUNCTIONS
# =============================================================================

def save_episodes_to_csv(episodes: List[Episode], csv_path: str):
    """Save episode list to CSV file."""
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Episode', 'URL', 'Title', 'Filename', 'Status'])
        for ep in episodes:
            writer.writerow([ep.number, ep.url, ep.title, ep.filename, ep.status])
    print_success(f"Saved {len(episodes)} episodes to {csv_path}")


def load_episodes_from_csv(csv_path: str) -> List[Episode]:
    """Load episode list from CSV file."""
    episodes = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            episodes.append(Episode(
                number=int(row['Episode']),
                url=row['URL'],
                title=row['Title'],
                filename=row['Filename'],
                status=row.get('Status', 'pending')
            ))
    print_success(f"Loaded {len(episodes)} episodes from {csv_path}")
    return episodes


# =============================================================================
# DOWNLOAD WORKER
# =============================================================================

def download_episode(episode: Episode, output_dir: str, audio_type: str, resolution: str, worker_id: int = 0) -> Episode:
    global last_download_time

    # Get thread-specific logger
    logger = get_worker_logger('download', worker_id) if worker_id > 0 else get_main_logger()
    worker_tag = f"W{worker_id}" if worker_id > 0 else ""

    if shutdown_event.is_set():
        episode.status = "cancelled"
        return episode

    # Skip if exists
    base_path = os.path.join(output_dir, episode.filename)
    for ext in ['.mkv', '.mp4']:
        if os.path.exists(base_path + ext):
            logger.info(f"EP{episode.number:02d}: Already exists, skipping")
            episode.video_path = base_path + ext
            episode.status = "skipped"
            return episode

    # Throttle
    with download_throttle_lock:
        elapsed = time.time() - last_download_time
        if elapsed < DOWNLOAD_DELAY:
            time.sleep(DOWNLOAD_DELAY - elapsed)
        last_download_time = time.time()

    try:
        episode.status = "downloading"
        video_path = os.path.join(output_dir, f"{episode.filename}.mp4")
        logger.info(f"EP{episode.number:02d}: Downloading - {episode.title}")

        cmd = [
            'yt-dlp', '-f', f'{audio_type}_{resolution}p',
            '--write-subs', '--sub-lang', SUBTITLE_LANG, '--convert-subs', 'srt',
            '-o', video_path, '--no-warnings', '--retries', '10', '--fragment-retries', '10',
            episode.url
        ]

        # Pass worker tag for yt-dlp output
        yt_prefix = f"{worker_tag}:EP{episode.number:02d}" if worker_tag else f"EP{episode.number:02d}"
        result = run_subprocess(cmd, DOWNLOAD_TIMEOUT, prefix=yt_prefix)

        if result.returncode != 0:
            logger.warning(f"EP{episode.number:02d}: Primary format failed, trying fallback")
            # Fallback
            cmd_fallback = [
                'yt-dlp', '-f', f'bv*[format_id^={audio_type}]+ba/b[format_id^={audio_type}]/b',
                '-S', f'res:{resolution}', '--write-subs', '--sub-lang', SUBTITLE_LANG,
                '--convert-subs', 'srt', '-o', video_path, '--retries', '10', episode.url
            ]
            result = run_subprocess(cmd_fallback, DOWNLOAD_TIMEOUT, prefix=yt_prefix)

        if result.returncode == 0 and os.path.exists(video_path):
            episode.video_path = video_path
            for ext in ['.en.srt', '.srt', '.eng.srt']:
                sub_path = os.path.splitext(video_path)[0] + ext
                if os.path.exists(sub_path):
                    episode.subtitle_path = sub_path
                    break
            episode.status = "downloaded"
            logger.success(f"EP{episode.number:02d}: Downloaded successfully")
        else:
            episode.status = "failed"
            episode.error = result.stderr[:500] if result.stderr else "Failed"
            logger.error(f"EP{episode.number:02d}: Download failed")

    except Exception as e:
        episode.status = "failed"
        episode.error = str(e)
        logger.error(f"EP{episode.number:02d}: {e}")

    return episode


# =============================================================================
# EMBED WORKER
# =============================================================================

def embed_subtitle(episode: Episode, worker_id: int = 0) -> Episode:
    # Get thread-specific logger
    logger = get_worker_logger('embed', worker_id) if worker_id > 0 else get_main_logger()

    if shutdown_event.is_set() or episode.status != "downloaded" or not episode.video_path:
        return episode

    if not episode.subtitle_path or not os.path.exists(episode.subtitle_path):
        logger.info(f"EP{episode.number:02d}: No subtitles to embed, marking complete")
        episode.final_path = episode.video_path
        episode.status = "completed"
        return episode

    try:
        episode.status = "embedding"
        base_path = os.path.splitext(episode.video_path)[0]
        temp_output = f"{base_path}_embedded.mkv"
        final_output = f"{base_path}.mkv"

        logger.info(f"EP{episode.number:02d}: Embedding subtitles...")

        cmd = [
            'ffmpeg', '-y', '-i', episode.video_path, '-i', episode.subtitle_path,
            '-c:v', 'copy', '-c:a', 'copy', '-c:s', 'srt',
            '-map', '0:v:0', '-map', '0:a?', '-map', '1:0',
            '-metadata:s:s:0', 'language=eng', '-disposition:s:0', 'default+forced',
            temp_output
        ]

        result = run_subprocess(cmd, EMBED_TIMEOUT)

        if result.returncode == 0 and os.path.exists(temp_output):
            safe_remove(episode.video_path)
            safe_remove(episode.subtitle_path)
            os.rename(temp_output, final_output)
            episode.final_path = final_output
            episode.status = "completed"
            logger.success(f"EP{episode.number:02d}: Subtitles embedded successfully")
        else:
            episode.status = "embed_failed"
            logger.error(f"EP{episode.number:02d}: Embed failed")

    except Exception as e:
        episode.status = "embed_failed"
        episode.error = str(e)
        logger.error(f"EP{episode.number:02d}: {e}")

    return episode


# =============================================================================
# DOWNLOAD PIPELINE (from episode list)
# =============================================================================

def download_from_episodes(
    episodes: List[Episode],
    output_dir: str,
    audio_type: str,
    resolution: str,
    download_workers: int,
    embed_workers: int
) -> dict:
    """Download and embed videos from a list of episodes."""
    os.makedirs(output_dir, exist_ok=True)

    main_logger = get_main_logger()

    download_queue = Queue()
    embed_queue = Queue()
    stats = {'downloaded': 0, 'embedded': 0, 'failed': 0, 'skipped': 0, 'total': len(episodes)}
    stats_lock = threading.Lock()
    stop_event = threading.Event()

    def log_stats():
        with stats_lock:
            done = stats['downloaded'] + stats['skipped']
            main_logger.info(
                f"Progress: {done}/{stats['total']} downloaded | "
                f"{stats['embedded']} embedded | {stats['failed']} failed"
            )

    for ep in episodes:
        download_queue.put(ep)

    def dl_worker(worker_id: int):
        while not stop_event.is_set():
            try:
                ep = download_queue.get(timeout=1)
            except Empty:
                continue
            result = download_episode(ep, output_dir, audio_type, resolution, worker_id=worker_id)
            with stats_lock:
                if result.status == "downloaded":
                    stats['downloaded'] += 1
                    embed_queue.put(result)
                elif result.status == "skipped":
                    stats['skipped'] += 1
                else:
                    stats['failed'] += 1
            log_stats()
            download_queue.task_done()

    def embed_worker_fn(worker_id: int):
        while not stop_event.is_set():
            try:
                ep = embed_queue.get(timeout=1)
            except Empty:
                if download_queue.empty() and stats['downloaded'] + stats['failed'] + stats['skipped'] >= stats['total']:
                    break
                continue
            result = embed_subtitle(ep, worker_id=worker_id)
            with stats_lock:
                if result.status == "completed":
                    stats['embedded'] += 1
            log_stats()
            embed_queue.task_done()

    threads = []
    for i in range(download_workers):
        t = threading.Thread(target=dl_worker, args=(i + 1,), daemon=True)
        t.start()
        threads.append(t)
    for i in range(embed_workers):
        t = threading.Thread(target=embed_worker_fn, args=(i + 1,), daemon=True)
        t.start()
        threads.append(t)

    try:
        download_queue.join()
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
    except KeyboardInterrupt:
        stop_event.set()

    return stats


# =============================================================================
# FETCH FUNCTION (scrape URLs → CSV)
# =============================================================================

def fetch_anime_to_csv(
    extractor: HianimeExtractor,
    anime: Anime,
    output_dir: str,
    start_ep: int = 1,
    end_ep: int = 9999
) -> tuple:
    """
    Fetch episode URLs and save to CSV.
    Returns: (episodes_list, csv_path)
    """
    episodes = extractor.build_episode_list(anime, start_ep, end_ep, filename_format=FILENAME_FORMAT)
    if not episodes:
        return [], None

    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, f"{anime.name}_episodes.csv")
    json_path = os.path.join(output_dir, f"{anime.name}_metadata.json")

    save_episodes_to_csv(episodes, csv_path)
    extractor.save_to_json(anime, episodes, json_path)

    return episodes, csv_path


# =============================================================================
# STREAMING SCRAPE + DOWNLOAD (parallel)
# =============================================================================

def scrape_and_download_parallel(
    extractor: HianimeExtractor,
    anime: Anime,
    output_dir: str,
    start_ep: int,
    end_ep: int,
    audio_type: str,
    resolution: str,
    download_workers: int,
    embed_workers: int
) -> dict:
    """
    Scrape episode URLs and download IN PARALLEL.
    As soon as an episode URL is found, it's added to the download queue.
    """
    import requests
    from bs4 import BeautifulSoup
    from tools.functions import sanitize_filename

    os.makedirs(output_dir, exist_ok=True)

    main_logger = get_main_logger()

    # Queues
    download_queue = Queue()
    embed_queue = Queue()
    all_episodes = []  # Collect all episodes for CSV
    episodes_lock = threading.Lock()

    stats = {'scraped': 0, 'downloaded': 0, 'embedded': 0, 'failed': 0, 'skipped': 0, 'total': end_ep - start_ep + 1}
    stats_lock = threading.Lock()
    stop_event = threading.Event()
    scrape_done = threading.Event()

    def log_stats():
        with stats_lock:
            main_logger.info(
                f"Scraped: {stats['scraped']}/{stats['total']} | "
                f"Downloaded: {stats['downloaded']} | Embedded: {stats['embedded']} | "
                f"Failed: {stats['failed']}"
            )

    # -------------------------------------------------------------------------
    # SCRAPER THREAD - scrapes URLs via AJAX API and feeds to download queue
    # -------------------------------------------------------------------------
    def scraper_thread():
        import re
        logger = get_scraper_logger()
        base_url = anime.url.split('?')[0]

        # Extract anime ID from URL (e.g., "bleach-thousand-year-blood-war-the-conflict-19322" -> "19322")
        match = re.search(r'-(\d+)$', base_url.rstrip('/'))
        if not match:
            logger.error("Could not extract anime ID from URL")
            scrape_done.set()
            return

        anime_id = match.group(1)
        logger.info(f"Anime ID: {anime_id}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": base_url,
        }

        try:
            # Fetch episodes via AJAX API
            logger.info("Fetching episodes from API...")
            api_url = f"https://hianime.to/ajax/v2/episode/list/{anime_id}"
            response = requests.get(api_url, headers=headers, timeout=30)

            if response.status_code != 200:
                logger.error(f"API returned status {response.status_code}")
                scrape_done.set()
                return

            data = response.json()
            if not data.get('status') or not data.get('html'):
                logger.error("Invalid API response")
                scrape_done.set()
                return

            # Parse the HTML from API response
            soup = BeautifulSoup(data['html'], "html.parser")
            ep_items = soup.find_all("a", attrs={"data-number": True})

            if not ep_items:
                logger.error("No episode links found in API response")
                scrape_done.set()
                return

            # Sort by episode number
            ep_data = []
            for item in ep_items:
                try:
                    ep_num = int(item.get("data-number"))
                    if start_ep <= ep_num <= end_ep:
                        href = item.get("href", "")
                        if href:
                            ep_url = f"https://hianime.to{href}" if href.startswith("/") else href
                            title = item.get("title", "") or f"Episode {ep_num}"
                            ep_data.append((ep_num, ep_url, title.strip()))
                except:
                    continue

            ep_data.sort(key=lambda x: x[0])

            # Update total count
            total_episodes = len(ep_data)
            with stats_lock:
                stats['total'] = total_episodes

            logger.success(f"Found {total_episodes} episodes to process")

            # Feed episodes to download queue one by one
            for ep_num, ep_url, ep_title in ep_data:
                if shutdown_event.is_set():
                    break

                # Use the format_filename method based on config
                # Pass total_episodes so single-episode anime (movies/OVAs) skip numbering
                filename = anime.format_filename(ep_num, ep_title, FILENAME_FORMAT, total_episodes)
                filename = sanitize_filename(filename)
                episode = Episode(
                    number=ep_num,
                    url=ep_url,
                    title=ep_title,
                    filename=filename
                )

                with episodes_lock:
                    all_episodes.append(episode)

                # Add to download queue immediately
                download_queue.put(episode)

                with stats_lock:
                    stats['scraped'] += 1

                logger.success(f"EP{ep_num:02d}: Scraped - {ep_title[:40]}...")
                log_stats()

                # Small delay to not overwhelm
                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Scraper error: {e}")
        finally:
            logger.info("Scraping complete")
            scrape_done.set()

    # -------------------------------------------------------------------------
    # DOWNLOAD WORKERS
    # -------------------------------------------------------------------------
    def dl_worker(worker_id: int):
        while not stop_event.is_set():
            try:
                ep = download_queue.get(timeout=1)
            except Empty:
                # Check if scraping is done and queue is empty
                if scrape_done.is_set() and download_queue.empty():
                    break
                continue

            result = download_episode(ep, output_dir, audio_type, resolution, worker_id=worker_id)

            with stats_lock:
                if result.status == "downloaded":
                    stats['downloaded'] += 1
                    embed_queue.put(result)
                elif result.status == "skipped":
                    stats['skipped'] += 1
                    stats['downloaded'] += 1  # Count as done
                else:
                    stats['failed'] += 1

            log_stats()
            download_queue.task_done()

    # -------------------------------------------------------------------------
    # EMBED WORKERS
    # -------------------------------------------------------------------------
    def embed_worker_fn(worker_id: int):
        while not stop_event.is_set():
            try:
                ep = embed_queue.get(timeout=1)
            except Empty:
                # Check if all downloads are done
                with stats_lock:
                    if scrape_done.is_set() and stats['downloaded'] + stats['failed'] >= stats['scraped']:
                        break
                continue

            result = embed_subtitle(ep, worker_id=worker_id)

            with stats_lock:
                if result.status == "completed":
                    stats['embedded'] += 1

            log_stats()
            embed_queue.task_done()

    # -------------------------------------------------------------------------
    # START ALL THREADS
    # -------------------------------------------------------------------------
    threads = []

    # Start scraper thread
    scraper = threading.Thread(target=scraper_thread, daemon=True)
    scraper.start()
    threads.append(scraper)

    # Start download workers
    for i in range(download_workers):
        t = threading.Thread(target=dl_worker, args=(i + 1,), daemon=True)
        t.start()
        threads.append(t)

    # Start embed workers
    for i in range(embed_workers):
        t = threading.Thread(target=embed_worker_fn, args=(i + 1,), daemon=True)
        t.start()
        threads.append(t)

    # -------------------------------------------------------------------------
    # WAIT FOR COMPLETION
    # -------------------------------------------------------------------------
    try:
        # Wait for scraper to finish
        scraper.join()

        # Wait for download queue to empty
        download_queue.join()

        # Signal stop and wait for embed workers
        stop_event.set()
        for t in threads:
            t.join(timeout=5)

    except KeyboardInterrupt:
        main_logger.warning("Interrupted by user!")
        stop_event.set()

    # Save CSV with all episodes
    csv_path = os.path.join(output_dir, f"{anime.name}_episodes.csv")
    with episodes_lock:
        save_episodes_to_csv(all_episodes, csv_path)
        extractor.save_to_json(anime, all_episodes, os.path.join(output_dir, f"{anime.name}_metadata.json"))

    print_success("All tasks completed!")
    return stats


# =============================================================================
# MAIN
# =============================================================================

def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  HiAnime Downloader{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")

    parser = argparse.ArgumentParser(description="HiAnime Downloader")
    parser.add_argument('-u', '--url', help='Anime URL')
    parser.add_argument('-s', '--search', help='Search anime by name')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT_DIR, help='Output directory')
    parser.add_argument('--from-csv', dest='from_csv', help='Download from existing CSV file')
    parser.add_argument('--fetch-only', action='store_true', help='Only fetch URLs to CSV, no download')
    parser.add_argument('--download-workers', type=int, default=MAX_DOWNLOAD_WORKERS)
    parser.add_argument('--embed-workers', type=int, default=MAX_EMBED_WORKERS)
    parser.add_argument('--resolution', default=RESOLUTION)
    parser.add_argument('--audio-type', choices=['sub', 'dub'], default='sub')
    parser.add_argument('--season', type=int, default=DEFAULT_SEASON if DEFAULT_SEASON > 0 else 1)
    args = parser.parse_args()

    # ==========================================================================
    # MODE 1: Download from existing CSV
    # ==========================================================================
    if args.from_csv:
        print_info(f"Loading episodes from: {args.from_csv}")
        episodes = load_episodes_from_csv(args.from_csv)

        if not episodes:
            print_error("No episodes in CSV")
            return

        # Determine output dir from CSV location
        output_dir = os.path.dirname(args.from_csv) or args.output

        print(f"\n{Fore.YELLOW}Downloading {len(episodes)} episodes{Style.RESET_ALL}")
        print(f"  Output: {output_dir}")
        print(f"  Audio: {args.audio_type}")
        print(f"  Resolution: {args.resolution}p")

        if not get_confirmation("\nStart download? (y/n): "):
            return

        stats = download_from_episodes(
            episodes, output_dir, args.audio_type, args.resolution,
            args.download_workers, args.embed_workers
        )

        print(f"\n{Fore.GREEN}Done! Downloaded: {stats['downloaded']}, Embedded: {stats['embedded']}, Failed: {stats['failed']}{Style.RESET_ALL}")
        return

    # ==========================================================================
    # MODE 2: Fetch + Download (or Fetch only)
    # ==========================================================================
    extractor = HianimeExtractor({'subtitle_lang': SUBTITLE_LANG, 'no_subtitles': NO_SUBTITLES})

    def process_single_anime(anime_url: str, is_queue: bool = False, queue_index: int = 0, queue_total: int = 0):
        """Process a single anime URL. Returns True if successful."""
        anime = extractor.get_anime_from_url(anime_url)

        if not anime:
            print_error(f"Failed to get anime info from: {anime_url}")
            return False

        # Show anime info
        if is_queue:
            print(f"\n{Fore.CYAN}[{queue_index}/{queue_total}]{Style.RESET_ALL} {Fore.GREEN}Anime: {anime.name}{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.GREEN}Anime: {anime.name}{Style.RESET_ALL}")
        print(f"Sub: {anime.sub_episodes} | Dub: {anime.dub_episodes}")

        # Select sub/dub - use AUDIO_TYPE from config if available
        if AUDIO_TYPE in ('sub', 'dub'):
            if AUDIO_TYPE == 'sub' and anime.sub_episodes > 0:
                anime.download_type = 'sub'
                print_info(f"Using audio type from config: sub")
            elif AUDIO_TYPE == 'dub' and anime.dub_episodes > 0:
                anime.download_type = 'dub'
                print_info(f"Using audio type from config: dub")
            elif anime.sub_episodes > 0:
                anime.download_type = 'sub'
                print_warning(f"Requested '{AUDIO_TYPE}' not available, falling back to sub")
            elif anime.dub_episodes > 0:
                anime.download_type = 'dub'
                print_warning(f"Requested '{AUDIO_TYPE}' not available, falling back to dub")
            else:
                print_error("No episodes available")
                return False
        else:
            anime.download_type = extractor.select_download_type(anime)

        anime.season_number = args.season

        # Get episode range
        max_eps = anime.sub_episodes if anime.download_type == 'sub' else anime.dub_episodes
        if DOWNLOAD_ALL:
            start_ep, end_ep = 1, max_eps or 9999
        else:
            start_ep = get_int_in_range("Start episode: ", 1, max_eps or 9999)
            end_ep = get_int_in_range("End episode: ", start_ep, max_eps or 9999)

        # Create output dir
        output_dir = os.path.join(args.output, f"{anime.name} ({anime.download_type.title()})")

        # If fetch-only mode, just scrape and save to CSV
        if args.fetch_only:
            print_info("Fetching episode URLs (fetch-only mode)...")
            episodes, csv_path = fetch_anime_to_csv(extractor, anime, output_dir, start_ep, end_ep)
            if episodes:
                print_success(f"Fetched {len(episodes)} episodes!")
                print_success(f"CSV saved: {csv_path}")
            else:
                print_error("Failed to fetch episodes")
            return True

        # Show summary
        print(f"\n{Fore.YELLOW}Summary:{Style.RESET_ALL}")
        print(f"  Anime: {anime.name}")
        print(f"  Episodes: {start_ep} - {end_ep}")
        print(f"  Type: {anime.download_type}")
        print(f"  Resolution: {args.resolution}p")
        print(f"  Mode: Parallel scrape + download")

        # Only prompt if not in queue mode (queue already confirmed at start)
        if not is_queue and not get_confirmation("\nStart? (y/n): "):
            print_info("Cancelled.")
            return False

        start_time = time.time()

        # Run parallel scrape + download
        stats = scrape_and_download_parallel(
            extractor, anime, output_dir,
            start_ep, end_ep,
            anime.download_type, args.resolution,
            args.download_workers, args.embed_workers
        )

        elapsed = time.time() - start_time

        print(f"\n{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.GREEN}  Complete!{Style.RESET_ALL}")
        print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
        print(f"Scraped: {stats.get('scraped', stats.get('total', 0))}")
        print(f"Downloaded: {stats['downloaded']}")
        print(f"Embedded: {stats['embedded']}")
        print(f"Skipped: {stats.get('skipped', 0)}")
        print(f"Failed: {stats['failed']}")
        print(f"Time: {elapsed/60:.1f} min")
        print(f"Output: {output_dir}")

        return True

    try:
        # Determine which anime to process
        if args.search:
            anime = extractor.select_anime_interactive(args.search)
            if anime:
                process_single_anime(anime.url)
        elif args.url:
            process_single_anime(args.url)
        elif ANIME_URL_QUEUE:
            # Queue mode - process all URLs in sequence
            queue_total = len(ANIME_URL_QUEUE)
            print_info(f"Found {queue_total} URLs in queue")
            for i, url in enumerate(ANIME_URL_QUEUE, 1):
                print(f"  {i}. {url}")

            if not get_confirmation(f"\nProcess all {queue_total} URLs? (y/n): "):
                print_info("Cancelled.")
                return

            # Process each URL in the queue
            success_count = 0
            fail_count = 0
            for i, url in enumerate(ANIME_URL_QUEUE, 1):
                if shutdown_event.is_set():
                    print_warning("Shutdown requested, stopping queue processing")
                    break

                print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
                print(f"{Fore.CYAN}  Processing queue item {i}/{queue_total}{Style.RESET_ALL}")
                print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
                print(f"URL: {url}")

                try:
                    if process_single_anime(url, is_queue=True, queue_index=i, queue_total=queue_total):
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as e:
                    print_error(f"Error processing {url}: {e}")
                    fail_count += 1

                # Small delay between anime in queue
                if i < queue_total and not shutdown_event.is_set():
                    print_info("Moving to next anime in 3 seconds...")
                    time.sleep(3)

            # Queue summary
            print(f"\n{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}  Queue Complete!{Style.RESET_ALL}")
            print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
            print(f"Total: {queue_total}")
            print(f"Success: {success_count}")
            print(f"Failed: {fail_count}")
        else:
            # Interactive mode
            print(f"{Fore.CYAN}1. Search anime{Style.RESET_ALL}")
            print(f"{Fore.CYAN}2. Enter URL{Style.RESET_ALL}")
            choice = get_int_in_range("\nSelect: ", 1, 2)
            if choice == 1:
                anime = extractor.select_anime_interactive()
                if anime:
                    process_single_anime(anime.url)
            else:
                url = input("Enter URL: ").strip()
                if url:
                    process_single_anime(url)

    finally:
        extractor.cleanup()


if __name__ == '__main__':
    main()
