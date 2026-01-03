"""
HiAnime Extractor - Handles all interaction with hianime.to

Features:
- Anime search by name
- Episode URL scraping (handles non-sequential IDs)
- Sub/Dub selection
- Server selection
- Selenium fallback for difficult pages
- Language detection for subtitles
"""

import json
import os
import sys
import time
import csv
import subprocess
import threading
from dataclasses import dataclass, asdict, field
from typing import Any, List, Optional, Tuple, Dict
from urllib.parse import urljoin
from queue import Queue, Empty

import requests
from bs4 import BeautifulSoup, Tag
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
from tools.logger import YTDLogger

# Optional imports for Selenium fallback
try:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.remote.webelement import WebElement
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium_stealth import stealth
    from seleniumwire import webdriver
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

# Optional import for language detection
try:
    from langdetect import detect as detect_lang
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False


@dataclass
class Anime:
    """Anime metadata."""
    name: str  # Full title: "Bleach Thousand Year Blood War The Conflict"
    url: str
    sub_episodes: int
    dub_episodes: int
    short_name: str = ""  # Short name: "Bleach" (extracted from URL slug)
    download_type: str = "sub"  # 'sub' or 'dub'
    season_number: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    def format_filename(self, ep_num: int, ep_title: str = "", fmt: str = "standard") -> str:
        """
        Generate filename based on format preference.

        Args:
            ep_num: Episode number
            ep_title: Episode title (optional)
            fmt: Format type - 'full', 'standard', 'short', 'season', 'episode'

        Returns:
            Formatted filename (without extension)
        """
        season_ep = f"S{self.season_number:02d}E{ep_num:02d}"

        if fmt == "episode":
            # E02
            return f"E{ep_num:02d}"

        elif fmt == "season":
            # S01E02
            return season_ep

        elif fmt == "short":
            # Bleach - S01E02
            name = self.short_name if self.short_name else self.name.split()[0]
            return f"{name} - {season_ep}"

        elif fmt == "full":
            # Bleach TYBW The Conflict - S01E02 - Kill The King
            base = f"{self.name} - {season_ep}"
            if ep_title and ep_title != f"Episode {ep_num}":
                safe_title = ep_title[:50]  # Limit title length
                return f"{base} - {safe_title}"
            return base

        else:  # 'standard' or default
            # Bleach TYBW The Conflict - S01E02
            return f"{self.name} - {season_ep}"


@dataclass
class Episode:
    """Episode information."""
    number: int
    url: str
    title: str
    filename: str
    video_path: Optional[str] = None
    subtitle_path: Optional[str] = None
    final_path: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None
    m3u8_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    def to_dict(self) -> dict:
        return {
            'number': self.number,
            'url': self.url,
            'title': self.title,
            'filename': self.filename,
            'status': self.status,
        }


