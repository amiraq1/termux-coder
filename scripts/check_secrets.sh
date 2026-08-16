#!/data/data/com.termux/files/usr/bin/bash
# حاجز أخير قبل أي commit/push
cd "$(dirname "$0")/.." || exit 1

if grep -RInE "nvapi-[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|xoxb-[0-9]+" \
    --exclude-dir=.git --exclude-dir=.venv --exclude=env.example.sh --exclude="env_*.sh" --exclude="start_nvidia.sh" . ; then
    echo "⚠️ مفاتيح حقيقية داخل المستودع — أزلها ودوِّرها (rotate) فورًا."
    exit 1
fi

echo "✓ لا مفاتيح واضحة في المستودع."
