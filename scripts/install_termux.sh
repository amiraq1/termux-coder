#!/data/data/com.termux/files/usr/bin/bash
set -e

echo "◈ تثبيت termux-coder على هذا الجهاز..."

pkg update -y
pkg install -y python git grep

python -m venv ~/tc-venv
source ~/tc-venv/bin/activate
python -m pip install --upgrade pip

if [ -n "$1" ] && [ -f "$1" ]; then
    # خيار 1: wheel منسوخة (مثلاً عبر ~/storage/shared/Download)
    pip install "$1"
else
    # خيار 2: من GitHub مباشرة
    pip install "git+https://github.com/USERNAME/termux-coder.git"
fi

echo ""
echo "✓ تم التثبيت. الخطوات التالية:"
echo "  1) cp env.example.sh ~/termux-coder/env_nvidia.sh وحرّر المفتاح"
echo "  2) source ~/termux-coder/env_nvidia.sh"
echo "  3) termux-coder doctor"
