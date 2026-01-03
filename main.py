"""
Parallel Anime Downloader for Hianime.to

Simple workflow:
1. Fetch episode links from hianime.to (just the URLs with ?ep=XXXXX)
2. Save to CSV with proper titles
3. Download using yt-dlp (with hianime plugin) in parallel
4. Embed subtitles with FFmpeg in parallel

Usage:
    python main.py
    python main.py -u "https://hianime.to/watch/bleach-806?ep=13793"
"""

import os
import sys
import csv
import time
import signal
import subprocess
import threading
import argparse
from queue import Queue, Empty
from typing import List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from colorama import init, Fore, Style
from dotenv import load_dotenv

init()

# Load .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)

# Configuration from environment variables
MAX_DOWNLOAD_WORKERS = int(os.getenv('DOWNLOAD_WORKERS', 6))
MAX_EMBED_WORKERS = int(os.getenv('EMBED_WORKERS', 4))
DEFAULT_OUTPUT_DIR = os.getenv('OUTPUT_DIR', 'output')
RESOLUTION = os.getenv('RESOLUTION', '720')
SUBTITLE_LANG = os.getenv('SUBTITLE_LANG', 'en')
DOWNLOAD_TIMEOUT = int(os.getenv('DOWNLOAD_TIMEOUT', 3600))
EMBED_TIMEOUT = int(os.getenv('EMBED_TIMEOUT', 600))
DEFAULT_ANIME_URL = os.getenv('ANIME_URL', '')
DOWNLOAD_DELAY = float(os.getenv('DOWNLOAD_DELAY', 2))  # Delay between starting downloads (rate limit protection)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.11 (KHTML, like Gecko) Chrome/23.0.1271.64 Safari/537.11",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
    "Connection": "keep-alive",
}

# Global state for graceful shutdown
shutdown_event = threading.Event()
active_processes: List[subprocess.Popen] = []
processes_lock = threading.Lock()
download_throttle_lock = threading.Lock()
last_download_time = 0.0


@dataclass
class Episode:
    number: int
    url: str
    title: str
    filename: str
    video_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    final_path: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None


def print_info(msg): print(f"{Fore.CYAN}[INFO] {msg}{Style.RESET_ALL}")
def print_success(msg): print(f"{Fore.GREEN}[SUCCESS] {msg}{Style.RESET_ALL}")
def print_error(msg): print(f"{Fore.RED}[ERROR] {msg}{Style.RESET_ALL}")
def print_warning(msg): print(f"{Fore.YELLOW}[WARNING] {msg}{Style.RESET_ALL}")


def signal_handler(signum, frame):
    """Handle Ctrl+C by setting shutdown event and killing all processes."""
    print_warning("\n\nReceived interrupt signal. Shutting down...")
    shutdown_event.set()
    with processes_lock:
        for proc in active_processes:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except:
                try:
                    proc.kill()
                except:
                    pass
        active_processes.clear()
    print_warning("All workers stopped.")
    sys.exit(1)


def run_subprocess(cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
    """Run subprocess with tracking for graceful shutdown."""
    if shutdown_event.is_set():
        raise InterruptedError("Shutdown requested")

    # On Windows, use CREATE_NEW_PROCESS_GROUP for proper termination
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == 'win32' else 0
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=creationflags
    )
    with processes_lock:
        active_processes.append(proc)
    try:
        # Poll with short intervals to check shutdown_event
        start_time = time.time()

        while True:
            # Check for shutdown
            if shutdown_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except:
                    proc.kill()
                raise InterruptedError("Shutdown requested")

            # Check if process finished
            retcode = proc.poll()
            if retcode is not None:
                # Process finished, read remaining output
                stdout, stderr = proc.communicate()
                return subprocess.CompletedProcess(cmd, retcode, stdout, stderr)

            # Check timeout
            if time.time() - start_time > timeout:
                proc.kill()
                proc.wait()
                raise subprocess.TimeoutExpired(cmd, timeout)

            # Short sleep to avoid busy-waiting
            time.sleep(0.5)

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise
    finally:
        with processes_lock:
            if proc in active_processes:
                active_processes.remove(proc)


def sanitize_filename(name: str) -> str:
    """Remove invalid filename characters."""
    invalid = '<>:"/\\|?*'
    for char in invalid:
        name = name.replace(char, '_')
    return name.strip()


