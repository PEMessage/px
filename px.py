#!/usr/bin/env python3
"""
px - Proxy Environment Variable Tool

Architecture:
    - Proxy: scheme and url_prefix only
    - Each Mode manages its own variable name mapping
    - Base class dispatches set/unset to separate methods
    - Interface returns str (not list[str]), each Mode formats itself
    - Mode can have sub-parser (e.g., systemd service and mode)
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
    """Proxy configuration data model - only scheme and url_prefix"""

    scheme: str  # http, https, socks5h
    url_prefix: str  # http://, socks5h://

    def full_url(self, host: str, port: str) -> str:
        return f"{self.url_prefix}{host}:{port}"


@dataclass
class ProxyList:
    """Proxy list"""

    proxies: list[Proxy]
    host: str = ""
    port: str = ""

    def active(self, action: str) -> list[Proxy]:
        if action == "unset":
            return self.proxies
        if self.host and self.port:
            return self.proxies
        return []


# Default proxy definitions
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
    """
    Abstract base class for output modes

    Subclasses implement:
        - _eval_set / _eval_unset: eval subcommand implementation
        - _echo_set / _echo_unset: echo subcommand implementation

    Optional:
        - get_parser(): returns sub-parser (for mode-specific args)
        - get_default_port(): returns default port for this mode

    Base class dispatch:
        - eval(action) -> calls _eval_set or _eval_unset
        - echo(action) -> calls _echo_set or _echo_unset

    Returns string (may contain newlines), each Mode formats itself
    """

    NAME: str = ""
    SUPPORTED_SCHEMES: set[str] = set()
    DEFAULT_PORT: str = "7890"  # Can be overridden by subclasses

    def __init__(
        self,
        proxy_list: ProxyList,
        extra_args: list[str],
        args: argparse.Namespace | None = None,
    ):
        """
        Initialize mode with proxy list, extra args, and optionally full parsed args

        Args:
            proxy_list: List of proxies with host/port configured
            extra_args: Mode-specific extra arguments (parsed by mode's parser)
            args: Full parsed arguments from main parser (optional, for accessing global options)
        """
        self.proxy_list = proxy_list
        self.extra_args = extra_args
        self.args = args  # Full args namespace
        self._post_init()

    @classmethod
    def get_default_port(cls) -> str:
        """Return default port for this mode (can be overridden by subclasses)"""
        return cls.DEFAULT_PORT

    def _post_init(self):
        """Subclasses can override this for initialization"""
        pass

    @classmethod
    def get_parser(cls) -> Optional[argparse.ArgumentParser]:
        """
        Optional: returns sub-parser
        Used for mode-specific args (e.g., systemd's service and mode)
        Returns None if no sub-args needed
        """
        return None

    def supports(self, scheme: str) -> bool:
        return scheme in self.SUPPORTED_SCHEMES

    def active_proxies(self, action: str) -> list[Proxy]:
        return [p for p in self.proxy_list.active(action) if self.supports(p.scheme)]

    # -------------------------------------------------------------------------
    # Dispatch methods
    # -------------------------------------------------------------------------
    def eval(self, action: str) -> str:
        """Generate eval commands - dispatch to specific method"""
        if action == "set":
            return self._eval_set()
        else:  # unset
            return self._eval_unset()

    def echo(self, action: str) -> str:
        """Generate output content - dispatch to specific method"""
        if action == "set":
            return self._echo_set()
        else:  # unset
            return self._echo_unset()

    # -------------------------------------------------------------------------
    # Abstract methods for subclasses to implement
    # -------------------------------------------------------------------------
    @abstractmethod
    def _eval_set(self) -> str:
        """eval set implementation"""
        return ""

    @abstractmethod
    def _eval_unset(self) -> str:
        """eval unset implementation"""
        return ""

    @abstractmethod
    def _echo_set(self) -> str:
        """echo set implementation"""
        return ""

    @abstractmethod
    def _echo_unset(self) -> str:
        """echo unset implementation"""
        return ""


class ShellMode(Mode):
    """Shell environment variable mode - sets both lowercase and uppercase vars"""

    NAME = "shell"
    SUPPORTED_SCHEMES = {"http", "https", "socks5h"}

    # Variable name mapping: scheme -> (lowercase, UPPERCASE)
    VAR_MAP = {
        "http": ("http_proxy", "HTTP_PROXY"),
        "https": ("https_proxy", "HTTPS_PROXY"),
        "socks5h": ("socks5h_proxy", "SOCKS5H_PROXY"),
    }

    def _eval_set(self) -> str:
        lines = []
        for proxy in self.active_proxies("set"):
            var_names = self.VAR_MAP.get(proxy.scheme)
            if not var_names:
                continue
            url = proxy.full_url(self.proxy_list.host, self.proxy_list.port)
            for var_name in var_names:
                lines.append(f'export {var_name}="{url}"')
        return "\n".join(lines)

    def _eval_unset(self) -> str:
        lines = []
        for proxy in self.active_proxies("unset"):
            var_names = self.VAR_MAP.get(proxy.scheme)
            if not var_names:
                continue
            for var_name in var_names:
                lines.append(f"unset {var_name}")
        return "\n".join(lines)

    def _echo_set(self) -> str:
        """echo set outputs same as eval set for preview"""
        return self._eval_set()

    def _echo_unset(self) -> str:
        """echo unset outputs same as eval unset"""
        return self._eval_unset()


class NpmMode(ShellMode):
    """NPM environment variable mode - inherits ShellMode, only overrides VAR_MAP"""

    NAME = "npm"
    SUPPORTED_SCHEMES = {"http", "https"}

    # Override parent's VAR_MAP (use single-element tuple for consistent interface)
    VAR_MAP = {
        "http": ("npm_config_proxy",),
        "https": ("npm_config_https_proxy",),
    }


class OpenaiMode(ShellMode):
    """OpenAI API configuration mode - inherits ShellMode, sets OpenAI-specific variables"""

    NAME = "openai"
    SUPPORTED_SCHEMES = {"http"}  # OpenAI uses HTTP
    DEFAULT_PORT = "8137"  # Override default port for OpenAI mode

    # Variable name mapping for OpenAI
    VAR_MAP = {
        "http": ("OPENAI_API_BASE", "OPENAI_API_KEY"),
    }

    def _eval_set(self) -> str:
        """Set OpenAI API environment variables"""
        lines = []
        for proxy in self.active_proxies("set"):
            var_names = self.VAR_MAP.get(proxy.scheme)
            if not var_names:
                continue

            # Build API base URL
            api_base = proxy.full_url(self.proxy_list.host, self.proxy_list.port)

            # Set OPENAI_API_BASE
            lines.append(f'export OPENAI_API_BASE="{api_base}"')

            # OPENAI_API_KEY should be already set by user, we just remind
            # But if unset action, we unset it
        return "\n".join(lines)

    def _eval_unset(self) -> str:
        """Unset OpenAI API environment variables"""
        lines = []
        for proxy in self.active_proxies("unset"):
            var_names = self.VAR_MAP.get(proxy.scheme)
            if not var_names:
                continue
            for var_name in var_names:
                lines.append(f"unset {var_name}")
        return "\n".join(lines)


class GradleMode(Mode):
    """Gradle configuration mode"""

    NAME = "gradle"
    SUPPORTED_SCHEMES = {"http", "https", "socks5h"}

    # Scheme mapping: maps socks5h to "sock" for gradle properties
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
        for proxy in self.active_proxies("set"):
            gradle_scheme = self.GRADLE_SCHEME_MAP.get(proxy.scheme, proxy.scheme)
            lines.append(f"systemProp.{gradle_scheme}.proxyHost={self.proxy_list.host}")
            lines.append(f"systemProp.{gradle_scheme}.proxyPort={self.proxy_list.port}")
        return "\n".join(lines)

    def _echo_unset(self) -> str:
        return ""


class SystemdMode(Mode):
    """Systemd service configuration mode"""

    NAME = "systemd"
    SUPPORTED_SCHEMES = {"http", "https", "socks5h"}

    # Variable name mapping: scheme -> (lowercase, UPPERCASE)
    VAR_MAP = {
        "http": ("http_proxy", "HTTP_PROXY"),
        "https": ("https_proxy", "HTTPS_PROXY"),
        "socks5h": ("socks5h_proxy", "SOCKS5H_PROXY"),
    }

    def __init__(
        self,
        proxy_list: ProxyList,
        extra_args: list[str],
        args: argparse.Namespace | None = None,
    ):
        # Call parent init first
        super().__init__(proxy_list, extra_args, args)

    def _post_init(self):
        """Parse service and mode from extra_args or merged args"""
        # Default values
        self.service = "docker.service"
        self.mode = "system"  # system or user

        # Check if args (merged namespace) has service/mode set by parse_mode_args
        if self.args:
            if hasattr(self.args, "service") and self.args.service:
                self.service = self.args.service
            if hasattr(self.args, "mode") and self.args.mode:
                self.mode = self.args.mode

        # Also check extra_args for backward compatibility
        for arg in self.extra_args:
            if arg in ("system", "user"):
                self.mode = arg
            elif arg:  # Non-empty string that's not a reserved word
                self.service = arg

    @classmethod
    def get_parser(cls) -> argparse.ArgumentParser:
        """Systemd-specific argument parser"""
        parser = argparse.ArgumentParser(prog="px -m systemd", add_help=False)
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

            for proxy in self.active_proxies("set"):
                url = proxy.full_url(self.proxy_list.host, self.proxy_list.port)
                var_names = self.VAR_MAP.get(proxy.scheme, ())
                for var_name in var_names:
                    lines.append(
                        f"echo 'Environment=\"{var_name}={url}\"' | sudo tee -a /run/systemd/system/{self.service}.d/override.conf"
                    )
        else:
            # user mode
            lines.append(f"mkdir -p $HOME/.config/systemd/user/{self.service}.d")
            lines.append(
                f"$EDITOR $HOME/.config/systemd/user/{self.service}.d/override.conf"
            )
            lines.append("[Service]")

            for proxy in self.active_proxies("set"):
                url = proxy.full_url(self.proxy_list.host, self.proxy_list.port)
                var_names = self.VAR_MAP.get(proxy.scheme, ())
                for var_name in var_names:
                    lines.append(f'Environment="{var_name}={url}"')
        return "\n".join(lines)

    def _echo_unset(self) -> str:
        lines = []
        if self.mode == "system":
            for proxy in self.active_proxies("unset"):
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
    m.NAME: m for m in [ShellMode, GradleMode, NpmMode, SystemdMode, OpenaiMode]
}


# =============================================================================
# WSL Detection
# =============================================================================


def detect_wsl_ip() -> Optional[str]:
    """Detect WSL2 host IP"""
    try:
        r = subprocess.run(
            ["wslinfo", "--networking-mode"], capture_output=True, text=True, timeout=2
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
# CLI
# =============================================================================


class HelpOnErrorParser(argparse.ArgumentParser):
    """Custom ArgumentParser that returns exit 2 for help instead of 0"""

    def print_help(self, file=None):
        super().print_help(file)
        sys.exit(2)  # Non-zero exit code prevents shell wrapper from eval

    def error(self, message):
        # Also exit 2 on error
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


def parse_mode_args(
    argv: list[str], mode_class: Type[Mode]
) -> tuple[argparse.Namespace, list[str], bool]:
    """
    Parse mode-specific arguments (similar to parse_known_args interface)

    Args:
        argv: Argument list (like sys.argv)
        mode_class: Mode class to get parser from

    Returns: (mode_args_namespace, unknown_args, whether_help_was_shown)

    Uses parse_known_args to allow flexible argument handling.
    Mode can define its own arguments which will be parsed and returned.
    """
    parser = mode_class.get_parser()
    if parser is None:
        # No parser for this mode, return empty namespace and original argv as unknown
        return argparse.Namespace(), argv, False

    # Check for -h or --help
    if "-h" in argv or "--help" in argv:
        parser.print_help()
        return argparse.Namespace(), [], True

    try:
        # Use parse_known_args to separate mode-specific args from unknown args
        # This mirrors argparse.parse_known_args interface
        mode_args, unknown_args = parser.parse_known_args(argv)

        return mode_args, unknown_args, False
    except SystemExit:
        # Parse failed, return empty namespace and original argv
        return argparse.Namespace(), argv, False


def merge_args_with_mode_args(
    args: argparse.Namespace, mode_args: argparse.Namespace | None
) -> argparse.Namespace:
    """
    Merge main parser args with mode-specific args.
    Mode args take precedence over main args for the same attribute.
    """
    if mode_args is None:
        return args

    # Create new namespace with merged values
    merged = argparse.Namespace()

    # Copy all attributes from main args
    for attr in dir(args):
        if not attr.startswith("_"):
            setattr(merged, attr, getattr(args, attr))

    # Override/add with mode-specific args
    for attr in dir(mode_args):
        if not attr.startswith("_"):
            value = getattr(mode_args, attr)
            if value is not None:
                setattr(merged, attr, value)

    return merged


# Alias map: short option -> expansion list
ALIAS_MAP = {
    "-g": ["--mode", "gradle"],
    "-n": ["--mode", "npm"],
    "-s": ["--mode", "systemd"],
}


def expand_aliases(argv: list[str]) -> list[str]:
    """Expand aliases in argv before parsing."""
    result = [argv[0]]  # Keep script name
    for arg in argv[1:]:
        if arg in ALIAS_MAP:
            result.extend(ALIAS_MAP[arg])
        else:
            result.append(arg)
    return result


def main():
    # Expand aliases before parsing
    sys.argv = expand_aliases(sys.argv)

    # Normal full argument parsing
    alias_help = "aliases:\n" + "\n".join(
        f"  {alias} = {' '.join(expansion)}" for alias, expansion in ALIAS_MAP.items()
    )
    parser = HelpOnErrorParser(
        description="Proxy environment variable tool",
        epilog=alias_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "cmd", choices=["eval", "echo"], help="Subcommand: eval or echo"
    )
    parser.add_argument("-a", "--action", choices=["set", "unset"], required=True)
    parser.add_argument("-m", "--mode", choices=list(MODES.keys()), default="shell")
    parser.add_argument("-i", "--ip", help="Proxy server IP (auto-detect if not set)")
    parser.add_argument(
        "-p",
        "--port",
        default=None,
        help="Proxy port (default: mode-specific, usually 7890)",
    )

    args, unknown_args = parser.parse_known_args()

    # Get selected mode class (user may have specified different one via -m)
    mode_class = MODES[args.mode]

    # Get default port from mode (allows modes to have different defaults like openai's 8137)
    default_port = mode_class.get_default_port()

    # Use mode-specific default port if user didn't specify
    port = args.port if args.port else default_port

    # If mode has sub-parser, parse its specific args
    mode_args = None
    if mode_class.get_parser():
        mode_args, unknown_args, showed_help = parse_mode_args(unknown_args, mode_class)
        if showed_help:
            sys.exit(2)  # Exit after showing help, non-zero code

        # Merge mode args with main args
        args = merge_args_with_mode_args(args, mode_args)

    # Auto-detect IP if not set
    host = args.ip
    if not host:
        host = detect_wsl_ip()
        if not host:
            print("# Warning: Cannot detect WSL IP, using localhost", file=sys.stderr)
            host = "localhost"

    if args.action == "set" and not host:
        print("Error: Cannot get proxy IP", file=sys.stderr)
        sys.exit(1)

    # Prepare proxy list
    proxies = ProxyList(list(DEFAULT_PROXIES.proxies), host, port)

    # Create Mode with full args access and any remaining unknown args
    mode = mode_class(proxies, unknown_args, args)

    # Execute subcommand - dispatch handled by Mode base class
    if args.cmd == "eval":
        output = mode.eval(args.action)
    else:  # echo
        output = mode.echo(args.action)

    # Output result (may be multi-line string)
    if output:
        print(output)


if __name__ == "__main__":
    main()
