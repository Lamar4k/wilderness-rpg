#!/usr/bin/env bash
set -e
echo "=== Установка зависимостей для компиляции Android APK (Ubuntu / Debian / WSL2) ==="
sudo apt-get update
sudo apt-get install -y git zip unzip openjdk-17-jdk python3-pip autoconf libtool pkg-config \
    zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev \
    automake libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev libsdl2-ttf-dev

pip3 install --upgrade Cython==0.29.36 buildozer

echo "=== Запуск компиляции APK (Wilderness: Эпоха Выживания) ==="
buildozer android debug

echo "=== ГОТОВО! Ваш APK-файл находится в папке bin/ ==="
ls -lh bin/*.apk