class HianimeExtractor:
    """
    Extractor for hianime.to anime content.

    Handles:
    - Searching for anime by name
    - Fetching anime details from URL
    - Scraping episode URLs (handles non-sequential IDs)
    - Sub/Dub and server selection
    - Selenium fallback for difficult pages
    """

    URL = "https://hianime.to"
    ENCODING = "utf-8"

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
        "Connection": "keep-alive",
    }

    # Languages to filter out when looking for English subtitles
    OTHER_LANGS = [
        "ita", "jpn", "pol", "por", "ara", "chi", "cze", "dan", "dut", "fin",
        "fre", "ger", "gre", "heb", "hun", "ind", "kor", "nob", "rum", "rus",
        "tha", "vie", "swe", "spa", "tur", "ces", "bul", "zho", "nld", "fra",
        "deu", "ell", "hin", "hrv", "msa", "may", "ron", "slk", "slo", "ukr",
    ]

    # Bad characters for filenames
    BAD_TITLE_CHARS = ["-", ".", "/", "\\", "?", "%", "*", "<", ">", "|", '"', "[", "]", ":"]

    # Selenium capture settings
    DOWNLOAD_ATTEMPT_CAP = 45
    DOWNLOAD_REFRESH = (15, 30)

    def __init__(self, config: dict = None):
        """
        Initialize the extractor.

        Args:
            config: Configuration dictionary with settings like:
                - subtitle_lang: Language code for subtitles (default: 'en')
                - no_subtitles: Skip subtitle download (default: False)
                - server: Preferred server name (default: None)
                - use_selenium: Force Selenium mode (default: False)
        """
        self.config = config or {}
        self.subtitle_lang = self.config.get('subtitle_lang', 'en')
        self.no_subtitles = self.config.get('no_subtitles', False)
        self.preferred_server = self.config.get('server', None)
        self.use_selenium = self.config.get('use_selenium', False)

        self.driver = None
        self.captured_video_urls = []
        self.captured_subtitle_urls = []

        # Title translation table for filename sanitization
        self.title_trans = str.maketrans("", "", "".join(self.BAD_TITLE_CHARS))

    # =========================================================================
    # ANIME SEARCH
    # =========================================================================

    def search_anime(self, query: str) -> List[Anime]:
        """
        Search for anime by name.

        Args:
            query: Search query string

        Returns:
            List of Anime objects matching the search
        """
        print_info(f"Searching for: {query}")

        url = urljoin(self.URL, f"/search?keyword={query}")

        try:
            response = requests.get(url, headers=self.HEADERS, timeout=30)
            soup = BeautifulSoup(response.content, "html.parser")

            main_content = soup.find("div", id="main-content")
            if not main_content:
                print_warning("Could not find main content on search page")
                return []

            anime_elements = main_content.find_all("div", class_="flw-item")
            if not anime_elements:
                print_warning("No anime found for this search")
                return []

            anime_list = []
            for element in anime_elements:
                try:
                    # Get name
                    name_elem = element.find("h3", class_="film-name")
                    raw_name = name_elem.text if name_elem else "Unknown"
                    name = raw_name.translate(self.title_trans).strip()

                    # Get URL
                    link_elem = element.find("a", class_="film-poster-ahref")
                    anime_url = urljoin(self.URL, link_elem["href"]) if link_elem else ""

                    # Get episode counts
                    sub_eps = 0
                    dub_eps = 0

                    sub_elem = element.find("div", class_="tick-item tick-sub")
                    if sub_elem:
                        try:
                            sub_eps = int(sub_elem.text.strip())
                        except ValueError:
                            pass

                    dub_elem = element.find("div", class_="tick-item tick-dub")
                    if dub_elem:
                        try:
                            dub_eps = int(dub_elem.text.strip())
                        except ValueError:
                            pass

                    # Extract short name from URL slug
                    import re
                    slug_match = re.search(r'/([^/]+?)(?:-\d+)?$', anime_url)
                    short_name = ""
                    if slug_match:
                        slug = slug_match.group(1)
                        first_word = slug.split('-')[0]
                        short_name = sanitize_filename(first_word.title())

                    anime_list.append(Anime(
                        name=name,
                        url=anime_url,
                        sub_episodes=sub_eps,
                        dub_episodes=dub_eps,
                        short_name=short_name,
                    ))
                except Exception as e:
                    continue

            print_success(f"Found {len(anime_list)} anime")
            return anime_list

        except Exception as e:
            print_error(f"Search failed: {e}")
            return []

    def select_anime_interactive(self, query: str = None) -> Optional[Anime]:
        """
        Interactive anime selection - search and let user choose.

        Args:
            query: Optional search query. If None, prompts user.

        Returns:
            Selected Anime or None if cancelled
        """
        clear_screen()
        print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}  HiAnime Downloader - Search{Style.RESET_ALL}")
        print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}\n")

        if not query:
            query = input(f"{Fore.CYAN}Enter anime name to search: {Style.RESET_ALL}").strip()
            if not query:
                return None

        anime_list = self.search_anime(query)
        if not anime_list:
            return None

        # Display results
        print(f"\n{Fore.GREEN}Search Results:{Style.RESET_ALL}\n")
        for i, anime in enumerate(anime_list, 1):
            sub_info = f"{Fore.YELLOW}{anime.sub_episodes}{Style.RESET_ALL} sub"
            dub_info = f"{Fore.YELLOW}{anime.dub_episodes}{Style.RESET_ALL} dub"
            print(f"  {Fore.RED}{i:2}{Style.RESET_ALL}: {Fore.CYAN}{anime.name}{Style.RESET_ALL}")
            print(f"      Episodes: {sub_info} / {dub_info}")

        # User selection
        selection = get_int_in_range(
            f"\n{Fore.CYAN}Select anime (1-{len(anime_list)}): {Style.RESET_ALL}",
            1,
            len(anime_list)
        )

        return anime_list[selection - 1]

    # =========================================================================
    # ANIME INFO FROM URL
    # =========================================================================

    def get_anime_from_url(self, url: str) -> Optional[Anime]:
        """
        Get anime details from a URL.

        Args:
            url: Anime page URL (watch or info page)

        Returns:
            Anime object or None if failed
        """
        print_info(f"Fetching anime info from URL...")

        try:
            response = requests.get(url, headers=self.HEADERS, timeout=30)
            soup = BeautifulSoup(response.content, "html.parser")

            # Try to find the detail section
            detail_div = soup.find("div", class_="anisc-detail")
            if not detail_div:
                detail_div = soup

            # Get name
            name_elem = detail_div.find("h2", class_="film-name") or detail_div.find("h2", class_="dynamic-name")
            if name_elem:
                a_tag = name_elem.find("a")
                name = (a_tag.text if a_tag else name_elem.text).translate(self.title_trans).strip()
            else:
                name = "Unknown Anime"

            # Get episode counts from film-stats or tick items
            sub_eps = 0
            dub_eps = 0

            stats_div = soup.find("div", class_="film-stats")
            search_area = stats_div if stats_div else soup

            sub_elem = search_area.find("div", class_="tick-item tick-sub")
            if sub_elem:
                try:
                    sub_eps = int(sub_elem.text.strip())
                except ValueError:
                    pass

            dub_elem = search_area.find("div", class_="tick-item tick-dub")
            if dub_elem:
                try:
                    dub_eps = int(dub_elem.text.strip())
                except ValueError:
                    pass

            # Also check episode list for max episode number
            ep_items = soup.find_all("a", attrs={"data-number": True})
            if ep_items:
                max_ep = max(int(item.get("data-number", 0)) for item in ep_items)
                sub_eps = max(sub_eps, max_ep)

            # Build watch URL
            base_url = url.split('?')[0]
            if '/watch/' not in base_url:
                # Convert info URL to watch URL
                base_url = base_url.replace('hianime.to/', 'hianime.to/watch/')

            # Extract short name from URL slug
            # e.g., "bleach-thousand-year-blood-war-the-conflict-19322" -> "Bleach"
            import re
            slug_match = re.search(r'/watch/([^/]+?)(?:-\d+)?$', base_url)
            short_name = ""
            if slug_match:
                slug = slug_match.group(1)
                # Get first word/segment of the slug as short name
                first_word = slug.split('-')[0]
                short_name = sanitize_filename(first_word.title())

            return Anime(
                name=sanitize_filename(name),
                url=base_url,
                sub_episodes=sub_eps,
                dub_episodes=dub_eps,
                short_name=short_name,
            )

        except Exception as e:
            print_error(f"Failed to get anime info: {e}")
            return None

    # =========================================================================
    # SUB/DUB SELECTION
    # =========================================================================

    def select_download_type(self, anime: Anime) -> str:
        """
        Let user select sub or dub download type.

        Args:
            anime: Anime object with episode counts

        Returns:
            'sub' or 'dub'
        """
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

    # =========================================================================
    # SEASON NUMBER
    # =========================================================================

    def get_season_number(self) -> int:
        """
        Get season number from user.

        Returns:
            Season number (default 1)
        """
        return get_int_in_range(
            f"{Fore.CYAN}Enter season number (default 1): {Style.RESET_ALL}",
            min_val=1,
            max_val=99
        )

    # =========================================================================
    # EPISODE URL SCRAPING
    # =========================================================================

    def get_episode_urls(self, url: str, start_ep: int, end_ep: int) -> List[Tuple[int, str, str]]:
        """
        Fetch episode URLs via AJAX API.
        Handles non-sequential episode IDs.

        Args:
            url: Anime watch URL
            start_ep: Starting episode number
            end_ep: Ending episode number

        Returns:
            List of (episode_number, url, title) tuples
        """
        import re

        base_url = url.split('?')[0]

        # Extract anime ID from URL (e.g., "bleach-thousand-year-blood-war-the-conflict-19322" -> "19322")
        match = re.search(r'-(\d+)$', base_url.rstrip('/'))
        if not match:
            print_error("Could not extract anime ID from URL")
            return []

        anime_id = match.group(1)
        print_info(f"Fetching episodes for anime ID: {anime_id}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": base_url,
        }

        try:
            # Fetch episodes via AJAX API
            api_url = f"https://hianime.to/ajax/v2/episode/list/{anime_id}"
            response = requests.get(api_url, headers=headers, timeout=30)

            if response.status_code != 200:
                print_error(f"API returned status {response.status_code}")
                return []

            data = response.json()
            if not data.get('status') or not data.get('html'):
                print_error("Invalid API response")
                return []

            # Parse the HTML from API response
            soup = BeautifulSoup(data['html'], "html.parser")
            ep_items = soup.find_all("a", attrs={"data-number": True})

            if not ep_items:
                print_error("No episode links found in API response")
                return []

            episodes = []
            for item in ep_items:
                try:
                    ep_num = int(item.get("data-number"))
                    if start_ep <= ep_num <= end_ep:
                        href = item.get("href", "")
                        if href:
                            ep_url = f"https://hianime.to{href}" if href.startswith("/") else href
                            title = item.get("title", "") or f"Episode {ep_num}"
                            episodes.append((ep_num, ep_url, title.strip()))
                except (ValueError, TypeError):
                    continue

            episodes.sort(key=lambda x: x[0])

            if episodes:
                print_success(f"Found {len(episodes)} episode URLs")
            else:
                print_warning("No episodes found in requested range")

            return episodes

        except Exception as e:
            print_error(f"Failed to fetch episodes: {e}")
            return []

    # =========================================================================
    # SERVER SELECTION (Selenium mode)
    # =========================================================================

    def configure_selenium_driver(self):
        """Configure Selenium driver with anti-detection measures."""
        if not SELENIUM_AVAILABLE:
            raise ImportError("Selenium not installed. Run: pip install selenium seleniumwire selenium-stealth")

        mobile_emulation = {"deviceName": "iPhone X"}
        options = webdriver.ChromeOptions()

        options.add_experimental_option("mobileEmulation", mobile_emulation)
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("window-size=600,1000")
        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.notifications": 2,
            "profile.default_content_setting_values.popups": 2,
            "profile.managed_default_content_settings.ads": 2,
        })
        options.add_argument("--disable-features=PopupBlocking")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-gpu")
        options.add_argument("--log-level=3")
        options.add_argument("--silent")
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        seleniumwire_options = {
            "verify_ssl": False,
            "disable_encoding": True,
        }

        self.driver = webdriver.Chrome(
            options=options,
            seleniumwire_options=seleniumwire_options,
        )

        stealth(
            self.driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )

        self.driver.implicitly_wait(10)

        # Block popups
        self.driver.execute_script("""
            window.alert = function() {};
            window.confirm = function() { return true; };
            window.prompt = function() { return null; };
            window.open = function() { return null; };
        """)

    def get_server_options(self, download_type: str) -> list:
        """Get available server options from the page."""
        if not self.driver:
            return []

        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "servers-content"))
            )

            servers_content = self.driver.find_element(By.ID, "servers-content")
            blocks = servers_content.find_elements(By.XPATH, "./div[contains(@class, 'ps_-block')]")

            options = []
            for block in blocks:
                try:
                    server_list = block.find_element(By.CLASS_NAME, "ps__-list")
                    options.append(server_list.find_elements(By.TAG_NAME, "a"))
                except:
                    pass

            # Return sub servers (first) or dub servers (second)
            if len(options) == 1:
                return options[0]
            elif download_type in ('sub', 's'):
                return options[0] if options else []
            else:
                return options[1] if len(options) > 1 else (options[0] if options else [])

        except Exception as e:
            print_error(f"Failed to get server options: {e}")
            return []

    def select_server_interactive(self, anime: Anime) -> Optional[str]:
        """
        Interactive server selection using Selenium.

        Args:
            anime: Anime object

        Returns:
            Selected server name or None
        """
        if not SELENIUM_AVAILABLE:
            print_warning("Selenium not available for server selection")
            return None

        self.configure_selenium_driver()
        self.driver.get(anime.url)

        options = self.get_server_options(anime.download_type)
        if not options:
            self.driver.quit()
            return None

        # Check if preferred server exists
        if self.preferred_server:
            for opt in options:
                if opt.text.lower().strip() == self.preferred_server.lower().strip():
                    self.driver.quit()
                    return opt.text

        # Display options
        print(f"\n{Fore.GREEN}Available servers:{Style.RESET_ALL}\n")
        server_names = []
        for i, opt in enumerate(options, 1):
            server_names.append(opt.text)
            print(f"  {Fore.RED}{i}{Style.RESET_ALL}: {Fore.CYAN}{opt.text}{Style.RESET_ALL}")

        selection = get_int_in_range(
            f"\n{Fore.CYAN}Select server: {Style.RESET_ALL}",
            1,
            len(options)
        )

        selected = server_names[selection - 1]
        self.driver.quit()
        return selected

    # =========================================================================
    # SELENIUM MEDIA CAPTURE (Fallback)
    # =========================================================================

    def capture_media_requests(self) -> Optional[Dict[str, Any]]:
        """
        Capture m3u8 and vtt URLs from browser network requests.
        This is the Selenium fallback method.

        Returns:
            Dict with 'm3u8', 'vtt', 'headers' keys or None if failed
        """
        if not self.driver:
            return None

        found_m3u8 = False
        found_vtt = self.no_subtitles
        attempt = 0
        urls = {"all-vtt": []}

        while (not found_m3u8 or not found_vtt) and attempt <= self.DOWNLOAD_ATTEMPT_CAP:
            sys.stdout.write(f"\r{Fore.CYAN}Capturing... Attempt {attempt}/{self.DOWNLOAD_ATTEMPT_CAP}{Style.RESET_ALL}")
            sys.stdout.flush()

            for request in self.driver.requests:
                if not request.response:
                    continue

                uri = request.url.lower()

                # Look for m3u8 master playlist
                if not found_m3u8 and uri.endswith(".m3u8") and "master" in uri:
                    if uri not in self.captured_video_urls:
                        urls["m3u8"] = request.url
                        urls["headers"] = dict(request.headers)
                        found_m3u8 = True
                        continue

                # Look for vtt subtitles
                if not found_vtt and ".vtt" in uri and "thumbnail" not in uri:
                    if uri not in self.captured_subtitle_urls:
                        if not any(lang in uri for lang in self.OTHER_LANGS):
                            # Verify it's English if langdetect is available
                            if LANGDETECT_AVAILABLE:
                                try:
                                    content = requests.get(request.url, headers=dict(request.headers)).content
                                    if detect_lang(content.decode(self.ENCODING)) == self.subtitle_lang:
                                        urls["all-vtt"].append(request.url)
                                except:
                                    urls["all-vtt"].append(request.url)
                            else:
                                urls["all-vtt"].append(request.url)

            # Check if we found vtt
            if urls["all-vtt"] and not found_vtt:
                found_vtt = True

            attempt += 1
            if attempt in self.DOWNLOAD_REFRESH:
                self.driver.refresh()
            time.sleep(1)

        print()

        if not found_m3u8:
            print_error("No m3u8 stream found")
            return None

        if not found_vtt and not self.no_subtitles:
            print_warning("No subtitles found")
            if get_confirmation("Continue without subtitles? (y/n): "):
                self.no_subtitles = True
            else:
                return None

        # Select vtt if multiple found
        if urls["all-vtt"]:
            if len(urls["all-vtt"]) == 1:
                urls["vtt"] = urls["all-vtt"][0]
            else:
                print(f"\n{Fore.YELLOW}Multiple subtitle files found:{Style.RESET_ALL}")
                for i, vtt in enumerate(urls["all-vtt"], 1):
                    print(f"  {i}: {vtt}")
                selection = get_int_in_range("Select subtitle: ", 1, len(urls["all-vtt"]))
                urls["vtt"] = urls["all-vtt"][selection - 1]

        return urls

    def get_m3u8_variant(self, m3u8_url: str, headers: dict) -> str:
        """
        Extract the actual video variant URL from master m3u8.

        Args:
            m3u8_url: Master m3u8 URL
            headers: Request headers

        Returns:
            Variant m3u8 URL
        """
        try:
            response = requests.get(m3u8_url, headers=headers)
            lines = response.text.splitlines()

            for line in lines:
                if line.strip().endswith(".m3u8") and "iframe" not in line:
                    return urljoin(m3u8_url, line.strip())

            print_warning("No video variant found in master m3u8")
            return m3u8_url

        except Exception as e:
            print_error(f"Failed to get m3u8 variant: {e}")
            return m3u8_url

    # =========================================================================
    # EPISODE LIST BUILDING
    # =========================================================================

    def build_episode_list(
        self,
        anime: Anime,
        start_ep: int,
        end_ep: int,
        filename_format: str = "standard",
    ) -> List[Episode]:
        """
        Build list of Episode objects with URLs scraped from page.

        Args:
            anime: Anime object
            start_ep: Starting episode number
            end_ep: Ending episode number
            filename_format: Format type - 'full', 'standard', 'short', 'season', 'episode'

        Returns:
            List of Episode objects
        """
        scraped = self.get_episode_urls(anime.url, start_ep, end_ep)
        if not scraped:
            return []

        episodes = []
        for ep_num, ep_url, ep_title in scraped:
            # Use the new format_filename method
            filename = anime.format_filename(ep_num, ep_title, filename_format)
            filename = sanitize_filename(filename)

            episodes.append(Episode(
                number=ep_num,
                url=ep_url,
                title=ep_title,
                filename=filename,
            ))

        return episodes

    # =========================================================================
    # EXPORT FUNCTIONS
    # =========================================================================

    def save_to_csv(self, episodes: List[Episode], csv_path: str):
        """Save episode list to CSV."""
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Episode', 'URL', 'Title', 'Filename', 'Status'])
            for ep in episodes:
                writer.writerow([ep.number, ep.url, ep.title, ep.filename, ep.status])
        print_success(f"Saved episode list to {csv_path}")

    def save_to_json(self, anime: Anime, episodes: List[Episode], json_path: str):
        """Save anime and episode metadata to JSON."""
        data = {
            **anime.to_dict(),
            'episodes': [ep.to_dict() for ep in episodes]
        }
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        print_success(f"Saved metadata to {json_path}")

    # =========================================================================
    # CLEANUP
    # =========================================================================

    def cleanup(self):
        """Clean up resources (close Selenium driver if open)."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None
