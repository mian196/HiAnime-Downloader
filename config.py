import os
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from platformdirs import user_config_dir
from dotenv import load_dotenv

APP_NAME = "kaa-downloader"

# Attempt loading legacy .env if present
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)


def get_global_config_path() -> Path:
    """Return OS-standard user configuration path (~/.config/kaa-downloader/config.yaml or %APPDATA%/kaa-downloader/config.yaml)."""
    return Path(user_config_dir(APP_NAME)) / "config.yaml"


def get_local_config_path() -> Optional[Path]:
    """Return local config.yaml or kaa.yaml if present in current working directory."""
    cwd = Path.cwd()
    for name in ("config.yaml", "config.yml", "kaa.yaml", "kaa.yml"):
        p = cwd / name
        if p.exists():
            return p
    return None


DEFAULT_CONFIG: Dict[str, Any] = {
    "download_workers": 6,
    "embed_workers": 4,
    "resolution": "720",
    "audio_type": "sub",
    "subtitle_lang": "en",
    "download_delay": 2.0,
    "download_timeout": 3600,
    "embed_timeout": 600,
    "download_all": True,
    "no_subtitles": False,
    "embed_chapters": True,
    "default_season": 0,
    "output_dir": "output",
    "filename_format": "standard",
    "verbose": True,
    "log_level": "INFO",
    "log_timestamps": True,
}


def load_yaml_file(path: Path) -> Dict[str, Any]:
    """Load flat dictionary from structured YAML file."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Flatten nested sections (download, output, logging)
        flat = {}
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, dict):
                    for sub_k, sub_v in val.items():
                        flat[sub_k] = sub_v
                else:
                    flat[key] = val
        return flat
    except Exception as e:
        print(f"Warning: Failed to parse YAML config at {path}: {e}")
        return {}


def init_global_config(overwrite: bool = False) -> Path:
    """Initialize default config.yaml at global OS config location."""
    target_path = get_global_config_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if target_path.exists() and not overwrite:
        return target_path

    template_content = """# KAA Downloader Configuration
# Generated configuration file

download:
  download_workers: 6      # Parallel download threads
  embed_workers: 4         # Parallel FFmpeg subtitle embedding processes
  resolution: "720"        # Preferred video resolution (720, 1080)
  audio_type: "sub"        # Preferred audio format (sub, dub)
  subtitle_lang: "en"      # Subtitle language code
  download_delay: 2.0      # Delay between downloads (seconds)
  download_timeout: 3600   # Max download timeout per episode (seconds)
  embed_timeout: 600       # Max embed timeout per episode (seconds)
  download_all: true       # Download all episodes by default
  no_subtitles: false      # Disable subtitle extraction/embedding
  embed_chapters: true     # Embed skip-time chapters into MKV container
  default_season: 0        # Season number (0 = auto-detect)

output:
  output_dir: "output"     # Default output directory for videos
  filename_format: "standard" # Options: episode, season, short, standard, full

logging:
  verbose: true            # Show detailed worker logs
  log_level: "INFO"        # Options: DEBUG, INFO, WARNING, ERROR
  log_timestamps: true     # Include timestamps in log output
