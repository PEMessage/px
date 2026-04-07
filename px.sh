#!/bin/bash
# px.sh - px 代理工具的 shell 包装层
#
# 原理:
#   对所有 mode 都执行 eval 和 echo 两个子命令:
#     - eval: 生成需要 eval 执行的命令（修改 shell 环境）
#     - echo: 生成直接输出的内容（配置、注释等）
#
#   安全机制:
#     - 只有 px 返回 exit 0 时才执行 eval
#     - 否则输出错误信息，保留 exit code
#
# 使用方法:
#   source px.sh       # 加载函数
#   px                 # 自动检测 IP，设置代理
#   unpx               # 取消代理

# 配置: px 脚本路径 (可通过环境变量覆盖)
: ${PX_CMD:=$(dirname $0)/px}

# 核心: 调用 px 执行 eval 和 echo
_px() {
    local mode="${1:-shell}"
    shift
    local eval_output
    local exit_code

    # 捕获 eval 输出和 exit code
    eval_output="$($PX_CMD eval -m "$mode" "$@" 2>&1)"
    exit_code=$?

    # 检查 exit code，非 0 则不 eval
    if ((exit_code != 0)); then
        echo "px error (exit $exit_code):" >&2
        echo "$eval_output" >&2
        return $exit_code
    fi

    # exit 0 时执行 eval
    if [[ -n "$eval_output" ]]; then
        eval "$eval_output"
    fi

    # 执行 echo 子命令（直接输出配置）
    $PX_CMD echo -m "$mode" "$@"
}

# 命令定义
px()   { _px shell -a set "$@"; }
unpx() { _px shell -a unset "$@"; }

# 查看当前代理
pxshow() {
    env | grep -iE '(_proxy|npm_config)=' | sort || echo "(无代理设置)"
}

# 帮助
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    cat << 'EOF'
px.sh - 代理环境变量设置工具

使用方法: source px.sh

命令:
  px [opts]                  - 设置代理 (默认 shell 模式)
  unpx [opts]                - 取消代理
  px -m gradle               - Gradle 配置
  px -m npm                  - npm 环境变量
  px -m systemd [svc] [mode] - Systemd 配置

选项:
  -i IP                      - 指定代理 IP (默认自动检测 WSL2)
  -p PORT                    - 指定端口 (默认 7890)

示例:
  px                         # 自动检测 WSL2 IP，设置 shell 代理
  px -i 192.168.1.1 -p 8080  # 手动指定
  px -m gradle               # 输出 Gradle 配置
  px -m systemd docker       # Docker systemd 配置
  px -m systemd myapp user   # User 模式配置

配置:
  export PX_CMD=/path/to/px  # 指定 px 脚本路径
EOF
fi
