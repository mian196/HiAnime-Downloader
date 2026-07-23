import re
from dataclasses import dataclass, asdict
from typing import Optional, Dict

def extract_season_from_name(name: str) -> int:
    """Extract season number from anime name.

    Matches patterns like:
    - "Season 2", "Season 02"
    - "S2", "S02"
    - "2nd Season", "3rd Season"
    - "Part 2", "Part 02"
    """
    # Pattern: "Season X" or "Season XX"
    match = re.search(r'\bseason\s*(\d{1,2})\b', name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Pattern: "SX" or "SXX" (but not part of a word)
    match = re.search(r'\bS(\d{1,2})\b', name)
    if match:
        return int(match.group(1))

    # Pattern: "Xnd/rd/th Season" (2nd Season, 3rd Season, etc.)
    match = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)\s+season\b', name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Pattern: "Part X"
    match = re.search(r'\bpart\s*(\d{1,2})\b', name, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return 1


@dataclass
class Anime:
    name: str
    url: str
    sub_episodes: int
    dub_episodes: int
    short_name: str = ""
    download_type: str = "sub"
    season_number: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    def format_filename(self, ep_num: int, ep_title: str = "", fmt: str = "standard", total_episodes: int = 0) -> str:
        is_series = (self.sub_episodes > 1 or self.dub_episodes > 1 or ep_num > 1)
        if total_episodes == 1 and not is_series:
            return self.name

        season_ep = f"S{self.season_number:02d}E{ep_num:02d}"

        if fmt == "episode":
            return f"E{ep_num:02d}"

        elif fmt == "season":
            return season_ep

        elif fmt == "short":
            name = self.short_name if self.short_name else self.name.split()[0]
            return f"{name} - {season_ep}"

        # Clean the title name to avoid duplicate season keywords in standard/full filenames
        clean_name = self.name
        clean_name = re.sub(r'\s*\b(?:season|part|S)\s*\d{1,2}\b.*$', '', clean_name, flags=re.IGNORECASE)
        clean_name = re.sub(r'\s*\b\d{1,2}(?:st|nd|rd|th)\s+season\b.*$', '', clean_name, flags=re.IGNORECASE)
        clean_name = clean_name.strip()
        if not clean_name:
            clean_name = self.name

        if fmt == "full":
            base = f"{clean_name} - {season_ep}"
            if ep_title and ep_title != f"Episode {ep_num}":
                safe_title = ep_title[:50]
                return f"{base} - {safe_title}"
            return base

        else:
            return f"{clean_name} - {season_ep}"


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
    m3u8_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    output_dir: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'number': self.number,
            'url': self.url,
            'title': self.title,
            'filename': self.filename,
            'status': self.status,
        }
