#!/usr/bin/env python3
"""
px 测试套件

运行方式:
    cd /path/to/px-project && python3 tests/test_px.py

测试内容:
    - Data Model 和 Modes
    - CLI 接口
    - Shell 包装层
"""

import subprocess
import sys
import os
from pathlib import Path
import unittest
import tempfile


class TestCLI(unittest.TestCase):
    """测试命令行接口"""

    @classmethod
    def setUpClass(cls):
        cls.project_dir = Path(__file__).parent.parent
        cls.px_path = cls.project_dir / "px"
        cls.px_sh_path = cls.project_dir / "px.sh"

    def run_px(self, *args):
        """运行 px 命令并返回结果"""
        result = subprocess.run(
            ["python3", str(self.px_path), *args], capture_output=True, text=True
        )
        return result

    def test_eval_set(self):
        """测试 eval set 命令 - 应该同时输出大小写变量"""
        result = self.run_px("eval", "-a", "set")
        self.assertEqual(result.returncode, 0)
        # 检查同时有小写和大写
        self.assertIn("export http_proxy=", result.stdout)
        self.assertIn("export HTTP_PROXY=", result.stdout)
        self.assertIn("export https_proxy=", result.stdout)
        self.assertIn("export HTTPS_PROXY=", result.stdout)
        self.assertIn("export socks5h_proxy=", result.stdout)
        self.assertIn("export SOCKS5H_PROXY=", result.stdout)
        self.assertIn("localhost:7890", result.stdout)

    def test_eval_unset(self):
        """测试 eval unset 命令 - 应该同时取消大小写变量"""
        result = self.run_px("eval", "-a", "unset")
        self.assertEqual(result.returncode, 0)
        self.assertIn("unset http_proxy", result.stdout)
        self.assertIn("unset HTTP_PROXY", result.stdout)
        self.assertIn("unset https_proxy", result.stdout)
        self.assertIn("unset HTTPS_PROXY", result.stdout)

    def test_echo_gradle(self):
        """测试 echo gradle 模式"""
        result = self.run_px("echo", "-a", "set", "-m", "gradle")
        self.assertEqual(result.returncode, 0)
        self.assertIn("gradle.properties", result.stdout)
        self.assertIn("systemProp.http.proxyHost", result.stdout)
        self.assertIn("systemProp.https.proxyPort", result.stdout)

    def test_echo_npm(self):
        """测试 echo npm 模式 - 继承 ShellMode，echo 与 eval 输出相同"""
        result = self.run_px("echo", "-a", "set", "-m", "npm")
        self.assertEqual(result.returncode, 0)
        # NpmMode 继承 ShellMode，echo 输出与 eval 相同
        self.assertIn("npm_config_proxy", result.stdout)
        self.assertIn("npm_config_https_proxy", result.stdout)

    def test_eval_npm(self):
        """测试 eval npm 模式"""
        result = self.run_px("eval", "-a", "set", "-m", "npm")
        self.assertEqual(result.returncode, 0)
        self.assertIn("npm_config_proxy", result.stdout)
        self.assertIn("npm_config_https_proxy", result.stdout)
        # npm 不设置大写变量
        self.assertNotIn("NPM_CONFIG_PROXY", result.stdout)

    def test_echo_systemd_default(self):
        """测试 echo systemd 默认模式"""
        result = self.run_px("echo", "-a", "set", "-m", "systemd")
        self.assertEqual(result.returncode, 0)
        self.assertIn("docker.service", result.stdout)
        self.assertIn("systemctl daemon-reload", result.stdout)
        # 检查同时有小写和大写
        self.assertIn("http_proxy=", result.stdout)
        self.assertIn("HTTP_PROXY=", result.stdout)

    def test_echo_systemd_user(self):
        """测试 echo systemd user 模式"""
        result = self.run_px("echo", "-a", "set", "-m", "systemd", "myapp", "user")
        self.assertEqual(result.returncode, 0)
        self.assertIn("myapp", result.stdout)
        self.assertIn(".config/systemd/user", result.stdout)
        self.assertIn("[Service]", result.stdout)

    def test_echo_systemd_positional_args(self):
        """测试 echo systemd 位置参数格式"""
        result = self.run_px("echo", "-a", "set", "-m", "systemd", "myapp", "user")
        self.assertEqual(result.returncode, 0)
        self.assertIn("myapp", result.stdout)
        self.assertIn("[Service]", result.stdout)

    def test_manual_ip_port(self):
        """测试手动指定 IP 和端口"""
        result = self.run_px("eval", "-a", "set", "-i", "192.168.1.100", "-p", "8080")
        self.assertEqual(result.returncode, 0)
        self.assertIn("http://192.168.1.100:8080", result.stdout)

    def test_unset_no_ip_required(self):
        """测试 unset 不需要 IP"""
        result = self.run_px("eval", "-a", "unset")
        self.assertEqual(result.returncode, 0)


class TestShellWrapper(unittest.TestCase):
    """测试 Shell 包装层"""

    @classmethod
    def setUpClass(cls):
        cls.project_dir = Path(__file__).parent.parent
        cls.px_sh_path = cls.project_dir / "px.sh"

    def test_wrapper_set_proxy(self):
        """测试包装层设置代理 - 检查大小写变量"""
        px_file = self.project_dir / "px"
        script = f"""
export PX_CMD={px_file}
source {self.px_sh_path}

# 清除现有代理
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY 2>/dev/null

# 测试设置代理
px

# 检查同时设置了小写和大写变量
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
        """测试包装层取消代理 - 检查同时取消大小写变量"""
        px_file = self.project_dir / "px"
        script = f"""
export PX_CMD={px_file}
source {self.px_sh_path}

# 先设置代理（大小写都设置）
export http_proxy="http://test:7890"
export HTTP_PROXY="http://test:7890"
export https_proxy="http://test:7890"
export HTTPS_PROXY="http://test:7890"

# 测试取消代理
unpx

# 检查同时取消了大小写变量
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
        """测试包装层 gradle 模式（直接输出，不 eval）"""
        px_file = self.project_dir / "px"
        script = f"""
export PX_CMD={px_file}
source {self.px_sh_path}

# 清除现有代理
unset http_proxy HTTP_PROXY 2>/dev/null

# 测试 gradle 模式（应该只输出，不设置环境变量）
output=$(px -m gradle)

# 检查输出内容
if [[ ! "$output" =~ "gradle.properties" ]]; then
    echo "FAIL: missing gradle.properties hint"
    exit 1
fi

# 检查没有设置 http_proxy
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
        """测试包装层 npm 模式"""
        px_file = self.project_dir / "px"
        script = f"""
export PX_CMD={px_file}
source {self.px_sh_path}

# 清除现有变量
unset npm_config_proxy npm_config_https_proxy 2>/dev/null

# 测试 npm 模式
px -m npm

# 检查是否设置了变量
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
        """测试包装层在 px 失败时返回错误"""
        px_file = self.project_dir / "px"

        # 创建一个假的 px 脚本返回错误
        fake_px = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        fake_px.write(
            "#!/usr/bin/env python3\nimport sys\nprint('error message')\nsys.exit(1)\n"
        )
        fake_px.close()
        os.chmod(fake_px.name, 0o755)

        script = f"""
export PX_CMD={fake_px.name}
source {self.px_sh_path}

# 尝试执行（应该返回非零）
px 2>/dev/null
exit_code=$?

# 检查 exit code
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
