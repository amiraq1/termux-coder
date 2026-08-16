#!/data/data/com.termux/files/usr/bin/bash
source ~/termux-coder/env_nvidia.sh
exec termux-coder --workspace "${1:-.}"
