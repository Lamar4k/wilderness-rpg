#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа main.py для упаковки игры Wilderness: Эпоха Выживания в Android APK (Buildozer / python-for-android).
"""
import os
import sys

os.environ.setdefault("ANDROID_ARGUMENT", "1")
from wilderness_survival_rpg import main

if __name__ == "__main__":
    main()
