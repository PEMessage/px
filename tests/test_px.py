#!/usr/bin/env python3
"""
px test suite

Run:
    cd /path/to/px-project && python3 tests/test_px.py

Tests:
    - Data Models and Modes
    - CLI interface
    - Shell wrapper
"""

import subprocess
import sys
import os
from pathlib import Path
import unittest
import tempfile


class TestCLI(unittest.TestCase):
    """Test command line interface"""

    @classmethod
    def setUpClass(cls):
        cls.project_dir = Path(__file__).parent.parent
        cls.px_path = cls.project_dir / "px.py"
        cls.px_sh_path = cls.project_dir / "px.sh"

    def run_px(self, *args):
        """Run px command and return result"""
        result = subprocess.run(
            ["python3", str(self.px_path), *args], capture_output=True, text=True
        )
        return result

    def test_eval_set(self):
        """Test eval set command - should output both lowercase and uppercase vars"""
        result = self.run_px("eval", "-a", "set")
        self.assertEqual(result.returncode, 0)
        # Check both lowercase and uppercase
        self.assertIn("export http_proxy=", result.stdout)
        self.assertIn("export HTTP_PROXY=", result.stdout)
        self.assertIn("export https_proxy=", result.stdout)
        self.assertIn("export HTTPS_PROXY=", result.stdout)
        self.assertIn("export socks5h_proxy=", result.stdout)
        self.assertIn("export SOCKS5H_PROXY=", result.stdout)
        self.assertIn("localhost:7890", result.stdout)

    def test_eval_unset(self):
        """Test eval unset command - should unset both lowercase and uppercase vars"""
        result = self.run_px("eval", "-a", "unset")
        self.assertEqual(result.returncode, 0)
        self.assertIn("unset http_proxy", result.stdout)
        self.assertIn("unset HTTP_PROXY", result.stdout)
        self.assertIn("unset https_proxy", result.stdout)
        self.assertIn("unset HTTPS_PROXY", result.stdout)

    def test_echo_gradle(self):
        """Test echo gradle mode"""
        result = self.run_px("echo", "-a", "set", "-m", "gradle")
        self.assertEqual(result.returncode, 0)
        self.assertIn("gradle.properties", result.stdout)
        self.assertIn("systemProp.http.proxyHost", result.stdout)
        self.assertIn("systemProp.https.proxyPort", result.stdout)

    def test_echo_npm(self):
        """Test echo npm mode - inherits ShellMode, echo same as eval"""
        result = self.run_px("echo", "-a", "set", "-m", "npm")
        self.assertEqual(result.returncode, 0)
        # NpmMode inherits ShellMode, echo outputs same as eval
        self.assertIn("npm_config_proxy", result.stdout)
        self.assertIn("npm_config_https_proxy", result.stdout)

    def test_eval_npm(self):
        """Test eval npm mode"""
        result = self.run_px("eval", "-a", "set", "-m", "npm")
        self.assertEqual(result.returncode, 0)
        self.assertIn("npm_config_proxy", result.stdout)
        self.assertIn("npm_config_https_proxy", result.stdout)
        # npm doesn't set uppercase vars (single-element tuple)
        self.assertNotIn("NPM_CONFIG_PROXY", result.stdout)

    def test_echo_systemd_default(self):
        """Test echo systemd default mode"""
        result = self.run_px("echo", "-a", "set", "-m", "systemd")
        self.assertEqual(result.returncode, 0)
        self.assertIn("docker.service", result.stdout)
        self.assertIn("systemctl daemon-reload", result.stdout)
        # Check both lowercase and uppercase
        self.assertIn("http_proxy=", result.stdout)
        self.assertIn("HTTP_PROXY=", result.stdout)

    def test_echo_systemd_user(self):
        """Test echo systemd user mode"""
        result = self.run_px("echo", "-a", "set", "-m", "systemd", "myapp", "user")
        self.assertEqual(result.returncode, 0)
        self.assertIn("myapp", result.stdout)
        self.assertIn(".config/systemd/user", result.stdout)
        self.assertIn("[Service]", result.stdout)

    def test_echo_systemd_positional_args(self):
        """Test echo systemd positional args format"""
        result = self.run_px("echo", "-a", "set", "-m", "systemd", "myapp", "user")
        self.assertEqual(result.returncode, 0)
        self.assertIn("myapp", result.stdout)
        self.assertIn("[Service]", result.stdout)

    def test_manual_ip_port(self):
        """Test manual IP and port specification"""
        result = self.run_px("eval", "-a", "set", "-i", "192.168.1.100", "-p", "8080")
        self.assertEqual(result.returncode, 0)
        self.assertIn("http://192.168.1.100:8080", result.stdout)

    def test_unset_no_ip_required(self):
        """Test unset doesn't require IP"""
        result = self.run_px("eval", "-a", "unset")
        self.assertEqual(result.returncode, 0)

    def test_openai_credential_long(self):
        """Test openai mode with --credential"""
        result = self.run_px(
            "eval", "-a", "set", "-m", "openai", "--credential", "testkey123"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("OPENAI_API_BASE=", result.stdout)
        self.assertIn('OPENAI_API_KEY="testkey123"', result.stdout)

    def test_openai_credential_short(self):
        """Test openai mode with -c"""
        result = self.run_px("eval", "-a", "set", "-m", "openai", "-c", "shortkey")
        self.assertEqual(result.returncode, 0)
        self.assertIn('OPENAI_API_KEY="shortkey"', result.stdout)

    def test_openai_credential_aliases(self):
        """Test all credential aliases work correctly"""
        aliases = [
            ("-k", "keyalias"),
            ("--key", "keyalias2"),
            ("-t", "tokenalias"),
            ("--token", "tokenalias2"),
        ]
        for flag, value in aliases:
            result = self.run_px("eval", "-a", "set", "-m", "openai", flag, value)
            self.assertEqual(result.returncode, 0)
            self.assertIn(f'OPENAI_API_KEY="{value}"', result.stdout)

    def test_openai_no_credential(self):
        """Test openai mode without credential - should only set base URL"""
        result = self.run_px("eval", "-a", "set", "-m", "openai")
        self.assertEqual(result.returncode, 0)
        self.assertIn("OPENAI_API_BASE=", result.stdout)
        self.assertNotIn("OPENAI_API_KEY", result.stdout)

    def test_anthropic_credential(self):
        """Test anthropic mode with credential"""
        result = self.run_px(
            "eval", "-a", "set", "-m", "anthropic", "--credential", "anthropic_key"
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("ANTHROPIC_API_BASE=", result.stdout)
        self.assertIn('ANTHROPIC_API_KEY="anthropic_key"', result.stdout)

    def test_host_option_with_port(self):
        """Test -H option with ip:port format"""
        result = self.run_px("eval", "-a", "set", "-H", "192.168.1.50:3128")
        self.assertEqual(result.returncode, 0)
        self.assertIn("http://192.168.1.50:3128", result.stdout)

    def test_host_option_without_port(self):
        """Test -H option with just ip (no port)"""
        result = self.run_px("eval", "-a", "set", "-H", "localhost")
        self.assertEqual(result.returncode, 0)
        # Without port, URL should not have :port suffix
        self.assertIn('http://localhost"', result.stdout)
        self.assertNotIn("http://localhost:7890", result.stdout)


class TestShellWrapper(unittest.TestCase):
    """Test shell wrapper"""

    @classmethod
    def setUpClass(cls):
        cls.project_dir = Path(__file__).parent.parent
        cls.px_sh_path = cls.project_dir / "px.sh"

    def test_wrapper_set_proxy(self):
        """Test wrapper set proxy - check both lowercase and uppercase vars"""
        px_file = self.project_dir / "px.py"
        script = f"""
export PX_CMD={px_file}
source {self.px_sh_path}

# Clear existing proxies
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null

# Test set proxy
px

# Check both lowercase and uppercase vars are set
if [[ -z "$http_proxy" ]]; then
    echo "FAIL: http_proxy not set"
    exit 1
fi
if [[ -z "$HTTP_PROXY" ]]; then
    echo "FAIL: HTTP_PROXY not set"
    exit 1
fi
if [[ "$http_proxy" != "$HTTP_PROXY" ]]; then
    echo "FAIL: http_proxy and HTTP_PROXY should be equal"
    exit 1
fi
if [[ "$http_proxy" != *":7890"* ]]; then
    echo "FAIL: port not 7890"
    exit 1
fi

echo "SUCCESS"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script)
            tmp_script = f.name

        try:
            result = subprocess.run(
                ["bash", tmp_script], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, f"Script failed: {result.stderr}")
            self.assertIn("SUCCESS", result.stdout)
        finally:
            os.unlink(tmp_script)

    def test_wrapper_unset_proxy(self):
        """Test wrapper unset proxy - check both lowercase and uppercase vars are unset"""
        px_file = self.project_dir / "px.py"
        script = f"""
export PX_CMD={px_file}
source {self.px_sh_path}

# First set proxies (both cases)
export http_proxy="http://test:7890"
export HTTP_PROXY="http://test:7890"
export https_proxy="http://test:7890"
export HTTPS_PROXY="http://test:7890"

# Test unset proxy
unpx

# Check both lowercase and uppercase vars are unset
if [[ -n "$http_proxy" ]]; then
    echo "FAIL: http_proxy still set: $http_proxy"
    exit 1
fi
if [[ -n "$HTTP_PROXY" ]]; then
    echo "FAIL: HTTP_PROXY still set: $HTTP_PROXY"
    exit 1
fi
if [[ -n "$https_proxy" ]]; then
    echo "FAIL: https_proxy still set"
    exit 1
fi
if [[ -n "$HTTPS_PROXY" ]]; then
    echo "FAIL: HTTPS_PROXY still set"
    exit 1
fi

echo "SUCCESS"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script)
            tmp_script = f.name

        try:
            result = subprocess.run(
                ["bash", tmp_script], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, f"Script failed: {result.stderr}")
            self.assertIn("SUCCESS", result.stdout)
        finally:
            os.unlink(tmp_script)

    def test_wrapper_gradle_mode(self):
        """Test wrapper gradle mode (display only, no eval)"""
        px_file = self.project_dir / "px.py"
        script = f"""
export PX_CMD={px_file}
source {self.px_sh_path}

# Clear existing proxies
unset http_proxy HTTP_PROXY 2>/dev/null

# Test gradle mode (should only display, not set env vars)
output=$(px -m gradle)

# Check output content
if [[ ! "$output" =~ "gradle.properties" ]]; then
    echo "FAIL: missing gradle.properties hint"
    exit 1
fi

# Check http_proxy is not set
if [[ -n "$http_proxy" ]]; then
    echo "FAIL: http_proxy should not be set in gradle mode"
    exit 1
fi
if [[ -n "$HTTP_PROXY" ]]; then
    echo "FAIL: HTTP_PROXY should not be set in gradle mode"
    exit 1
fi

echo "SUCCESS"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script)
            tmp_script = f.name

        try:
            result = subprocess.run(
                ["bash", tmp_script], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, f"Script failed: {result.stderr}")
            self.assertIn("SUCCESS", result.stdout)
        finally:
            os.unlink(tmp_script)

    def test_wrapper_npm_mode(self):
        """Test wrapper npm mode"""
        px_file = self.project_dir / "px.py"
        script = f"""
export PX_CMD={px_file}
source {self.px_sh_path}

# Clear existing vars
unset npm_config_proxy npm_config_https_proxy 2>/dev/null

# Test npm mode
px -m npm

# Check vars are set
if [[ -z "$npm_config_proxy" ]]; then
    echo "FAIL: npm_config_proxy not set"
    exit 1
fi
if [[ -z "$npm_config_https_proxy" ]]; then
    echo "FAIL: npm_config_https_proxy not set"
    exit 1
fi

echo "SUCCESS"
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script)
            tmp_script = f.name

        try:
            result = subprocess.run(
                ["bash", tmp_script], capture_output=True, text=True
            )
            self.assertEqual(result.returncode, 0, f"Script failed: {result.stderr}")
            self.assertIn("SUCCESS", result.stdout)
        finally:
            os.unlink(tmp_script)

    def test_wrapper_exit_code_on_error(self):
        """Test wrapper returns error when px fails"""
        px_file = self.project_dir / "px"

        # Create fake px script that returns error
        fake_px = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        fake_px.write(
            "#!/usr/bin/env python3\nimport sys\nprint('error message')\nsys.exit(1)\n"
        )
        fake_px.close()
        os.chmod(fake_px.name, 0o755)

        script = f"""
source {self.px_sh_path}

# Override PX_CMD to use fake script
PX_CMD="{fake_px.name}"

# Try to execute (should return non-zero)
px 2>/dev/null
exit_code=$?

# Check exit code
if [[ $exit_code -ne 0 ]]; then
    echo "SUCCESS"
else
    echo "FAIL: exit code should be non-zero, got $exit_code"
fi
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
            f.write(script)
            tmp_script = f.name

        try:
            result = subprocess.run(
                ["bash", tmp_script], capture_output=True, text=True
            )
            self.assertIn("SUCCESS", result.stdout)
        finally:
            os.unlink(tmp_script)
            os.unlink(fake_px.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