def get_int_input(prompt: str, min_val: int = 1, max_val: int = 9999) -> int:
    """Get integer input from user."""
    while True:
        try:
            val = int(input(prompt))
            if min_val <= val <= max_val:
                return val
            print(f"Please enter a number between {min_val} and {max_val}")
        except ValueError:
            print("Please enter a valid number")


def get_confirmation(prompt: str) -> bool:
    """Get yes/no confirmation."""
    while True:
        resp = input(prompt).strip().lower()
        if resp in ('y', 'yes'):
            return True
        if resp in ('n', 'no'):
            return False
        print("Please enter 'y' or 'n'")


def fetch_anime_info(url: str) -> Tuple[str, int, str]:
    """
    Fetch anime info from URL.
    Returns: (anime_name, total_episodes, base_watch_url)
    """
    print_info(f"Fetching anime info from {url}")

    # Handle both watch and info URLs
    if '/watch/' in url:
        # Extract base URL without episode param
        base_url = url.split('?')[0]
        # Convert to info page to get details
        info_url = base_url.replace('/watch/', '/')
    else:
        info_url = url
        base_url = url.replace('/', '/watch/', 1) if '/watch/' not in url else url

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')

        # Get anime name
        title_elem = soup.find('h2', class_='film-name')
        if not title_elem:
            title_elem = soup.find('h2', class_='dynamic-name')
        anime_name = title_elem.text.strip() if title_elem else "Unknown Anime"

        # Get episode count from tick items
        sub_eps = 0
        tick_sub = soup.find('div', class_='tick-item tick-sub')
        if tick_sub:
            try:
                sub_eps = int(tick_sub.text.strip())
            except:
                pass

        # Also try to get from episode list
        ep_items = soup.find_all('a', attrs={'data-number': True})
        if ep_items:
            max_ep = max(int(item.get('data-number', 0)) for item in ep_items)
            sub_eps = max(sub_eps, max_ep)

        return anime_name, sub_eps, base_url.split('?')[0]

    except Exception as e:
        print_error(f"Failed to fetch anime info: {e}")
        return "Unknown Anime", 0, url.split('?')[0]


def fetch_episode_links(base_url: str, start_ep: int, end_ep: int, first_ep_id: int) -> List[Tuple[int, str]]:
    """
    Generate episode URLs based on the pattern.
    The ep ID increments sequentially from the first episode.

    Returns: List of (episode_number, url) tuples
    """
    episodes = []

    for i, ep_num in enumerate(range(start_ep, end_ep + 1)):
        ep_id = first_ep_id + i
        url = f"{base_url}?ep={ep_id}"
        episodes.append((ep_num, url))

    return episodes


def fetch_episode_links_from_page(url: str, start_ep: int, end_ep: int) -> List[Tuple[int, str, str]]:
    """
    Fetch episode links by scraping the page.
    Returns: List of (episode_number, url, title) tuples
    """
    print_info("Fetching episode links from page...")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(response.text, 'html.parser')

        episodes = []
        ep_items = soup.find_all('a', attrs={'data-number': True})

        for item in ep_items:
            try:
                ep_num = int(item.get('data-number', 0))
                if start_ep <= ep_num <= end_ep:
                    href = item.get('href', '')
                    ep_url = f"https://hianime.to{href}" if href.startswith('/') else href
                    title = item.get('title', f'Episode {ep_num}')
                    episodes.append((ep_num, ep_url, title))
            except:
                continue

        episodes.sort(key=lambda x: x[0])
        return episodes

    except Exception as e:
        print_error(f"Failed to fetch episodes: {e}")
        return []


def save_to_csv(episodes: List[Episode], csv_path: str):
    """Save episode list to CSV."""
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Episode', 'URL', 'Title', 'Filename', 'Status'])
        for ep in episodes:
            writer.writerow([ep.number, ep.url, ep.title, ep.filename, ep.status])
    print_success(f"Saved episode list to {csv_path}")


