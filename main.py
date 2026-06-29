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
from typing import List, Optional

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
    EMBED_CHAPTERS,
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
from extractors import KickAssAnimeExtractor
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


shutdown_event = threading.Event()
active_processes: List[subprocess.Popen] = []
processes_lock = threading.Lock()
download_throttle_lock = threading.Lock()
last_download_time = 0.0
print_lock = threading.Lock()


def is_single_episode_anime(extractor: KickAssAnimeExtractor, url: str) -> tuple:
    anime = extractor.get_anime_from_url(url)
    if not anime:
        return None, None

    max_eps = max(anime.sub_episodes, anime.dub_episodes)
    is_single = max_eps <= 1
    return is_single, anime

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


def save_episodes_to_csv(episodes: List[Episode], csv_path: str):
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Episode', 'URL', 'Title', 'Filename', 'Status'])
        for ep in episodes:
            writer.writerow([ep.number, ep.url, ep.title, ep.filename, ep.status])
    print_success(f"Saved {len(episodes)} episodes to {csv_path}")


def load_episodes_from_csv(csv_path: str) -> List[Episode]:
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


def download_episode(episode: Episode, output_dir: str, audio_type: str, resolution: str, worker_id: int = 0, extractor: Optional[KickAssAnimeExtractor] = None) -> Episode:
    global last_download_time

    logger = get_worker_logger('download', worker_id) if worker_id > 0 else get_main_logger()
    worker_tag = f"W{worker_id}" if worker_id > 0 else ""

    if shutdown_event.is_set():
        episode.status = "cancelled"
        return episode

    base_path = os.path.join(output_dir, episode.filename)
    for ext in ['.mkv', '.mp4']:
        if os.path.exists(base_path + ext):
            logger.info(f"EP{episode.number:02d}: Already exists, skipping")
            episode.video_path = base_path + ext
            episode.status = "skipped"
            return episode

    with download_throttle_lock:
        elapsed = time.time() - last_download_time
        if elapsed < DOWNLOAD_DELAY:
            time.sleep(DOWNLOAD_DELAY - elapsed)
        last_download_time = time.time()

    # Ensure episode has output_dir set for subtitle extraction
    episode.output_dir = output_dir

    # Resolve media URLs
    if not episode.m3u8_url:
        local_extractor = extractor or KickAssAnimeExtractor({'subtitle_lang': SUBTITLE_LANG, 'no_subtitles': NO_SUBTITLES})
        media_info = local_extractor.resolve_media(episode, audio_type, resolution)
        if media_info:
            episode.m3u8_url = media_info.get("m3u8")
            episode.subtitle_path = media_info.get("subtitle_path")
            episode.headers = media_info.get("headers")

    try:
        episode.status = "downloading"
        video_path = os.path.join(output_dir, f"{episode.filename}.mp4")
        logger.info(f"EP{episode.number:02d}: Downloading - {episode.title}")

        if episode.m3u8_url:
            # Map audio type to language codes used in m3u8
            lang_code = "jpn" if audio_type == "sub" else "eng"
            format_filter = f"bestvideo[height<={resolution}]+bestaudio[language={lang_code}]/bestvideo[height<={resolution}]+bestaudio/best[height<={resolution}]/best"
            
            cmd = [
                'yt-dlp', '-f', format_filter,
                '-o', video_path, '--no-warnings', '--retries', '10', '--fragment-retries', '10',
                '--socket-timeout', '30'
            ]
            if episode.headers:
                for k, v in episode.headers.items():
                    cmd.extend(['--add-header', f"{k}:{v}"])
            cmd.append(episode.m3u8_url)
        else:
            # Fallback to original Hianime logic if m3u8 was not resolved
            cmd = [
                'yt-dlp', '-f', f'{audio_type}_{resolution}p',
                '--write-subs', '--sub-lang', SUBTITLE_LANG, '--convert-subs', 'srt',
                '-o', video_path, '--no-warnings', '--retries', '10', '--fragment-retries', '10',
                '--socket-timeout', '30', episode.url
            ]

        yt_prefix = f"{worker_tag}:EP{episode.number:02d}" if worker_tag else f"EP{episode.number:02d}"
        result = run_subprocess(cmd, DOWNLOAD_TIMEOUT, prefix=yt_prefix)

        if result.returncode != 0 and episode.m3u8_url:
            logger.warning(f"EP{episode.number:02d}: Primary format failed, trying fallback")
            cmd_fallback = [
                'yt-dlp', '-f', f'bestvideo[height<={resolution}]+bestaudio/best[height<={resolution}]/best',
                '-o', video_path, '--retries', '10', '--socket-timeout', '30', episode.m3u8_url
            ]
            if episode.headers:
                for k, v in episode.headers.items():
                    cmd_fallback.extend(['--add-header', f"{k}:{v}"])
            result = run_subprocess(cmd_fallback, DOWNLOAD_TIMEOUT, prefix=yt_prefix)


        if result.returncode == 0 and os.path.exists(video_path):
            episode.video_path = video_path
            # If subtitles were not downloaded in Python, check for yt-dlp downloaded subs
            if not episode.subtitle_path:
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


