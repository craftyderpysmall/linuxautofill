"""Load the config file, which holds secrets and so must be private."""

import pathlib
import re
import stat
import tomllib
from dataclasses import dataclass, field

DEFAULT_PATH = pathlib.Path.home() / ".config/linuxautofill/config.toml"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    clear_after: int = 60
    extra_keywords: list = field(default_factory=list)
    http_host: str = "0.0.0.0"
    http_port: int = 8787
    http_token: str = ""
    # (address, app password) pairs.
    gmail_accounts: list = field(default_factory=list)


def load(path=DEFAULT_PATH):
    try:
        mode = path.stat().st_mode
        with path.open("rb") as file:
            raw = tomllib.load(file)
    except FileNotFoundError:
        raise ConfigError(f"{path} not found; copy config.example.toml there") from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from None

    if stat.S_IMODE(mode) & 0o077:
        raise ConfigError(f"{path} holds secrets; run: chmod 600 {path}")

    http = raw.get("http", {})
    # [gmail] is one account and [[gmail]] is a list of them.
    gmail = raw.get("gmail", [])
    accounts = [gmail] if isinstance(gmail, dict) else gmail
    config = Config(
        clear_after=raw.get("clear_after", 60),
        extra_keywords=[re.escape(word) for word in raw.get("extra_keywords", [])],
        http_host=http.get("host", "0.0.0.0"),
        http_port=http.get("port", 8787),
        http_token=http.get("token", ""),
        # Google displays app passwords with spaces.
        gmail_accounts=[
            (account["address"], account.get("app_password", "").replace(" ", ""))
            for account in accounts
            if account.get("address")
        ],
    )
    if not config.http_token and not config.gmail_accounts:
        raise ConfigError(f"{path}: set up at least one of [http] or [gmail]")
    for address, password in config.gmail_accounts:
        if not password:
            raise ConfigError(f"{path}: {address} needs an app_password")
    return config
