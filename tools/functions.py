import os
import sys
from colorama import Fore, Style


def get_confirmation(prompt: str) -> bool:
    while True:
        resp = input(prompt).strip().lower()
        if resp in ('y', 'yes'):
            return True
        if resp in ('n', 'no'):
            return False
        print(f"{Fore.RED}Please enter 'y' or 'n'{Style.RESET_ALL}")


def get_int_in_range(prompt: str, min_val: int = 1, max_val: int = 9999) -> int:
    while True:
        try:
            val = int(input(prompt))
            if min_val <= val <= max_val:
                return val
            print(f"{Fore.RED}Please enter a number between {min_val} and {max_val}{Style.RESET_ALL}")
        except ValueError:
            print(f"{Fore.RED}Please enter a valid number{Style.RESET_ALL}")


def sanitize_filename(name: str) -> str:
    invalid = '<>:"/\\|?*'
    for char in invalid:
        name = name.replace(char, '_')
    name = name.replace('[', '').replace(']', '')
    return name.strip()


def safe_remove(path: str) -> bool:
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except Exception as e:
        print(f"{Fore.RED}Failed to remove {path}: {e}{Style.RESET_ALL}")
    return False


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def print_info(msg: str):
    print(f"{Fore.CYAN}[INFO] {msg}{Style.RESET_ALL}")


def print_success(msg: str):
    print(f"{Fore.GREEN}[SUCCESS] {msg}{Style.RESET_ALL}")


def print_error(msg: str):
    print(f"{Fore.RED}[ERROR] {msg}{Style.RESET_ALL}")


def print_warning(msg: str):
    print(f"{Fore.YELLOW}[WARNING] {msg}{Style.RESET_ALL}")