def fetch_mal_id(anime_name: str) -> Optional[int]:
    import requests
    # Search Jikan API for the anime
    url = "https://api.jikan.moe/v4/anime"
    try:
        clean_name = re.sub(r'[\(\[\{\}\]\)]', '', anime_name).strip()
        r = requests.get(url, params={"q": clean_name, "limit": 1}, timeout=10)
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                mal_id = data[0].get("mal_id")
                return mal_id
    except Exception:
        pass
    return None


def generate_chapters_metadata(episode: Episode, video_path: str) -> Optional[str]:
    if not EMBED_CHAPTERS:
        return None
    mal_id = getattr(episode, 'mal_id', None)
    if not mal_id:

        return None
        
    url = f"https://api.aniskip.com/v1/skip-times/{mal_id}/{episode.number}"
    params = {"types[]": ["op", "ed"]}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        if not data.get("found"):
            return None
            
        op = None
        ed = None
        for res in data.get("results", []):
            skip_type = res.get("skip_type")
            interval = res.get("interval", {})
            start = interval.get("start_time")
            end = interval.get("end_time")
            if start is not None and end is not None:
                if skip_type == "op":
                    op = (start, end)
                elif skip_type == "ed":
                    ed = (start, end)
                    
        if op is None and ed is None:
            return None
            
        duration = 0.0
        ffprobe_cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', video_path
        ]
        try:
            res = subprocess.run(ffprobe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            probe_data = json.loads(res.stdout)
            duration = float(probe_data.get('format', {}).get('duration', 0.0))
        except Exception:
            for res in data.get("results", []):
                if res.get("episode_length"):
                    duration = float(res.get("episode_length"))
                    break
                    
        if duration <= 0.0:
            return None
            
        chapters = []
        events = []
        if op and op[1] > op[0]:
            events.append((op[0], op[1], "Opening"))
        if ed and ed[1] > ed[0]:
            events.append((ed[0], ed[1], "Ending"))
            
        events.sort(key=lambda x: x[0])
        current_time = 0.0
        part_idx = 1
        
        for start, end, label in events:
            if start > current_time:
                gap_label = "Prologue" if current_time == 0.0 else (f"Episode Part {part_idx}" if part_idx > 1 else "Episode")
                if gap_label.startswith("Episode Part"):
                    part_idx += 1
                chapters.append({"start": current_time, "end": start, "title": gap_label})
            chapters.append({"start": start, "end": end, "title": label})
            current_time = end
            
        if duration > current_time:
            gap_label = "Epilogue" if current_time > 0.0 else "Episode"
            chapters.append({"start": current_time, "end": duration, "title": gap_label})
            
        metadata_filepath = os.path.splitext(video_path)[0] + "_metadata.txt"
        with open(metadata_filepath, "w", encoding="utf-8") as f:
            f.write(";FFMETADATA1\n")
            f.write(f"title={episode.filename}\n\n")
            for ch in chapters:
                start_ms = int(ch["start"] * 1000)
                end_ms = int(ch["end"] * 1000)
                f.write("[CHAPTER]\n")
                f.write("TIMEBASE=1/1000\n")
                f.write(f"START={start_ms}\n")
                f.write(f"END={end_ms}\n")
                f.write(f"title={ch['title']}\n\n")
                
        return metadata_filepath
    except Exception:
        return None


def embed_subtitle(episode: Episode, worker_id: int = 0) -> Episode:
    logger = get_worker_logger('embed', worker_id) if worker_id > 0 else get_main_logger()

    if shutdown_event.is_set() or episode.status != "downloaded" or not episode.video_path:
        return episode

    has_subs = episode.subtitle_path and os.path.exists(episode.subtitle_path)
    
    metadata_path = generate_chapters_metadata(episode, episode.video_path)
    has_chapters = metadata_path is not None and os.path.exists(metadata_path)

    if not has_subs and not has_chapters:
        logger.info(f"EP{episode.number:02d}: No subtitles or chapters to embed, marking complete")
        episode.final_path = episode.video_path
        episode.status = "completed"
        return episode

    try:
        episode.status = "embedding"
        base_path = os.path.splitext(episode.video_path)[0]
        temp_output = f"{base_path}_embedded.mkv"
        final_output = f"{base_path}.mkv"

        logger.info(f"EP{episode.number:02d}: Embedding subtitles/chapters...")

        cmd = ['ffmpeg', '-y']
        cmd.extend(['-i', episode.video_path])
        if has_subs:
            cmd.extend(['-i', episode.subtitle_path])
        if has_chapters:
            cmd.extend(['-i', metadata_path])

        cmd.extend(['-c:v', 'copy', '-c:a', 'copy'])
        if has_subs:
            cmd.extend(['-c:s', 'srt'])

        cmd.extend(['-map', '0:v:0', '-map', '0:a?'])
        if has_subs:
            cmd.extend(['-map', '1:0'])
            cmd.extend(['-metadata:s:s:0', 'language=eng', '-disposition:s:0', 'default+forced'])

        if has_chapters:
            metadata_idx = 2 if has_subs else 1
            cmd.extend(['-map_metadata', str(metadata_idx)])

        cmd.append(temp_output)

        result = run_subprocess(cmd, EMBED_TIMEOUT)

        if result.returncode == 0 and os.path.exists(temp_output):
            safe_remove(episode.video_path)
            if has_subs:
                safe_remove(episode.subtitle_path)
            if has_chapters:
                safe_remove(metadata_path)
            os.rename(temp_output, final_output)
            episode.final_path = final_output
            episode.status = "completed"
            logger.success(f"EP{episode.number:02d}: Subtitles/chapters embedded successfully")
        else:
            episode.status = "embed_failed"
            logger.error(f"EP{episode.number:02d}: Embed failed")
            if has_chapters:
                safe_remove(metadata_path)

    except Exception as e:
        episode.status = "embed_failed"
        episode.error = str(e)
        logger.error(f"EP{episode.number:02d}: {e}")
        if 'metadata_path' in locals() and metadata_path:
            safe_remove(metadata_path)

    return episode


def download_from_episodes(
    episodes: List[Episode],
    output_dir: str,
    audio_type: str,
    resolution: str,
    download_workers: int,
    embed_workers: int
) -> dict:
    os.makedirs(output_dir, exist_ok=True)

    # Resolve MAL ID for chapters skip times
    anime_folder_name = os.path.basename(os.path.abspath(output_dir))
    clean_anime_name = re.sub(r'\s*\((?:Sub|Dub)\)\s*$', '', anime_folder_name, flags=re.IGNORECASE).strip()
    mal_id = fetch_mal_id(clean_anime_name)
    for ep in episodes:
        ep.mal_id = mal_id

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
        embed_queue.join()
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
    except KeyboardInterrupt:
        stop_event.set()

    return stats


def fetch_anime_to_csv(
    extractor: HianimeExtractor,
    anime: Anime,
    output_dir: str,
    start_ep: int = 1,
    end_ep: int = 9999
) -> tuple:
    episodes = extractor.build_episode_list(anime, start_ep, end_ep, filename_format=FILENAME_FORMAT)
    if not episodes:
        return [], None

    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, f"{anime.name}_episodes.csv")
    json_path = os.path.join(output_dir, f"{anime.name}_metadata.json")

    save_episodes_to_csv(episodes, csv_path)
    extractor.save_to_json(anime, episodes, json_path)

    return episodes, csv_path


