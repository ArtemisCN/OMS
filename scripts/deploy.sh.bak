#!/bin/bash
# 医院故障工单管理系统 - 一键部署脚本
# 适用于 Windows (Git Bash/WSL) 和 Linux/Mac

set -e

echo "========================================="
echo "  医院故障工单管理系统 - 部署脚本"
echo "========================================="
echo ""

# 检查 Python 3
if command -v python3 &> /dev/null; then
    PYTHON=python3
elif command -v python &> /dev/null; then
    PYTHON=python
else
    echo "❌ 未找到 Python，请先安装 Python 3.8+"
    echo "  下载地址: https://www.python.org/downloads/"
    exit 1
fi

echo "✓ Python: $($PYTHON --version)"

# 检查 pip
if ! $PYTHON -m pip --version &> /dev/null; then
    echo "❌ 未找到 pip，请确保 Python 安装时勾选了 pip"
    exit 1
fi

# 创建虚拟环境（可选）
if [ ! -d "venv" ]; then
    echo ""
    echo "正在创建虚拟环境..."
    $PYTHON -m venv venv
    echo "✓ 虚拟环境已创建"
fi

# 激活虚拟环境
if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

echo ""

# 安装依赖
echo "正在安装依赖..."
$PYTHON -m pip install -r requirements.txt -q
echo "✓ 依赖安装完成"

# 初始化数据库
echo ""
echo "正在初始化数据库..."
$PYTHON app.py --init-only 2>/dev/null || true

# 启动
echo ""
echo "========================================="
echo "  ✅ 部署完成！"
echo "========================================="
echo ""
echo "  启动命令: $PYTHON app.py"
echo "  访问地址: http://127.0.0.1:5000"
echo "  管理员:   admin / admin123"
echo ""
echo "========================================="
echo ""

# 询问是否启动
read -p "是否立即启动系统？(Y/n): " start_now
if [ "$start_now" != "n" ] && [ "$start_now" != "N" ]; then
    echo "正在启动..."
    $PYTHON app.py
fi
