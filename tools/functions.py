"""Utility functions for the anime downloader."""

import os
import sys
from colorama import Fore, Style


def get_confirmation(prompt: str) -> bool:
    """Get yes/no confirmation from user."""
    while True:
        resp = input(prompt).strip().lower()
        if resp in ('y', 'yes'):
            return True
        if resp in ('n', 'no'):
            return False
        print(f"{Fore.RED}Please enter 'y' or 'n'{Style.RESET_ALL}")


def get_int_in_range(prompt: str, min_val: int = 1, max_val: int = 9999) -> int:
    """Get integer input from user within a range."""
    while True:
        try:
            val = int(input(prompt))
            if min_val <= val <= max_val:
                return val
            print(f"{Fore.RED}Please enter a number between {min_val} and {max_val}{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")


def sanitize_filename(name: str) -> str:
    """Remove invalid filename characters."""
    invalid = '<>:"/\\|?*'
    for char in invalid:
        name = name.replace(char, '_')
    # Also remove other problematic characters
    name = name.replace('[', '').replace(']', '')
    return name.strip()


def safe_remove(path: str) -> bool:
    """Safely remove a file, returning True if successful."""
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception as e:
        print(f"{Fore.RED}Failed to remove {path}: {e}{Style.RESET_ALL}")
    return False


def clear_screen():
    """Clear the terminal screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_info(msg: str):
    print(f"{Fore.CYAN}[INFO] {msg}{Style.RESET_ALL}")


def print_success(msg: str):
    print(f"{Fore.GREEN}[SUCCESS] {msg}{Style.RESET_ALL}")


def print_error(msg: str):
    print(f"{Fore.RED}[ERROR] {msg}{Style.RESET_ALL}")


def print_warning(msg: str):
    print(f"{Fore.YELLOW}[WARNING] {msg}{Style.RESET_ALL}")
