[app]
# Название игры на экране телефона
title = Wilderness: Эпоха Выживания
package.name = wilderness_rpg
package.domain = org.wilderness

# Исходный код (main.py автоматически запускает wilderness_survival_rpg.py)
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json

# Версия приложения
version = 1.5.0

# Требуемые библиотеки Python для сборки APK
requirements = python3,pygame,numpy

# Горизонтальная ориентация (альбомная) и полноэкранный режим для 3D-игры
orientation = landscape
fullscreen = 1

# Архитектуры процессоров современных Android-телефонов
android.archs = arm64-v8a
android.api = 33
android.minapi = 24
android.ndk = 25b
android.accept_sdk_license = True
android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 0
