# px - 代理环境变量设置工具

一个 Pythonic 的代理环境变量管理工具，支持多种输出模式（shell、gradle、npm、systemd）。

## 特性

- 🐍 **Pythonic 架构**: Data Class + ABC Mode + Registry
- 🔍 **WSL2 自动检测**: 自动检测宿主机 IP（支持 mirrored 模式）
- 🎯 **多模式支持**: shell、npm、gradle、systemd
- 📝 **双通道输出**: eval（环境变量）+ echo（配置文件）
- 🔧 **Systemd 集成**: 支持 system/user 模式，自定义服务名

## 安装

```bash
# 1. 下载到 PATH 目录
curl -L https://raw.githubusercontent.com/yourname/px/main/px -o ~/.local/bin/px
chmod +x ~/.local/bin/px

# 2. 可选: 加载 shell 函数
curl -L https://raw.githubusercontent.com/yourname/px/main/px.sh -o ~/.config/px.sh
echo 'source ~/.config/px.sh' >> ~/.bashrc
```

## 使用方法

### 直接调用 px

```bash
# 基本命令格式
px <subcommand> -a <action> [-m <mode>] [options] [extra_args...]

# 子命令
px eval -a set              # 生成 eval 执行的命令
px echo -a set -m gradle    # 生成直接输出的配置
```

### 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-a, --action` | `set` 或 `unset` | 必需 |
| `-m, --mode` | `shell`, `gradle`, `npm`, `systemd` | shell |
| `-i, --ip` | 代理服务器 IP | 自动检测 |
| `-p, --port` | 代理端口 | 7890 |
| `extra_args` | 额外参数（由 mode 解析） | 无 |

### 示例

```bash
# Shell 模式 - 设置代理
px eval -a set
# 输出:
# export http_proxy="http://localhost:7890"
# export HTTP_PROXY="http://localhost:7890"
# ...

# 取消代理
px eval -a unset

# Gradle 配置
px echo -a set -m gradle
# 输出:
# # 将以下内容添加到 gradle.properties:
# systemProp.http.proxyHost=localhost
# systemProp.http.proxyPort=7890
# ...

# npm 环境变量
px eval -a set -m npm

# Systemd 配置（默认 docker.service, system 模式）
px echo -a set -m systemd

# Systemd 自定义服务和模式
px echo -a set -m systemd myapp user
px echo -a set -m systemd myservice,system
```

### 配合 Shell 包装层

```bash
# 加载函数
source px.sh

# 设置代理（自动检测 IP）
px
pxshow
#  http_proxy=http://localhost:7890
#  https_proxy=http://localhost:7890
#  ...

# 取消代理
unpx

# 其他模式（直接输出配置）
px -m gradle
px -m systemd docker user
```

## 架构设计

### Data Model

```python
@dataclass(frozen=True)
class Proxy:
    name: str           # http_proxy
    scheme: str         # http/https/socks5h
    url_prefix: str     # http://
    aliases: tuple      # (HTTP_PROXY,)

@dataclass
class ProxyList:
    proxies: list[Proxy]
    host: str
    port: str
```

### Mode ABC

```python
class Mode(ABC):
    NAME: str
    SUPPORTED_SCHEMES: set[str]

    def eval(self, action: str) -> list[str]:
        """生成需要 eval 执行的命令"""
        
    def echo(self, action: str) -> list[str]:
        """生成直接输出的内容"""
```

### 各 Mode 特点

| Mode | Eval 输出 | Echo 输出 | 说明 |
|------|-----------|-----------|------|
| `shell` | export/unset | 警告注释 | 标准环境变量 |
| `npm` | npm_config_* | 空 | npm 专用 |
| `gradle` | 空 | gradle.properties | 构建工具配置 |
| `systemd` | 空 | override.conf | 服务配置 |

## WSL2 自动检测

支持两种模式：
- **mirrored 模式**: `wslinfo --networking-mode` 返回 `mirrored`，使用 `localhost`
- **传统模式**: 从 `ip route` 获取默认网关 IP

## 测试

```bash
# 运行测试
python3 tests/test_px.py

# 详细输出
python3 tests/test_px.py -v
```

测试覆盖:
- Data Model 和 Modes
- CLI 接口
- Shell 包装层（包括错误处理）

## 安全机制

Shell 包装层 (`px.sh`) 有严格的安全检查:

- 捕获 px 输出并检查 exit code
- 只有 exit 0 时才执行 `eval`
- 非零 exit code 时输出错误信息并保留 exit code

```bash
# 正常情况
px          # 成功，eval 执行

# px 失败时
px          # 失败，显示错误，不执行 eval
```

## License

MIT
