import json
import os
import re
import sys
import time
import csv
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from typing import Any, List, Optional, Tuple, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from colorama import Fore, Style

from tools.functions import (
    get_confirmation,
    get_int_in_range,
    sanitize_filename,
    safe_remove,
    print_info,
    print_success,
    print_error,
    print_warning,
    clear_screen,
)

from extractors.models import Anime, Episode, extract_season_from_name

try:
    from selenium import webdriver
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


class KickAssAnimeExtractor:
    URL = "https://kaa.lt"
    ENCODING = "utf-8"
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.8",
        "Referer": "https://kaa.lt/",
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.subtitle_lang = self.config.get('subtitle_lang', 'en')
        self.no_subtitles = self.config.get('no_subtitles', False)
        self.preferred_server = self.config.get('server', None)
        
    def search_anime(self, query: str) -> List[Anime]:
        print_info(f"Searching for: {query}")
        search_url = f"{self.URL}/api/search"
        try:
            r = requests.post(search_url, headers=self.HEADERS, json={"query": query}, timeout=15)
            if r.status_code != 200:
                print_error(f"Search API failed with status code {r.status_code}")
                return []
                
            results = r.json()
            if not results:
                print_warning("No anime found for this search")
                return []
                
            print_info(f"Found {len(results)} matches. Fetching details for top 10 in parallel...")
            
            def enrich(item):
                slug = item["slug"]
                title = item["title"]
                
                locales = []
                try:
                    r_details = requests.get(f"{self.URL}/api/show/{slug}", headers=self.HEADERS, timeout=5)
                    if r_details.status_code == 200:
                        locales = r_details.json().get("locales", [])
                except Exception:
                    pass
                
                sub_eps = 0
                dub_eps = 0
                
                def get_eps_for_lang(lang):
                    url_eps = f"{self.URL}/api/show/{slug}/episodes?ep=1&lang={lang}"
                    try:
                        r_eps = requests.get(url_eps, headers=self.HEADERS, timeout=5)
                        if r_eps.status_code == 200:
                            pages = r_eps.json().get("pages", [])
                            if pages:
                                max_val = 0
                                for page in pages:
                                    eps = page.get("eps", [])
                                    if eps:
                                        max_val = max(max_val, max(int(e) for e in eps))
                                return max_val
                    except:
                        pass
                    return 0
                
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = {}
                    if "ja-JP" in locales or not locales:
                        futures["sub"] = executor.submit(get_eps_for_lang, "ja-JP")
                    if "en-US" in locales:
                        futures["dub"] = executor.submit(get_eps_for_lang, "en-US")
                        
                    sub_eps = futures["sub"].result() if "sub" in futures else 0
                    dub_eps = futures["dub"].result() if "dub" in futures else 0
                    
                sanitized_title = sanitize_filename(title)
                return Anime(
                    name=sanitized_title,
                    url=f"{self.URL}/{slug}",
                    sub_episodes=sub_eps,
                    dub_episodes=dub_eps,
                    short_name=slug.split('-')[0].title(),
                    season_number=extract_season_from_name(sanitized_title)
                )
                
            enriched_results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                enriched_results = list(executor.map(enrich, results[:10]))
                
            valid_results = [a for a in enriched_results if a.sub_episodes > 0 or a.dub_episodes > 0]
            if not valid_results:
                valid_results = [
                    Anime(
                        name=sanitize_filename(item["title"]),
                        url=f"{self.URL}/{item['slug']}",
                        sub_episodes=1,
                        dub_episodes=0,
                        short_name=item["slug"].split('-')[0].title(),
                        season_number=1
                    ) for item in results[:10]
                ]
                
            print_success(f"Found {len(valid_results)} valid anime")
            return valid_results
            
        except Exception as e:
            print_error(f"Search failed: {e}")
            return []

    def select_anime_interactive(self, query: str = None) -> Optional[Anime]:
        try:
            from tools.ui import print_banner, print_search_results
            print_banner()
            if not query:
                query = input("Enter anime name to search: ").strip()
                if not query:
                    return None

            anime_list = self.search_anime(query)
            if not anime_list:
                return None

            return print_search_results(anime_list)
        except Exception:
            if not query:
                query = input("Enter anime name to search: ").strip()
                if not query:
                    return None
            anime_list = self.search_anime(query)
            if not anime_list:
                return None
            return anime_list[0]

    def get_anime_from_url(self, url: str) -> Optional[Anime]:
        print_info(f"Fetching anime info from URL...")
        try:
            clean_url = url.split('?')[0].rstrip('/')
            
            # Extract show slug
            slug_match = re.search(r'https?://(?:[a-zA-Z0-9.-]+\.)?(?:kaa\.lt|kickassanime\.[a-z]+)/([^/]+)', clean_url)
            if not slug_match:
                print_error("Invalid KickAssAnime URL format")
                return None
                
            slug = slug_match.group(1)
            
            # Fetch show details via API
            details_url = f"{self.URL}/api/show/{slug}"
            r_details = requests.get(details_url, headers=self.HEADERS, timeout=15)
            if r_details.status_code != 200:
                print_error(f"Details API returned status code {r_details.status_code}")
                return None
                
            details = r_details.json()
            title = details.get("title", slug)
            locales = details.get("locales", [])
            
            sub_eps = 0
            dub_eps = 0
            
            def get_eps_for_lang(lang):
                url_eps = f"{self.URL}/api/show/{slug}/episodes?ep=1&lang={lang}"
                try:
                    r_eps = requests.get(url_eps, headers=self.HEADERS, timeout=5)
                    if r_eps.status_code == 200:
                        pages = r_eps.json().get("pages", [])
                        if pages:
                            max_val = 0
                            for page in pages:
                                eps = page.get("eps", [])
                                if eps:
                                    max_val = max(max_val, max(int(e) for e in eps))
                            return max_val
                except:
                    pass
                return 0
                
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {}
                if "ja-JP" in locales or not locales:
                    futures["sub"] = executor.submit(get_eps_for_lang, "ja-JP")
                if "en-US" in locales:
                    futures["dub"] = executor.submit(get_eps_for_lang, "en-US")
                    
                sub_eps = futures["sub"].result() if "sub" in futures else 0
                dub_eps = futures["dub"].result() if "dub" in futures else 0
                
            sanitized_title = sanitize_filename(title)
            return Anime(
                name=sanitized_title,
                url=f"{self.URL}/{slug}",
                sub_episodes=sub_eps,
                dub_episodes=dub_eps,
                short_name=slug.split('-')[0].title(),
                season_number=extract_season_from_name(sanitized_title)
            )
        except Exception as e:
            print_error(f"Failed to get anime info from URL: {e}")
            return None

    def select_download_type(self, anime: Anime) -> str:
        if anime.sub_episodes > 0 and anime.dub_episodes > 0:
            print(f"\n{Fore.GREEN}Both sub and dub available:{Style.RESET_ALL}")
            print(f"  Sub episodes: {Fore.YELLOW}{anime.sub_episodes}{Style.RESET_ALL}")
            print(f"  Dub episodes: {Fore.YELLOW}{anime.dub_episodes}{Style.RESET_ALL}")

            while True:
                choice = input(f"\n{Fore.CYAN}Download sub or dub? (sub/dub): {Style.RESET_ALL}").strip().lower()
                if choice in ('sub', 's'):
                    return 'sub'
                elif choice in ('dub', 'd'):
                    return 'dub'
                print_warning("Please enter 'sub' or 'dub'")

        elif anime.dub_episodes == 0:
            print_info("Only sub episodes available")
            return 'sub'
        else:
            print_info("Only dub episodes available")
            return 'dub'

    def get_season_number(self) -> int:
        return get_int_in_range(
            f"{Fore.CYAN}Enter season number (default 1): {Style.RESET_ALL}",
            min_val=1,
            max_val=99
        )

    def get_episode_urls(self, url: str, start_ep: int, end_ep: int) -> List[Tuple[int, str, str]]:
        clean_url = url.split('?')[0].rstrip('/')
        slug_match = re.search(r'https?://(?:[a-zA-Z0-9.-]+\.)?(?:kaa\.lt|kickassanime\.[a-z]+)/([^/]+)', clean_url)
        if not slug_match:
            print_error("Could not extract show slug from URL")
            return []
            
        show_slug = slug_match.group(1)
        lang = "ja-JP" if self.config.get('audio_type', 'sub') == 'sub' else "en-US"
        
        url_eps = f"{self.URL}/api/show/{show_slug}/episodes?ep=1&lang={lang}"
        try:
            r = requests.get(url_eps, headers=self.HEADERS, timeout=15)
            if r.status_code != 200:
                print_error(f"Episodes API returned status {r.status_code}")
                return []
                
            data = r.json()
            pages = data.get("pages", [])
            
            needed_pages = []
            for p in pages:
                p_from = int(p["from"])
                p_to = int(p["to"])
                if start_ep <= p_to and end_ep >= p_from:
                    needed_pages.append(p)
                    
            episodes = []
            for p in needed_pages:
                first_ep = p["eps"][0]
                page_url = f"{self.URL}/api/show/{show_slug}/episodes?ep={first_ep}&lang={lang}"
                page_data = requests.get(page_url, headers=self.HEADERS, timeout=15).json()
                
                for ep in page_data.get("result", []):
                    ep_num = ep["episode_number"]
                    if start_ep <= ep_num <= end_ep:
                        ep_slug = ep["slug"]
                        watch_url = f"{self.URL}/{show_slug}/ep-{ep_num}-{ep_slug}"
                        title = f"Episode {ep_num}"
                        episodes.append((ep_num, watch_url, title))
                        
            episodes.sort(key=lambda x: x[0])
            return episodes
            
        except Exception as e:
            print_error(f"Failed to fetch episode URLs: {e}")
            return []

    def select_server_interactive(self, anime: Anime) -> Optional[str]:
        return "VidStreaming"

    def resolve_media(self, episode: Episode, audio_type: str, resolution: str) -> Optional[Dict[str, Any]]:
        if not SELENIUM_AVAILABLE:
            print_error(f"EP{episode.number:02d}: Selenium not available. Cannot resolve KAA media streams.")
            return None
            
        print_info(f"EP{episode.number:02d}: Resolving streaming and subtitle URLs...")
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": self.URL,
        }
        try:
            r = requests.get(episode.url, headers=headers, timeout=15)
            if r.status_code != 200:
                print_error(f"EP{episode.number:02d}: Failed to fetch watch page (status {r.status_code})")
                return None
                
            clean_html = r.text.replace('\\u002F', '/').replace('\\/', '/')
            
            player_src = None
            matches = re.finditer(r'\{\s*name:\s*"([^"]+)"\s*,\s*shortName:\s*"([^"]+)"\s*,\s*src:\s*"([^"]+)"\s*\}', clean_html)
            for m in matches:
                if m.group(1).lower() == "vidstreaming" or not player_src:
                    player_src = m.group(3)
                    
            if not player_src:
                fallback_match = re.search(r'(https?://[a-zA-Z0-9.-]+/cat-player/player\?[^"\']+)', clean_html)
                if fallback_match:
                    player_src = fallback_match.group(1)
                    
            if not player_src:
                print_error(f"EP{episode.number:02d}: Player source URL not found")
                return None

            m3u8_url = None
            vtt_url = None

            # Fast direct HTTP GET attempt on player_src
            try:
                player_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": episode.url,
                }
                resp_p = requests.get(player_src, headers=player_headers, timeout=10)
                if resp_p.status_code == 200:
                    p_text = resp_p.text.replace('\\u002F', '/').replace('\\/', '/')
                    m3u8_match = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*master[^\s"\'<>]*)', p_text)
                    if not m3u8_match:
                        m3u8_match = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', p_text)
                    if m3u8_match:
                        m3u8_url = m3u8_match.group(1)

                    vtt_match = re.search(r'(https?://[^\s"\'<>]+\.vtt[^\s"\'<>]*)', p_text)
                    if vtt_match and 'thumbnail' not in vtt_match.group(1).lower():
                        vtt_url = vtt_match.group(1)
            except Exception:
                pass

            # Fallback to Selenium Chrome only if direct HTTP GET did not extract m3u8_url
            if not m3u8_url and SELENIUM_AVAILABLE:
                options = webdriver.ChromeOptions()
                options.add_argument("--headless")
                options.add_argument("--no-sandbox")
                options.add_argument("--disable-gpu")
                options.add_argument("--log-level=3")
                options.add_argument("--silent")
                options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
                
                driver = webdriver.Chrome(options=options)
                try:
                    driver.get(player_src)
                    attempt = 0
                    while (not m3u8_url or (not vtt_url and not self.no_subtitles)) and attempt < 12:
                        time.sleep(1)
                        attempt += 1
                        
                        logs = driver.get_log('performance')
                        for entry in logs:
                            try:
                                log_data = json.loads(entry['message'])['message']
                                method = log_data.get('method')
                                
                                url_candidate = None
                                if method == 'Network.requestWillBeSent':
                                    url_candidate = log_data['params']['request']['url']
                                elif method == 'Network.responseReceived':
                                    url_candidate = log_data['params']['response']['url']
                                    
                                if url_candidate:
                                    if not m3u8_url and '.m3u8' in url_candidate and 'master' in url_candidate:
                                        m3u8_url = url_candidate
                                    if not vtt_url and '.vtt' in url_candidate and 'thumbnail' not in url_candidate:
                                        vtt_url = url_candidate
                            except Exception:
                                pass
                finally:
                    driver.quit()
                
            if not m3u8_url:
                print_error(f"EP{episode.number:02d}: Master m3u8 URL could not be resolved.")
                return None
                
            print_success(f"EP{episode.number:02d}: Extracted master m3u8")
            
            sub_path = None
            if vtt_url and not self.no_subtitles:
                output_dir = episode.output_dir or os.getcwd()
                sub_path = os.path.join(output_dir, f"{episode.filename}.srt")
                
                sub_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://krussdomi.com/",
                    "Origin": "https://krussdomi.com"
                }
                
                try:
                    r_sub = requests.get(vtt_url, headers=sub_headers, timeout=10)
                    if r_sub.status_code == 200:
                        srt_content = self.vtt_to_srt(r_sub.text)
                        with open(sub_path, "w", encoding="utf-8") as f:
                            f.write(srt_content)
                        print_success(f"EP{episode.number:02d}: Subtitle file saved and converted to srt")
                    else:
                        sub_path = None
                except Exception as e:
                    print_warning(f"EP{episode.number:02d}: Failed to fetch subtitles: {e}")
                    sub_path = None
                    
            return {
                "m3u8": m3u8_url,
                "subtitle_path": sub_path,
                "headers": {
                    "Referer": "https://krussdomi.com/",
                    "Origin": "https://krussdomi.com"
                }
            }
            
        except Exception as e:
            print_error(f"EP{episode.number:02d}: Exception occurred resolving media: {e}")
            return None

    def vtt_to_srt(self, vtt_content: str) -> str:
        lines = vtt_content.replace('\r\n', '\n').split('\n')
        srt_lines = []
        cue_idx = 1
        
        in_header = True
        for line in lines:
            if in_header:
                if line.startswith('WEBVTT') or not line.strip() or line.startswith('NOTE') or line.startswith('STYLE'):
                    continue
                if '-->' in line:
                    in_header = False
                else:
                    continue
            
            if '-->' in line:
                line = line.replace('.', ',')
                srt_lines.append(str(cue_idx))
                srt_lines.append(line)
                cue_idx += 1
            else:
                srt_lines.append(line)
                
        return '\n'.join(srt_lines)

    def build_episode_list(
        self,
        anime: Anime,
        start_ep: int,
        end_ep: int,
        filename_format: str = "standard",
    ) -> List[Episode]:
        scraped = self.get_episode_urls(anime.url, start_ep, end_ep)
        if not scraped:
            return []

        total_episodes = len(scraped)
        episodes = []
        for ep_num, ep_url, ep_title in scraped:
            filename = anime.format_filename(ep_num, ep_title, filename_format, total_episodes)
            filename = sanitize_filename(filename)

            episodes.append(Episode(
                number=ep_num,
                url=ep_url,
                title=ep_title,
                filename=filename,
            ))

        return episodes

    def save_to_csv(self, episodes: List[Episode], csv_path: str):
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Episode', 'URL', 'Title', 'Filename', 'Status'])
            for ep in episodes:
                writer.writerow([ep.number, ep.url, ep.title, ep.filename, ep.status])
        print_success(f"Saved episode list to {csv_path}")

    def save_to_json(self, anime: Anime, episodes: List[Episode], json_path: str):
        data = {
            **anime.to_dict(),
            'episodes': [ep.to_dict() for ep in episodes]
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print_success(f"Saved metadata to {json_path}")

    def cleanup(self):
        pass
