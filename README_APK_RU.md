# Сборка Android APK — «Wilderness: Эпоха Выживания» (3D Survival RPG)

В этом архиве подготовлен полный проект для компиляции игры в установочный файл **`.apk`** для Android, с уже включенным сенсорным управлением (виртуальный 360°-джойстик, мультитач-обзор свайпом и экранные кнопки действий).

---

## Способ 1. Сборка `.apk` в облаке в 1 клик (бесплатно, без установки программ на ПК)

Поскольку компиляция Python + Pygame + NumPy под процессоры телефонов (`arm64-v8a`) требует около 4 ГБ Android SDK и NDK, проще всего собрать `.apk` автоматически через **GitHub Actions** или **Google Colab**:

### Вариант А — через GitHub Actions (автоматически):
1. Создайте бесплатный репозиторий на [GitHub](https://github.com/new) и загрузите туда файлы из этого архива (`main.py`, `wilderness_survival_rpg.py`, `buildozer.spec` и папку `.github/workflows/build_apk.yml`).
2. Перейдите во вкладку **Actions** в вашем репозитории -> выберите **Build Android APK** -> нажмите **Run workflow**.
3. Через ~12–15 минут внизу страницы сборки появится готовый файл **`wilderness-survival-rpg-apk`** — скачайте его и установите `.apk` на телефон!

### Вариант Б — через Google Colab (прямо в браузере с телефона или ПК):
1. Откройте [Google Colab](https://colab.research.google.com/), создайте новый блокнот и загрузите в панель файлов слева 3 файла из архива: `main.py`, `wilderness_survival_rpg.py` и `buildozer.spec`.
2. Выполните в ячейке следующие команды:
   ```bash
   !apt-get update && apt-get install -y git zip unzip openjdk-17-jdk autoconf libtool pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 cmake libffi-dev libssl-dev automake
   !pip install buildozer Cython==0.29.36
   !yes | buildozer android debug
   ```
3. По завершении скачайте готовый файл `bin/wilderness_rpg-1.5.0-arm64-v8a_armeabi-v7a-debug.apk` из папки `bin/`.

---

## Способ 2. Локальная компиляция `.apk` на ПК (Linux или Windows WSL2)

1. Распакуйте этот архив в отдельную папку.
2. Запустите готовый скрипт автоматической сборки:
   ```bash
   chmod +x build_apk.sh
   ./build_apk.sh
   ```
3. Готовый файл `wilderness_rpg-1.5.0-arm64-v8a_armeabi-v7a-debug.apk` появится в папке `bin/`.

---

## Способ 3. Мгновенный запуск на Android без компиляции (через Pydroid 3)

Если вы хотите запустить игру на телефоне прямо сейчас за 1 минуту без ожидания сборки APK:
1. Установите из Google Play бесплатное приложение **Pydroid 3**.
2. В меню Pydroid 3 откройте **Pip** и установите `pygame` и `numpy`.
3. Откройте файл `wilderness_survival_rpg.py` и нажмите желтую кнопку **Play (▶)** — игра сразу запустится в полноэкранном альбомном режиме с сенсорным джойстиком и кнопками!