def download_movies_parallel(
    extractor: KickAssAnimeExtractor,
    movie_list: List[tuple],
    output_base: str,
    audio_type: str,
    resolution: str,
    season_number: Optional[int],
    download_workers: int,
    embed_workers: int,
) -> dict:
    main_logger = get_main_logger()
    all_episodes = []

    print_info(f"Preparing {len(movie_list)} movies for parallel download...")

    for _, anime in movie_list:
        if shutdown_event.is_set():
            break

        # Determine audio type
        if audio_type == 'sub' and anime.sub_episodes > 0:
            anime.download_type = 'sub'
        elif audio_type == 'dub' and anime.dub_episodes > 0:
            anime.download_type = 'dub'
        elif anime.sub_episodes > 0:
            anime.download_type = 'sub'
        elif anime.dub_episodes > 0:
            anime.download_type = 'dub'
        else:
            print_warning(f"No episodes available for: {anime.name}")
            continue

        # Use explicitly provided season, or keep auto-detected from title
        if season_number is not None:
            anime.season_number = season_number

        # Build episode list (should be just 1 episode for movies)
        episodes = extractor.build_episode_list(anime, 1, 1, filename_format=FILENAME_FORMAT)
        if not episodes:
            print_warning(f"Failed to get episode info for: {anime.name}")
            continue

        # Set output directory per movie
        output_dir = os.path.join(output_base, f"{anime.name} ({anime.download_type.title()})")
        os.makedirs(output_dir, exist_ok=True)

        # Resolve MAL ID for movies
        mal_id = fetch_mal_id(anime.name)
        # Store output_dir and mal_id in episode for the worker
        for ep in episodes:
            ep.output_dir = output_dir
            ep.mal_id = mal_id
            all_episodes.append(ep)

        main_logger.info(f"Queued: {anime.name}")

    if not all_episodes:
        print_error("No movies to download")
        return {'downloaded': 0, 'embedded': 0, 'failed': 0, 'skipped': 0, 'total': 0}

    print_info(f"Starting parallel download of {len(all_episodes)} movies with {download_workers} workers")

    # Use modified download_from_episodes that handles per-episode output dirs
    download_queue = Queue()
    embed_queue = Queue()
    stats = {'downloaded': 0, 'embedded': 0, 'failed': 0, 'skipped': 0, 'total': len(all_episodes)}
    stats_lock = threading.Lock()
    stop_event = threading.Event()

    def log_stats():
        with stats_lock:
            done = stats['downloaded'] + stats['skipped']
            main_logger.info(
                f"Movies: {done}/{stats['total']} downloaded | "
                f"{stats['embedded']} embedded | {stats['failed']} failed"
            )

    for ep in all_episodes:
        download_queue.put(ep)

    def dl_worker(worker_id: int):
        while not stop_event.is_set() and not shutdown_event.is_set():
            try:
                ep = download_queue.get(timeout=1)
            except Empty:
                continue
            # Get output_dir from episode
            ep_output_dir = ep.output_dir or output_base
            result = download_episode(ep, ep_output_dir, audio_type, resolution, worker_id=worker_id, extractor=extractor)
            with stats_lock:
                if result.status == "downloaded":
                    stats['downloaded'] += 1
                    result.output_dir = ep_output_dir
                    embed_queue.put(result)
                elif result.status == "skipped":
                    stats['skipped'] += 1
                else:
                    stats['failed'] += 1
            log_stats()
            download_queue.task_done()

    def embed_worker_fn(worker_id: int):
        while not stop_event.is_set() and not shutdown_event.is_set():
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
        embed_queue.join()
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
    except KeyboardInterrupt:
        stop_event.set()

    return stats


