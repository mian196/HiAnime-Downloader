"""
Modern Rich TUI Component for KAA Downloader
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich import box

console = Console(highlight=False)


def print_banner():
    """Render a modern gradient banner for KAA Downloader."""
    banner_text = Text()
    banner_text.append("KICKASSANIME DOWNLOADER\n", style="bold cyan")
    banner_text.append("High-Performance Parallel Downloader with Subtitle & Chapter Muxing", style="dim italic")

    panel = Panel(
        banner_text,
        box=box.ROUNDED,
        border_style="bold magenta",
        subtitle="[bold white]v1.0.0[/bold white]",
        subtitle_align="right",
        padding=(1, 4),
    )
    console.print()
    console.print(panel)
    console.print()


def print_info(msg: str):
    console.print(f"[bold cyan][INFO][/bold cyan] {msg}")


def print_success(msg: str):
    console.print(f"[bold green][SUCCESS][/bold green] {msg}")


def print_error(msg: str):
    console.print(f"[bold red][ERROR][/bold red] {msg}")


def print_warning(msg: str):
    console.print(f"[bold yellow][WARNING][/bold yellow] {msg}")


def print_config_table(cfg: Dict[str, Any], global_path: Path, local_path: Optional[Path] = None):
    """Render active configuration settings in a styled Rich Table."""
    table = Table(title="Active Configuration", box=box.ROUNDED, header_style="bold magenta")
    table.add_column("Setting", style="bold white", width=25)
    table.add_column("Value", style="cyan")

    global_status = "[bold green]Exists[/bold green]" if global_path.exists() else "[dim]Not Found[/dim]"
    table.add_row("Global Config Path", f"{global_path} {global_status}")
    if local_path:
        table.add_row("Local Config Override", f"{local_path} [bold green]Active[/bold green]")

    table.add_row("Download Workers", f"[bold yellow]{cfg.get('download_workers')}[/bold yellow] threads")
    table.add_row("Embed Workers", f"[bold yellow]{cfg.get('embed_workers')}[/bold yellow] processes")
    table.add_row("Output Directory", f"[bold underline]{cfg.get('output_dir')}[/bold underline]")
    table.add_row("Resolution", f"[bold green]{cfg.get('resolution')}p[/bold green]")
    table.add_row("Audio Type", f"[bold magenta]{str(cfg.get('audio_type')).upper()}[/bold magenta]")
    table.add_row("Subtitle Language", f"[bold cyan]{cfg.get('subtitle_lang')}[/bold cyan]")
    table.add_row("Download Delay", f"{cfg.get('download_delay')} sec")
    table.add_row("Download All", "[green]YES[/green]" if cfg.get('download_all') else "[yellow]NO[/yellow]")
    table.add_row("Embed Chapters", "[green]ENABLED[/green]" if cfg.get('embed_chapters') else "[red]DISABLED[/red]")
    table.add_row("Filename Format", f"[bold blue]{cfg.get('filename_format')}[/bold blue]")
    table.add_row("Verbose Logging", "[green]YES[/green]" if cfg.get('verbose') else "[dim]NO[/dim]")
    table.add_row("Log Level", f"[bold dim]{cfg.get('log_level')}[/bold dim]")

    console.print()
    console.print(table)
    console.print()


def print_search_results(results: List[Any]) -> Optional[Any]:
    """Render interactive anime search results in a styled Table."""
    if not results:
        print_warning("No search results found.")
        return None

    table = Table(title="Search Results", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("#", justify="center", style="bold yellow", width=4)
    table.add_column("Anime Title", style="bold white")
    table.add_column("Sub Episodes", justify="center", style="green", width=14)
    table.add_column("Dub Episodes", justify="center", style="magenta", width=14)

    for idx, anime in enumerate(results, 1):
        table.add_row(
            str(idx),
            anime.name,
            f"{anime.sub_episodes} eps",
            f"{anime.dub_episodes} eps",
        )

    console.print()
    console.print(table)
    console.print()

    selection = IntPrompt.ask(
        "[bold cyan]Select anime number[/bold cyan]",
        choices=[str(i) for i in range(1, len(results) + 1)],
        show_choices=False,
    )
    return results[int(selection) - 1]


def print_summary_card(
    anime_name: str,
    season: int,
    start_ep: int,
    end_ep: int,
    download_type: str,
    resolution: str,
    output_dir: str,
):
    """Render pre-download execution summary inside a Rich Panel card."""
    summary_text = (
        f"[bold white]Anime:[/bold white] [bold cyan]{anime_name}[/bold cyan]\n"
        f"[bold white]Season:[/bold white] [bold yellow]S{season:02d}[/bold yellow]\n"
        f"[bold white]Episodes:[/bold white] [bold green]EP{start_ep:02d} to EP{end_ep:02d}[/bold green]\n"
        f"[bold white]Format:[/bold white] [bold magenta]{download_type.upper()}[/bold magenta] @ [bold yellow]{resolution}p[/bold yellow]\n"
        f"[bold white]Output Directory:[/bold white] [underline]{output_dir}[/underline]"
    )
    card = Panel(
        summary_text,
        title="[bold green]Download Task Summary[/bold green]",
        box=box.ROUNDED,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print()
    console.print(card)
    console.print()


def create_progress_bar() -> Progress:
    """Create a modern Rich multi-task progress bar."""
    return Progress(
        SpinnerColumn("dots"),
        TextColumn("[bold cyan]{task.description}[/bold cyan]"),
        BarColumn(bar_width=35, style="dim white", complete_style="bold magenta", finished_style="bold green"),
        TaskProgressColumn("[bold yellow]{task.percentage:>3.0f}%[/bold yellow]"),
        TimeRemainingColumn(),
        console=console,
        expand=False,
    )


def run_config_wizard() -> Path:
    """Guided TUI Configuration Wizard."""
    from config import get_global_config_path, DEFAULT_CONFIG
    import yaml

    console.print()
    wizard_panel = Panel(
        "[bold cyan]KAA Downloader Setup Wizard[/bold cyan]\n"
        "Configure your preferred settings. Press [bold green]Enter[/bold green] on any prompt to accept default.",
        title="⚙️ Configuration Setup",
        box=box.ROUNDED,
        border_style="magenta",
        padding=(1, 2),
    )
    console.print(wizard_panel)
    console.print()

    # 1. Workers & Threads
    download_workers = IntPrompt.ask(
        "[bold white]Parallel Download Threads[/bold white] (1-16)",
        default=DEFAULT_CONFIG["download_workers"],
    )
    embed_workers = IntPrompt.ask(
        "[bold white]Parallel Subtitle Muxing Processes[/bold white] (1-8)",
        default=DEFAULT_CONFIG["embed_workers"],
    )

    # 2. Preferred Video Quality & Language
    resolution = Prompt.ask(
        "[bold white]Preferred Video Resolution[/bold white]",
        choices=["720", "1080"],
        default=DEFAULT_CONFIG["resolution"],
    )
    audio_type = Prompt.ask(
        "[bold white]Preferred Audio Language[/bold white]",
        choices=["sub", "dub"],
        default=DEFAULT_CONFIG["audio_type"],
    )
    subtitle_lang = Prompt.ask(
        "[bold white]Subtitle Language Code[/bold white]",
        default=DEFAULT_CONFIG["subtitle_lang"],
    )

    # 3. Output Directory & Filename Format
    output_dir = Prompt.ask(
        "[bold white]Default Output Directory[/bold white]",
        default=DEFAULT_CONFIG["output_dir"],
    )
    filename_format = Prompt.ask(
        "[bold white]Filename Format[/bold white]",
        choices=["episode", "season", "short", "standard", "full"],
        default=DEFAULT_CONFIG["filename_format"],
    )

    # 4. Features & Toggles
    embed_chapters = Confirm.ask(
        "[bold white]Embed Opening/Ending Chapter Skip Times?[/bold white]",
        default=DEFAULT_CONFIG["embed_chapters"],
    )
    download_delay = float(Prompt.ask(
        "[bold white]Download Throttle Delay (seconds)[/bold white]",
        default=str(DEFAULT_CONFIG["download_delay"]),
    ))

    # Construct YAML content
    config_dict = {
        "download": {
            "download_workers": download_workers,
            "embed_workers": embed_workers,
            "resolution": resolution,
            "audio_type": audio_type,
            "subtitle_lang": subtitle_lang,
            "download_delay": download_delay,
            "download_timeout": 3600,
            "embed_timeout": 600,
            "download_all": True,
            "no_subtitles": False,
            "embed_chapters": embed_chapters,
            "default_season": 0,
        },
        "output": {
            "output_dir": output_dir,
            "filename_format": filename_format,
        },
        "logging": {
            "verbose": True,
            "log_level": "INFO",
            "log_timestamps": True,
        }
    }

    target_path = get_global_config_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with open(target_path, "w", encoding="utf-8") as f:
        yaml.dump(config_dict, f, default_flow_style=False, sort_keys=False)

    console.print()
    print_success(f"Configuration saved successfully to: [bold underline]{target_path}[/bold underline]")
    console.print()

    return target_path

