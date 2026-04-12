#!/usr/bin/env python3
"""
px - Environment Variable Configuration Tool

Architecture:
    - Proxy: scheme and url_prefix only (constant data)
    - ProxyList: list of proxies
    - Each Mode gets args and processes host/port in post_init
    - process_args() handles host/ip/port smart resolution
    - Base class dispatches set/unset to separate methods
    - Interface returns str (not list[str]), each Mode formats itself
    - Mode can have sub-parser (e.g., systemd's service and mode)
    - Supports --credential/-c for credential passing
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Type


# =============================================================================
# Data Models
# =============================================================================


@dataclass(frozen=True)
class Proxy:
    scheme: str
    url_prefix: str

    def full_url(self, host: str, port: str | None) -> str:
        if port is None:
            return f"{self.url_prefix}{host}"
        return f"{self.url_prefix}{host}:{port}"


@dataclass
class ProxyList:
    proxies: list[Proxy]


DEFAULT_PROXIES = ProxyList(
    [
        Proxy("http", "http://"),
        Proxy("https", "http://"),
        Proxy("socks5h", "socks5h://"),
    ]
)


# =============================================================================
# Output Modes
# =============================================================================


class Mode(ABC):
    """Abstract base class for output modes."""

    NAME: str = ""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self._post_init()

    def _post_init(self):
        """Subclasses override for initialization (set host/port defaults)."""
        pass

    @classmethod
    def get_parser(cls) -> Optional[argparse.ArgumentParser]:
        return None

    def eval(self, action: str) -> str:
        return self._eval_set() if action == "set" else self._eval_unset()

    def echo(self, action: str) -> str:
        return self._echo_set() if action == "set" else self._echo_unset()

    @abstractmethod
    def _eval_set(self) -> str:
        return ""

    @abstractmethod
    def _eval_unset(self) -> str:
        return ""

    @abstractmethod
    def _echo_set(self) -> str:
        return ""

    @abstractmethod
    def _echo_unset(self) -> str:
        return ""


class ProxyMode(Mode):
    """Base class for modes that work with proxies."""

    SUPPORTED_SCHEMES: set[str] = set()

    def __init__(self, args: argparse.Namespace):
        self.proxies = DEFAULT_PROXIES
        super().__init__(args)

    def supports(self, scheme: str) -> bool:
        return scheme in self.SUPPORTED_SCHEMES

    def get_proxies(self) -> list[Proxy]:
        return [p for p in self.proxies.proxies if self.supports(p.scheme)]


class ShellMode(ProxyMode):
    """Shell environment variable mode - sets both lowercase and uppercase vars."""

    NAME = "shell"
    SUPPORTED_SCHEMES = {"http", "https", "socks5h"}
    DEFAULT_PORT = "7890"

    VAR_MAP = {
        "http": ("http_proxy", "HTTP_PROXY"),
        "https": ("https_proxy", "HTTPS_PROXY"),
        "socks5h": ("socks5h_proxy", "SOCKS5H_PROXY"),
    }

    def _post_init(self):
        if self.args.port == "default":
            self.args.port = self.DEFAULT_PORT

    def _eval_set(self) -> str:
        lines = []
        for proxy in self.get_proxies():
            var_names = self.VAR_MAP.get(proxy.scheme)
            if not var_names:
                continue
            url = proxy.full_url(self.args.host, self.args.port)
            for var_name in var_names:
                lines.append(f'export {var_name}="{url}"')
        return "\n".join(lines)

    def _eval_unset(self) -> str:
        lines = []
        for proxy in self.get_proxies():
            var_names = self.VAR_MAP.get(proxy.scheme)
            if not var_names:
                continue
            for var_name in var_names:
                lines.append(f"unset {var_name}")
        return "\n".join(lines)

    def _echo_set(self) -> str:
        return self._eval_set()

    def _echo_unset(self) -> str:
        return self._eval_unset()


class NpmMode(ShellMode):
    """NPM environment variable mode - inherits ShellMode, overrides VAR_MAP."""

    NAME = "npm"
    SUPPORTED_SCHEMES = {"http", "https"}

    VAR_MAP = {
        "http": ("npm_config_proxy",),
        "https": ("npm_config_https_proxy",),
    }


class OpenaiMode(ProxyMode):
    """OpenAI API configuration mode with VAR_MAP support for multiple providers."""

    NAME = "openai"
    SUPPORTED_SCHEMES = {"http"}
    DEFAULT_PORT = "8137"
    DEFAULT_ENDPOINT = "/v1"

    VAR_MAP = {
        "http": ("OPENAI_API_BASE", "OPENAI_API_KEY", "/v1"),
    }

    def _post_init(self):
        if self.args.port == "default":
            self.args.port = self.DEFAULT_PORT
        self.endpoint = getattr(self.args, "endpoint", None) or self.DEFAULT_ENDPOINT

    @classmethod
    def get_parser(cls) -> "HelpOnErrorParser":
        parser = HelpOnErrorParser(prog="px -m openai", add_help=False)
        parser.add_argument(
            "--endpoint",
            default=cls.DEFAULT_ENDPOINT,
            help=f"API endpoint path (default: {cls.DEFAULT_ENDPOINT})",
        )
        return parser

    def _get_credential(self) -> str | None:
        return getattr(self.args, "credential", None)

    def _eval_set(self) -> str:
        lines = []
        for proxy in self.get_proxies():
            var_config = self.VAR_MAP.get(proxy.scheme)
            if not var_config:
                continue
            base_var, key_var, default_endpoint = var_config

            base_url = proxy.full_url(self.args.host, self.args.port)
            endpoint = self.endpoint if self.endpoint else default_endpoint
            if not endpoint.startswith("/"):
                endpoint = "/" + endpoint
            api_base = f"{base_url}{endpoint}"

            lines.append(f'export {base_var}="{api_base}"')
            credential = self._get_credential()
            if credential:
                lines.append(f'export {key_var}="{credential}"')
        return "\n".join(lines)

    def _eval_unset(self) -> str:
        lines = []
        for proxy in self.get_proxies():
            var_config = self.VAR_MAP.get(proxy.scheme)
            if not var_config:
                continue
            base_var, key_var, _ = var_config
            lines.append(f"unset {base_var} {key_var}")
        return "\n".join(lines) if lines else ""

    def _echo_set(self) -> str:
        return self._eval_set()

    def _echo_unset(self) -> str:
        return self._eval_unset()


class AnthropicMode(OpenaiMode):
    """Anthropic API configuration mode - inherits OpenaiMode, overrides VAR_MAP."""

    NAME = "anthropic"
    DEFAULT_PORT = "8137"

    VAR_MAP = {
        "http": ("ANTHROPIC_API_BASE", "ANTHROPIC_API_KEY", "/v1"),
    }


class GradleMode(ProxyMode):
    """Gradle configuration mode."""

    NAME = "gradle"
    SUPPORTED_SCHEMES = {"http", "https", "socks5h"}

    GRADLE_SCHEME_MAP = {
        "http": "http",
        "https": "https",
        "socks5h": "sock",
    }

    def _eval_set(self) -> str:
        return ""

    def _eval_unset(self) -> str:
        return ""

    def _echo_set(self) -> str:
        lines = ["# Add the following to gradle.properties:"]
        for proxy in self.get_proxies():
            gradle_scheme = self.GRADLE_SCHEME_MAP.get(proxy.scheme, proxy.scheme)
            lines.append(f"systemProp.{gradle_scheme}.proxyHost={self.args.host}")
            if self.args.port is not None:
                lines.append(f"systemProp.{gradle_scheme}.proxyPort={self.args.port}")
        return "\n".join(lines)

    def _echo_unset(self) -> str:
        return ""


class SystemdMode(ProxyMode):
    """Systemd service configuration mode."""

    NAME = "systemd"
    SUPPORTED_SCHEMES = {"http", "https", "socks5h"}
    DEFAULT_PORT = "7890"

    VAR_MAP = {
        "http": ("http_proxy", "HTTP_PROXY"),
        "https": ("https_proxy", "HTTPS_PROXY"),
        "socks5h": ("socks5h_proxy", "SOCKS5H_PROXY"),
    }

    def _post_init(self):
        if self.args.port == "default":
            self.args.port = self.DEFAULT_PORT

        self.service = getattr(self.args, "service", None) or "docker.service"
        self.mode = getattr(self.args, "mode", None) or "system"

        if self.service.startswith("-"):
            print(f"Error: Invalid service name '{self.service}'", file=sys.stderr)
            sys.exit(2)

        if self.mode not in ("system", "user"):
            print(
                f"Error: Invalid mode '{self.mode}', must be 'system' or 'user'",
                file=sys.stderr,
            )
            sys.exit(2)

    @classmethod
    def get_parser(cls) -> "HelpOnErrorParser":
        parser = HelpOnErrorParser(prog="px -m systemd", add_help=False)
        parser.add_argument(
            "service",
            nargs="?",
            default="docker.service",
            help="Service name (default: docker.service)",
        )
        parser.add_argument(
            "mode",
            nargs="?",
            choices=["system", "user"],
            default="system",
            help="Systemd mode: system or user (default: system)",
        )
        return parser

    def _eval_set(self) -> str:
        return ""

    def _eval_unset(self) -> str:
        return ""

    def _echo_set(self) -> str:
        lines = []
        if self.mode == "system":
            lines.append(f"sudo systemctl daemon-reload")
            lines.append(f"sudo systemctl restart {self.service}")

            for proxy in self.get_proxies():
                url = proxy.full_url(self.args.host, self.args.port)
                var_names = self.VAR_MAP.get(proxy.scheme, ())
                for var_name in var_names:
                    lines.append(
                        f"echo 'Environment=\"{var_name}={url}\"' | sudo tee -a /run/systemd/system/{self.service}.d/override.conf"
                    )
        else:
            lines.append(f"mkdir -p $HOME/.config/systemd/user/{self.service}.d")
            lines.append(
                f"$EDITOR $HOME/.config/systemd/user/{self.service}.d/override.conf"
            )
            lines.append("[Service]")

            for proxy in self.get_proxies():
                url = proxy.full_url(self.args.host, self.args.port)
                var_names = self.VAR_MAP.get(proxy.scheme, ())
                for var_name in var_names:
                    lines.append(f'Environment="{var_name}={url}"')
        return "\n".join(lines)

    def _echo_unset(self) -> str:
        lines = []
        if self.mode == "system":
            for proxy in self.get_proxies():
                var_names = self.VAR_MAP.get(proxy.scheme, ())
                for var_name in var_names:
                    lines.append(
                        f"sudo sed -i '/Environment=\"{var_name}=/d' /run/systemd/system/{self.service}.d/override.conf"
                    )
        return "\n".join(lines)


# =============================================================================
# Registry
# =============================================================================

MODES: dict[str, Type[Mode]] = {
    m.NAME: m
    for m in [ShellMode, GradleMode, NpmMode, SystemdMode, OpenaiMode, AnthropicMode]
}


# =============================================================================
# WSL Detection
# =============================================================================


def detect_wsl_ip() -> Optional[str]:
    """Detect WSL2 host IP."""
    try:
        r = subprocess.run(
            ["wslinfo", "--networking-mode"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip() == "mirrored":
            return "localhost"
    except:
        pass

    try:
        r = subprocess.run(["uname", "-a"], capture_output=True, text=True, timeout=2)
        if "wsl2" in r.stdout.lower():
            r = subprocess.run(
                ["ip", "route", "show"], capture_output=True, text=True, timeout=2
            )
            for line in r.stdout.split("\n"):
                if "default" in line:
                    parts = line.split()
                    for i, p in enumerate(parts):
                        if p == "via" and i + 1 < len(parts):
                            return parts[i + 1]
    except:
        pass
    return None


# =============================================================================
# Args Processing
# =============================================================================


def process_args(args: argparse.Namespace) -> argparse.Namespace:
    """
    Process args to resolve host, ip, and port.

    Priority:
    1. --host (-H): "ip:port" or "ip" - overrides both ip and port
    2. --ip (-i): specific IP/host
    3. Auto-detect: WSL IP or localhost

    Port resolution:
    - If -H specifies port: use that port
    - If -H without port and no -p: port = None (no port)
    - If -p "none": port = None (no port)
    - If -p specific value: use that value
    - If -p not specified and no -H: port stays as "default" (Mode will set default)
    """
    if args.host_str:
        if ":" in args.host_str:
            host_parts = args.host_str.rsplit(":", 1)
            args.host = host_parts[0]
            args.port = host_parts[1]
        else:
            args.host = args.host_str
            if args.port == "default":
                args.port = None
    else:
        args.host = args.ip or detect_wsl_ip()
        if not args.host:
            print("# Warning: Cannot detect WSL IP, using localhost", file=sys.stderr)
            args.host = "localhost"

    if args.port == "none":
        args.port = None

    return args


# =============================================================================
# CLI
# =============================================================================


class HelpOnErrorParser(argparse.ArgumentParser):
    """Custom ArgumentParser that returns exit 2 for help instead of 0."""

    def print_help(self, file=None):
        super().print_help(file)
        sys.exit(2)

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


def parse_mode_args(
    mode_class: Type[Mode], argv: list[str]
) -> tuple[argparse.Namespace, list[str]]:
    """Parse mode-specific arguments (similar to parse_known_args interface)."""
    parser = mode_class.get_parser()
    if parser is None:
        return argparse.Namespace(), argv

    mode_args, unknown_args = parser.parse_known_args(argv)
    return mode_args, unknown_args


def merge_args_with_mode_args(
    args: argparse.Namespace, mode_args: argparse.Namespace | None
) -> argparse.Namespace:
    """Merge main parser args with mode-specific args (mode args take precedence)."""
    if mode_args is None:
        return args

    merged = argparse.Namespace()

    for attr in dir(args):
        if not attr.startswith("_"):
            setattr(merged, attr, getattr(args, attr))

    for attr in dir(mode_args):
        if not attr.startswith("_"):
            value = getattr(mode_args, attr)
            if value is not None:
                setattr(merged, attr, value)

    return merged


ALIAS_MAP = {
    "-g": ["--mode", "gradle"],
    "-n": ["--mode", "npm"],
    "-s": ["--mode", "systemd"],
    "-o": ["--mode", "openai"],
    "--ant": ["--mode", "anthropic"],
}


def expand_aliases(argv: list[str]) -> list[str]:
    """Expand aliases in argv before parsing."""
    result = [argv[0]]
    for arg in argv[1:]:
        if arg in ALIAS_MAP:
            result.extend(ALIAS_MAP[arg])
        else:
            result.append(arg)
    return result


def main():
    sys.argv = expand_aliases(sys.argv)

    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("-m", "--mode", choices=list(MODES.keys()), default="shell")
    pre_args, remaining = pre_parser.parse_known_args()
    mode_class = MODES[pre_args.mode]

    if "-h" in remaining or "--help" in remaining:
        mode_parser = mode_class.get_parser()
        if mode_parser:
            mode_parser.print_help()
            sys.exit(2)

    alias_help = "aliases:\n" + "\n".join(
        f"  {alias} = {' '.join(expansion)}" for alias, expansion in ALIAS_MAP.items()
    )
    parser = HelpOnErrorParser(
        description="Environment variable configuration tool",
        epilog=alias_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "cmd", choices=["eval", "echo"], help="Subcommand: eval or echo"
    )
    parser.add_argument("-a", "--action", choices=["set", "unset"], required=True)
    parser.add_argument("-m", "--mode", choices=list(MODES.keys()), default="shell")
    parser.add_argument(
        "-i", "--ip", dest="ip", help="Server IP (auto-detect if not set)"
    )
    parser.add_argument(
        "-p",
        "--port",
        default="default",
        help="Port (default: mode-specific, e.g., 7890 for most modes, 8137 for openai; 'none' for no port)",
    )
    parser.add_argument(
        "-H",
        "--host",
        dest="host_str",
        default=None,
        help="Host as 'ip:port' or 'ip' (sets both IP and port, e.g., localhost:8080)",
    )
    parser.add_argument(
        "-c",
        "--credential",
        "-k",
        "--key",
        "-t",
        "--token",
        dest="credential",
        default=None,
        help="API credential (token, password, or key)",
    )

    args, unknown_args = parser.parse_known_args()

    mode_class = MODES[args.mode]

    mode_args = None
    if mode_class.get_parser():
        mode_args, unknown_args = parse_mode_args(mode_class, unknown_args)
        args = merge_args_with_mode_args(args, mode_args)

    args = process_args(args)

    if args.action == "set" and not args.host:
        print("Error: Cannot get server IP", file=sys.stderr)
        sys.exit(1)

    mode = mode_class(args)

    if args.cmd == "eval":
        output = mode.eval(args.action)
    else:
        output = mode.echo(args.action)

    if output:
        print(output)


if __name__ == "__main__":
    main()