def scrape_and_download_parallel(
    extractor: KickAssAnimeExtractor,
    anime: Anime,
    output_dir: str,
    start_ep: int,
    end_ep: int,
    audio_type: str,
    resolution: str,
    download_workers: int,
    embed_workers: int
) -> dict:
    import requests
    from bs4 import BeautifulSoup
    from tools.functions import sanitize_filename

    os.makedirs(output_dir, exist_ok=True)

    main_logger = get_main_logger()

    download_queue = Queue()
    embed_queue = Queue()
    all_episodes = []
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

    def scraper_thread():
        logger = get_scraper_logger()
        try:
            logger.info("Fetching episodes...")
            ep_data = extractor.get_episode_urls(anime.url, start_ep, end_ep)
            if not ep_data:
                logger.error("No episode links found")
                scrape_done.set()
                return

            total_episodes = len(ep_data)
            with stats_lock:
                stats['total'] = total_episodes

            logger.success(f"Found {total_episodes} episodes to process")

            for ep_num, ep_url, ep_title in ep_data:
                if shutdown_event.is_set():
                    break

                filename = anime.format_filename(ep_num, ep_title, FILENAME_FORMAT, total_episodes)
                filename = sanitize_filename(filename)
                episode = Episode(
                    number=ep_num,
                    url=ep_url,
                    title=ep_title,
                    filename=filename
                )
                episode.mal_id = getattr(anime, 'mal_id', None)

                with episodes_lock:
                    all_episodes.append(episode)

                download_queue.put(episode)

                with stats_lock:
                    stats['scraped'] += 1

                logger.success(f"EP{ep_num:02d}: Scraped - {ep_title[:40]}...")
                log_stats()

                time.sleep(0.1)

        except Exception as e:
            logger.error(f"Scraper error: {e}")
        finally:
            logger.info("Scraping complete")
            scrape_done.set()

    def dl_worker(worker_id: int):
        while not stop_event.is_set():
            try:
                ep = download_queue.get(timeout=1)
            except Empty:
                if scrape_done.is_set() and download_queue.empty():
                    break
                continue

            result = download_episode(ep, output_dir, audio_type, resolution, worker_id=worker_id, extractor=extractor)

            with stats_lock:
                if result.status == "downloaded":
                    stats['downloaded'] += 1
                    embed_queue.put(result)
                elif result.status == "skipped":
                    stats['skipped'] += 1
                    stats['downloaded'] += 1
                else:
                    stats['failed'] += 1

            log_stats()
            download_queue.task_done()

    def embed_worker_fn(worker_id: int):
        while not stop_event.is_set():
            try:
                ep = embed_queue.get(timeout=1)
            except Empty:
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

    threads = []

    scraper = threading.Thread(target=scraper_thread, daemon=True)
    scraper.start()
    threads.append(scraper)

    for i in range(download_workers):
        t = threading.Thread(target=dl_worker, args=(i + 1,), daemon=True)
        t.start()
        threads.append(t)

    for i in range(embed_workers):
        t = threading.Thread(target=embed_worker_fn, args=(i + 1,), daemon=True)
        t.start()
        threads.append(t)

    try:
        scraper.join()
        download_queue.join()
        embed_queue.join()
        stop_event.set()
        for t in threads:
            t.join(timeout=5)

    except KeyboardInterrupt:
        main_logger.warning("Interrupted by user!")
        stop_event.set()

    csv_path = os.path.join(output_dir, f"{anime.name}_episodes.csv")
    with episodes_lock:
        save_episodes_to_csv(all_episodes, csv_path)
        extractor.save_to_json(anime, all_episodes, os.path.join(output_dir, f"{anime.name}_metadata.json"))

    print_success("All tasks completed!")
    return stats


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
    parser.add_argument('--season', type=int, default=None, help='Season number (auto-detected from title if not specified)')
    args = parser.parse_args()

    if args.from_csv:
        print_info(f"Loading episodes from: {args.from_csv}")
        episodes = load_episodes_from_csv(args.from_csv)

        if not episodes:
            print_error("No episodes in CSV")
            return

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

    extractor = KickAssAnimeExtractor({'subtitle_lang': SUBTITLE_LANG, 'no_subtitles': NO_SUBTITLES})

    def process_single_anime(anime_url: str, is_queue: bool = False, queue_index: int = 0, queue_total: int = 0, anime_ref: Optional[Anime] = None):
        anime = anime_ref or extractor.get_anime_from_url(anime_url)

        if not anime:
            print_error(f"Failed to get anime info from: {anime_url}")
            return False

        if is_queue:
            print(f"\n{Fore.CYAN}[{queue_index}/{queue_total}]{Style.RESET_ALL} {Fore.GREEN}Anime: {anime.name}{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.GREEN}Anime: {anime.name}{Style.RESET_ALL}")
        print(f"Sub: {anime.sub_episodes} | Dub: {anime.dub_episodes}")

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

        # Use explicitly provided season, or keep auto-detected season from title
        if args.season is not None:
            anime.season_number = args.season
        # anime.season_number is already set by extract_season_from_name() in get_anime_from_url()

        # Resolve MAL ID for chapters skip times
        anime.mal_id = fetch_mal_id(anime.name)

        max_eps = anime.sub_episodes if anime.download_type == 'sub' else anime.dub_episodes
        if DOWNLOAD_ALL:
            start_ep, end_ep = 1, max_eps or 9999
        else:
            print(f"\n{Fore.GREEN}Episodes available: 1 to {max_eps}{Style.RESET_ALL}")
            print(f"  {Fore.CYAN}1. Download all episodes (1-{max_eps}){Style.RESET_ALL}")
            print(f"  {Fore.CYAN}2. Download single episode{Style.RESET_ALL}")
            print(f"  {Fore.CYAN}3. Download from episode X to last episode{Style.RESET_ALL}")
            print(f"  {Fore.CYAN}4. Download specific range (X-Y){Style.RESET_ALL}")
            
            option = get_int_in_range(f"\n{Fore.CYAN}Select option (1-4): {Style.RESET_ALL}", 1, 4)
            
            if option == 1:
                start_ep, end_ep = 1, max_eps or 9999
            elif option == 2:
                start_ep = get_int_in_range(f"{Fore.CYAN}Enter episode number to download: {Style.RESET_ALL}", 1, max_eps or 9999)
                end_ep = start_ep
            elif option == 3:
                start_ep = get_int_in_range(f"{Fore.CYAN}Start download from episode: {Style.RESET_ALL}", 1, max_eps or 9999)
                end_ep = max_eps or 9999
            else:
                start_ep = get_int_in_range(f"{Fore.CYAN}Start episode: {Style.RESET_ALL}", 1, max_eps or 9999)
                end_ep = get_int_in_range(f"{Fore.CYAN}End episode: {Style.RESET_ALL}", start_ep, max_eps or 9999)


        output_dir = os.path.join(args.output, f"{anime.name} ({anime.download_type.title()})")

        if args.fetch_only:
            print_info("Fetching episode URLs (fetch-only mode)...")
            episodes, csv_path = fetch_anime_to_csv(extractor, anime, output_dir, start_ep, end_ep)
            if episodes:
                print_success(f"Fetched {len(episodes)} episodes!")
                print_success(f"CSV saved: {csv_path}")
            else:
                print_error("Failed to fetch episodes")
            return True

        print(f"\n{Fore.YELLOW}Summary:{Style.RESET_ALL}")
        print(f"  Anime: {anime.name}")
        print(f"  Season: {anime.season_number}")
        print(f"  Episodes: {start_ep} - {end_ep}")
        print(f"  Type: {anime.download_type}")
        print(f"  Resolution: {args.resolution}p")
        print(f"  Mode: Parallel scrape + download")

        if not is_queue and not get_confirmation("\nStart? (y/n): "):
            print_info("Cancelled.")
            return False

        start_time = time.time()

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
        if args.search:
            anime = extractor.select_anime_interactive(args.search)
            if anime:
                process_single_anime(anime.url)
        elif args.url:
            process_single_anime(args.url)
        elif ANIME_URL_QUEUE:
            queue_total = len(ANIME_URL_QUEUE)
            print_info(f"Found {queue_total} URLs in queue")
            for i, url in enumerate(ANIME_URL_QUEUE, 1):
                print(f"  {i}. {url}")

            if not get_confirmation(f"\nProcess all {queue_total} URLs? (y/n): "):
                print_info("Cancelled.")
                return

            # Categorize URLs into movies (single episode) and series (multiple episodes)
            print_info("Analyzing URLs to detect movies vs series...")
            movies = []  # List of (url, anime) tuples
            series = []  # List of urls
            failed_urls = []

            for url in ANIME_URL_QUEUE:
                if shutdown_event.is_set():
                    break
                is_single, anime = is_single_episode_anime(extractor, url)
                if anime is None:
                    print_warning(f"Failed to get info for: {url}")
                    failed_urls.append(url)
                elif is_single:
                    movies.append((url, anime))
                    print(f"  {Fore.YELLOW}[MOVIE]{Style.RESET_ALL} {anime.name}")
                else:
                    series.append((url, anime))
                    print(f"  {Fore.CYAN}[SERIES]{Style.RESET_ALL} {anime.name} ({max(anime.sub_episodes, anime.dub_episodes)} eps)")

            success_count = 0
            fail_count = len(failed_urls)

            # Process movies in parallel if any exist
            if movies and not shutdown_event.is_set():
                print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
                print(f"{Fore.CYAN}  Downloading {len(movies)} movies in parallel ({args.download_workers} workers){Style.RESET_ALL}")
                print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")

                start_time = time.time()
                stats = download_movies_parallel(
                    extractor,
                    movies,
                    args.output,
                    AUDIO_TYPE if AUDIO_TYPE in ('sub', 'dub') else 'sub',
                    args.resolution,
                    args.season,
                    args.download_workers,
                    args.embed_workers,
                )
                elapsed = time.time() - start_time

                print(f"\n{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
                print(f"{Fore.GREEN}  Movies Complete!{Style.RESET_ALL}")
                print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
                print(f"Downloaded: {stats['downloaded']}")
                print(f"Embedded: {stats['embedded']}")
                print(f"Skipped: {stats.get('skipped', 0)}")
                print(f"Failed: {stats['failed']}")
                print(f"Time: {elapsed/60:.1f} min")

                success_count += stats['downloaded'] + stats.get('skipped', 0)
                fail_count += stats['failed']

            # Process series sequentially (each series uses parallel episode downloads internally)
            for i, (url, anime_ref) in enumerate(series, 1):
                if shutdown_event.is_set():
                    print_warning("Shutdown requested, stopping queue processing")
                    break

                print(f"\n{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
                print(f"{Fore.CYAN}  Processing series {i}/{len(series)}{Style.RESET_ALL}")
                print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
                print(f"URL: {url}")

                try:
                    if process_single_anime(url, is_queue=True, queue_index=i, queue_total=len(series), anime_ref=anime_ref):
                        success_count += 1
                    else:
                        fail_count += 1
                except Exception as e:
                    print_error(f"Error processing {url}: {e}")
                    fail_count += 1

                if i < len(series) and not shutdown_event.is_set():
                    print_info("Moving to next series in 3 seconds...")
                    time.sleep(3)

            print(f"\n{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}  Queue Complete!{Style.RESET_ALL}")
            print(f"{Fore.GREEN}{'='*60}{Style.RESET_ALL}")
            print(f"Total URLs: {queue_total}")
            print(f"Movies: {len(movies)}")
            print(f"Series: {len(series)}")
            print(f"Success: {success_count}")
            print(f"Failed: {fail_count}")
        else:
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