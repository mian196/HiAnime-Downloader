from colorama import Fore, Style


class YTDLogger:
    def __init__(self, prefix: str = ""):
        self.prefix = prefix

    def debug(self, msg: str):
        if msg.startswith('[debug]'):
            return
        if any(x in msg for x in ['[download]', '[hlsnative]', '[info]', 'Destination:']):
            if self.prefix:
                print(f"{Fore.YELLOW}[{self.prefix}]{Style.RESET_ALL} {msg}")
            else:
                print(f"{Fore.CYAN}{msg}{Style.RESET_ALL}")

    def info(self, msg: str):
        if self.prefix:
            print(f"{Fore.YELLOW}[{self.prefix}]{Style.RESET_ALL} {msg}")
        else:
            print(f"{Fore.CYAN}{msg}{Style.RESET_ALL}")

    def warning(self, msg: str):
        print(f"{Fore.YELLOW}[WARNING] {msg}{Style.RESET_ALL}")

    def error(self, msg: str):
        print(f"{Fore.RED}[ERROR] {msg}{Style.RESET_ALL}")