def download_episode(episode: Episode, output_dir: str) -> Episode:
    """Download a single episode using yt-dlp."""
    global last_download_time

    if shutdown_event.is_set():
        episode.status = "cancelled"
        return episode

    # Check if episode already exists (skip if found)
    base_path = os.path.join(output_dir, episode.filename)
    for ext in ['.mkv', '.mp4']:
        existing_file = base_path + ext
        if os.path.exists(existing_file):
            print_info(f"EP{episode.number:02d}: Already exists, skipping")
            episode.video_path = existing_file
            episode.final_path = existing_file
            episode.status = "skipped"
            return episode

    # Throttle downloads to avoid rate limiting
    with download_throttle_lock:
        elapsed = time.time() - last_download_time
        if elapsed < DOWNLOAD_DELAY:
            time.sleep(DOWNLOAD_DELAY - elapsed)
        last_download_time = time.time()

    try:
        episode.status = "downloading"
        video_path = os.path.join(output_dir, f"{episode.filename}.mp4")

        print_info(f"Downloading EP{episode.number:02d}: {episode.title}")

        cmd = [
            'yt-dlp',
            '-S', f'res:{RESOLUTION}',
            '-f', 'b[format_id*=sub]',
            '--write-subs',
            '--sub-lang', SUBTITLE_LANG,
            '--convert-subs', 'srt',
            '-o', video_path,
            '--no-warnings',
            '--retries', '10',
            '--fragment-retries', '10',
            episode.url
        ]

        result = run_subprocess(cmd, DOWNLOAD_TIMEOUT)

        if result.returncode != 0:
            # Try fallback without format filter
            print_warning(f"EP{episode.number:02d}: Retrying without format filter...")
            cmd_fallback = [
                'yt-dlp',
                '-S', f'res:{RESOLUTION}',
                '--write-subs',
                '--sub-lang', SUBTITLE_LANG,
                '--convert-subs', 'srt',
                '-o', video_path,
                '--no-warnings',
                '--retries', '10',
                episode.url
            ]
            result = run_subprocess(cmd_fallback, DOWNLOAD_TIMEOUT)

        if result.returncode == 0 and os.path.exists(video_path):
            episode.video_path = video_path

            # Find subtitle file (yt-dlp may add language suffix)
            base_name = os.path.splitext(video_path)[0]
            for ext in ['.en.srt', '.srt', '.eng.srt']:
                sub_path = base_name + ext
                if os.path.exists(sub_path):
                    episode.subtitle_path = sub_path
                    break

            episode.status = "downloaded"
            print_success(f"EP{episode.number:02d}: Downloaded")
        else:
            episode.status = "failed"
            episode.error = result.stderr[:500] if result.stderr else "Download failed"
            print_error(f"EP{episode.number:02d}: Download failed")

    except InterruptedError:
        episode.status = "cancelled"
    except subprocess.TimeoutExpired:
        episode.status = "failed"
        episode.error = "Download timed out"
        print_error(f"EP{episode.number:02d}: Timed out")
    except Exception as e:
        episode.status = "failed"
        episode.error = str(e)
        print_error(f"EP{episode.number:02d}: {e}")

    return episode