"""
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(template_content)
    return target_path


def load_config() -> Dict[str, Any]:
    """
    Load resolved configuration based on priority:
    Environment Variables / .env > Local YAML > Global YAML > Defaults
    """
    config = DEFAULT_CONFIG.copy()

    # 1. Load Global YAML
    global_path = get_global_config_path()
    config.update(load_yaml_file(global_path))

    # 2. Load Local YAML (overrides global)
    local_path = get_local_config_path()
    if local_path:
        config.update(load_yaml_file(local_path))

    # 3. Apply Environment Variable overrides (KAA_ or legacy names)
    def parse_bool(val: str) -> bool:
        return str(val).lower() in ("true", "1", "yes")

    env_mappings = {
        "download_workers": (["KAA_DOWNLOAD_WORKERS", "DOWNLOAD_WORKERS"], int),
        "embed_workers": (["KAA_EMBED_WORKERS", "EMBED_WORKERS"], int),
        "output_dir": (["KAA_OUTPUT_DIR", "OUTPUT_DIR"], str),
        "resolution": (["KAA_RESOLUTION", "RESOLUTION"], str),
        "audio_type": (["KAA_AUDIO_TYPE", "AUDIO_TYPE"], str),
        "subtitle_lang": (["KAA_SUBTITLE_LANG", "SUBTITLE_LANG"], str),
        "download_delay": (["KAA_DOWNLOAD_DELAY", "DOWNLOAD_DELAY"], float),
        "download_timeout": (["KAA_DOWNLOAD_TIMEOUT", "DOWNLOAD_TIMEOUT"], int),
        "embed_timeout": (["KAA_EMBED_TIMEOUT", "EMBED_TIMEOUT"], int),
        "download_all": (["KAA_DOWNLOAD_ALL", "DOWNLOAD_ALL"], parse_bool),
        "verbose": (["KAA_VERBOSE", "VERBOSE"], parse_bool),
        "log_level": (["KAA_LOG_LEVEL", "LOG_LEVEL"], lambda x: str(x).upper()),
        "log_timestamps": (["KAA_LOG_TIMESTAMPS", "LOG_TIMESTAMPS"], parse_bool),
        "no_subtitles": (["KAA_NO_SUBTITLES", "NO_SUBTITLES"], parse_bool),
        "embed_chapters": (["KAA_EMBED_CHAPTERS", "EMBED_CHAPTERS"], parse_bool),
        "default_season": (["KAA_DEFAULT_SEASON", "DEFAULT_SEASON"], int),
        "filename_format": (["KAA_FILENAME_FORMAT", "FILENAME_FORMAT"], lambda x: str(x).lower()),
    }

    for key, (env_vars, converter) in env_mappings.items():
        for ev in env_vars:
            val = os.getenv(ev)
            if val is not None:
                try:
                    config[key] = converter(val)
                    break
                except Exception:
                    pass

    return config


# Resolved active configuration
_cfg = load_config()

MAX_DOWNLOAD_WORKERS = int(_cfg["download_workers"])
MAX_EMBED_WORKERS = int(_cfg["embed_workers"])
DEFAULT_OUTPUT_DIR = str(_cfg["output_dir"])
RESOLUTION = str(_cfg["resolution"])
AUDIO_TYPE = str(_cfg["audio_type"])
SUBTITLE_LANG = str(_cfg["subtitle_lang"])
DOWNLOAD_DELAY = float(_cfg["download_delay"])
DOWNLOAD_TIMEOUT = int(_cfg["download_timeout"])
EMBED_TIMEOUT = int(_cfg["embed_timeout"])

DOWNLOAD_ALL = bool(_cfg["download_all"])
VERBOSE = bool(_cfg["verbose"])
LOG_LEVEL = str(_cfg["log_level"])
LOG_TIMESTAMPS = bool(_cfg["log_timestamps"])
NO_SUBTITLES = bool(_cfg["no_subtitles"])
EMBED_CHAPTERS = bool(_cfg["embed_chapters"])
DEFAULT_SEASON = int(_cfg["default_season"])
FILENAME_FORMAT = str(_cfg["filename_format"])


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


def print_config(active_config: Optional[Dict[str, Any]] = None):
    try:
        from tools.ui import print_config_table
        cfg = active_config or _cfg
        global_path = get_global_config_path()
        local_path = get_local_config_path()
        print_config_table(cfg, global_path, local_path)
    except Exception:
        cfg = active_config or _cfg
        print(f"Download Workers: {cfg.get('download_workers')}")
        print(f"Embed Workers: {cfg.get('embed_workers')}")
        print(f"Output Dir: {cfg.get('output_dir')}")
        print(f"Resolution: {cfg.get('resolution')}p")