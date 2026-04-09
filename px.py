#!/usr/bin/env python3
"""
px - Environment Variable Configuration Tool

Architecture:
    - Template: scheme and url_prefix only
    - Each Mode manages its own variable name mapping
    - Base class dispatches set/unset to separate methods
    - Interface returns str (not list[str]), each Mode formats itself
    - Mode can have sub-parser (e.g., systemd service and mode)
    - Supports --token/--password/--key/-t/-k for credential passing
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
class Template:
    """Template configuration data model - scheme and url_prefix"""

    scheme: str  # http, https, socks5h
    url_prefix: str  # http://, socks5h://

    def full_url(self, host: str, port: str) -> str:
        return f"{self.url_prefix}{host}:{port}"


@dataclass
class TemplateGroup:
    """Template group for managing multiple templates"""

    templates: list[Template]
    host: str = ""
    port: str = ""

    def active(self, action: str) -> list[Template]:
        if action == "unset":
            return self.templates
        if self.host and self.port:
            return self.templates
        return []


# Default template definitions
DEFAULT_TEMPLATES = TemplateGroup(
    [
        Template("http", "http://"),
        Template("https", "http://"),
        Template("socks5h", "socks5h://"),
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
        template_group: TemplateGroup,
        unknown_args: list[str],
        args: argparse.Namespace | None = None,
    ):
        """
        Initialize mode with template group, unknown args, and optionally full parsed args

        Args:
            template_group: Group of templates with host/port configured
            unknown_args: Mode-specific unknown arguments
            args: Full parsed arguments from main parser (optional, for accessing global options)
        """
        self.template_group = template_group
        self.unknown_args = unknown_args
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

    def active_templates(self, action: str) -> list[Template]:
        return [
            t for t in self.template_group.active(action) if self.supports(t.scheme)
        ]

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
        for template in self.active_templates("set"):
            var_names = self.VAR_MAP.get(template.scheme)
            if not var_names:
                continue
            url = template.full_url(self.template_group.host, self.template_group.port)
            for var_name in var_names:
                lines.append(f'export {var_name}="{url}"')
        return "\n".join(lines)

    def _eval_unset(self) -> str:
        lines = []
        for template in self.active_templates("unset"):
            var_names = self.VAR_MAP.get(template.scheme)
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
    DEFAULT_ENDPOINT = "/v1"  # Default API endpoint path

    # Variable name mapping for OpenAI
    VAR_MAP = {
        "http": ("OPENAI_API_BASE", "OPENAI_API_KEY"),
    }

    def _post_init(self):
        """Initialize endpoint from args or use default"""
        super()._post_init()
        # Get endpoint from merged args, or use default
        if self.args and hasattr(self.args, "endpoint") and self.args.endpoint:
            self.endpoint = self.args.endpoint
        else:
            self.endpoint = self.DEFAULT_ENDPOINT

    @classmethod
    def get_parser(cls) -> "HelpOnErrorParser":
        """OpenAI-specific argument parser with --endpoint option"""
        parser = HelpOnErrorParser(prog="px -m openai", add_help=False)
        parser.add_argument(
            "--endpoint",
            default=cls.DEFAULT_ENDPOINT,
            help=f"API endpoint path (default: {cls.DEFAULT_ENDPOINT})",
        )
        return parser

    def _eval_set(self) -> str:
        """Set OpenAI API environment variables with endpoint"""
        lines = []
        for template in self.active_templates("set"):
            var_names = self.VAR_MAP.get(template.scheme)
            if not var_names:
                continue

            # Build API base URL with endpoint
            base_url = template.full_url(
                self.template_group.host, self.template_group.port
            )
            # Ensure endpoint starts with / and append to base URL
            endpoint = (
                self.endpoint if self.endpoint.startswith("/") else "/" + self.endpoint
            )
            api_base = f"{base_url}{endpoint}"

            # Set OPENAI_API_BASE
            lines.append(f'export OPENAI_API_BASE="{api_base}"')

            # Set OPENAI_API_KEY from --token/--password if provided
            key = self._get_api_key()
            if key:
                lines.append(f'export OPENAI_API_KEY="{key}"')
        return "\n".join(lines)

    def _eval_unset(self) -> str:
        """Unset OpenAI API environment variables"""
        lines = []
        for template in self.active_templates("unset"):
            var_names = self.VAR_MAP.get(template.scheme)
            if not var_names:
                continue
            for var_name in var_names:
                lines.append(f"unset {var_name}")
        return "\n".join(lines)

    def _get_api_key(self) -> str | None:
        """Get API key from -t/--token/--password arguments"""
        if not self.args:
            return None
        return getattr(self.args, "credential", None)


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
        for template in self.active_templates("set"):
            gradle_scheme = self.GRADLE_SCHEME_MAP.get(template.scheme, template.scheme)
            lines.append(
                f"systemProp.{gradle_scheme}.proxyHost={self.template_group.host}"
            )
            lines.append(
                f"systemProp.{gradle_scheme}.proxyPort={self.template_group.port}"
            )
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
        template_group: TemplateGroup,
        unknown_args: list[str],
        args: argparse.Namespace | None = None,
    ):
        # Call parent init first
        super().__init__(template_group, unknown_args, args)

    def _post_init(self):
        """Parse service and mode from unknown_args or merged args"""
        # Default values
        self.service = "docker.service"
        self.mode = "system"  # system or user

        # Check if args (merged namespace) has service/mode set by parse_mode_args
        if self.args:
            if hasattr(self.args, "service") and self.args.service:
                self.service = self.args.service
            if hasattr(self.args, "mode") and self.args.mode:
                self.mode = self.args.mode

        # Validate service name - should not start with '-'
        if self.service.startswith("-"):
            print(f"Error: Invalid service name '{self.service}'", file=sys.stderr)
            sys.exit(2)

        # Validate mode
        if self.mode not in ("system", "user"):
            print(
                f"Error: Invalid mode '{self.mode}', must be 'system' or 'user'",
                file=sys.stderr,
            )
            sys.exit(2)

    @classmethod
    def get_parser(cls) -> "HelpOnErrorParser":
        """Systemd-specific argument parser using HelpOnErrorParser"""
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

            for template in self.active_templates("set"):
                url = template.full_url(
                    self.template_group.host, self.template_group.port
                )
                var_names = self.VAR_MAP.get(template.scheme, ())
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

            for template in self.active_templates("set"):
                url = template.full_url(
                    self.template_group.host, self.template_group.port
                )
                var_names = self.VAR_MAP.get(template.scheme, ())
                for var_name in var_names:
                    lines.append(f'Environment="{var_name}={url}"')
        return "\n".join(lines)

    def _echo_unset(self) -> str:
        lines = []
        if self.mode == "system":
            for template in self.active_templates("unset"):
                var_names = self.VAR_MAP.get(template.scheme, ())
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
    mode_class: Type[Mode], argv: list[str]
) -> tuple[argparse.Namespace, list[str]]:
    """
    Parse mode-specific arguments (similar to parse_known_args interface)

    Args:
        mode_class: Mode class to get parser from
        argv: Argument list (like sys.argv)

    Returns: (mode_args_namespace, unknown_args)

    Uses parse_known_args to allow flexible argument handling.
    Help is handled by HelpOnErrorParser (exit 2).
    Errors cause immediate exit (2).
    """
    parser = mode_class.get_parser()
    if parser is None:
        # No parser for this mode, return empty namespace and original argv as unknown
        return argparse.Namespace(), argv

    # Use parse_known_args to separate mode-specific args from unknown args
    # This mirrors argparse.parse_known_args interface
    # Note: HelpOnErrorParser will exit(2) on errors or help, so this may not return
    mode_args, unknown_args = parser.parse_known_args(argv)

    return mode_args, unknown_args


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
    "-o": ["--mode", "openai"],
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

    # Pre-parse to extract mode (needed for mode-specific help handling)
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("-m", "--mode", choices=list(MODES.keys()), default="shell")
    pre_args, remaining = pre_parser.parse_known_args()
    mode_class = MODES[pre_args.mode]

    # Check for mode-specific help before main parsing
    if "-h" in remaining or "--help" in remaining:
        mode_parser = mode_class.get_parser()
        if mode_parser:
            # Show mode-specific help and exit with 2
            mode_parser.print_help()
            sys.exit(2)

    # Normal full argument parsing
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
    parser.add_argument("-i", "--ip", help="Server IP (auto-detect if not set)")
    parser.add_argument(
        "-p",
        "--port",
        default=None,
        help="Port (default: mode-specific, usually 7890)",
    )
    # Credential arguments - all map to 'credential' attribute
    parser.add_argument(
        "-t",
        "--token",
        "--password",
        dest="credential",
        default=None,
        help="API token, password, or key (all are the same, use whichever you prefer)",
    )
    parser.add_argument("--key", default=None, help="API key (alternative to --token)")

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
        mode_args, unknown_args = parse_mode_args(mode_class, unknown_args)
        # Note: HelpOnErrorParser handles -h/--help by printing and exiting with 2

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
        print("Error: Cannot get server IP", file=sys.stderr)
        sys.exit(1)

    # Prepare template group
    templates = TemplateGroup(list(DEFAULT_TEMPLATES.templates), host, port)

    # Create Mode with full args access and any remaining unknown args
    mode = mode_class(templates, unknown_args, args)

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