def embed_subtitle(episode: Episode) -> Episode:
    """
    Embed subtitle into video using FFmpeg.
    Uses MKV format with default+forced disposition for auto-enabled subtitles.
    """
    if shutdown_event.is_set():
        episode.status = "cancelled"
        return episode
    if episode.status != "downloaded" or not episode.video_path:
        return episode

    if not episode.subtitle_path or not os.path.exists(episode.subtitle_path):
        print_warning(f"EP{episode.number:02d}: No subtitle to embed")
        episode.final_path = episode.video_path
        episode.status = "completed"
        return episode

    try:
        episode.status = "embedding"
        print_info(f"Embedding subs for EP{episode.number:02d}")

        base_path = os.path.splitext(episode.video_path)[0]
        
        # Use MKV - better subtitle support and default flags work more reliably
        temp_output = f"{base_path}_embedded.mkv"
        final_output = f"{base_path}.mkv"

        # FFmpeg with default+forced disposition - subs auto-enable in most players
        cmd = [
            'ffmpeg', '-y',
            '-i', episode.video_path,
            '-i', episode.subtitle_path,
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-c:s', 'srt',
            '-map', '0:v:0',
            '-map', '0:a?',
            '-map', '1:0',
            '-metadata:s:s:0', 'language=eng',
            '-metadata:s:s:0', 'title=English',
            '-disposition:s:0', 'default+forced',
            temp_output
        ]

        result = run_subprocess(cmd, EMBED_TIMEOUT)

        if result.returncode == 0 and os.path.exists(temp_output):
            os.remove(episode.video_path)
            os.remove(episode.subtitle_path)
            os.rename(temp_output, final_output)
            episode.final_path = final_output
            episode.status = "completed"
            print_success(f"EP{episode.number:02d}: Subtitles embedded")
        else:
            # Try MP4 as fallback
            print_warning(f"EP{episode.number:02d}: MKV failed, trying MP4...")
            temp_output_mp4 = f"{base_path}_embedded.mp4"

            cmd_mp4 = [
                'ffmpeg', '-y',
                '-i', episode.video_path,
                '-i', episode.subtitle_path,
                '-c:v', 'copy',
                '-c:a', 'copy',
                '-c:s', 'mov_text',
                '-map', '0:v:0',
                '-map', '0:a?',
                '-map', '1:0',
                '-metadata:s:s:0', 'language=eng',
                '-disposition:s:0', 'default+forced',
                temp_output_mp4
            ]

            result = run_subprocess(cmd_mp4, EMBED_TIMEOUT)

            if result.returncode == 0 and os.path.exists(temp_output_mp4):
                os.remove(episode.video_path)
                os.remove(episode.subtitle_path)
                os.rename(temp_output_mp4, episode.video_path)
                episode.final_path = episode.video_path
                episode.status = "completed"
                print_success(f"EP{episode.number:02d}: Subtitles embedded (MP4)")
            else:
                episode.status = "embed_failed"
                episode.error = "FFmpeg failed"
                print_error(f"EP{episode.number:02d}: Embed failed")

    except InterruptedError:
        episode.status = "cancelled"
    except Exception as e:
        episode.status = "embed_failed"
        episode.error = str(e)
        print_error(f"EP{episode.number:02d}: Embed error: {e}")

    return episode


def run_pipeline(episodes: List[Episode], output_dir: str, download_workers: int, embed_workers: int):
    """
    Run the download and embed pipeline in parallel.
    Downloads and embedding happen concurrently.
    """
    os.makedirs(output_dir, exist_ok=True)

    download_queue = Queue()
    embed_queue = Queue()

    # Stats
    stats = {'downloaded': 0, 'embedded': 0, 'failed': 0, 'skipped': 0, 'total': len(episodes)}
    stats_lock = threading.Lock()

    def print_stats():
        with stats_lock:
            # Skipped episodes count as "done" for progress purposes
            done = stats['downloaded'] + stats['skipped']
            print(f"\n{Fore.CYAN}Progress: Downloaded {done}/{stats['total']} | "
                  f"Embedded {stats['embedded']}/{stats['total']} | Skipped {stats['skipped']} | Failed {stats['failed']}{Style.RESET_ALL}\n")

    # Add all episodes to download queue
    for ep in episodes:
        download_queue.put(ep)

    stop_event = threading.Event()

    def download_worker():
        while not stop_event.is_set():
            try:
                ep = download_queue.get(timeout=1)
            except Empty:
                continue

            result = download_episode(ep, output_dir)

            with stats_lock:
                if result.status == "downloaded":
                    stats['downloaded'] += 1
                    embed_queue.put(result)
                elif result.status == "skipped":
                    stats['skipped'] += 1
                else:
                    stats['failed'] += 1

            print_stats()
            download_queue.task_done()

    def embed_worker():
        while not stop_event.is_set():
            try:
                ep = embed_queue.get(timeout=1)
            except Empty:
                if download_queue.empty() and stats['downloaded'] + stats['failed'] + stats['skipped'] >= stats['total']:
                    break
                continue

            result = embed_subtitle(ep)

            with stats_lock:
                if result.status == "completed":
                    stats['embedded'] += 1
                else:
                    stats['failed'] += 1

            print_stats()
            embed_queue.task_done()

    # Start workers
    download_threads = []
    embed_threads = []

    for i in range(download_workers):
        t = threading.Thread(target=download_worker, daemon=True)
        t.start()
        download_threads.append(t)

    for i in range(embed_workers):
        t = threading.Thread(target=embed_worker, daemon=True)
        t.start()
        embed_threads.append(t)

    try:
        # Wait for downloads to complete
        download_queue.join()
        print_info("All downloads complete!")

        # Wait for embeds to complete
        stop_event.set()
        for t in embed_threads:
            t.join(timeout=5)

        print_info("All embedding complete!")

    except KeyboardInterrupt:
        print_warning("\nInterrupted! Stopping...")
        stop_event.set()

    return stats


def main():
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  Parallel Anime Downloader for Hianime.to{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")

    parser = argparse.ArgumentParser(description="Parallel Anime Downloader")
    parser.add_argument('-u', '--url', help='Anime URL (with first episode)')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT_DIR, help='Output directory')
    parser.add_argument('--download-workers', type=int, default=MAX_DOWNLOAD_WORKERS)
    parser.add_argument('--embed-workers', type=int, default=MAX_EMBED_WORKERS)
    parser.add_argument('--csv-only', action='store_true', help='Only generate CSV, no download')
    args = parser.parse_args()

    # Get URL (priority: CLI arg > env var > user input)
    if args.url:
        url = args.url
    elif DEFAULT_ANIME_URL:
        url = DEFAULT_ANIME_URL
        print_info(f"Using URL from .env: {url}")
    else:
        url = input("Enter anime URL (e.g., https://hianime.to/watch/bleach-806?ep=13793): ").strip()

    if not url:
        print_error("No URL provided")
        sys.exit(1)

    # Parse the URL to get first episode ID
    if '?ep=' in url:
        base_url = url.split('?ep=')[0]
        first_ep_id = int(url.split('?ep=')[1].split('&')[0])
    else:
        print_error("URL must include ?ep= parameter for the first episode")
        print_info("Example: https://hianime.to/watch/bleach-806?ep=13793")
        sys.exit(1)

    # Fetch anime info
    anime_name, total_eps, _ = fetch_anime_info(url)
    anime_name = sanitize_filename(anime_name)

    print(f"\n{Fore.GREEN}Anime: {anime_name}{Style.RESET_ALL}")
    print(f"Total Episodes: {total_eps}")
    print(f"First Episode ID: {first_ep_id}")

    # Get episode range
    print()
    start_ep = get_int_input("Start episode number: ", 1, max(total_eps, 9999))
    end_ep = get_int_input("End episode number: ", start_ep, max(total_eps, 9999))

    num_episodes = end_ep - start_ep + 1
    print(f"\nWill download {num_episodes} episodes (EP{start_ep:02d} - EP{end_ep:02d})")

    # Generate episode list
    episodes = []
    for i, ep_num in enumerate(range(start_ep, end_ep + 1)):
        ep_id = first_ep_id + (ep_num - start_ep)  # Adjust based on starting episode
        ep_url = f"{base_url}?ep={ep_id}"
        filename = f"{anime_name} - EP{ep_num:02d}"

        episodes.append(Episode(
            number=ep_num,
            url=ep_url,
            title=f"Episode {ep_num}",
            filename=filename
        ))

    # Create output directory
    output_dir = os.path.join(args.output, anime_name)
    os.makedirs(output_dir, exist_ok=True)

    # Save CSV
    csv_path = os.path.join(output_dir, f"{anime_name}_episodes.csv")
    save_to_csv(episodes, csv_path)

    if args.csv_only:
        print_success("CSV generated. Exiting (--csv-only mode)")
        sys.exit(0)

    # Confirm
    print(f"\n{Fore.YELLOW}Summary:{Style.RESET_ALL}")
    print(f"  Episodes: {num_episodes}")
    print(f"  Output: {output_dir}")
    print(f"  Download workers: {args.download_workers}")
    print(f"  Embed workers: {args.embed_workers}")
    print()

    if not get_confirmation("Start download? (y/n): "):
        print_info("Cancelled")
        sys.exit(0)

    # Run pipeline
    start_time = time.time()

    stats = run_pipeline(
        episodes,
        output_dir,
        args.download_workers,
        args.embed_workers
    )

    elapsed = time.time() - start_time

    # Final summary
    print(f"\n{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}  Download Complete!{Style.RESET_ALL}")
    print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
    print(f"\nDownloaded: {stats['downloaded']}/{stats['total']}")
    print(f"Embedded: {stats['embedded']}/{stats['total']}")
    print(f"Skipped: {stats['skipped']}")
    print(f"Failed: {stats['failed']}")
    print(f"Time: {elapsed/60:.1f} minutes")
    print(f"\nFiles saved to: {output_dir}")

    # Update CSV with final status
    save_to_csv(episodes, csv_path)


if __name__ == '__main__':
    main()
