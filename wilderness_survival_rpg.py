#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  WILDERNESS: ЭПОХА ВЫЖИВАНИЯ (TURBO-OPTIMIZED 3D Open-World Survival RPG)
================================================================================
Полноценная 3D-игра с открытым миром от первого лица на языке Python (без JS).
Версия с глубокой оптимизацией GPU/CPU и встроенным мониторингом FPS / ms.

Ключевые оптимизации движка (60–300+ FPS):
  1. Полный отказ от медленного glDrawPixels:
     - Весь 2D-интерфейс (полоски здоровья, хотбар, радар, прицел, окна) рисуется
       напрямую аппаратными 2D-примитивами OpenGL (GL_QUADS / GL_LINES), а текст
       рендерится через LRU-кеш маленьких текстур (GLTextCache) на видеокарте.
  2. Скомпилированные 3D-меши в видеопамяти (OpenGL Display Lists):
     - Единичный куб, все виды деревьев (сосна, дуб, береза), кусты, валуны и
       рудные жилы компилируются в GPU Display Lists при старте — каждое дерево
       рисуется за 1 вызов glCallList без циклов Python!
  3. Чанковый ландшафт (8x8 секторов) + Frustum & Distance Culling:
     - Мир разбит на 64 пространственных сектора (чанка). В каждом кадре рисуются
       только те чанки и объекты, которые находятся в конусе взгляда камеры.
  4. Пространственная хеш-сетка коллизий O(1) (Spatial Hash Grid):
     - Проверка столкновений игрока и 85+ животных с деревьями и стенами дома
       выполняется за O(1) по локальной ячейке сетки (ускорение физики в 200+ раз).
  5. Адаптивный ИИ (AI LOD) и переключение профилей графики [G]:
     - Клавиша [G] на лету переключает дальность прорисовки (Киберспорт / Высокие / Ультра).
     - Клавиша [V] переключает лимит кадров (60 FPS / 120 FPS / Без лимита).

Запуск:
  pip install pygame PyOpenGL numpy
  python wilderness_survival_rpg.py

Управление:
  WASD          — Передвижение
  Мышь / ЛКМ    — Обзор / Атака, добыча ресурсов, выстрел из лука, постройка
  ПКМ или [E]   — Быстрое строительство / взаимодействие
  Space / Shift — Прыжок / Спринт (или всплытие в озере)
  1 .. 9        — Выбор оружия или инструмента в руках
  [C]           — Меню крафта оружия, брони и предметов
  [B]           — Режим строительства дома (Z/X — выбор блока, R — поворот)
  [K] / [Tab]   — Меню РПГ-прокачки персонажа (F1..F5 — прокачка навыков)
  [F]           — Взаимодействие (пожарить мясо на костре, попить из озера,
                  собрать ягоды, открыть/закрыть дверь, отдохнуть у очага)
  [H]           — Съесть еду / Использовать целебный бальзам
  [G]           — Переключить профиль графики и дальности прорисовки (FPS Boost)
  [V]           — Переключить лимит FPS (60 / 120 / Без лимита)
  [F5] / [F9]   — Быстрое сохранение / Быстрая загрузка мира
  [Esc]         — Освободить курсор мыши / Выход из меню
================================================================================
"""

from __future__ import annotations

from collections import deque
import json
import math
import os
import random
import glob
import site
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


def _bootstrap_venv_packages() -> None:
    """
    Автоматически находит уже установленные numpy / pygame / PyOpenGL в системном Python
    или соседних виртуальных окружениях (.venv) на компьютере, либо доустанавливает их через pip,
    если скрипт запущен в новом пустом виртуальном окружении (.venv).
    """
    missing = []
    for mod_name in ("numpy", "pygame", "OpenGL"):
        try:
            __import__(mod_name)
        except ImportError:
            missing.append(mod_name)
    if not missing:
        return

    candidate_dirs = []
    # 1. Глобальный (базовый) Python, из которого был создан .venv
    for prefix in {getattr(sys, "base_prefix", ""), getattr(sys, "real_prefix", ""), sys.prefix}:
        if prefix:
            candidate_dirs.append(os.path.join(prefix, "Lib", "site-packages"))
            candidate_dirs.append(
                os.path.join(prefix, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
            )

    # 2. Пользовательский site-packages (%APPDATA%\Python\Python3XX\site-packages)
    try:
        user_site = site.getusersitepackages()
        if isinstance(user_site, str):
            candidate_dirs.append(user_site)
    except Exception:
        pass

    # 3. Соседние папки проектов на Рабочем столе (например, предыдущие папки со старым .venv)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    if parent_dir and os.path.isdir(parent_dir):
        for pat in ("*/.venv/Lib/site-packages", "*/venv/Lib/site-packages", ".venv/Lib/site-packages"):
            candidate_dirs.extend(glob.glob(os.path.join(parent_dir, pat)))

    # 4. Стандартные пути установки Python в Windows AppData
    local_app = os.environ.get("LOCALAPPDATA", "")
    roaming_app = os.environ.get("APPDATA", "")
    py_tag = f"Python{sys.version_info.major}{sys.version_info.minor}"
    if local_app:
        candidate_dirs.extend(glob.glob(os.path.join(local_app, "Programs", "Python", py_tag, "Lib", "site-packages")))
        candidate_dirs.extend(glob.glob(os.path.join(local_app, "Programs", "Python", "Python*", "Lib", "site-packages")))
    if roaming_app:
        candidate_dirs.extend(glob.glob(os.path.join(roaming_app, "Python", py_tag, "site-packages")))

    for d in candidate_dirs:
        if d and os.path.isdir(d) and d not in sys.path:
            if any(os.path.exists(os.path.join(d, m)) for m in ("numpy", "pygame", "OpenGL")):
                sys.path.append(d)

    still_missing = []
    for mod_name, pip_name in (("numpy", "numpy"), ("pygame", "pygame"), ("OpenGL", "PyOpenGL")):
        try:
            __import__(mod_name)
        except ImportError:
            still_missing.append(pip_name)

    # 5. Если в текущем .venv нет numpy, но в соседней папке на Рабочем столе или в системе есть другой Python с numpy —
    #    автоматически перезапускаем игру через тот Python-интерпретатор, где все библиотеки уже установлены!
    if "numpy" in still_missing and not os.environ.get("WSRPG_RELAUNCHED"):
        candidate_pythons = []
        if parent_dir and os.path.isdir(parent_dir):
            candidate_pythons.extend(glob.glob(os.path.join(parent_dir, "*/.venv/Scripts/python.exe")))
            candidate_pythons.extend(glob.glob(os.path.join(parent_dir, "*/venv/Scripts/python.exe")))
        base_py = os.path.join(getattr(sys, "base_prefix", ""), "python.exe")
        if os.path.isfile(base_py):
            candidate_pythons.append(base_py)
        if local_app:
            candidate_pythons.extend(glob.glob(os.path.join(local_app, "Programs", "Python", "Python*", "python.exe")))

        for py_exe in candidate_pythons:
            if os.path.isfile(py_exe) and os.path.normcase(py_exe) != os.path.normcase(sys.executable):
                try:
                    res = subprocess.run(
                        [py_exe, "-c", "import numpy, pygame, OpenGL"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=4,
                    )
                    if res.returncode == 0:
                        env = os.environ.copy()
                        env["WSRPG_RELAUNCHED"] = "1"
                        raise SystemExit(subprocess.call([py_exe, os.path.abspath(__file__), *sys.argv[1:]], env=env))
                except SystemExit:
                    raise
                except Exception:
                    pass


_bootstrap_venv_packages()
import numpy as np

# Попытка импорта Pygame и PyOpenGL
HAS_PYGAME = False
HAS_OPENGL = False

try:
    import pygame
    from pygame.locals import (
        DOUBLEBUF,
        KEYDOWN,
        MOUSEBUTTONDOWN,
        OPENGL,
        QUIT,
        RESIZABLE,
    )
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False

try:
    from OpenGL.GL import (
        GL_AMBIENT_AND_DIFFUSE,
        GL_BLEND,
        GL_CLAMP_TO_EDGE,
        GL_REPEAT,
        GL_COLOR_BUFFER_BIT,
        GL_COLOR_MATERIAL,
        GL_COMPILE,
        GL_CULL_FACE,
        GL_DEPTH_BUFFER_BIT,
        GL_DEPTH_TEST,
        GL_DIFFUSE,
        GL_EXP2,
        GL_FOG,
        GL_FOG_COLOR,
        GL_FOG_DENSITY,
        GL_FOG_MODE,
        GL_FRONT_AND_BACK,
        GL_LEQUAL,
        GL_LIGHT0,
        GL_LIGHT1,
        GL_LIGHTING,
        GL_LIGHT_MODEL_AMBIENT,
        GL_LINEAR,
        GL_LINES,
        GL_LINE_LOOP,
        GL_MODELVIEW,
        GL_NORMALIZE,
        GL_ONE_MINUS_SRC_ALPHA,
        GL_CONSTANT_ATTENUATION,
        GL_LINEAR_ATTENUATION,
        GL_QUADRATIC_ATTENUATION,
        GL_POSITION,
        GL_PROJECTION,
        GL_QUADS,
        GL_RGBA,
        GL_SHININESS,
        GL_SMOOTH,
        GL_SPECULAR,
        GL_SRC_ALPHA,
        GL_TEXTURE_2D,
        GL_TEXTURE_MAG_FILTER,
        GL_TEXTURE_MIN_FILTER,
        GL_TEXTURE_WRAP_S,
        GL_TEXTURE_WRAP_T,
        GL_TRIANGLES,
        GL_UNSIGNED_BYTE,
        glBindTexture,
        glBegin,
        glBlendFunc,
        glCallList,
        glClear,
        glClearColor,
        glColor3f,
        glColor4f,
        glColorMaterial,
        glDeleteTextures,
        glDepthFunc,
        glDepthMask,
        glDisable,
        glEnable,
        glEnd,
        glEndList,
        glFogf,
        glFogfv,
        glFogi,
        glGenLists,
        glGenTextures,
        glLightModelfv,
        glLightfv,
        glLineWidth,
        glMaterialf,
        glMaterialfv,
        glLoadIdentity,
        glMatrixMode,
        glNewList,
        glNormal3f,
        glOrtho,
        glPopMatrix,
        glPushMatrix,
        glRotatef,
        glScalef,
        glShadeModel,
        glTexCoord2f,
        glTexImage2D,
        glTexParameteri,
        glTranslatef,
        glVertex2f,
        glVertex3f,
        glViewport,
    )
    from OpenGL.GLU import gluPerspective
    HAS_OPENGL = True
except ImportError:
    HAS_OPENGL = False


# ==============================================================================
# 1. КОНСТАНТЫ МИРА, ПРОФИЛИ ОПТИМИЗАЦИИ, РУДЫ, ЕДА И ИНСТРУМЕНТЫ
# ==============================================================================

WORLD_HALF_SIZE = 192.0
WATER_LEVEL = 0.0
BEACH_LEVEL = 1.8
MOUNTAIN_LEVEL = 13.5      # Широкие предгорья и середина гор (13.5 .. 26.0 м)
MOUNTAIN_MID_MIN = 13.5    # Нижняя граница спавна горных козлов (середина гор)
MOUNTAIN_MID_MAX = 25.5    # Верхняя граница спавна горных козлов (середина гор)
SNOW_LEVEL = 26.5          # Высокогорные снежные пики
GRAVITY = 24.0
IS_ANDROID = bool(
    "ANDROID_ARGUMENT" in os.environ
    or "ANDROID_PRIVATE" in os.environ
    or "ANDROID_ROOT" in os.environ
    or sys.platform == "android"
)
_ANDROID_DATA_DIR = os.environ.get("ANDROID_PRIVATE") or os.environ.get(" KP_TMP_DIR") or os.path.expanduser("~")
SAVE_FILE_PATH = (
    os.path.join(_ANDROID_DATA_DIR, "wilderness_savegame.json")
    if IS_ANDROID and os.path.isdir(_ANDROID_DATA_DIR)
    else "wilderness_savegame.json"
)

GRAPHICS_PROFILES = [
    {
        "name": "НИЗКИЕ (Макс. FPS / Слабый ПК)",
        "render_dist": 72.0,
        "sw_render_dist": 50.0,
        "fog_density": 0.0115,
        "particles_mult": 0.35,
        "clouds_enabled": False,
        "detail_idx": 0,
        "shadows": False,
        "grass_idx": 1,
    },
    {
        "name": "СРЕДНИЕ (Баланс)",
        "render_dist": 105.0,
        "sw_render_dist": 66.0,
        "fog_density": 0.0080,
        "particles_mult": 0.70,
        "clouds_enabled": True,
        "detail_idx": 1,
        "shadows": True,
        "grass_idx": 2,
    },
    {
        "name": "ВЫСОКИЕ (Реализм HD)",
        "render_dist": 135.0,
        "sw_render_dist": 78.0,
        "fog_density": 0.0062,
        "particles_mult": 1.0,
        "clouds_enabled": True,
        "detail_idx": 2,
        "shadows": True,
        "grass_idx": 3,
    },
    {
        "name": "УЛЬТРА HD (Макс. Реализм)",
        "render_dist": 168.0,
        "sw_render_dist": 90.0,
        "fog_density": 0.0048,
        "particles_mult": 1.25,
        "clouds_enabled": True,
        "detail_idx": 3,
        "shadows": True,
        "grass_idx": 4,
    },
]

DETAIL_QUALITY_PRESETS = [
    ("Низкая (Минимум полигонов)", 0),
    ("Средняя (Стандартные модели)", 1),
    ("Высокая (Детальная + Цветы)", 2),
    ("Ультра HD (Корни, Ветви, Блики)", 3),
]

ANTIALIAS_PRESETS = [
    ("Выкл (Без сглаживания)", 0),
    ("2x (Сглаживание линий)", 2),
    ("MSAA 4x (Аппаратное)", 4),
    ("Ultra MSAA 8x + Анизотропия", 8),
]

SCREEN_RESOLUTIONS: List[Tuple[int, int, str]] = [
    (1024, 576, "1024x576 (HD Lite)"),
    (1280, 720, "1280x720 (HD 720p)"),
    (1366, 768, "1366x768 (WXGA)"),
    (1600, 900, "1600x900 (HD+)"),
    (1920, 1080, "1920x1080 (Full HD)"),
    (2560, 1440, "2560x1440 (2K QHD)"),
]

CHUNK_GEN_PRESETS: List[Tuple[int, str]] = [
    (1, "1 чанк (3x3 = 9 секторов)"),
    (2, "2 чанка (5x5 = 25 секторов)"),
    (3, "3 чанка (7x7 = 49 секторов)"),
    (4, "4 чанка (9x9 = 81 сектор)"),
    (5, "5 чанков (11x11 = 121 сектор)"),
]

FPS_CAPS = [30, 60, 120, 144, 0]
GRASS_DENSITY_PRESETS = [
    ("0% (Выкл)", 0.0),
    ("50% (Низкая)", 0.5),
    ("100% (Средняя)", 1.0),
    ("150% (Высокая)", 1.5),
    ("200% (Максимум)", 2.0),
]
MAX_INVENTORY_SLOTS = 25
MAX_CHEST_SLOTS = 15
DEATH_LOOT_DESPAWN_SECONDS = 300.0  # 5 минут (300 секунд) предметы лежат на месте гибели, затем исчезают!


@dataclass
class WeaponSpec:
    id: str
    name: str
    category: str          # 'tool', 'spear', 'axe', 'sword', 'bow', 'fishing', 'utility'
    damage: float
    tree_mult: float
    rock_mult: float
    reach: float
    cooldown: float
    stamina_cost: float
    color: Tuple[float, float, float]
    description: str


WEAPONS_DB: Dict[str, WeaponSpec] = {
    "rock": WeaponSpec(
        id="rock",
        name="Камень выжившего",
        category="tool",
        damage=10.0,
        tree_mult=1.0,
        rock_mult=1.0,
        reach=3.2,
        cooldown=0.40,
        stamina_cost=3.5,
        color=(0.55, 0.54, 0.52),
        description="Грубый осколок скалы для первой добычи дерева и камня.",
    ),
    "stone_axe": WeaponSpec(
        id="stone_axe",
        name="Каменный топор",
        category="axe",
        damage=24.0,
        tree_mult=2.8,
        rock_mult=1.2,
        reach=3.6,
        cooldown=0.44,
        stamina_cost=5.0,
        color=(0.65, 0.62, 0.58),
        description="Надежный топор для быстрой валки леса и ближнего боя.",
    ),
    "wooden_spear": WeaponSpec(
        id="wooden_spear",
        name="Деревянное копье (и Гарпун)",
        category="spear",
        damage=29.0,
        tree_mult=0.6,
        rock_mult=0.4,
        reach=5.4,
        cooldown=0.38,
        stamina_cost=4.8,
        color=(0.76, 0.58, 0.36),
        description="Длинное копье для боя на дистанции и ловли рыбы в реках и озерах.",
    ),
    "stone_pickaxe": WeaponSpec(
        id="stone_pickaxe",
        name="Рудокопная кирка",
        category="tool",
        damage=19.0,
        tree_mult=0.8,
        rock_mult=3.5,
        reach=3.6,
        cooldown=0.45,
        stamina_cost=5.5,
        color=(0.52, 0.55, 0.60),
        description="Добывает уголь, медь, железо, золото и мифрил в горах и пещерах.",
    ),
    "copper_sword": WeaponSpec(
        id="copper_sword",
        name="Медный клинок",
        category="sword",
        damage=38.0,
        tree_mult=1.4,
        rock_mult=0.8,
        reach=4.0,
        cooldown=0.34,
        stamina_cost=4.5,
        color=(0.88, 0.52, 0.28),
        description="Быстрый кованый медный меч с широким рубящим взмахом.",
    ),
    "iron_axe": WeaponSpec(
        id="iron_axe",
        name="Железный боевой топор",
        category="axe",
        damage=48.0,
        tree_mult=4.6,
        rock_mult=2.0,
        reach=3.9,
        cooldown=0.44,
        stamina_cost=6.0,
        color=(0.78, 0.83, 0.90),
        description="Тяжелый стальной топор. Валит вековые деревья и сокрушает хищников.",
    ),
    "hunting_bow": WeaponSpec(
        id="hunting_bow",
        name="Охотничий лук",
        category="bow",
        damage=45.0,
        tree_mult=0.0,
        rock_mult=0.0,
        reach=65.0,
        cooldown=0.60,
        stamina_cost=6.5,
        color=(0.58, 0.38, 0.18),
        description="Дальнобойный лук с живой анимацией натяжения тетивы и стрелы.",
    ),
    "mythril_blade": WeaponSpec(
        id="mythril_blade",
        name="Мифриловый ледяной клинок",
        category="sword",
        damage=72.0,
        tree_mult=3.0,
        rock_mult=2.5,
        reach=4.6,
        cooldown=0.33,
        stamina_cost=5.0,
        color=(0.35, 0.88, 1.00),
        description="Легендарный клинок из пещерного мифрила, золота и клыков хищников.",
    ),
    "torch": WeaponSpec(
        id="torch",
        name="Горящий факел",
        category="utility",
        damage=16.0,
        tree_mult=0.5,
        rock_mult=0.3,
        reach=3.3,
        cooldown=0.36,
        stamina_cost=2.5,
        color=(1.0, 0.62, 0.15),
        description="Освещает темные пещеры и ночь, согревает в Зимнем биоме.",
    ),
    "fishing_rod": WeaponSpec(
        id="fishing_rod",
        name="Удочка рыболова",
        category="fishing",
        damage=8.0,
        tree_mult=0.2,
        rock_mult=0.2,
        reach=16.0,
        cooldown=0.45,
        stamina_cost=3.0,
        color=(0.72, 0.54, 0.28),
        description="Забрасывает поплавок в реки и озера (ЛКМ — забросить / подсечь улов!).",
    ),
    "workbench_item": WeaponSpec(
        id="workbench_item",
        name="Стол мастерской (Верстак)",
        category="placeable",
        damage=8.0,
        tree_mult=0.5,
        rock_mult=0.5,
        reach=4.8,
        cooldown=0.30,
        stamina_cost=2.0,
        color=(0.66, 0.45, 0.24),
        description="Установите Стол на землю, чтобы открыть Крафт и Строительство!",
    ),
    "hammer": WeaponSpec(
        id="hammer",
        name="Строительный молот",
        category="utility",
        damage=14.0,
        tree_mult=1.0,
        rock_mult=1.0,
        reach=4.8,
        cooldown=0.30,
        stamina_cost=2.5,
        color=(0.68, 0.50, 0.30),
        description="Строительство дома с привязкой стен к краям фундамента.",
    ),
}

SLOT_ORDER = [
    "rock",
    "stone_axe",
    "wooden_spear",
    "stone_pickaxe",
    "copper_sword",
    "iron_axe",
    "hunting_bow",
    "fishing_rod",
    "mythril_blade",
]


@dataclass
class CraftingRecipe:
    id: str
    name: str
    cost: Dict[str, int]
    result_item: str
    result_count: int
    unlock_weapon: Optional[str]
    xp_reward: int
    description: str


CRAFTING_RECIPES: List[CraftingRecipe] = [
    CraftingRecipe(
        id="craft_stone_axe",
        name="Каменный топор",
        cost={"wood": 3, "stone": 3},
        result_item="stone_axe",
        result_count=1,
        unlock_weapon="stone_axe",
        xp_reward=35,
        description="Быстрая рубка леса и защита",
    ),
    CraftingRecipe(
        id="craft_wooden_spear",
        name="Деревянное копье / Гарпун",
        cost={"wood": 4, "stone": 2},
        result_item="wooden_spear",
        result_count=1,
        unlock_weapon="wooden_spear",
        xp_reward=35,
        description="Длинный выпад и ловля рыбы в реках и озерах",
    ),
    CraftingRecipe(
        id="craft_stone_pickaxe",
        name="Рудокопная кирка",
        cost={"wood": 3, "stone": 4},
        result_item="stone_pickaxe",
        result_count=1,
        unlock_weapon="stone_pickaxe",
        xp_reward=40,
        description="Добыча угля, меди, железа, золота и мифрила в горах и пещерах",
    ),
    CraftingRecipe(
        id="craft_fishing_rod",
        name="Удочка рыболова",
        cost={"wood": 3, "wool": 1},
        result_item="fishing_rod",
        result_count=1,
        unlock_weapon="fishing_rod",
        xp_reward=40,
        description="Удилище с катушкой и поплавком для рыбалки в озерах и реках",
    ),
    CraftingRecipe(
        id="craft_torch",
        name="Горящий факел",
        cost={"wood": 2, "coal": 1},
        result_item="torch",
        result_count=1,
        unlock_weapon="torch",
        xp_reward=25,
        description="Живой огонь для пещер и защиты от мороза в Зимнем биоме",
    ),
    CraftingRecipe(
        id="craft_copper_sword",
        name="Медный клинок",
        cost={"wood": 2, "copper": 3, "coal": 1},
        result_item="copper_sword",
        result_count=1,
        unlock_weapon="copper_sword",
        xp_reward=65,
        description="Быстрый меч из переплавленной медной руды",
    ),
    CraftingRecipe(
        id="craft_hunting_bow",
        name="Охотничий лук + 10 стрел",
        cost={"wood": 5, "wool": 2, "feather": 3},
        result_item="arrow",
        result_count=10,
        unlock_weapon="hunting_bow",
        xp_reward=70,
        description="Лук с анимированной тетивой для охоты на козлов и хищников",
    ),
    CraftingRecipe(
        id="craft_arrows",
        name="Охотничьи стрелы (x12)",
        cost={"wood": 2, "stone": 2, "feather": 2},
        result_item="arrow",
        result_count=12,
        unlock_weapon=None,
        xp_reward=25,
        description="Запас оперенных стрел для лука",
    ),
    CraftingRecipe(
        id="craft_iron_axe",
        name="Железный боевой топор",
        cost={"wood": 3, "iron": 4, "coal": 2, "leather": 1},
        result_item="iron_axe",
        result_count=1,
        unlock_weapon="iron_axe",
        xp_reward=95,
        description="Мощный стальной топор против тигров и медведей",
    ),
    CraftingRecipe(
        id="craft_mythril_blade",
        name="Мифриловый ледяной клинок",
        cost={"mythril": 3, "gold": 2, "iron": 3, "fang": 2},
        result_item="mythril_blade",
        result_count=1,
        unlock_weapon="mythril_blade",
        xp_reward=160,
        description="Вершина кузнечного дела: огромный урон (72 ед.) и добыча руд",
    ),
    CraftingRecipe(
        id="craft_fur_helmet",
        name="Теплая меховая шапка",
        cost={"wool": 2, "pelt": 1},
        result_item="fur_helmet",
        result_count=1,
        unlock_weapon=None,
        xp_reward=65,
        description="Ячейка [Голова]: снижает урон на +12% и защищает от мороза",
    ),
    CraftingRecipe(
        id="craft_fur_armor",
        name="Теплый меховой доспех",
        cost={"leather": 2, "wool": 3, "pelt": 2},
        result_item="fur_armor",
        result_count=1,
        unlock_weapon=None,
        xp_reward=100,
        description="Ячейка [Броня]: снижает урон на +25% и согревает в Зимнем биоме",
    ),
    CraftingRecipe(
        id="craft_fur_pants",
        name="Кожаные штаны охотника",
        cost={"leather": 2, "wool": 2},
        result_item="fur_pants",
        result_count=1,
        unlock_weapon=None,
        xp_reward=80,
        description="Ячейка [Штаны]: снижает урон на +15% и согревает ноги",
    ),
    CraftingRecipe(
        id="craft_wool_socks",
        name="Шерстяные носки и сапоги",
        cost={"wool": 2, "leather": 1},
        result_item="wool_socks",
        result_count=1,
        unlock_weapon=None,
        xp_reward=55,
        description="Ячейка [Носки/Обувь]: снижает урон на +8% и ускоряет шаг",
    ),
    CraftingRecipe(
        id="craft_hunter_stew",
        name="Ароматное жаркое охотника (x2)",
        cost={"raw_meat": 1, "mushroom": 2, "berries": 2},
        result_item="hunter_stew",
        result_count=2,
        unlock_weapon=None,
        xp_reward=35,
        description="Деликатес: восстанавливает +70 Сытости, +45 HP и согревает",
    ),
    CraftingRecipe(
        id="craft_herbal_salve",
        name="Целебный бальзам из трав и грибов (x2)",
        cost={"berries": 3, "mushroom": 1},
        result_item="salve",
        result_count=2,
        unlock_weapon=None,
        xp_reward=25,
        description="Мгновенно исцеляет +50 HP в бою",
    ),
]


ARMOR_SLOT_KEYS: List[str] = ["head", "chest", "legs", "feet"]
ARMOR_SLOT_TITLES: List[str] = [
    "1. Голова / Шапка",
    "2. Торс / Доспех",
    "3. Штаны / Поножи",
    "4. Носки / Сапоги",
]
ITEM_TO_ARMOR_SLOT_IDX: Dict[str, int] = {
    "fur_helmet": 0,
    "fur_armor": 1,
    "fur_pants": 2,
    "wool_socks": 3,
}
ARMOR_DEFENSE_BONUS: Dict[str, float] = {
    "fur_helmet": 0.12,
    "fur_armor": 0.25,
    "fur_pants": 0.15,
    "wool_socks": 0.08,
}

# Максимальная прочность всех инструментов, оружия и одежды/брони (отображается полоской снизу ячейки!)
ITEM_MAX_DURABILITY: Dict[str, float] = {
    "rock": 60.0,
    "stone_axe": 120.0,
    "wooden_spear": 110.0,
    "stone_pickaxe": 130.0,
    "fishing_rod": 90.0,
    "torch": 100.0,
    "hammer": 180.0,
    "copper_sword": 180.0,
    "hunting_bow": 160.0,
    "iron_axe": 240.0,
    "mythril_blade": 360.0,
    "fur_helmet": 140.0,
    "fur_armor": 220.0,
    "fur_pants": 180.0,
    "wool_socks": 120.0,
}


def make_slot_dict(
    item_id: str,
    count: int = 1,
    durability: Optional[float] = None,
    max_durability: Optional[float] = None,
) -> Dict[str, object]:
    """Создает словарь ячейки инвентаря/хотбара/брони/сундука с автоматической инициализацией прочности."""
    sl: Dict[str, object] = {"item": item_id, "count": int(count)}
    if item_id in ITEM_MAX_DURABILITY:
        mx = float(max_durability if max_durability is not None else ITEM_MAX_DURABILITY[item_id])
        cur = float(durability if durability is not None else mx)
        sl["durability"] = max(0.0, min(mx, cur))
        sl["max_durability"] = mx
    return sl


def get_slot_durability_ratio(sl: Optional[Dict[str, object]]) -> Optional[float]:
    """Возвращает долю прочности предмета в ячейке (0.0 .. 1.0) для инструментов, оружия и одежды, либо None для ресурсов."""
    if sl is None:
        return None
    item_id = str(sl.get("item", ""))
    if item_id not in ITEM_MAX_DURABILITY:
        return None
    mx = float(sl.get("max_durability", ITEM_MAX_DURABILITY[item_id]))
    if "durability" not in sl:
        sl["durability"] = mx
        sl["max_durability"] = mx
    cur = float(sl.get("durability", mx))
    return max(0.0, min(1.0, cur / max(1.0, mx)))


@dataclass
class BuildPieceSpec:
    id: str
    name: str
    cost: Dict[str, int]
    size: Tuple[float, float, float]
    y_offset: float
    is_solid: bool
    is_roof: bool
    xp_reward: int
    description: str


BUILD_PIECES: List[BuildPieceSpec] = [
    BuildPieceSpec(
        id="foundation",
        name="Деревянный фундамент (Пол 4x4)",
        cost={"wood": 4, "stone": 2},
        size=(4.0, 0.45, 4.0),
        y_offset=0.22,
        is_solid=True,
        is_roof=False,
        xp_reward=30,
        description="Основание дома 4x4 м. Автоматически выравнивается с соседним полом!",
    ),
    BuildPieceSpec(
        id="wall",
        name="Бревенчатая стена (По краю пола)",
        cost={"wood": 4},
        size=(4.0, 3.0, 0.42),
        y_offset=1.50,
        is_solid=True,
        is_roof=False,
        xp_reward=25,
        description="Автоматически примагничивается ровно к краю фундамента!",
    ),
    BuildPieceSpec(
        id="window_wall",
        name="Стена с резным окном",
        cost={"wood": 4},
        size=(4.0, 3.0, 0.42),
        y_offset=1.50,
        is_solid=True,
        is_roof=False,
        xp_reward=28,
        description="Бревенчатая стена с оконной рамой и ставнями по краю пола",
    ),
    BuildPieceSpec(
        id="doorway",
        name="Входная стена с дверью",
        cost={"wood": 5},
        size=(4.0, 3.0, 0.42),
        y_offset=1.50,
        is_solid=True,
        is_roof=False,
        xp_reward=35,
        description="Дверной проем с дверью на петлях и ручкой",
    ),
    BuildPieceSpec(
        id="roof",
        name="Двускатная бревенчатая крыша",
        cost={"wood": 5},
        size=(4.3, 1.9, 4.3),
        y_offset=3.20,
        is_solid=False,
        is_roof=True,
        xp_reward=35,
        description="Плотная двускатная крыша со сплошными скатами и фронтонами (дает статус 'В ДОМЕ')",
    ),
    BuildPieceSpec(
        id="stairs",
        name="Резная лестница со ступенями",
        cost={"wood": 3},
        size=(2.4, 1.4, 3.0),
        y_offset=0.60,
        is_solid=False,
        is_roof=False,
        xp_reward=25,
        description="Пристраивается к краю фундамента для плавного входа в дом",
    ),
    BuildPieceSpec(
        id="campfire",
        name="Анимированный костер",
        cost={"wood": 4, "stone": 4},
        size=(1.5, 0.65, 1.5),
        y_offset=0.25,
        is_solid=False,
        is_roof=False,
        xp_reward=40,
        description="Живое пламя! Жарит рыбу и мясо в стейки",
    ),
    BuildPieceSpec(
        id="bedroll",
        name="Деревянная кровать с подушкой и пледом",
        cost={"wood": 4, "wool": 2, "leather": 1},
        size=(2.3, 0.85, 1.5),
        y_offset=0.42,
        is_solid=False,
        is_roof=False,
        xp_reward=65,
        description="Детализированная кровать с изголовьем, матрасом, подушкой и меховым пледом!",
    ),
    BuildPieceSpec(
        id="chest",
        name="Кованый сундук для хранения вещей",
        cost={"wood": 4, "stone": 2},
        size=(1.25, 0.82, 0.85),
        y_offset=0.40,
        is_solid=False,
        is_roof=False,
        xp_reward=45,
        description="Вместительный сундук с открывающейся крышкой и замком для хранения ресурсов!",
    ),
    BuildPieceSpec(
        id="workbench",
        name="Стол мастерской (Верстак)",
        cost={"wood": 2},
        size=(1.65, 0.92, 1.10),
        y_offset=0.45,
        is_solid=False,
        is_roof=False,
        xp_reward=50,
        description="Главный стол ремесленника для создания оружия и инструментов!",
    ),
    BuildPieceSpec(
        id="chimney_hearth",
        name="Каменная печь-камин с дымоходом",
        cost={"stone": 6, "wood": 2},
        size=(1.60, 3.20, 1.40),
        y_offset=0.45,
        is_solid=True,
        is_roof=False,
        xp_reward=70,
        description="Каменный очаг с высокой трубой для дома: согревает и жарит мясо и рыбу!",
    ),
    BuildPieceSpec(
        id="fence",
        name="Бревенчатый забор / Ограда",
        cost={"wood": 2},
        size=(4.0, 1.35, 0.32),
        y_offset=0.68,
        is_solid=True,
        is_roof=False,
        xp_reward=20,
        description="Крепкая бревенчатая изгородь для защиты двора от хищников!",
    ),
    BuildPieceSpec(
        id="torch_stand",
        name="Уличная жаровня-факел на столбе",
        cost={"wood": 2, "coal": 1},
        size=(0.65, 2.10, 0.65),
        y_offset=0.45,
        is_solid=True,
        is_roof=False,
        xp_reward=30,
        description="Высокий резной столб с огненной чашей для освещения двора и дома ночью!",
    ),
    BuildPieceSpec(
        id="table_chair",
        name="Дубовый стол со скамьями",
        cost={"wood": 3},
        size=(1.80, 0.85, 1.40),
        y_offset=0.42,
        is_solid=True,
        is_roof=False,
        xp_reward=35,
        description="Добротный обеденный стол с двумя лавками и посудой для уюта в доме!",
    ),
]


RESOURCE_NAMES_RU: Dict[str, str] = {
    "wood": "Дерево",
    "stone": "Камень",
    "coal": "Уголь",
    "copper": "Медная руда",
    "iron": "Железная руда",
    "gold": "Золотая руда",
    "mythril": "Мифрил",
    "berries": "Ягоды",
    "mushroom": "Лесные грибы",
    "apple": "Лесные яблоки",
    "raw_fish": "Сырая рыба",
    "cooked_fish": "Запеченная рыба",
    "raw_meat": "Сырое мясо",
    "cooked_meat": "Жареный стейк",
    "hunter_stew": "Жаркое охотника",
    "leather": "Кожа",
    "wool": "Шерсть",
    "feather": "Перья",
    "fang": "Клык / Рог",
    "pelt": "Шкура зверя",
    "arrow": "Стрелы",
    "salve": "Целебный бальзам",
    "fur_helmet": "Меховая шапка",
    "fur_armor": "Меховой доспех",
    "fur_pants": "Кожаные штаны",
    "wool_socks": "Шерстяные носки",
    "workbench_item": "Стол мастерской",
}

RESOURCE_ICON_COLORS: Dict[str, Tuple[int, int, int]] = {
    "wood": (168, 112, 62),
    "stone": (145, 150, 158),
    "coal": (52, 56, 64),
    "copper": (228, 126, 68),
    "iron": (195, 205, 220),
    "gold": (255, 215, 65),
    "mythril": (80, 228, 255),
    "berries": (235, 55, 80),
    "mushroom": (215, 175, 130),
    "apple": (240, 65, 55),
    "raw_fish": (95, 185, 215),
    "cooked_fish": (245, 165, 95),
    "raw_meat": (215, 85, 85),
    "cooked_meat": (210, 125, 65),
    "hunter_stew": (245, 190, 75),
    "leather": (160, 95, 52),
    "wool": (240, 240, 232),
    "feather": (220, 235, 250),
    "fang": (245, 240, 215),
    "pelt": (130, 95, 70),
    "arrow": (195, 165, 100),
    "salve": (95, 235, 135),
    "fur_helmet": (195, 155, 110),
    "fur_armor": (175, 130, 95),
    "fur_pants": (140, 95, 58),
    "wool_socks": (225, 215, 195),
    "workbench_item": (185, 125, 65),
}


# ==============================================================================
# 2. ПРОЦЕДУРНЫЙ СИНТЕЗАТОР ЗВУКА (БЕЗ ВНЕШНИХ WAV-ФАЙЛОВ)
# ==============================================================================

class ProceduralSoundEngine:
    """Генерирует звуковые эффекты в памяти с помощью математического синтеза NumPy."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled and HAS_PYGAME
        self.sounds: Dict[str, object] = {}
        if not self.enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
            self._build_sounds()
        except Exception:
            self.enabled = False

    def _make_sound(self, mono_wave: np.ndarray, volume: float = 0.35) -> Optional[object]:
        if not self.enabled:
            return None
        try:
            clipped = np.clip(mono_wave * volume, -1.0, 1.0)
            pcm16 = (clipped * 32767).astype(np.int16)
            stereo = np.column_stack((pcm16, pcm16))
            return pygame.sndarray.make_sound(stereo)
        except Exception:
            return None

    def _build_sounds(self) -> None:
        sr = 22050
        rng = np.random.default_rng(42)

        t = np.linspace(0, 0.16, int(sr * 0.16), endpoint=False)
        env = np.exp(-t * 26.0)
        wave = (np.sin(2 * np.pi * 115 * t) * 0.7 + np.sin(2 * np.pi * 230 * t) * 0.3 + rng.normal(0, 0.25, t.size)) * env
        self.sounds["chop"] = self._make_sound(wave, 0.42)

        t = np.linspace(0, 0.20, int(sr * 0.20), endpoint=False)
        env = np.exp(-t * 22.0)
        wave = (np.sin(2 * np.pi * 880 * t) * 0.5 + np.sin(2 * np.pi * 1340 * t) * 0.35 + rng.normal(0, 0.2, t.size)) * env
        self.sounds["mine"] = self._make_sound(wave, 0.35)

        t = np.linspace(0, 0.14, int(sr * 0.14), endpoint=False)
        env = np.sin(np.pi * t / 0.14)
        freq = np.linspace(340, 140, t.size)
        wave = (np.sin(2 * np.pi * freq * t) * 0.4 + rng.normal(0, 0.35, t.size)) * env
        self.sounds["swing"] = self._make_sound(wave, 0.28)

        t = np.linspace(0, 0.22, int(sr * 0.22), endpoint=False)
        env = np.exp(-t * 16.0)
        wave = np.sin(2 * np.pi * (190 + 60 * np.sin(2 * np.pi * 35 * t)) * t) * env
        self.sounds["bow"] = self._make_sound(wave, 0.38)

        t = np.linspace(0, 0.38, int(sr * 0.38), endpoint=False)
        env = np.sin(np.pi * t / 0.38)
        wave = (np.sin(2 * np.pi * 78 * t + np.sin(2 * np.pi * 18 * t) * 3.0) * 0.65 + rng.normal(0, 0.3, t.size)) * env
        self.sounds["growl"] = self._make_sound(wave, 0.36)

        t = np.linspace(0, 0.22, int(sr * 0.22), endpoint=False)
        env = np.exp(-t * 14.0)
        wave = (np.sin(2 * np.pi * 330 * t) + np.sin(2 * np.pi * 495 * t)) * 0.5 * env
        self.sounds["build"] = self._make_sound(wave, 0.35)

        t = np.linspace(0, 0.65, int(sr * 0.65), endpoint=False)
        env = np.exp(-t * 3.5)
        wave = (
            np.sin(2 * np.pi * 523.25 * t)
            + np.sin(2 * np.pi * 659.25 * t)
            + np.sin(2 * np.pi * 783.99 * t)
            + np.sin(2 * np.pi * 1046.5 * t)
        ) * 0.25 * env
        self.sounds["levelup"] = self._make_sound(wave, 0.45)

        t = np.linspace(0, 0.28, int(sr * 0.28), endpoint=False)
        env = np.exp(-t * 10.0)
        wave = (np.sin(2 * np.pi * 440 * t) * 0.5 + np.sin(2 * np.pi * 660 * t) * 0.5) * env
        self.sounds["heal"] = self._make_sound(wave, 0.32)

    def play(self, name: str) -> None:
        if not self.enabled:
            return
        snd = self.sounds.get(name)
        if snd is not None:
            try:
                snd.play()
            except Exception:
                pass


# ==============================================================================
# 3. БЕСКОНЕЧНЫЙ МИР: УЗКИЕ ВЫСОКИЕ ПИКИ + ШИРОКИЕ ГОРЫ, БИОМ ЛЕСА, ЗИМА И РЕКИ
# ==============================================================================

CHUNK_SIZE = 48.0
CHUNK_STEP = 2.0
CHUNK_CELLS = int(CHUNK_SIZE // CHUNK_STEP)  # 24x24 = 576 ячеек (1152 треугольника рельефа на каждый чанк!)
NARROW_PEAK_SUMMIT_MIN = 22.5       # Вершины и предвершины высоких узких гор (для горных козлов!)
HIGH_MOUNTAIN_ELEVATION_MIN = 13.5  # Граница высоких гор (взбираться на высокие горы может только горный козел)
GOAT_MAX_CLIMB_ANGLE_DEG = 85.0     # Максимальный угол подъема для горных козлов (вплоть до 85 градусов!)
ANIMAL_MAX_CLIMB_ANGLE_DEG = 70.0   # Максимальный угол подъема для остальных животных (вплоть до 70 градусов!)
PLAYER_MAX_CLIMB_ANGLE_DEG = 75.0   # Максимальный угол подъема для персонажа (вплоть до 75 градусов!)
PREDATOR_CRITICAL_LEVEL = 10        # Критический уровень РПГ, после которого спавн хищников перестает расти
MIN_PREDATOR_SPACING = 18.0         # Уменьшенная дистанция между хищниками для более частого спавна (м)


@dataclass
class TerrainChunkData:
    cx: int
    cz: int
    center_x: float
    center_z: float
    biome_name: str
    verts: np.ndarray
    norms: np.ndarray
    cols: np.ndarray
    uvs: np.ndarray
    sw_verts: np.ndarray
    sw_cols: np.ndarray
    sw_norms: np.ndarray
    sw_centers: np.ndarray
    has_water: bool
    gl_list_id: Optional[int] = None
    gl_props_list_id: Optional[int] = None
    gl_grass_list_id: Optional[int] = None
    props_dirty: bool = True
    compiled_grass_idx: int = -1
    compiled_detail_idx: int = -1
    compiled_shadows: bool = False
    prop_count: int = 0
    grass_count: int = 0


class TerrainWorld:
    """
    Бесконечный процедурный генератор мира, сочетающий:
      1) Широкие массивные нагорья (с пещерами и рудными жилами).
      2) Высокие и узкие остроконечные горные пики (на вершинах которых живут Горные козлы!).
      3) Густой Биом Леса с объемной 3D-травой, Зимний биом (со Снежными барсами), Реки и Озера.
    """

    def __init__(self, seed: int = 2026) -> None:
        self.seed = seed
        self.phase_x = (seed * 17.31) % 1000.0
        self.phase_z = (seed * 31.79) % 1000.0
        self.generated_chunks: Dict[Tuple[int, int], TerrainChunkData] = {}
        self.populated_chunks: set[Tuple[int, int]] = set()
        self.compile_queue: deque[Tuple[int, int]] = deque()
        self._vertex_h_cache: Dict[Tuple[int, int], float] = {}
        self._grad_cache: Dict[Tuple[int, int], Tuple[float, float, float]] = {}

        for cx in range(-2, 3):
            for cz in range(-2, 3):
                self.get_or_create_chunk(cx, cz)

    def _eval_narrow_peaks_array(self, x: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Вычисляет вклад высоких и узких остроконечные горных пиков."""
        px = x + self.phase_x
        pz = z + self.phase_z
        # Периодическая решетка острых узких пиков + два знаковых узких пика рядом со стартом
        cell_x = np.sin(px * 0.032 + 0.9) * np.cos(pz * 0.032 - 0.6)
        sharp_spires = np.clip((cell_x - 0.52) / 0.48, 0.0, 1.0) ** 2.4 * 34.0

        spire1 = 33.5 * np.exp(-((x - 54.0) ** 2 + (z + 52.0) ** 2) / (2.0 * 14.5 ** 2))
        spire2 = 35.0 * np.exp(-((x + 58.0) ** 2 + (z + 48.0) ** 2) / (2.0 * 15.0 ** 2))
        return (sharp_spires + spire1 + spire2).astype(np.float32)

    def _eval_narrow_peaks_scalar(self, x: float, z: float) -> float:
        px = x + self.phase_x
        pz = z + self.phase_z
        cell_x = math.sin(px * 0.032 + 0.9) * math.cos(pz * 0.032 - 0.6)
        sharp_spires = (max(0.0, (cell_x - 0.52) / 0.48) ** 2.4) * 34.0
        if x * x + z * z < 220.0 ** 2:
            spire1 = 33.5 * math.exp(-((x - 54.0) ** 2 + (z + 52.0) ** 2) / (2.0 * 14.5 ** 2))
            spire2 = 35.0 * math.exp(-((x + 58.0) ** 2 + (z + 48.0) ** 2) / (2.0 * 15.0 ** 2))
            return sharp_spires + spire1 + spire2
        return sharp_spires

    def is_narrow_peak_summit(self, x: float, z: float) -> bool:
        """Возвращает True, если точка находится на вершине или почти вершине УЗКОЙ высокой горы."""
        narrow_h = self._eval_narrow_peaks_scalar(x, z)
        total_h = self.get_height(x, z)
        return narrow_h >= 16.5 and total_h >= NARROW_PEAK_SUMMIT_MIN

    def _eval_gorge_factor_array(self, x: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Вычисляет фактор глубоких скалистых ущелий и каньонов (0..1), прорезающих рельеф."""
        px = x + self.phase_x
        pz = z + self.phase_z
        gorge_curve_x = -38.0 + 36.0 * np.sin(pz * 0.015 + 0.5) + 14.0 * np.cos(pz * 0.031)
        g_dist1 = np.abs(x - gorge_curve_x)
        g1 = np.exp(-((g_dist1 / 8.5) ** 4))

        gorge_curve_z = -44.0 + 34.0 * np.cos(px * 0.014 - 0.4)
        g_dist2 = np.abs(z - gorge_curve_z)
        g2 = np.exp(-((g_dist2 / 8.0) ** 4)) * np.clip((x - 15.0) / 30.0, 0.0, 1.0)
        return np.clip(np.maximum(g1, g2), 0.0, 1.0).astype(np.float32)

    def _eval_gorge_factor_scalar(self, x: float, z: float) -> float:
        px = x + self.phase_x
        pz = z + self.phase_z
        gorge_curve_x = -38.0 + 36.0 * math.sin(pz * 0.015 + 0.5) + 14.0 * math.cos(pz * 0.031)
        g_dist1 = abs(x - gorge_curve_x)
        g1 = math.exp(-((g_dist1 / 8.5) ** 4)) if g_dist1 < 24.0 else 0.0

        gorge_curve_z = -44.0 + 34.0 * math.cos(px * 0.014 - 0.4)
        g_dist2 = abs(z - gorge_curve_z)
        g2 = (math.exp(-((g_dist2 / 8.0) ** 4)) * max(0.0, min(1.0, (x - 15.0) / 30.0))) if g_dist2 < 24.0 else 0.0
        return min(1.0, max(g1, g2))

    def is_gorge(self, x: float, z: float) -> bool:
        """Возвращает True, если точка находится на дне или склонах скалистого ущелья."""
        return self._eval_gorge_factor_scalar(x, z) >= 0.32 and self._eval_narrow_peaks_scalar(x, z) < 10.0

    def _eval_height_and_moisture(self, x: np.ndarray, z: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        px = x + self.phase_x
        pz = z + self.phase_z

        temp = np.sin(px * 0.0052 + 0.6) * np.cos(pz * 0.0052 - 0.5)
        moisture = np.cos(px * 0.0062 - pz * 0.0048) * np.sin(px * 0.0042 + pz * 0.0068)

        # Фактор бескрайних степей и просторных полей (выравнивает рельеф в широкие равнины и луга!)
        plains_openness = np.clip((temp + 0.15) * 0.95 - np.abs(moisture) * 0.35, 0.0, 1.0)
        flat_factor = 1.0 - 0.62 * plains_openness

        h_macro = np.sin(px * 0.011) * np.cos(pz * 0.011) * 9.2 * flat_factor
        h_hills = np.sin((px + pz) * 0.028 + 1.1) * np.sin((px - pz) * 0.024) * 4.2 * flat_factor
        h_detail = (
            np.cos(px * 0.085 - pz * 0.080) * 1.05
            + np.sin(px * 0.19) * np.cos(pz * 0.19) * 0.32
            + np.sin(px * 0.42 + pz * 0.38) * 0.14 * (1.0 - flat_factor * 0.5)
        )

        # 1. ШИРОКИЕ ГОРНЫЕ МАССИВЫ (локализованы, чтобы вокруг были степи, поля и ущелья)
        m_zone = np.clip((-temp + 0.18) * 1.10, 0.0, 1.45) ** 1.55
        ridge_broad = 0.5 + 0.5 * np.cos(px * 0.011 + np.sin(pz * 0.011) * 1.6)
        h_mountains_broad = m_zone * (ridge_broad ** 1.35) * 35.0
        near_broad_mountain = 26.5 * np.exp(-((x + 68.0) ** 2 + (z - 58.0) ** 2) / (2.0 * 44.0 ** 2))
        near_winter_ridge = 23.0 * np.exp(-((x - 78.0) ** 2 + (z + 68.0) ** 2) / (2.0 * 42.0 ** 2))

        # 2. ВЫСОКИЕ И УЗКИЕ ОСТРОКОНЕЧНЫЕ ГОРЫ
        h_mountains_narrow = self._eval_narrow_peaks_array(x, z)

        raw_h = (
            3.6
            + h_macro
            + h_hills
            + h_detail
            + h_mountains_broad
            + near_broad_mountain
            + near_winter_ridge
            + h_mountains_narrow
        )

        # 3. ГЛУБОКИЕ СКАЛИСТЫЕ УЩЕЛЬЯ (прорезают массивы и холмы, образуя каньоны с крутыми стенами и проходимым дном!)
        gorge_w = self._eval_gorge_factor_array(x, z)
        gorge_w = np.where(h_mountains_narrow > 12.0, 0.0, gorge_w)
        # По краям ущелья поднимаем скальные бровки, а в центре опускаем дно каньона до 2.3 м
        gorge_rim = np.clip(gorge_w * (1.0 - gorge_w) * 4.0, 0.0, 1.0) * 6.5
        raw_h = (raw_h + gorge_rim) * (1.0 - gorge_w * 0.85) + 2.35 * (gorge_w * 0.85)

        dist_origin_sq = x * x + z * z
        spawn_mask = np.exp(-dist_origin_sq / (2.0 * 16.0 ** 2))
        h = raw_h * (1.0 - 0.75 * spawn_mask) + 3.2 * (0.75 * spawn_mask)

        # 4. ОЗЕРА И РЕКИ
        lake_w = np.clip((moisture - 0.24) * 1.9, 0.0, 1.0) ** 1.4
        start_lake_w = np.exp(-((x - 26.0) ** 2 + (z - 20.0) ** 2) / (2.0 * 19.0 ** 2))
        river_curve_z = 32.0 * np.sin(px * 0.013) + 14.0 * np.cos(px * 0.029)
        river_dist = np.abs(z - river_curve_z)
        river_w = np.exp(-(river_dist ** 2) / (2.0 * 7.8 ** 2)) * np.clip(1.0 - m_zone * 0.7, 0.0, 1.0)

        water_carve_w = np.clip(np.maximum(np.maximum(lake_w, start_lake_w), river_w), 0.0, 1.0)
        water_carve_w = np.where(h_mountains_narrow > 10.0, 0.0, water_carve_w)
        h = h * (1.0 - water_carve_w) + (-4.8) * water_carve_w
        return h.astype(np.float32), temp.astype(np.float32), moisture.astype(np.float32)

    def _eval_scalar(self, x: float, z: float) -> Tuple[float, float, float]:
        px = x + self.phase_x
        pz = z + self.phase_z
        temp = math.sin(px * 0.0052 + 0.6) * math.cos(pz * 0.0052 - 0.5)
        moisture = math.cos(px * 0.0062 - pz * 0.0048) * math.sin(px * 0.0042 + pz * 0.0068)

        plains_openness = max(0.0, min(1.0, (temp + 0.15) * 0.95 - abs(moisture) * 0.35))
        flat_factor = 1.0 - 0.62 * plains_openness

        h_macro = math.sin(px * 0.011) * math.cos(pz * 0.011) * 9.2 * flat_factor
        h_hills = math.sin((px + pz) * 0.028 + 1.1) * math.sin((px - pz) * 0.024) * 4.2 * flat_factor
        h_detail = (
            math.cos(px * 0.085 - pz * 0.080) * 1.05
            + math.sin(px * 0.19) * math.cos(pz * 0.19) * 0.32
            + math.sin(px * 0.42 + pz * 0.38) * 0.14 * (1.0 - flat_factor * 0.5)
        )

        m_zone = max(0.0, min(1.45, (-temp + 0.18) * 1.10)) ** 1.55
        ridge_broad = 0.5 + 0.5 * math.cos(px * 0.011 + math.sin(pz * 0.011) * 1.6)
        h_mountains_broad = m_zone * (ridge_broad ** 1.35) * 35.0
        h_mountains_narrow = self._eval_narrow_peaks_scalar(x, z)

        dist_origin_sq = x * x + z * z
        if dist_origin_sq < 240.0 ** 2:
            near_broad_mountain = 26.5 * math.exp(-((x + 68.0) ** 2 + (z - 58.0) ** 2) / (2.0 * 44.0 ** 2))
            near_winter_ridge = 23.0 * math.exp(-((x - 78.0) ** 2 + (z + 68.0) ** 2) / (2.0 * 42.0 ** 2))
            spawn_mask = math.exp(-dist_origin_sq / (2.0 * 16.0 ** 2))
            raw_h = 3.6 + h_macro + h_hills + h_detail + h_mountains_broad + near_broad_mountain + near_winter_ridge + h_mountains_narrow
            start_lake_w = math.exp(-((x - 26.0) ** 2 + (z - 20.0) ** 2) / (2.0 * 19.0 ** 2))
        else:
            raw_h = 3.6 + h_macro + h_hills + h_detail + h_mountains_broad + h_mountains_narrow
            spawn_mask = 0.0
            start_lake_w = 0.0

        if h_mountains_narrow <= 12.0:
            gorge_w = self._eval_gorge_factor_scalar(x, z)
            if gorge_w > 1e-4:
                gorge_rim = min(1.0, gorge_w * (1.0 - gorge_w) * 4.0) * 6.5
                raw_h = (raw_h + gorge_rim) * (1.0 - gorge_w * 0.85) + 2.35 * (gorge_w * 0.85)

        h = raw_h * (1.0 - 0.75 * spawn_mask) + 3.2 * (0.75 * spawn_mask)

        if h_mountains_narrow <= 10.0:
            lake_w = max(0.0, min(1.0, (moisture - 0.24) * 1.9)) ** 1.4
            river_curve_z = 32.0 * math.sin(px * 0.013) + 14.0 * math.cos(px * 0.029)
            river_dist = abs(z - river_curve_z)
            river_w = (math.exp(-(river_dist * river_dist) / (2.0 * 7.8 ** 2)) * max(0.0, min(1.0, 1.0 - m_zone * 0.7))) if river_dist < 30.0 else 0.0
            water_carve_w = min(1.0, max(lake_w, start_lake_w, river_w))
            h = h * (1.0 - water_carve_w) + (-4.8) * water_carve_w

        if (x - 78.0) ** 2 + (z + 68.0) ** 2 < 75.0 ** 2:
            temp = min(temp, -0.45)

        return h, temp, moisture

    def _grid_vertex_height(self, ix: int, iz: int) -> float:
        """Возвращает точную высоту узла сетки чанка (ix * CHUNK_STEP, iz * CHUNK_STEP) с быстрым кешированием."""
        key = (ix, iz)
        val = self._vertex_h_cache.get(key)
        if val is None:
            val = float(self._eval_scalar(ix * CHUNK_STEP, iz * CHUNK_STEP)[0])
            if len(self._vertex_h_cache) > 65000:
                self._vertex_h_cache.clear()
            self._vertex_h_cache[key] = val
        return val

    def get_height(self, x: float, z: float) -> float:
        """
        Вычисляет точную барицентрическую высоту на полигональной сетке треугольников чанка (шаг CHUNK_STEP = 3.0 м).
        Благодаря этому трава, деревья, сундуки, постройки и животные стоят на 3D-земле с точностью 0.000 м и никогда не висят в воздухе!
        """
        u = x / CHUNK_STEP
        v = z / CHUNK_STEP
        ix = int(math.floor(u))
        iz = int(math.floor(v))
        fx = u - ix
        fz = v - iz
        h00 = self._grid_vertex_height(ix, iz)
        h10 = self._grid_vertex_height(ix + 1, iz)
        h01 = self._grid_vertex_height(ix, iz + 1)
        h11 = self._grid_vertex_height(ix + 1, iz + 1)
        if fx + fz <= 1.0:
            return h00 + fx * (h10 - h00) + fz * (h01 - h00)
        return h11 + (1.0 - fx) * (h01 - h11) + (1.0 - fz) * (h10 - h11)

    def _cached_grad_and_slope(self, x: float, z: float) -> Tuple[float, float, float]:
        """Кеширует (dh_dx, dh_dz, slope_deg) на мелкой сетке 1.5 м для 12-кратного ускорения физики и спавна без потери точности."""
        key = (int(math.floor(x * 0.6666667)), int(math.floor(z * 0.6666667)))
        entry = self._grad_cache.get(key)
        if entry is None:
            eps = 0.35
            dh_dx = (self._eval_scalar(x + eps, z)[0] - self._eval_scalar(x - eps, z)[0]) / (2.0 * eps)
            dh_dz = (self._eval_scalar(x, z + eps)[0] - self._eval_scalar(x, z - eps)[0]) / (2.0 * eps)
            slope_deg = math.degrees(math.atan(math.hypot(dh_dx, dh_dz)))
            if len(self._grad_cache) > 65000:
                self._grad_cache.clear()
            entry = (dh_dx, dh_dz, slope_deg)
            self._grad_cache[key] = entry
        return entry

    def get_gradient(self, x: float, z: float, eps: float = 0.35) -> Tuple[float, float]:
        """Вычисляет гладкий градиент рельефа (dh/dx, dh/dz) с быстрым кешированием."""
        g = self._cached_grad_and_slope(x, z)
        return g[0], g[1]

    def get_slope_degrees(self, x: float, z: float) -> float:
        """Возвращает полный угол наклона поверхности горы/холма в градусах (0° = ровно, 90° = отвесная скала)."""
        return self._cached_grad_and_slope(x, z)[2]

    def get_directional_slope_degrees(self, x: float, z: float, dir_x: float, dir_z: float) -> float:
        """Возвращает угол подъема/спуска в градусах вдоль направления движения (dir_x, dir_z)."""
        d_len = math.hypot(dir_x, dir_z)
        if d_len < 1e-6:
            return 0.0
        ux, uz = dir_x / d_len, dir_z / d_len
        dh_dx, dh_dz = self.get_gradient(x, z)
        return math.degrees(math.atan(dh_dx * ux + dh_dz * uz))

    def is_high_mountain_or_hill(self, x: float, z: float) -> bool:
        """
        Возвращает True, если точка находится на высокой горе или высоком крутом холме.
        На такие горы и холмы может взбираться ТОЛЬКО горный козел (mountain_goat),
        а все остальные животные при попытке забраться падают/скатываются вниз!
        """
        h = self.get_height(x, z)
        narrow_h = self._eval_narrow_peaks_scalar(x, z)
        return h >= HIGH_MOUNTAIN_ELEVATION_MIN or narrow_h >= 6.0

    def get_body_tilt_angles(
        self,
        x: float,
        z: float,
        yaw_deg: float,
        half_len: float = 0.62,
        half_width: float = 0.30,
    ) -> Tuple[float, float, float]:
        """
        Вычисляет продольный угол наклона туловища (pitch) и поперечный крен (roll) животного
        по реальным точкам опоры передних и задних лап/копыт вдоль дуги рельефа местности!
        Например, на склоне 45° животное наклоняет корпус ровно под 45° вдоль дуги горы.
        """
        rad = math.radians(yaw_deg)
        fx, fz = math.sin(rad), -math.cos(rad)
        rx, rz = math.cos(rad), math.sin(rad)

        h_front = self.get_height(x + fx * half_len, z + fz * half_len)
        h_back = self.get_height(x - fx * half_len, z - fz * half_len)
        h_right = self.get_height(x + rx * half_width, z + rz * half_width)
        h_left = self.get_height(x - rx * half_width, z - rz * half_width)
        h_center = self.get_height(x, z)

        pitch_deg = math.degrees(math.atan2(h_front - h_back, max(0.1, 2.0 * half_len)))
        roll_deg = math.degrees(math.atan2(h_right - h_left, max(0.1, 2.0 * half_width)))
        arc_y = 0.5 * (h_center + 0.5 * (h_front + h_back))
        return pitch_deg, roll_deg, arc_y

    def get_biome_weights(self, x: float, z: float) -> Tuple[float, float, str]:
        h, temp, moist = self._eval_scalar(x, z)
        px = x + self.phase_x
        river_curve_z = 32.0 * math.sin(px * 0.013) + 14.0 * math.cos(px * 0.029)
        if h < WATER_LEVEL:
            if abs(z - river_curve_z) < 12.5:
                return temp, moist, "Полноводная река"
            return temp, moist, "Лазурное озеро"
        if h < BEACH_LEVEL:
            return temp, moist, "Песчаный берег"
        if self.is_narrow_peak_summit(x, z):
            return temp, moist, "Вершина узкой горы (Обитель козлов)"
        if self.is_gorge(x, z):
            return temp, moist, "Скалистое ущелье"
        if h >= SNOW_LEVEL:
            return temp, moist, "Снежные вершины гор"
        if MOUNTAIN_MID_MIN <= h <= MOUNTAIN_MID_MAX:
            return temp, moist, "Широкое горное нагорье"
        if temp < -0.22:
            return temp, moist, "Зимний снежный биом (Снежные барсы)"
        if temp > 0.24 and moist < 0.02:
            return temp, moist, "Бескрайняя степь"
        if temp > 0.34:
            return temp, moist, "Золотое осеннее плато"
        if moist > 0.20:
            return temp, moist, "Вековая хвойная тайга"
        if moist > 0.02:
            return temp, moist, "Густой древний лес"
        return temp, moist, "Просторное поле и луга"

    def get_biome(self, x: float, z: float) -> str:
        return self.get_biome_weights(x, z)[2]

    def get_or_create_chunk(self, cx: int, cz: int) -> TerrainChunkData:
        key = (cx, cz)
        existing = self.generated_chunks.get(key)
        if existing is not None:
            return existing

        x0 = cx * CHUNK_SIZE
        z0 = cz * CHUNK_SIZE
        xs = np.linspace(x0 - CHUNK_STEP, x0 + CHUNK_SIZE + CHUNK_STEP, CHUNK_CELLS + 3, dtype=np.float32)
        zs = np.linspace(z0 - CHUNK_STEP, z0 + CHUNK_SIZE + CHUNK_STEP, CHUNK_CELLS + 3, dtype=np.float32)
        gx_pad, gz_pad = np.meshgrid(xs, zs, indexing="ij")
        h_pad, temp_pad, moist_pad = self._eval_height_and_moisture(gx_pad, gz_pad)

        winter_spot = (gx_pad - 78.0) ** 2 + (gz_pad + 68.0) ** 2 < 75.0 ** 2
        temp_pad = np.where(winter_spot, np.minimum(temp_pad, -0.45), temp_pad)

        dx = (h_pad[2:, 1:-1] - h_pad[:-2, 1:-1]) / (2.0 * CHUNK_STEP)
        dz = (h_pad[1:-1, 2:] - h_pad[1:-1, :-2]) / (2.0 * CHUNK_STEP)
        nx = -dx
        ny = np.ones_like(dx)
        nz = -dz
        nlen = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
        normals = np.stack([nx / nlen, ny / nlen, nz / nlen], axis=-1).astype(np.float32)

        gx = gx_pad[1:-1, 1:-1]
        gz = gz_pad[1:-1, 1:-1]
        h = h_pad[1:-1, 1:-1]
        temp = temp_pad[1:-1, 1:-1]
        moist = moist_pad[1:-1, 1:-1]

        colors = self._compute_vertex_colors(gx, gz, h, temp, moist, normals)
        uvs_grid = np.stack([gx * 0.18, gz * 0.18], axis=-1).astype(np.float32)

        v = np.stack([gx, h, gz], axis=-1)
        p00, p10, p01, p11 = v[:-1, :-1], v[1:, :-1], v[:-1, 1:], v[1:, 1:]
        n00, n10, n01, n11 = normals[:-1, :-1], normals[1:, :-1], normals[:-1, 1:], normals[1:, 1:]
        c00, c10, c01, c11 = colors[:-1, :-1], colors[1:, :-1], colors[:-1, 1:], colors[1:, 1:]
        u00, u10, u01, u11 = uvs_grid[:-1, :-1], uvs_grid[1:, :-1], uvs_grid[:-1, 1:], uvs_grid[1:, 1:]

        verts = np.concatenate(
            [
                np.stack([p00, p01, p10], axis=2).reshape(-1, 3, 3),
                np.stack([p10, p01, p11], axis=2).reshape(-1, 3, 3),
            ],
            axis=0,
        )
        norms = np.concatenate(
            [
                np.stack([n00, n01, n10], axis=2).reshape(-1, 3, 3),
                np.stack([n10, n01, n11], axis=2).reshape(-1, 3, 3),
            ],
            axis=0,
        )
        cols = np.concatenate(
            [
                np.stack([c00, c01, c10], axis=2).reshape(-1, 3, 3),
                np.stack([c10, c01, c11], axis=2).reshape(-1, 3, 3),
            ],
            axis=0,
        )
        uvs = np.concatenate(
            [
                np.stack([u00, u01, u10], axis=2).reshape(-1, 3, 2),
                np.stack([u10, u01, u11], axis=2).reshape(-1, 3, 2),
            ],
            axis=0,
        )

        v_s = v[::2, ::2]
        c_s = colors[::2, ::2]
        n_s = normals[::2, ::2]
        sp00, sp10, sp01, sp11 = v_s[:-1, :-1], v_s[1:, :-1], v_s[:-1, 1:], v_s[1:, 1:]
        sc00, sc10, sc01, sc11 = c_s[:-1, :-1], c_s[1:, :-1], c_s[:-1, 1:], c_s[1:, 1:]
        sw_v = np.concatenate(
            [
                np.stack([sp00, sp01, sp10], axis=2).reshape(-1, 3, 3),
                np.stack([sp10, sp01, sp11], axis=2).reshape(-1, 3, 3),
            ],
            axis=0,
        )
        sw_c = np.concatenate(
            [
                ((sc00 + sc01 + sc10) / 3.0).reshape(-1, 3),
                ((sc10 + sc01 + sc11) / 3.0).reshape(-1, 3),
            ],
            axis=0,
        )
        sw_n = np.concatenate(
            [
                n_s[:-1, :-1].reshape(-1, 3),
                n_s[1:, 1:].reshape(-1, 3),
            ],
            axis=0,
        )

        center_x = x0 + CHUNK_SIZE * 0.5
        center_z = z0 + CHUNK_SIZE * 0.5
        chunk = TerrainChunkData(
            cx=cx,
            cz=cz,
            center_x=center_x,
            center_z=center_z,
            biome_name=self.get_biome(center_x, center_z),
            verts=verts,
            norms=norms,
            cols=cols,
            uvs=uvs,
            sw_verts=sw_v,
            sw_cols=sw_c,
            sw_norms=sw_n,
            sw_centers=sw_v.mean(axis=1),
            has_water=bool(np.any(h < WATER_LEVEL + 0.35)),
            gl_list_id=None,
        )
        self.generated_chunks[key] = chunk
        self.compile_queue.append(key)
        return chunk

    @staticmethod
    def _compute_vertex_colors(
        x: np.ndarray,
        z: np.ndarray,
        h: np.ndarray,
        temp: np.ndarray,
        moist: np.ndarray,
        normals: np.ndarray,
    ) -> np.ndarray:
        """
        Реалистичное многослойное окрашивание вершин ландшафта (PBR-подобный биомный шейдинг):
          - Микрорельеф почвы, мха и травяных кочек (3 октавы частот).
          - Влажное потемнение песка и гальки у кромки воды (wet shoreline).
          - Геологическая слоистость скал (rock strata) на крутых склонах и в ущельях.
          - Мягкое затенение впадин и каньонов (Ambient Occlusion).
        """
        slope = 1.0 - np.clip(normals[..., 1], 0.0, 1.0)
        micro = (
            0.042 * np.sin(x * 0.48 + np.cos(z * 0.42))
            + 0.028 * np.sin(x * 1.25 + z * 1.15)
            + 0.016 * np.cos(x * 2.85 - z * 2.65)
        )
        patch = 0.5 + 0.5 * np.sin(x * 0.14 - z * 0.11 + np.sin(x * 0.05) * 2.0)

        c_emerald = np.array([0.22, 0.58, 0.20], dtype=np.float32)
        c_meadow_gold = np.array([0.34, 0.64, 0.23], dtype=np.float32)
        c_forest = np.array([0.13, 0.43, 0.16], dtype=np.float32)
        c_autumn = np.array([0.62, 0.49, 0.16], dtype=np.float32)
        c_winter = np.array([0.89, 0.94, 0.99], dtype=np.float32)

        w_winter = np.clip((-temp - 0.18) * 2.2, 0.0, 1.0)[..., None]
        w_autumn = np.clip((temp - 0.15) * 1.6, 0.0, 1.0)[..., None] * (1.0 - w_winter)
        w_forest = np.clip((moist + 0.05) * 1.4, 0.0, 1.0)[..., None] * (1.0 - w_autumn - w_winter)
        w_emerald = np.clip(1.0 - w_autumn - w_forest - w_winter, 0.0, 1.0)
        meadow_mix = c_emerald * (1.0 - 0.42 * patch[..., None]) + c_meadow_gold * (0.42 * patch[..., None])
        grass_col = meadow_mix * w_emerald + c_forest * w_forest + c_autumn * w_autumn + c_winter * w_winter

        c_wet_mud = np.array([0.38, 0.34, 0.25], dtype=np.float32)
        c_sand = np.array([0.83, 0.76, 0.57], dtype=np.float32)
        c_rock = np.array([0.46, 0.45, 0.44], dtype=np.float32)
        c_snow = np.array([0.96, 0.98, 1.00], dtype=np.float32)

        # Влажный берег у самой кромки воды -> теплый песок -> луговая трава
        t_wet = np.clip((h - (WATER_LEVEL - 0.3)) / 1.1, 0.0, 1.0)[..., None]
        shore_col = c_wet_mud * (1.0 - t_wet) + c_sand * t_wet
        t_beach = np.clip((h - (BEACH_LEVEL - 0.6)) / 1.5, 0.0, 1.0)[..., None]
        col = shore_col * (1.0 - t_beach) + grass_col * t_beach

        # Переход в горную породу со слоистой структурой скал (strata)
        strata = (0.045 * np.sin(h * 1.85 + x * 0.12))[..., None]
        t_rock = np.clip((h - (MOUNTAIN_LEVEL - 1.5)) / 5.5, 0.0, 1.0)[..., None]
        col = col * (1.0 - t_rock) + (c_rock + strata) * t_rock

        # Переход в искрящийся высокогорный снег с легким голубоватым оттенком в тенях
        snow_tint = np.where((normals[..., 0:1] + normals[..., 2:3]) < 0.0, np.array([0.88, 0.93, 1.00], dtype=np.float32), c_snow)
        t_snow = np.clip((h - (SNOW_LEVEL - 2.5)) / 4.2, 0.0, 1.0)[..., None]
        col = col * (1.0 - t_snow) + snow_tint * t_snow

        # Скалистые обрывы с мшистыми прожилками
        cliff_base = np.array([0.35, 0.34, 0.33], dtype=np.float32) + strata * 1.2
        t_cliff = np.clip((slope - 0.22) / 0.17, 0.0, 1.0)[..., None]
        col = col * (1.0 - t_cliff) + cliff_base * t_cliff

        # Мягкое затенение низин и каньонов (Ambient Occlusion)
        ao = np.clip(0.86 + 0.14 * np.clip((h - 1.5) / 8.0, 0.0, 1.0) - 0.10 * slope, 0.76, 1.04)[..., None]
        col = col * ao + micro[..., None]
        return np.clip(col, 0.07, 1.0).astype(np.float32)


# ==============================================================================
# 4. ФЛОРА, ПЕЩЕРЫ, РУДЫ, ПОСТРОЙКИ И ЖИВОТНЫЕ (ВКЛЮЧАЯ ГОРНЫХ КОЗЛОВ И РЫБУ)
# ==============================================================================

@dataclass
class ResourceNode:
    id: int
    kind: str
    name: str
    x: float
    y: float
    z: float
    scale: float
    rotation: float
    hp: float
    max_hp: float
    radius: float
    hit_shake: float = 0.0
    respawn_timer: float = 0.0

    @property
    def alive(self) -> bool:
        return self.hp > 0.0


@dataclass
class BuiltStructure:
    id: int
    piece_id: str
    name: str
    x: float
    y: float
    z: float
    rotation: float
    size: Tuple[float, float, float]
    is_solid: bool
    is_roof: bool
    door_open: bool = False
    storage: Dict[str, int] = None
    chest_slots: List[Optional[Dict[str, object]]] = None

    def __post_init__(self) -> None:
        if self.storage is None:
            self.storage = {}
        if self.chest_slots is None:
            self.chest_slots = [None] * MAX_CHEST_SLOTS
            self.sync_slots_from_storage()

    def sync_slots_from_storage(self) -> None:
        """Синхронизирует 15 ячеек сундука из словаря storage (с поддержкой прочности инструментов и одежды)."""
        self.chest_slots = [None] * MAX_CHEST_SLOTS
        idx = 0
        for k, cnt in list(self.storage.items()):
            if cnt > 0 and idx < MAX_CHEST_SLOTS:
                self.chest_slots[idx] = make_slot_dict(k, int(cnt))
                idx += 1

    def sync_storage_from_slots(self) -> None:
        """Пересчитывает словарь storage по текущим 15 ячейкам сундука."""
        new_st: Dict[str, int] = {}
        for sl in self.chest_slots:
            if sl is not None and int(sl.get("count", 0)) > 0:
                ik = str(sl["item"])
                new_st[ik] = new_st.get(ik, 0) + int(sl["count"])
        self.storage.clear()
        self.storage.update(new_st)


@dataclass
class FishingBobber:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    in_water: bool = False
    bite_timer: float = 2.2
    biting: bool = False
    bite_window: float = 0.0
    ttl: float = 25.0


@dataclass
class ArrowProjectile:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    damage: float
    ttl: float = 4.5


@dataclass
class Particle3D:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    color: Tuple[float, float, float]
    size: float
    ttl: float
    kind: str = "spark"  # 'spark', 'snow' (круглые снежинки), 'flame' (языки пламени), 'ember' (искры углей), 'smoke' (дым)
    max_ttl: float = 0.6


@dataclass
class DroppedItem3D:
    id: int
    item_id: str
    count: int
    x: float
    y: float
    z: float
    vy: float = 2.5
    rotation: float = 0.0
    pickup_delay: float = 0.65
    despawn_timer: float = DEATH_LOOT_DESPAWN_SECONDS  # Лежит максимум 5 минут (300 сек), затем исчезает!
    is_death_drop: bool = False
    durability: Optional[float] = None


class Animal:
    """
    Животное открытого мира с составной 3D-моделью и ИИ:
      - Мирные сухопутные: 'cow' (Корова), 'sheep' (Овца), 'chicken' (Курица)
      - Горные (ТОЛЬКО середина гор): 'mountain_goat' (Горный козел)
      - Водные (в озерах и реках): 'fish' (Озерная форель / Рыба)
      - Атакующие хищники: 'wolf' (Волк), 'tiger' (Тигр), 'bear' (Медведь)
    """

    SPECS = {
        "cow": {
            "name": "Корова",
            "hostile": False,
            "aquatic": False,
            "mountain_mid_only": False,
            "hp": 85.0,
            "speed": 2.6,
            "flee_speed": 5.4,
            "damage": 0.0,
            "aggro_range": 0.0,
            "attack_range": 0.0,
            "radius": 1.25,
            "xp": 35,
            "drops": {"raw_meat": (2, 3), "leather": (1, 2)},
            "body_color": (0.48, 0.30, 0.18),
            "accent_color": (0.92, 0.90, 0.86),
            "scale": 1.15,
        },
        "sheep": {
            "name": "Овца",
            "hostile": False,
            "aquatic": False,
            "mountain_mid_only": False,
            "hp": 55.0,
            "speed": 2.8,
            "flee_speed": 5.8,
            "damage": 0.0,
            "aggro_range": 0.0,
            "attack_range": 0.0,
            "radius": 0.95,
            "xp": 28,
            "drops": {"raw_meat": (1, 2), "wool": (2, 3)},
            "body_color": (0.93, 0.92, 0.88),
            "accent_color": (0.28, 0.25, 0.24),
            "scale": 0.92,
        },
        "chicken": {
            "name": "Курица",
            "hostile": False,
            "aquatic": False,
            "mountain_mid_only": False,
            "hp": 25.0,
            "speed": 3.2,
            "flee_speed": 6.4,
            "damage": 0.0,
            "aggro_range": 0.0,
            "attack_range": 0.0,
            "radius": 0.55,
            "xp": 18,
            "drops": {"raw_meat": (1, 1), "feather": (2, 4)},
            "body_color": (0.95, 0.93, 0.85),
            "accent_color": (0.88, 0.16, 0.16),
            "scale": 0.55,
        },
        "mountain_goat": {
            "name": "Горный Козел",
            "hostile": False,
            "aquatic": False,
            "mountain_mid_only": True,
            "hp": 78.0,
            "speed": 3.4,
            "flee_speed": 6.8,
            "damage": 0.0,
            "aggro_range": 0.0,
            "attack_range": 0.0,
            "radius": 1.00,
            "xp": 50,
            "drops": {"raw_meat": (2, 3), "wool": (2, 3), "fang": (1, 2)},
            "body_color": (0.68, 0.64, 0.58),
            "accent_color": (0.26, 0.24, 0.22),
            "scale": 1.02,
        },
        "fish": {
            "name": "Озерная Форель (Рыба)",
            "hostile": False,
            "aquatic": True,
            "mountain_mid_only": False,
            "hp": 20.0,
            "speed": 3.0,
            "flee_speed": 6.2,
            "damage": 0.0,
            "aggro_range": 0.0,
            "attack_range": 0.0,
            "radius": 0.65,
            "xp": 25,
            "drops": {"raw_fish": (1, 2)},
            "body_color": (0.32, 0.68, 0.78),
            "accent_color": (0.94, 0.56, 0.42),
            "scale": 0.72,
        },
        "wolf": {
            "name": "Лесной Волк",
            "hostile": True,
            "aquatic": False,
            "mountain_mid_only": False,
            "hp": 95.0,
            "speed": 3.8,
            "flee_speed": 7.4,
            "damage": 14.0,
            "aggro_range": 22.0,
            "attack_range": 2.4,
            "radius": 0.95,
            "xp": 65,
            "drops": {"raw_meat": (1, 2), "pelt": (1, 1), "fang": (1, 2)},
            "body_color": (0.46, 0.48, 0.52),
            "accent_color": (0.76, 0.78, 0.82),
            "scale": 0.95,
        },
        "snow_leopard": {
            "name": "Снежный Барс",
            "hostile": True,
            "aquatic": False,
            "mountain_mid_only": False,
            "hp": 175.0,
            "speed": 4.6,
            "flee_speed": 8.8,
            "damage": 26.0,
            "aggro_range": 26.0,
            "attack_range": 2.7,
            "radius": 1.18,
            "xp": 140,
            "drops": {"raw_meat": (2, 3), "pelt": (2, 2), "fang": (2, 3)},
            "body_color": (0.88, 0.90, 0.94),
            "accent_color": (0.20, 0.22, 0.26),
            "scale": 1.16,
        },
        "tiger": {
            "name": "Свирепый Тигр",
            "hostile": True,
            "aquatic": False,
            "mountain_mid_only": False,
            "hp": 165.0,
            "speed": 4.4,
            "flee_speed": 8.6,
            "damage": 24.0,
            "aggro_range": 26.0,
            "attack_range": 2.7,
            "radius": 1.20,
            "xp": 125,
            "drops": {"raw_meat": (2, 3), "pelt": (1, 2), "fang": (2, 3)},
            "body_color": (0.92, 0.50, 0.12),
            "accent_color": (0.14, 0.12, 0.10),
            "scale": 1.18,
        },
        "bear": {
            "name": "Горный Медведь",
            "hostile": True,
            "aquatic": False,
            "mountain_mid_only": False,
            "hp": 260.0,
            "speed": 3.3,
            "flee_speed": 6.8,
            "damage": 34.0,
            "aggro_range": 20.0,
            "attack_range": 3.0,
            "radius": 1.50,
            "xp": 200,
            "drops": {"raw_meat": (3, 4), "pelt": (2, 3), "fang": (2, 3), "leather": (2, 3)},
            "body_color": (0.34, 0.21, 0.12),
            "accent_color": (0.50, 0.34, 0.20),
            "scale": 1.48,
        },
    }

    def __init__(self, animal_id: int, kind: str, x: float, y: float, z: float, level: int = 1) -> None:
        spec = self.SPECS[kind]
        self.id = animal_id
        self.kind = kind
        self.name = spec["name"]
        self.hostile: bool = spec["hostile"]
        self.aquatic: bool = spec["aquatic"]
        self.mountain_mid_only: bool = spec["mountain_mid_only"]
        self.level = level
        lvl_mult = 1.0 + (level - 1) * 0.18
        self.max_hp: float = round(spec["hp"] * lvl_mult, 1)
        self.hp: float = self.max_hp
        self.walk_speed: float = spec["speed"]
        self.chase_speed: float = spec["flee_speed"]
        self.damage: float = round(spec["damage"] * lvl_mult, 1)
        self.aggro_range: float = spec["aggro_range"]
        self.attack_range: float = spec["attack_range"]
        self.radius: float = spec["radius"]
        self.xp_reward: int = int(spec["xp"] * lvl_mult)
        self.drops: Dict[str, Tuple[int, int]] = spec["drops"]
        self.body_color: Tuple[float, float, float] = spec["body_color"]
        self.accent_color: Tuple[float, float, float] = spec["accent_color"]
        self.scale: float = spec["scale"]

        self.x = x
        self.y = y
        self.z = z
        self.vy = 0.0
        self.yaw = random.uniform(0.0, 360.0)
        self.pitch = 0.0   # Продольный наклон туловища вдоль дуги и угла горы (в градусах)
        self.roll = 0.0    # Поперечный наклон туловища по склону (в градусах)
        self.is_sliding_down = False  # Падение/скатывание вниз при попытке залезть на высокую гору (не козел)
        self.state = "wander"
        self.state_timer = random.uniform(2.5, 6.0)
        self.anim_phase = 0.0
        self.leg_swing = 0.0  # Текущий угол взмаха лап/ног (при остановке всегда ровно 0.0°!)
        self.attack_cooldown = 0.0
        self.hurt_flash = 0.0
        self.respawn_timer = 0.0
        self.ai_sleep_accum = 0.0

    def can_climb_slope(self, slope_deg: float, is_high_mountain: bool = False) -> bool:
        """
        Проверяет, может ли животное подняться по склону:
          1) Горный козел (mountain_goat) может взбираться вплоть до 85° (GOAT_MAX_CLIMB_ANGLE_DEG = 85.0).
          2) Остальные животные могут взбираться вплоть до 70° (ANIMAL_MAX_CLIMB_ANGLE_DEG = 70.0).
          3) На высокие горы может взбираться ТОЛЬКО горный козел.
        """
        max_ang = GOAT_MAX_CLIMB_ANGLE_DEG if self.kind == "mountain_goat" else ANIMAL_MAX_CLIMB_ANGLE_DEG
        if slope_deg > max_ang:
            return False
        if is_high_mountain and self.kind != "mountain_goat":
            return False
        return True

    @property
    def alive(self) -> bool:
        return self.hp > 0.0


# ==============================================================================
# 5. СИСТЕМА ИГРОКА ОТ ПЕРВОГО ЛИЦА, ПЛАВАНИЯ, АНИМАЦИЙ И РПГ
# ==============================================================================

class SlotBackedInventoryDict(dict):
    """
    Словарь ресурсов, напрямую работающий поверх 25 свободных ячеек инвентаря (player.slots[0..24]).
    Первые 9 ячеек (slots[0..8]) — это ячейки хотбара 1..9!
    На старте в инвентаре нет никаких фиксированных предметов, кроме Камня в 1-й ячейке.
    """

    def __init__(self, player: "PlayerFirstPerson") -> None:
        super().__init__()
        self._player = player

    def _total_of(self, key: str) -> int:
        total = 0
        for sl in self._player.slots:
            if sl is not None and sl.get("item") == key:
                total += int(sl.get("count", 0))
        return total

    def __getitem__(self, key: str) -> int:
        return self._total_of(key)

    def get(self, key: str, default: int = 0) -> int:  # type: ignore[override]
        val = self._total_of(key)
        return val if val > 0 else default

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._total_of(key) > 0

    def __setitem__(self, key: str, new_total: int) -> None:
        new_total = max(0, int(new_total))
        cur_total = self._total_of(key)
        delta = new_total - cur_total
        if delta > 0:
            self._player.add_item_to_slots(key, delta)
        elif delta < 0:
            self._player.remove_item_from_slots(key, -delta)

    def items(self):  # type: ignore[override]
        totals: Dict[str, int] = {}
        for sl in self._player.slots:
            if sl is not None:
                k = str(sl["item"])
                totals[k] = totals.get(k, 0) + int(sl.get("count", 0))
        return totals.items()

    def keys(self):  # type: ignore[override]
        return [k for k, _ in self.items()]

    def values(self):  # type: ignore[override]
        return [v for _, v in self.items()]

    def to_plain_dict(self) -> Dict[str, int]:
        return dict(self.items())


class HotbarListProxy:
    """
    Прямая проекция первых 9 ячеек инвентаря (player.slots[0..8]) на панель быстрого доступа (хотбар 1..9).
    Любое изменение хотбара мгновенно меняет первые 9 ячеек инвентаря и наоборот!
    """

    def __init__(self, player: "PlayerFirstPerson") -> None:
        self._player = player

    def __len__(self) -> int:
        return 9

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [
                (self._player.slots[i]["item"] if self._player.slots[i] is not None else None)
                for i in range(*index.indices(9))
            ]
        if 0 <= index < 9:
            sl = self._player.slots[index]
            return str(sl["item"]) if sl is not None else None
        raise IndexError(index)

    def __setitem__(self, index: int, item_id: Optional[str]) -> None:
        if not (0 <= index < 9):
            raise IndexError(index)
        if item_id is None:
            self._player.slots[index] = None
        else:
            existing_cnt = 1
            existing_dur: Optional[float] = None
            for i in range(MAX_INVENTORY_SLOTS):
                sl = self._player.slots[i]
                if sl is not None and sl.get("item") == item_id and i != index:
                    existing_cnt = max(1, int(sl.get("count", 1)))
                    if "durability" in sl:
                        existing_dur = float(sl["durability"])
                    self._player.slots[i] = None
                    break
            self._player.slots[index] = make_slot_dict(item_id, existing_cnt, durability=existing_dur)
        self._player.sync_active_weapon_from_hotbar()

    def __iter__(self):
        for i in range(9):
            yield self[i]

    def __contains__(self, item_id: object) -> bool:
        return any(self[i] == item_id for i in range(9))

    def index(self, item_id: str) -> int:
        for i in range(9):
            if self[i] == item_id:
                return i
        raise ValueError(f"{item_id} is not in hotbar")


class PlayerFirstPerson:
    """
    Управляет физикой от первого лица (подъем до 75°), плаванием, выживанием, РПГ
    и 25-ячеечным нефиксированным инвентарем, напрямую связанным с хотбаром (1..9).
    """

    def __init__(self, start_x: float, start_y: float, start_z: float) -> None:
        self.x = start_x
        self.y = start_y
        self.z = start_z
        self.vx = 0.0
        self.vy = 0.0
        self.vz = 0.0
        self.yaw = 35.0
        self.pitch = -6.0
        self.eye_height = 1.72
        self.on_ground = True
        self.fall_peak_y = start_y
        self.in_water = False
        self.head_underwater = False
        self.is_sheltered = False
        self.near_campfire = False
        self.in_cave = False
        self.spawn_point = (start_x, start_y, start_z)

        self.max_hp = 100.0
        self.hp = 100.0
        self.max_stamina = 100.0
        self.stamina = 100.0
        self.hunger = 100.0
        self.thirst = 100.0
        self.warmth = 100.0

        self.level = 1
        self.xp = 0
        self.xp_to_next = 100
        self.skill_points = 0
        self.skills: Dict[str, int] = {
            "strength": 1,
            "vitality": 1,
            "endurance": 1,
            "harvesting": 1,
            "hunter": 1,
        }

        # 25 СВОБОДНЫХ ЯЧЕЕК ИНВЕНТАРЯ (0..24):
        # - Изначально в инвентаре НЕТ НИЧЕГО, кроме Камня выжившего ('rock') с полной прочностью в 1-й ячейке (slots[0])!
        # - Ячейки 0..8 напрямую являются 9 ячейками хотбара (1..9)!
        self.slots: List[Optional[Dict[str, object]]] = [None] * MAX_INVENTORY_SLOTS
        self.slots[0] = make_slot_dict("rock", 1)

        # 4 ОТДЕЛЬНЫЕ ВЕРТИКАЛЬНЫЕ ЯЧЕЙКИ ЭКИПИРОВКИ ПЕРСОНАЖА (0: Голова/Шапка, 1: Торс/Броня, 2: Штаны/Поножи, 3: Носки/Сапоги)
        self.armor_slots: List[Optional[Dict[str, object]]] = [None, None, None, None]

        self.inventory: SlotBackedInventoryDict = SlotBackedInventoryDict(self)
        self.hotbar: HotbarListProxy = HotbarListProxy(self)
        self.active_hotbar_slot: int = 0
        self.unlocked_weapons = {"rock"}
        self.equipped_weapon = "rock"
        self.attack_timer = 0.0
        self.swing_anim = 0.0
        self.bow_pull_anim = 0.0
        self.walk_bob = 0.0
        self.swim_stroke = 0.0
        self.damage_flash = 0.0

        self.stats_trees_cut = 0
        self.stats_animals_hunted = 0
        self.stats_predators_slain = 0
        self.stats_blocks_built = 0
        self.stats_meat_cooked = 0

    def sync_active_weapon_from_hotbar(self) -> None:
        """
        Синхронизирует текущий предмет в руках с выбранной ячейкой хотбара (0..8).
        Если выбран ресурс/руда/еда — в руках отображается именно этот предмет, а если слот пуст — пустая рука!
        """
        if 0 <= self.active_hotbar_slot < 9:
            sl = self.slots[self.active_hotbar_slot]
            if sl is not None:
                self.equipped_weapon = str(sl["item"])
            else:
                self.equipped_weapon = "empty_hand"

    def add_item_to_slots(self, item_id: str, count: int = 1, durability: Optional[float] = None) -> bool:
        """Добавляет предмет в существующий стек или в первую свободную ячейку из 25 ячеек инвентаря."""
        if count <= 0:
            return True
        is_unique_equip = (item_id in WEAPONS_DB and item_id != "workbench_item") or (item_id in ITEM_TO_ARMOR_SLOT_IDX)
        if item_id in WEAPONS_DB and item_id != "workbench_item":
            for sl in self.slots:
                if sl is not None and sl.get("item") == item_id:
                    mx_d = ITEM_MAX_DURABILITY.get(item_id, 100.0)
                    sl["durability"] = float(durability if durability is not None else mx_d)
                    sl["max_durability"] = mx_d
                    return True
            for i in range(MAX_INVENTORY_SLOTS):
                if self.slots[i] is None:
                    self.slots[i] = make_slot_dict(item_id, 1, durability=durability)
                    self.sync_active_weapon_from_hotbar()
                    return True
            return False

        if not is_unique_equip:
            for sl in self.slots:
                if sl is not None and sl.get("item") == item_id:
                    sl["count"] = int(sl.get("count", 0)) + count
                    self.sync_active_weapon_from_hotbar()
                    return True

        for i in range(MAX_INVENTORY_SLOTS):
            if self.slots[i] is None:
                self.slots[i] = make_slot_dict(item_id, count, durability=durability)
                self.sync_active_weapon_from_hotbar()
                return True
        return False

    def remove_item_from_slots(self, item_id: str, count: int = 1) -> bool:
        """Удаляет указанное количество предмета из ячеек инвентаря; пустая ячейка становится None."""
        if count <= 0:
            return True
        rem = count
        order = list(range(MAX_INVENTORY_SLOTS - 1, -1, -1))
        if 0 <= self.active_hotbar_slot < 9:
            act = self.active_hotbar_slot
            if self.slots[act] is not None and self.slots[act].get("item") == item_id:
                order.remove(act)
                order.insert(0, act)
        for i in order:
            sl = self.slots[i]
            if sl is not None and sl.get("item") == item_id:
                have = int(sl.get("count", 0))
                take = min(have, rem)
                have -= take
                rem -= take
                if have <= 0:
                    self.slots[i] = None
                else:
                    sl["count"] = have
                if rem <= 0:
                    break
        self.sync_active_weapon_from_hotbar()
        return rem == 0

    def equip_armor_item(self, item_id: str, from_inv_idx: Optional[int] = None) -> bool:
        """Надевает предмет экипировки (шапку, доспех, штаны, носки/сапоги) с сохранением его прочности."""
        if item_id not in ITEM_TO_ARMOR_SLOT_IDX:
            return False
        a_idx = ITEM_TO_ARMOR_SLOT_IDX[item_id]
        prev_eq = self.armor_slots[a_idx]
        item_dur: Optional[float] = None
        if from_inv_idx is not None and 0 <= from_inv_idx < MAX_INVENTORY_SLOTS:
            sl = self.slots[from_inv_idx]
            if sl is None or sl.get("item") != item_id:
                return False
            if "durability" in sl:
                item_dur = float(sl["durability"])
            cnt = int(sl.get("count", 1))
            if cnt > 1:
                sl["count"] = cnt - 1
            else:
                self.slots[from_inv_idx] = None
        else:
            for i in range(MAX_INVENTORY_SLOTS):
                sl = self.slots[i]
                if sl is not None and sl.get("item") == item_id:
                    if "durability" in sl:
                        item_dur = float(sl["durability"])
                    break
            if not self.remove_item_from_slots(item_id, 1):
                return False
        self.armor_slots[a_idx] = make_slot_dict(item_id, 1, durability=item_dur)
        if prev_eq is not None:
            prev_dur = float(prev_eq["durability"]) if "durability" in prev_eq else None
            self.add_item_to_slots(str(prev_eq["item"]), int(prev_eq.get("count", 1)), durability=prev_dur)
        self.sync_active_weapon_from_hotbar()
        return True

    def unequip_armor_slot(self, armor_idx: int) -> bool:
        """Снимает предмет из вертикальной ячейки брони (0..3) обратно в основной инвентарь с сохранением прочности."""
        if not (0 <= armor_idx < 4) or self.armor_slots[armor_idx] is None:
            return False
        eq = self.armor_slots[armor_idx]
        eq_dur = float(eq["durability"]) if "durability" in eq else None
        if self.add_item_to_slots(str(eq["item"]), int(eq.get("count", 1)), durability=eq_dur):
            self.armor_slots[armor_idx] = None
            return True
        return False

    def damage_active_tool(self, wear: float = 1.0) -> Optional[str]:
        """Уменьшает прочность активного инструмента/оружия в руках при ударе, добыче или выстреле."""
        if not (0 <= self.active_hotbar_slot < 9):
            return None
        sl = self.slots[self.active_hotbar_slot]
        if sl is None:
            return None
        item_id = str(sl.get("item", ""))
        if item_id not in ITEM_MAX_DURABILITY:
            return None
        mx = float(sl.get("max_durability", ITEM_MAX_DURABILITY[item_id]))
        cur = float(sl.get("durability", mx)) - wear
        if cur <= 0.0:
            name_ru = WEAPONS_DB[item_id].name if item_id in WEAPONS_DB else RESOURCE_NAMES_RU.get(item_id, item_id)
            self.slots[self.active_hotbar_slot] = None
            if not any(s is not None and s.get("item") == item_id for s in self.slots):
                self.unlocked_weapons.discard(item_id)
            self.sync_active_weapon_from_hotbar()
            return f"Ваш предмет '{name_ru}' полностью износился и сломался!"
        sl["durability"] = cur
        sl["max_durability"] = mx
        return None

    def damage_equipped_armor(self, wear: float = 2.0) -> List[str]:
        """Уменьшает прочность надетой одежды/брони при получении урона от хищников или падения."""
        broken_msgs: List[str] = []
        for a_idx in range(4):
            asl = self.armor_slots[a_idx]
            if asl is None:
                continue
            item_id = str(asl.get("item", ""))
            mx = float(asl.get("max_durability", ITEM_MAX_DURABILITY.get(item_id, 150.0)))
            cur = float(asl.get("durability", mx)) - wear
            if cur <= 0.0:
                name_ru = RESOURCE_NAMES_RU.get(item_id, item_id)
                self.armor_slots[a_idx] = None
                broken_msgs.append(f"Экипировка '{name_ru}' разрушилась от ударов!")
            else:
                asl["durability"] = cur
                asl["max_durability"] = mx
        return broken_msgs

    @property
    def armor_status_value(self) -> float:
        """
        Возвращает показатель состояния брони (0 .. 100) для 6-й полоски в левом столбце состояния (HUD):
        учитывает как надетые элементы брони (4 слота), так и их текущую прочность!
        """
        total_val = 0.0
        max_bonus = 0.60
        for asl in self.armor_slots:
            if asl is not None:
                item_id = str(asl.get("item", ""))
                bonus = ARMOR_DEFENSE_BONUS.get(item_id, 0.10)
                ratio = get_slot_durability_ratio(asl)
                r_val = 1.0 if ratio is None else ratio
                total_val += (bonus / max_bonus) * 100.0 * r_val
        return min(100.0, total_val)

    @property
    def armor_reduction(self) -> float:
        equipped_bonus = 0.0
        for asl in self.armor_slots:
            if asl is not None:
                item_id = str(asl.get("item", ""))
                ratio = get_slot_durability_ratio(asl)
                eff_mult = 1.0 if ratio is None else (0.35 + 0.65 * ratio)
                equipped_bonus += ARMOR_DEFENSE_BONUS.get(item_id, 0.10) * eff_mult
        if equipped_bonus == 0.0 and self.inventory.get("fur_armor", 0) > 0:
            equipped_bonus = 0.35
        vit_bonus = (self.skills["vitality"] - 1) * 0.03
        return min(0.75, equipped_bonus + vit_bonus)

    @property
    def melee_damage_multiplier(self) -> float:
        return 1.0 + (self.skills["strength"] - 1) * 0.16

    @property
    def harvest_multiplier(self) -> float:
        return 1.0 + (self.skills["harvesting"] - 1) * 0.25

    @property
    def crit_chance(self) -> float:
        return min(0.55, 0.08 + (self.skills["hunter"] - 1) * 0.08)

    def gain_xp(self, amount: int) -> List[str]:
        messages: List[str] = []
        self.xp += amount
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self.level += 1
            self.skill_points += 2
            self.xp_to_next = int(self.xp_to_next * 1.35)
            self.max_hp = 100.0 + (self.level - 1) * 10.0 + (self.skills["vitality"] - 1) * 25.0
            self.max_stamina = 100.0 + (self.skills["endurance"] - 1) * 20.0
            self.hp = self.max_hp
            self.stamina = self.max_stamina
            messages.append(
                f"НОВЫЙ УРОВЕНЬ РПГ: {self.level}! Получено +2 очка навыков!"
            )
        return messages

    def upgrade_skill(self, skill_key: str) -> Optional[str]:
        if self.skill_points <= 0 or skill_key not in self.skills:
            return None
        self.skill_points -= 1
        self.skills[skill_key] += 1
        self.max_hp = 100.0 + (self.level - 1) * 10.0 + (self.skills["vitality"] - 1) * 25.0
        self.max_stamina = 100.0 + (self.skills["endurance"] - 1) * 20.0
        if skill_key == "vitality":
            self.hp = min(self.max_hp, self.hp + 25.0)
        elif skill_key == "endurance":
            self.stamina = min(self.max_stamina, self.stamina + 20.0)
        names = {
            "strength": "Сила удара",
            "vitality": "Живучесть",
            "endurance": "Выносливость",
            "harvesting": "Мастер добычи",
            "hunter": "Инстинкт охотника",
        }
        return f"Навык '{names[skill_key]}' повышен до ур. {self.skills[skill_key]}!"


# ==============================================================================
# 6. ЯДРО МИРА: СТОЛ МАСТЕРСКОЙ, DRAG & DROP МЫШЬЮ, БИОМ ЛЕСА, КОЗЛЫ И БАРСЫ
# ==============================================================================

class SurvivalRPGGame:
    """Главный класс игры с прогрессией через Стол мастерской, Drag & Drop инвентарем и 3D-коллизиями по Y."""

    GRID_CELL_SIZE = 16.0

    def __init__(self, width: int = 1280, height: int = 720, headless: bool = False) -> None:
        self.width = width
        self.height = height
        self.headless = headless
        self.rng = random.Random(2026)

        # Стартовые настройки при первом заходе в игру (в точности как на скриншоте пользователя!):
        self.graphics_profile_idx = 3      # Сейчас: УЛЬТРА HD (Макс. Реализм)
        self.detail_quality_idx = 3        # Сейчас: Ультра HD (Корни, Ветви, Блики)
        self.shadows_enabled: bool = False # Сейчас: Выкл (Повышает FPS)
        self.custom_render_dist: float = 60.0  # Сейчас: 60 метров
        self.grass_density_idx = 3         # Сейчас: 150% (Высокая)
        self.fps_cap_idx = 4               # Сейчас: Без лимита (Макс. FPS) -> индекс 4 (0 в FPS_CAPS)
        self.clouds_enabled: bool = True   # Сейчас: Включены (Объемные 3D)
        self.chunk_gen_idx: int = 1        # По умолчанию 2 чанка вокруг игрока (5x5 = 25 секторов)
        self.antialias_idx: int = 2        # По умолчанию MSAA 4x (Аппаратное сглаживание)
        self.resolution_idx: int = 1       # По умолчанию 1280x720 (HD 720p)
        self.fps_history: deque[float] = deque(maxlen=45)
        self.current_fps: float = 60.0
        self.frame_ms: float = 16.6
        self.visible_chunks_count: int = 0
        self.visible_entities_count: int = 0
        self.anim_clock: float = 0.0

        self.sound = ProceduralSoundEngine(enabled=not headless)
        self.terrain = TerrainWorld(seed=2026)

        start_x, start_z = 0.0, 0.0
        start_y = self.terrain.get_height(start_x, start_z)
        self.player = PlayerFirstPerson(start_x, start_y, start_z)

        self.time_of_day = 8.5
        self.day_number = 1

        self.resources: List[ResourceNode] = []
        self.resource_grid: Dict[Tuple[int, int], List[ResourceNode]] = {}
        self.chunk_resources: Dict[Tuple[int, int], List[ResourceNode]] = {}
        self.shaking_resources: List[ResourceNode] = []
        self.animals: List[Animal] = []
        self.structures: List[BuiltStructure] = []
        self.arrows: List[ArrowProjectile] = []
        self.particles: List[Particle3D] = []
        self.dropped_items: List[DroppedItem3D] = []
        self.last_death_pos: Optional[Tuple[float, float, float]] = None
        self.last_death_timer: float = 0.0

        self._next_entity_id = 1
        self._populate_world()

        # Облака в МИРОВЫХ координатах (двигаются по ветру полностью независимо от ходьбы игрока!)
        self.clouds: List[Tuple[float, float, float, float, float]] = [
            (
                self.rng.uniform(-260.0, 260.0),
                self.rng.uniform(48.0, 68.0),
                self.rng.uniform(-260.0, 260.0),
                self.rng.uniform(16.0, 30.0),
                self.rng.uniform(10.0, 18.0),
            )
            for _ in range(26)
        ]
        self.stars: List[Tuple[float, float, float]] = [
            (
                self.rng.uniform(-175.0, 175.0),
                self.rng.uniform(58.0, 95.0),
                self.rng.uniform(-175.0, 175.0),
            )
            for _ in range(60)
        ]

        # Состояние интерфейса, настроек, Drag & Drop мыши, управления для телефона и прогрессии через Стол мастерской
        self.show_inventory = False
        self.selected_inv_idx = 0
        self.active_chest: Optional[BuiltStructure] = None
        self.bobber: Optional[FishingBobber] = None
        self.show_crafting = False
        self.show_skills = False
        self.show_quests = False
        self.show_controls_help = False
        self.show_settings = False
        self.is_fullscreen = False
        self.build_mode = False
        self.selected_build_idx = 0
        self.build_rotation = 0.0
        self.selected_recipe_idx = 0
        self.paused = False

        # ПОЛНОЦЕННОЕ СЕНСОРНОЕ УПРАВЛЕНИЕ ДЛЯ ТЕЛЕФОНА (Экранный джойстик, кнопки действий, мультитач и свайп-обзор 360°!)
        self.mobile_controls_enabled: bool = True
        self.touch_joy_active: bool = False
        self.touch_joy_pointer_id: Optional[int] = None
        self.touch_joy_dx: float = 0.0   # -1.0 (влево) .. +1.0 (вправо)
        self.touch_joy_dy: float = 0.0   # -1.0 (вперед/вверх на экране) .. +1.0 (назад/вниз на экране)
        self.touch_look_active: bool = False
        self.touch_look_pointer_id: Optional[int] = None
        self.touch_look_last_pos: Tuple[float, float] = (0.0, 0.0)
        self.touch_sprint_locked: bool = False
        self.touch_jump_held: bool = False
        self.touch_dive_held: bool = False
        self.touch_attack_held: bool = False
        self.touch_active_button: Optional[str] = None

        # Точное перетаскивание предметов мышью (Drag & Drop) между Инвентарем (0..24), Хотбаром (0..8) и Сундуком (0..14)
        self.dragged_item: Optional[str] = None
        self.dragged_count: int = 1
        self.dragged_from_chest: bool = False
        self.drag_source: Optional[Tuple[str, int]] = None  # ('inv', idx) | ('hotbar', idx) | ('chest', idx)
        self.drag_offset: Tuple[float, float] = (24.0, 24.0)
        self.drag_card_size: Tuple[float, float] = (56.0, 48.0)
        self.nearest_campfire_pos: Optional[Tuple[float, float, float]] = None

        self.notifications: List[Tuple[str, float, Tuple[int, int, int]]] = []
        self.add_notification(
            "Добудьте камнем два дерева, создайте Стол мастерской в инвентаре и установите его на землю!",
            8.5,
            (255, 235, 140),
        )

        self.hovered_target_text: str = ""
        self.hovered_animal: Optional[Animal] = None
        self.hovered_resource: Optional[ResourceNode] = None
        self.hovered_structure: Optional[BuiltStructure] = None

    def has_placed_workbench(self) -> bool:
        """Возвращает True, если игрок уже установил Стол мастерской (workbench) в мире."""
        return any(st.piece_id == "workbench" for st in self.structures)

    def get_held_item_display_name(self) -> str:
        """Возвращает название предмета, который сейчас находится в выбранной ячейке хотбара (над хотбаром)."""
        slot_idx = self.player.active_hotbar_slot
        item_id = self.player.hotbar[slot_idx] if 0 <= slot_idx < len(self.player.hotbar) else None
        if item_id is None:
            return "Пустые руки"
        if item_id in WEAPONS_DB:
            return WEAPONS_DB[item_id].name
        cnt = self.player.inventory.get(item_id, 0)
        name_ru = RESOURCE_NAMES_RU.get(item_id, item_id)
        return f"{name_ru} (x{cnt})" if cnt > 0 else name_ru

    @staticmethod
    def get_adaptive_predator_cap(player_level: int) -> int:
        """
        Повышенный адаптивный лимит хищников в зависимости от уровня персонажа с потолком:
          - На уровне 0: 12 хищников в мире.
          - На уровне 1: 14 хищников (частые встречи с волками, тиграми, медведями и снежными барсами!).
          - На уровне 5: 22 хищника.
          - На критическом уровне (уровень 10 и выше): спавн доходит до потолка (30 хищников)
            и ПЕРЕСТАЕТ РАСТИ даже на 25, 50 или 100 уровне!
        """
        eff_level = max(0, min(int(player_level), PREDATOR_CRITICAL_LEVEL))
        return min(30, 12 + int(round(eff_level * 1.8)))

    @staticmethod
    def get_adaptive_predator_spawn_chance(player_level: int) -> float:
        """
        Повышенный шанс спавна хищника в чанке: от 0.38 (на ур. 0) до 0.62 (на ур. 10+).
        """
        eff_level = max(0, min(int(player_level), PREDATOR_CRITICAL_LEVEL))
        return round(0.38 + (eff_level / float(PREDATOR_CRITICAL_LEVEL)) * 0.24, 4)

    def _is_near_or_inside_any_structure(self, x: float, z: float, min_clear_dist: float = 2.0) -> bool:
        """
        Проверяет, находится ли точка (x, z) прямо внутри дома/постройки или ближе чем в min_clear_dist (2+ м)
        от границ любой постройки, чтобы никто не спавнился в доме или в 2 метрах от построек!
        """
        margin = max(2.2, float(min_clear_dist))
        for st in self.structures:
            dx = x - st.x
            dz = z - st.z
            rad = math.radians(st.rotation)
            lx = abs(dx * math.cos(rad) - dz * math.sin(rad))
            lz = abs(dx * math.sin(rad) + dz * math.cos(rad))
            hx = st.size[0] * 0.5 + margin
            hz = st.size[2] * 0.5 + margin
            if lx <= hx and lz <= hz:
                return True
        return False

    def _is_near_any_tree_or_rock(self, x: float, z: float, min_clear_dist: float = 1.8) -> bool:
        """
        Проверяет, находится ли точка (x, z) внутри или слишком близко к стволу дерева, валуну, рудной жиле или пещере,
        чтобы животные никогда не спавнились в деревьях или камнях и не застревали!
        """
        for res in self.get_nearby_resources(x, z, cell_radius=1):
            if not res.alive or res.kind in ("grass_tuft", "berry_bush", "wild_bush", "mushroom_patch"):
                continue
            if math.hypot(x - res.x, z - res.z) < res.radius + min_clear_dist:
                return True
        return False

    def _can_spawn_animal_at(self, x: float, z: float, hostile: bool = False, player_level: Optional[int] = None) -> bool:
        """
        Единая проверка спавна любого животного:
          - Никто не может спавниться в деревьях, камнях, рудных жилах и пещерах (чтобы не застревать)!
          - Никто не может спавниться внутри построек или ближе 2 метров от любых построек!
          - Хищники (hostile=True) спавнятся ТОЛЬКО на расстоянии >= 10 метров от персонажа!
        """
        if self._is_near_or_inside_any_structure(x, z, min_clear_dist=2.2):
            return False
        if self._is_near_any_tree_or_rock(x, z, min_clear_dist=1.85):
            return False
        if hostile:
            return self._can_spawn_predator_at(x, z, player_level)
        return True

    def _can_spawn_predator_at(self, x: float, z: float, player_level: Optional[int] = None) -> bool:
        """
        Проверяет, можно ли заспавнить хищника в точке (x, z):
          - Не ближе 10 метров от текущего положения персонажа (self.player.x, self.player.z)!
          - Не внутри дома/построек и не ближе 2 метров от любых построек!
        """
        lvl = self.player.level if player_level is None else player_level
        alive_predators = [a for a in self.animals if a.alive and a.hostile]
        if len(alive_predators) >= self.get_adaptive_predator_cap(lvl):
            return False
        px = self.player.x if hasattr(self, "player") and self.player is not None else 0.0
        pz = self.player.z if hasattr(self, "player") and self.player is not None else 0.0
        if math.hypot(x - px, z - pz) < 10.5:
            return False
        if self._is_near_or_inside_any_structure(x, z, min_clear_dist=2.2):
            return False
        if self._is_near_any_tree_or_rock(x, z, min_clear_dist=1.85):
            return False
        if self.terrain.is_high_mountain_or_hill(x, z):
            return False
        if self.terrain.get_slope_degrees(x, z) > ANIMAL_MAX_CLIMB_ANGLE_DEG:
            return False
        for p_anim in alive_predators:
            if math.hypot(x - p_anim.x, z - p_anim.z) < MIN_PREDATOR_SPACING:
                return False
        return True

    @staticmethod
    def can_player_climb_angle(slope_deg: float) -> bool:
        """Персонаж может подниматься по склону с углом <= 75° (PLAYER_MAX_CLIMB_ANGLE_DEG = 75.0)."""
        return slope_deg <= PLAYER_MAX_CLIMB_ANGLE_DEG

    @staticmethod
    def can_goat_climb_angle(slope_deg: float) -> bool:
        """Горный козел может взбираться по склону вплоть до 85° (GOAT_MAX_CLIMB_ANGLE_DEG = 85.0)."""
        return slope_deg <= GOAT_MAX_CLIMB_ANGLE_DEG

    @staticmethod
    def can_animal_climb_angle(slope_deg: float, kind: str = "cow") -> bool:
        """
        Горные козлы могут взбираться до 85°, а все остальные животные — вплоть до 70°!
        """
        if kind == "mountain_goat":
            return slope_deg <= GOAT_MAX_CLIMB_ANGLE_DEG
        return slope_deg <= ANIMAL_MAX_CLIMB_ANGLE_DEG

    def can_player_move_to(self, curr_x: float, curr_z: float, next_x: float, next_z: float) -> bool:
        """Проверяет, позволяет ли угол наклона горы (<= 65°) игроку шагнуть из (curr_x, curr_z) в (next_x, next_z)."""
        for st in self.structures:
            if st.piece_id in ("foundation", "stairs", "bedroll"):
                if abs(next_x - st.x) <= 2.35 and abs(next_z - st.z) <= 2.35:
                    return True
        curr_h = self.terrain.get_height(curr_x, curr_z)
        dest_h = self.terrain.get_height(next_x, next_z)
        if dest_h <= curr_h + 1e-4:
            return True
        step_dist = math.hypot(next_x - curr_x, next_z - curr_z)
        climb_deg = math.degrees(math.atan2(dest_h - curr_h, max(1e-5, step_dist)))
        dest_slope_deg = self.terrain.get_slope_degrees(next_x, next_z)
        dir_slope_deg = self.terrain.get_directional_slope_degrees(curr_x, curr_z, next_x - curr_x, next_z - curr_z)
        effective_slope = max(climb_deg, min(dest_slope_deg, max(climb_deg, dir_slope_deg)))
        if dest_slope_deg > PLAYER_MAX_CLIMB_ANGLE_DEG and dir_slope_deg > 10.0:
            effective_slope = max(effective_slope, dest_slope_deg)
        return self.can_player_climb_angle(effective_slope)

    def put_in_hotbar(self, item_id: str, slot_idx: Optional[int] = None) -> None:
        """Помещает предмет в ячейку хотбара 1..9 (которая является ячейкой 0..8 инвентаря)."""
        if slot_idx is not None and 0 <= slot_idx < 9:
            self.player.hotbar[slot_idx] = item_id
            return
        if item_id in self.player.hotbar:
            return
        for i in range(9):
            if self.player.slots[i] is None:
                self.player.hotbar[i] = item_id
                return
        self.player.hotbar[8] = item_id

    def scroll_hotbar_wheel(self, direction: int) -> None:
        """Переключает активный предмет в хотбаре (1..9) прокруткой колесика мыши."""
        new_slot = (self.player.active_hotbar_slot + direction) % 9
        self.select_hotbar_slot(new_slot)

    def handle_mouse_wheel(self, direction: int) -> None:
        """
        Обрабатывает прокрутку колесика мыши:
          - Если включен режим строительства (build_mode или в руках молот) — прокручивает элементы стройки (BUILD_PIECES)!
          - Иначе — прокручивает слоты хотбара (1..9).
        """
        if (self.build_mode or self.player.equipped_weapon == "hammer") and self.has_placed_workbench():
            self.selected_build_idx = (self.selected_build_idx + direction) % len(BUILD_PIECES)
            self.sound.play("build")
        else:
            self.scroll_hotbar_wheel(direction)

    def move_or_swap_slots(self, src: Tuple[str, int], dst: Tuple[str, int]) -> bool:
        """
        Переносит или меняет местами предметы между любыми ячейками:
          - Инвентарь ('inv', 0..24) <-> Хотбар ('hotbar', 0..8, где hotbar[i] === slots[i])
          - Инвентарь/Хотбар <-> Сундук ('chest', 0..14)
        """
        src_kind, src_idx = src
        dst_kind, dst_idx = dst
        if src_kind == "hotbar":
            src_kind = "inv"
        if dst_kind == "hotbar":
            dst_kind = "inv"
        if src_kind == dst_kind and src_idx == dst_idx:
            return False

        def get_slot(kind: str, idx: int) -> Optional[Dict[str, object]]:
            if kind == "inv" and 0 <= idx < MAX_INVENTORY_SLOTS:
                return self.player.slots[idx]
            if kind == "armor" and 0 <= idx < 4:
                return self.player.armor_slots[idx]
            if kind == "chest" and self.active_chest is not None and 0 <= idx < MAX_CHEST_SLOTS:
                return self.active_chest.chest_slots[idx]
            return None

        def set_slot(kind: str, idx: int, val: Optional[Dict[str, object]]) -> None:
            if kind == "inv" and 0 <= idx < MAX_INVENTORY_SLOTS:
                self.player.slots[idx] = val
            elif kind == "armor" and 0 <= idx < 4:
                self.player.armor_slots[idx] = val
            elif kind == "chest" and self.active_chest is not None and 0 <= idx < MAX_CHEST_SLOTS:
                self.active_chest.chest_slots[idx] = val

        s_val = get_slot(src_kind, src_idx)
        if s_val is None:
            return False
        if dst_kind == "armor":
            req_armor_slot = ITEM_TO_ARMOR_SLOT_IDX.get(str(s_val.get("item", "")), -1)
            if req_armor_slot != dst_idx:
                self.add_notification("Этот предмет не подходит для данной ячейки брони!", 2.5, (255, 150, 120))
                return False
        d_val = get_slot(dst_kind, dst_idx)
        if src_kind == "armor" and d_val is not None:
            req_armor_slot = ITEM_TO_ARMOR_SLOT_IDX.get(str(d_val.get("item", "")), -1)
            if req_armor_slot != src_idx:
                return False

        # Если перетаскиваем одинаковый стакающийся ресурс (без индивидуальной прочности) — объединяем стеки!
        s_item = str(s_val["item"])
        is_unique = s_item in ITEM_MAX_DURABILITY or (s_item in WEAPONS_DB and s_item != "workbench_item")
        if d_val is not None and str(d_val["item"]) == s_item and not is_unique:
            d_val["count"] = int(d_val.get("count", 1)) + int(s_val.get("count", 1))
            set_slot(src_kind, src_idx, None)
        else:
            set_slot(dst_kind, dst_idx, dict(s_val))
            set_slot(src_kind, src_idx, dict(d_val) if d_val is not None else None)

        if self.active_chest is not None:
            self.active_chest.sync_storage_from_slots()
        self.player.sync_active_weapon_from_hotbar()
        self.sound.play("build")
        return True

    def drop_item_from_slot(
        self,
        source_kind: str = "inv",
        slot_idx: Optional[int] = None,
        drop_all: bool = True,
    ) -> bool:
        """
        Сбрасывает предмет из выбранной ячейки инвентаря, хотбара или брони на землю перед персонажем (клавиша [Q]
        или кнопка 'Выбросить предмет' или перетаскивание за пределы окна инвентаря).
        """
        if source_kind == "hotbar":
            source_kind = "inv"
        if slot_idx is None:
            slot_idx = self.selected_inv_idx if self.show_inventory else self.player.active_hotbar_slot

        sl: Optional[Dict[str, object]] = None
        if source_kind == "inv" and 0 <= slot_idx < MAX_INVENTORY_SLOTS:
            sl = self.player.slots[slot_idx]
        elif source_kind == "armor" and 0 <= slot_idx < 4:
            sl = self.player.armor_slots[slot_idx]
        elif source_kind == "chest" and self.active_chest is not None and 0 <= slot_idx < MAX_CHEST_SLOTS:
            sl = self.active_chest.chest_slots[slot_idx]

        if sl is None:
            self.add_notification("Ячейка пуста — нечего выбрасывать!", 2.2, (235, 175, 130))
            return False

        item_id = str(sl["item"])
        have = int(sl.get("count", 1))
        drop_cnt = have if drop_all else 1
        rem = have - drop_cnt

        if source_kind == "inv":
            if rem <= 0:
                self.player.slots[slot_idx] = None
            else:
                sl["count"] = rem
            if rem <= 0 and item_id in WEAPONS_DB and not any(
                s is not None and s.get("item") == item_id for s in self.player.slots
            ):
                self.player.unlocked_weapons.discard(item_id)
        elif source_kind == "armor":
            self.player.armor_slots[slot_idx] = None
        elif source_kind == "chest" and self.active_chest is not None:
            if rem <= 0:
                self.active_chest.chest_slots[slot_idx] = None
            else:
                sl["count"] = rem
            self.active_chest.sync_storage_from_slots()

        self.player.sync_active_weapon_from_hotbar()

        yaw_rad = math.radians(self.player.yaw)
        dx = self.player.x + math.sin(yaw_rad) * 1.75 + self.rng.uniform(-0.22, 0.22)
        dz = self.player.z - math.cos(yaw_rad) * 1.75 + self.rng.uniform(-0.22, 0.22)
        dy = self.player.y + 1.05
        self.dropped_items.append(
            DroppedItem3D(
                id=self._alloc_id(),
                item_id=item_id,
                count=drop_cnt,
                x=dx,
                y=dy,
                z=dz,
                vy=2.6,
                rotation=self.rng.uniform(0.0, 360.0),
                pickup_delay=0.75,
            )
        )
        name_ru = WEAPONS_DB[item_id].name if item_id in WEAPONS_DB else RESOURCE_NAMES_RU.get(item_id, item_id)
        self.sound.play("swing")
        self.add_notification(f"Выброшено на землю: {name_ru} (x{drop_cnt}) [Подойдите и нажмите F, чтобы подобрать]", 3.4, (255, 215, 125))
        return True

    def get_effective_render_dist(self) -> float:
        """Возвращает текущую дальность прорисовки (настраиваемую в меню Настроек)."""
        return float(self.custom_render_dist)

    def get_grass_density_multiplier(self) -> float:
        """Возвращает множитель количества травы и кустов из меню Настроек (0.0 .. 2.0)."""
        return float(GRASS_DENSITY_PRESETS[self.grass_density_idx][1])

    def adjust_render_distance(self, delta: float) -> None:
        self.custom_render_dist = max(60.0, min(210.0, self.custom_render_dist + delta))
        self.add_notification(f"Дальность прорисовки: {int(self.custom_render_dist)} м", 2.5, (145, 240, 255))

    def adjust_grass_density(self, delta_idx: int) -> None:
        self.grass_density_idx = max(0, min(len(GRASS_DENSITY_PRESETS) - 1, self.grass_density_idx + delta_idx))
        lbl, _ = GRASS_DENSITY_PRESETS[self.grass_density_idx]
        self.add_notification(f"Количество травы и кустов: {lbl}", 2.5, (145, 255, 175))

    def get_chunk_gen_radius(self) -> int:
        """Возвращает текущий радиус генерации чанков вокруг игрока (1..5 чанков)."""
        return int(CHUNK_GEN_PRESETS[self.chunk_gen_idx][0])

    def adjust_chunk_gen_radius(self, delta_idx: int) -> None:
        """Изменяет параметр генерации чанков вокруг игрока (от 3x3 до 11x11 секторов)."""
        self.chunk_gen_idx = max(0, min(len(CHUNK_GEN_PRESETS) - 1, self.chunk_gen_idx + delta_idx))
        rad, lbl = CHUNK_GEN_PRESETS[self.chunk_gen_idx]
        self.stream_infinite_chunks()
        self.add_notification(f"Генерация чанков: {lbl}", 2.6, (145, 255, 195))

    def adjust_antialiasing(self, delta_idx: int) -> None:
        """Изменяет уровень сглаживания (Выкл / 2x / MSAA 4x / Ultra MSAA 8x)."""
        self.antialias_idx = max(0, min(len(ANTIALIAS_PRESETS) - 1, self.antialias_idx + delta_idx))
        lbl, _ = ANTIALIAS_PRESETS[self.antialias_idx]
        self.add_notification(f"Сглаживание: {lbl}", 2.6, (155, 240, 255))

    def adjust_detail_quality(self, delta_idx: int) -> None:
        """Позволяет понизить или повысить детализацию 3D-моделей (4 разных уровня: Низкая / Средняя / Высокая / Ультра HD)."""
        self.detail_quality_idx = max(0, min(len(DETAIL_QUALITY_PRESETS) - 1, self.detail_quality_idx + delta_idx))
        for ch in self.terrain.generated_chunks.values():
            ch.props_dirty = True
        lbl, _ = DETAIL_QUALITY_PRESETS[self.detail_quality_idx]
        self.add_notification(f"Детализация 3D-моделей: {lbl}", 2.8, (145, 245, 255))

    def toggle_shadows_and_reflections(self) -> None:
        """Включает или отключает мягкие тени от объектов и блики на воде для повышения FPS на слабых ПК."""
        self.shadows_enabled = not self.shadows_enabled
        for ch in self.terrain.generated_chunks.values():
            ch.props_dirty = True
        st_str = "Включены (Реалистичные тени и блики)" if self.shadows_enabled else "Отключены (Макс. FPS)"
        self.add_notification(f"Тени и блики воды: {st_str}", 2.8, (150, 240, 255))

    def apply_graphics_profile(self, idx: int) -> None:
        """Применяет выбранный пресет графики (от НИЗКИХ для слабых ПК до УЛЬТРА HD реализма)."""
        self.graphics_profile_idx = idx % len(GRAPHICS_PROFILES)
        prof = GRAPHICS_PROFILES[self.graphics_profile_idx]
        self.custom_render_dist = float(prof["render_dist"])
        self.clouds_enabled = bool(prof["clouds_enabled"])
        self.detail_quality_idx = int(prof.get("detail_idx", 2))
        self.shadows_enabled = bool(prof.get("shadows", True))
        self.grass_density_idx = int(prof.get("grass_idx", 2))
        for ch in self.terrain.generated_chunks.values():
            ch.props_dirty = True
        self.add_notification(
            f"Качество графики: {prof['name']} (Обзор: {int(self.custom_render_dist)} м)",
            3.5,
            (135, 255, 185),
        )

    def select_hotbar_slot(self, slot_idx: int) -> None:
        """
        Тихо выбирает ячейку 1..9 хотбара БЕЗ спама в уведомлениях слева сверху!
        Сразу обновляет предмет в 3D-руке (оружие, руду, ресурс, еду или пустую ладонь).
        """
        if not (0 <= slot_idx < 9):
            return
        self.player.active_hotbar_slot = slot_idx
        self.player.sync_active_weapon_from_hotbar()
        item_id = self.player.hotbar[slot_idx]
        if item_id == "hammer":
            if self.has_placed_workbench():
                self.build_mode = True
            else:
                self.build_mode = False
        else:
            self.build_mode = False

    def craft_workbench_in_inventory(self) -> bool:
        """Создает Стол мастерской в инвентаре [I] за 2 Дерева (первый шаг прогрессии!)."""
        if self.player.inventory.get("wood", 0) < 2:
            have = self.player.inventory.get("wood", 0)
            self.add_notification(
                f"Для создания Стола мастерской нужно 2 Дерева (сейчас: {have}/2)! Сначала добудьте дерево камнем.",
                3.5,
                (255, 135, 115),
            )
            return False
        self.player.inventory["wood"] -= 2
        self.player.inventory["workbench_item"] = self.player.inventory.get("workbench_item", 0) + 1
        self.player.unlocked_weapons.add("workbench_item")
        self.put_in_hotbar("workbench_item")
        # Сразу берем Стол в руки для удобной установки на землю
        if "workbench_item" in self.player.hotbar:
            self.player.active_hotbar_slot = self.player.hotbar.index("workbench_item")
        self.player.equipped_weapon = "workbench_item"
        self.sound.play("build")
        self.add_notification(
            "Создан Стол мастерской! Выберите его в ячейке и установите на землю.",
            5.0,
            (130, 255, 185),
        )
        self.player.gain_xp(30)
        return True

    def place_workbench_from_hand(self) -> bool:
        """Устанавливает 3D-Стол мастерской из рук на землю перед игроком и открывает доступ к Крафту и Стройке."""
        if self.player.inventory.get("workbench_item", 0) <= 0 and "workbench_item" not in self.player.unlocked_weapons:
            return False
        yaw_rad = math.radians(self.player.yaw)
        bx = round((self.player.x + math.sin(yaw_rad) * 3.2) * 2.0) * 0.5
        bz = round((self.player.z - math.cos(yaw_rad) * 3.2) * 2.0) * 0.5
        base_y = self.terrain.get_height(bx, bz)
        for st in self.structures:
            if st.piece_id == "foundation" and abs(st.x - bx) <= 2.05 and abs(st.z - bz) <= 2.05:
                base_y = max(base_y, st.y + 0.22)
        by = base_y + 0.45

        wb_st = BuiltStructure(
            id=self._alloc_id(),
            piece_id="workbench",
            name="Стол мастерской (Верстак)",
            x=bx,
            y=by,
            z=bz,
            rotation=self.build_rotation,
            size=(1.65, 0.92, 1.10),
            is_solid=False,
            is_roof=False,
        )
        self.structures.append(wb_st)
        self.player.stats_blocks_built += 1
        if self.player.inventory.get("workbench_item", 0) > 0:
            self.player.inventory["workbench_item"] -= 1
        if self.player.inventory.get("workbench_item", 0) <= 0:
            self.player.unlocked_weapons.discard("workbench_item")
            for i in range(9):
                if self.player.hotbar[i] == "workbench_item":
                    self.player.hotbar[i] = None
            self.player.equipped_weapon = "rock"
            self.player.active_hotbar_slot = 0

        # Разблокируем Строительный молот после установки Стола!
        self.player.unlocked_weapons.add("hammer")
        self.sound.play("build")
        self.spawn_particles(bx, by, bz, (0.82, 0.64, 0.36), count=12, speed=3.5)
        self.add_notification(
            "Стол мастерской установлен! Теперь вам доступны создание оружия на Столе и строительство дома!",
            5.5,
            (135, 255, 195),
        )
        self.player.gain_xp(45)
        return True

    def _alloc_id(self) -> int:
        eid = self._next_entity_id
        self._next_entity_id += 1
        return eid

    def _cell_coords(self, x: float, z: float) -> Tuple[int, int]:
        return (int(math.floor(x / self.GRID_CELL_SIZE)), int(math.floor(z / self.GRID_CELL_SIZE)))

    def _mark_chunk_props_dirty(self, x: float, z: float) -> None:
        ckey = (int(math.floor(x / CHUNK_SIZE)), int(math.floor(z / CHUNK_SIZE)))
        ch = self.terrain.generated_chunks.get(ckey)
        if ch is not None:
            ch.props_dirty = True

    def _register_resource(self, node: ResourceNode) -> None:
        self.resources.append(node)
        cell = self._cell_coords(node.x, node.z)
        self.resource_grid.setdefault(cell, []).append(node)
        ckey = (int(math.floor(node.x / CHUNK_SIZE)), int(math.floor(node.z / CHUNK_SIZE)))
        self.chunk_resources.setdefault(ckey, []).append(node)
        ch = self.terrain.generated_chunks.get(ckey)
        if ch is not None:
            ch.props_dirty = True

    def get_nearby_resources(self, x: float, z: float, cell_radius: int = 1) -> List[ResourceNode]:
        cx, cz = self._cell_coords(x, z)
        out: List[ResourceNode] = []
        for dx in range(-cell_radius, cell_radius + 1):
            for dz in range(-cell_radius, cell_radius + 1):
                bucket = self.resource_grid.get((cx + dx, cz + dz))
                if bucket:
                    out.extend(bucket)
        return out

    def add_notification(self, text: str, duration: float = 4.2, color: Tuple[int, int, int] = (235, 245, 255)) -> None:
        self.notifications.append((text, duration, color))
        if len(self.notifications) > 5:
            self.notifications.pop(0)

    def cycle_graphics_profile(self) -> None:
        self.apply_graphics_profile((self.graphics_profile_idx + 1) % len(GRAPHICS_PROFILES))

    def cycle_fps_cap(self) -> None:
        self.fps_cap_idx = (self.fps_cap_idx + 1) % len(FPS_CAPS)
        cap = FPS_CAPS[self.fps_cap_idx]
        cap_str = f"{cap} FPS" if cap > 0 else "Без лимита (Макс. FPS)"
        self.add_notification(f"Лимит кадров: {cap_str}", 3.0, (150, 235, 255))

    def regenerate_with_new_seed(self, new_seed: Optional[int] = None) -> None:
        if new_seed is None:
            new_seed = random.randint(1000, 999999)
        self.rng = random.Random(new_seed)
        self.terrain = TerrainWorld(seed=new_seed)
        self.resources.clear()
        self.resource_grid.clear()
        self.chunk_resources.clear()
        self.shaking_resources.clear()
        self.animals.clear()
        self.structures.clear()
        self.arrows.clear()
        self.particles.clear()
        self.dropped_items.clear()
        self.last_death_pos = None
        self.last_death_timer = 0.0
        self._populate_world()
        sy = self.terrain.get_height(0.0, 0.0)
        self.player.x, self.player.y, self.player.z = 0.0, max(sy, WATER_LEVEL), 0.0
        self.add_notification(
            f"Сгенерирован новый бесконечный мир! Seed: #{new_seed}",
            5.0,
            (130, 255, 195),
        )

    def _populate_world(self) -> None:
        """Заселяет мир, гарантирует узкие и широкие горы, горных козлов на вершинах узких гор и снежных барсов в зимнем биоме."""
        guaranteed_nodes = [
            ("pine", "Вековая сосна", 7.5, 5.5, 60.0, 0.85),
            ("apple_tree", "Дикая яблоня", -8.0, 6.5, 60.0, 0.90),
            ("birch", "Белая береза", 6.5, -7.5, 55.0, 0.72),
            ("stone_rock", "Скальный валун", -8.0, -7.0, 70.0, 1.0),
            ("coal_vein", "Угольный пласт", 12.0, -5.0, 80.0, 1.05),
            ("copper_vein", "Жила медной руды", -13.0, -4.0, 90.0, 1.05),
            ("berry_bush", "Лесной ягодный куст", 5.5, 4.5, 30.0, 0.8),
            ("mushroom_patch", "Поляна лесных грибов", -5.5, 6.0, 20.0, 0.65),
            ("grass_tuft", "Пышная лесная трава", 3.5, 3.0, 10.0, 0.5),
            ("grass_tuft", "Пышная лесная трава", -4.0, 3.5, 10.0, 0.5),
            ("cave_grotto", "Древняя Горная Пещера", -33.0, -15.0, 9999.0, 1.35),
            ("gold_vein", "Самородная золотая жила", -31.5, -16.5, 130.0, 1.15),
            ("mythril_vein", "Кристалл ледяного мифрила", -34.8, -14.0, 150.0, 1.15),
            ("iron_vein", "Богатая железная жила", -30.0, -15.5, 110.0, 1.15),
        ]
        for kind, name, gx, gz, hp, rad in guaranteed_nodes:
            gh = self.terrain.get_height(gx, gz)
            self._register_resource(
                ResourceNode(
                    id=self._alloc_id(),
                    kind=kind,
                    name=name,
                    x=gx,
                    y=gh,
                    z=gz,
                    scale=1.1 if kind == "cave_grotto" else 1.0,
                    rotation=35.0,
                    hp=hp,
                    max_hp=hp,
                    radius=rad,
                )
            )

        # Размещаем оба сундука на ровных площадках с плотной посадкой основания на треугольную сетку земли (+0.32 м)
        starter_chest = BuiltStructure(
            id=self._alloc_id(),
            piece_id="chest",
            name="Походный сундук выжившего",
            x=4.5,
            y=self.terrain.get_height(4.5, -4.5) + 0.32,
            z=-4.5,
            rotation=0.0,
            size=(1.25, 0.82, 0.85),
            is_solid=False,
            is_roof=False,
            storage={"stone": 6, "coal": 4, "cooked_fish": 2, "arrow": 8, "salve": 2},
        )
        cave_chest = BuiltStructure(
            id=self._alloc_id(),
            piece_id="chest",
            name="Древний сундук пещеры",
            x=-31.0,
            y=self.terrain.get_height(-31.0, -13.0) + 0.32,
            z=-13.0,
            rotation=25.0,
            size=(1.25, 0.82, 0.85),
            is_solid=False,
            is_roof=False,
            storage={"gold": 4, "mythril": 2, "iron": 6, "hunter_stew": 2},
        )
        self.structures.extend([starter_chest, cave_chest])

        for cx in range(-3, 4):
            for cz in range(-3, 4):
                self._populate_chunk_entities(cx, cz)

        # Стая рыб в стартовом озере (26, 20)
        for fx, fz in [(26.0, 20.0), (28.0, 22.0), (24.0, 18.0), (0.0, 32.0)]:
            fh = self.terrain.get_height(fx, fz)
            if fh < WATER_LEVEL - 0.2:
                self.animals.append(Animal(self._alloc_id(), "fish", fx, WATER_LEVEL - 0.55, fz, level=1))

        # Гарантируем Горных козлов СТРОГО на вершинах или почти вершинах узких гор!
        for gx, gz in [(54.0, -52.0), (55.5, -51.0), (-58.0, -48.0), (-56.5, -49.0)]:
            if self.terrain.is_narrow_peak_summit(gx, gz):
                gh = self.terrain.get_height(gx, gz)
                goat = Animal(self._alloc_id(), "mountain_goat", gx, gh, gz, level=2)
                p_deg, r_deg, arc_y = self.terrain.get_body_tilt_angles(gx, gz, goat.yaw, 0.62 * goat.scale, 0.30 * goat.scale)
                goat.pitch, goat.roll, goat.y = p_deg, r_deg, arc_y
                self.animals.append(goat)

        # Гарантируем редких одиночных хищников в дальних биомах в рамках стартового адаптивного лимита (<= 4 на 1 ур.)
        for p_kind, px_s, pz_s in [
            ("snow_leopard", 82.0, -116.0),
            ("wolf", -84.0, -76.0),
            ("bear", 88.0, 74.0),
            ("tiger", -86.0, 82.0),
        ]:
            if not any(a.kind == p_kind for a in self.animals):
                alive_preds = [a for a in self.animals if a.alive and a.hostile]
                if len(alive_preds) >= self.get_adaptive_predator_cap(self.player.level):
                    # Заменяем дублирующийся вид хищника, чтобы не превысить адаптивный лимит!
                    counts = {}
                    for ap in alive_preds:
                        counts[ap.kind] = counts.get(ap.kind, 0) + 1
                    dup = next((ap for ap in reversed(alive_preds) if counts[ap.kind] > 1), None)
                    if dup is not None:
                        self.animals.remove(dup)
                if len([a for a in self.animals if a.alive and a.hostile]) < self.get_adaptive_predator_cap(self.player.level):
                    ph = self.terrain.get_height(px_s, pz_s)
                    panim = Animal(self._alloc_id(), p_kind, px_s, ph, pz_s, level=2)
                    p_deg, r_deg, arc_y = self.terrain.get_body_tilt_angles(px_s, pz_s, panim.yaw, 0.62 * panim.scale, 0.30 * panim.scale)
                    panim.pitch, panim.roll, panim.y = p_deg, r_deg, arc_y
                    self.animals.append(panim)

    def _populate_chunk_entities(self, cx: int, cz: int) -> None:
        if (cx, cz) in self.terrain.populated_chunks:
            return
        self.terrain.populated_chunks.add((cx, cz))
        self.terrain.get_or_create_chunk(cx, cz)

        chunk_seed = (self.terrain.seed * 73856093) ^ (cx * 19349663) ^ (cz * 83492791)
        crng = random.Random(chunk_seed)

        x0 = cx * CHUNK_SIZE
        z0 = cz * CHUNK_SIZE

        # 1. Деревья (в Лесу и Тайге — густой лес; в Степях, Полях и Ущельях — простор!)
        _, center_moist, center_biome = self.terrain.get_biome_weights(x0 + CHUNK_SIZE * 0.5, z0 + CHUNK_SIZE * 0.5)
        cb_low = center_biome.lower()
        if "лес" in cb_low or "тайга" in cb_low:
            tree_min, tree_max = (14, 20)
        elif "степь" in cb_low or "ущелье" in cb_low:
            tree_min, tree_max = (2, 4)
        elif "поле" in cb_low:
            tree_min, tree_max = (4, 7)
        else:
            tree_min, tree_max = (7, 12)
        for _ in range(crng.randint(tree_min, tree_max)):
            x = x0 + crng.uniform(2.5, CHUNK_SIZE - 2.5)
            z = z0 + crng.uniform(2.5, CHUNK_SIZE - 2.5)
            if x * x + z * z < 11.0 ** 2:
                continue
            h = self.terrain.get_height(x, z)
            if h < BEACH_LEVEL + 0.25 or h > SNOW_LEVEL - 1.5:
                continue
            temp, moist, _ = self.terrain.get_biome_weights(x, z)
            if temp < -0.22 or h >= MOUNTAIN_LEVEL + 4.0:
                kind, name, hp, rad = "snow_pine", "Заснеженная зимняя ель", 90.0, 0.88
            elif temp > 0.30:
                kind, name, hp, rad = (
                    ("autumn_oak", "Золотой клен", 95.0, 0.92)
                    if crng.random() < 0.65
                    else ("apple_tree", "Дикая яблоня", 85.0, 0.90)
                )
            elif moist > 0.22:
                kind, name, hp, rad = "pine", "Вековая ель", 85.0, 0.85
            else:
                r = crng.random()
                if r < 0.38:
                    kind, name, hp, rad = "oak", "Могучий лесной дуб", 105.0, 0.95
                elif r < 0.62:
                    kind, name, hp, rad = "apple_tree", "Дикая яблоня", 85.0, 0.90
                elif r < 0.82:
                    kind, name, hp, rad = "pine", "Лесная сосна", 80.0, 0.85
                else:
                    kind, name, hp, rad = "birch", "Белая береза", 65.0, 0.72

            scale = crng.uniform(0.85, 1.40)
            self._register_resource(
                ResourceNode(
                    id=self._alloc_id(),
                    kind=kind,
                    name=name,
                    x=x,
                    y=h,
                    z=z,
                    scale=scale,
                    rotation=crng.uniform(0, 360),
                    hp=hp,
                    max_hp=hp,
                    radius=rad * scale,
                )
            )

        # 2. Пещеры и 6 видов руд (генерируем до травы и животных, чтобы трава и звери не спавнились внутри камней!)
        center_h = self.terrain.get_height(x0 + CHUNK_SIZE * 0.5, z0 + CHUNK_SIZE * 0.5)
        if MOUNTAIN_LEVEL - 4.0 <= center_h <= MOUNTAIN_MID_MAX and crng.random() < 0.38:
            cx_cave = x0 + crng.uniform(10.0, CHUNK_SIZE - 10.0)
            cz_cave = z0 + crng.uniform(10.0, CHUNK_SIZE - 10.0)
            ch_cave = self.terrain.get_height(cx_cave, cz_cave)
            if ch_cave >= BEACH_LEVEL + 2.0 and self.terrain.get_slope_degrees(cx_cave, cz_cave) <= 38.0:
                self._register_resource(
                    ResourceNode(
                        id=self._alloc_id(),
                        kind="cave_grotto",
                        name="Горная Пещера (Залежи руд)",
                        x=cx_cave,
                        y=ch_cave,
                        z=cz_cave,
                        scale=crng.uniform(1.15, 1.45),
                        rotation=crng.uniform(0, 360),
                        hp=9999.0,
                        max_hp=9999.0,
                        radius=2.2,
                    )
                )
                for ox, oz, okind, oname, ohp in [
                    (1.8, 1.2, "gold_vein", "Золотая рудная жила", 130.0),
                    (-1.8, 1.5, "mythril_vein", "Кристалл ледяного мифрила", 150.0),
                    (1.5, -1.8, "coal_vein", "Пещерный угольный пласт", 85.0),
                ]:
                    rx, rz = cx_cave + ox, cz_cave + oz
                    self._register_resource(
                        ResourceNode(
                            id=self._alloc_id(),
                            kind=okind,
                            name=oname,
                            x=rx,
                            y=self.terrain.get_height(rx, rz),
                            z=rz,
                            scale=1.1,
                            rotation=crng.uniform(0, 360),
                            hp=ohp,
                            max_hp=ohp,
                            radius=1.05,
                        )
                    )

        for _ in range(crng.randint(4, 7)):
            x = x0 + crng.uniform(3.0, CHUNK_SIZE - 3.0)
            z = z0 + crng.uniform(3.0, CHUNK_SIZE - 3.0)
            if x * x + z * z < 9.0 ** 2:
                continue
            if self._is_near_any_tree_or_rock(x, z, min_clear_dist=1.2) or self._is_near_or_inside_any_structure(x, z, min_clear_dist=2.0):
                continue
            h = self.terrain.get_height(x, z)
            if h < WATER_LEVEL + 0.35 or self.terrain.get_slope_degrees(x, z) > 46.0:
                continue
            temp, _, _ = self.terrain.get_biome_weights(x, z)
            r = crng.random()
            if (h >= SNOW_LEVEL - 2.0 or temp < -0.25) and r < 0.35:
                kind, name, hp = "mythril_vein", "Кристалл ледяного мифрила", 145.0
            elif h >= MOUNTAIN_MID_MIN and r < 0.32:
                kind, name, hp = "gold_vein", "Золотая рудная жила", 125.0
            elif h >= MOUNTAIN_LEVEL - 3.0 and r < 0.65:
                kind, name, hp = "iron_vein", "Жила железной руды", 110.0
            elif r < 0.28:
                kind, name, hp = "copper_vein", "Жила медной руды", 90.0
            elif r < 0.52:
                kind, name, hp = "coal_vein", "Угольный пласт", 80.0
            else:
                kind, name, hp = "stone_rock", "Скальный валун", 75.0
            scale = crng.uniform(0.85, 1.45)
            self._register_resource(
                ResourceNode(
                    id=self._alloc_id(),
                    kind=kind,
                    name=name,
                    x=x,
                    y=h,
                    z=z,
                    scale=scale,
                    rotation=crng.uniform(0, 360),
                    hp=hp,
                    max_hp=hp,
                    radius=1.05 * scale,
                )
            )

        # 3. 3D-Трава (grass_tuft) и кусты — спавнятся ТОЛЬКО на пологих/умеренных склонах (<= 32°), вне камней и деревьев и плотно на треугольной сетке земли!
        base_grass_min, base_grass_max = (56, 76) if ("поле" in cb_low or "степь" in cb_low or "лес" in cb_low) else (42, 58)
        for _ in range(crng.randint(base_grass_min, base_grass_max)):
            x = x0 + crng.uniform(1.5, CHUNK_SIZE - 1.5)
            z = z0 + crng.uniform(1.5, CHUNK_SIZE - 1.5)
            h = self.terrain.get_height(x, z)
            temp, _, _ = self.terrain.get_biome_weights(x, z)
            if (
                BEACH_LEVEL + 0.15 <= h <= MOUNTAIN_LEVEL + 3.5
                and temp >= -0.24
                and self.terrain.get_slope_degrees(x, z) <= 32.0
                and not self._is_near_any_tree_or_rock(x, z, min_clear_dist=0.55)
                and not self._is_near_or_inside_any_structure(x, z, min_clear_dist=1.2)
            ):
                self._register_resource(
                    ResourceNode(
                        id=self._alloc_id(),
                        kind="grass_tuft",
                        name="Пышная трава",
                        x=x,
                        y=h,
                        z=z,
                        scale=crng.uniform(0.85, 1.45),
                        rotation=crng.uniform(0, 360),
                        hp=12.0,
                        max_hp=12.0,
                        radius=0.45,
                    )
                )

        for _ in range(crng.randint(11, 16)):
            x = x0 + crng.uniform(2.5, CHUNK_SIZE - 2.5)
            z = z0 + crng.uniform(2.5, CHUNK_SIZE - 2.5)
            h = self.terrain.get_height(x, z)
            if (
                BEACH_LEVEL + 0.3 <= h <= MOUNTAIN_LEVEL + 0.5
                and self.terrain.get_slope_degrees(x, z) <= 30.0
                and not self._is_near_any_tree_or_rock(x, z, min_clear_dist=0.85)
                and not self._is_near_or_inside_any_structure(x, z, min_clear_dist=1.6)
            ):
                r_b = crng.random()
                if r_b < 0.45:
                    kind, name, hp, rad = "berry_bush", "Лесной ягодный куст", 30.0, 0.80
                elif r_b < 0.82:
                    kind, name, hp, rad = "wild_bush", "Раскидистый кустарник", 25.0, 0.78
                else:
                    kind, name, hp, rad = "mushroom_patch", "Поляна лесных грибов", 20.0, 0.65
                self._register_resource(
                    ResourceNode(
                        id=self._alloc_id(),
                        kind=kind,
                        name=name,
                        x=x,
                        y=h,
                        z=z,
                        scale=crng.uniform(0.85, 1.35),
                        rotation=crng.uniform(0, 360),
                        hp=hp,
                        max_hp=hp,
                        radius=rad,
                    )
                )

        # 4. Фауна чанка (животные гарантированно спавнятся ВНЕ деревьев, камней, построек и крутых обрывов у воды!):
        dist_origin = math.hypot(x0 + CHUNK_SIZE * 0.5, z0 + CHUNK_SIZE * 0.5)
        for _ in range(crng.randint(2, 4)):
            for _attempt in range(10):
                x = x0 + crng.uniform(4.0, CHUNK_SIZE - 4.0)
                z = z0 + crng.uniform(4.0, CHUNK_SIZE - 4.0)
                h = self.terrain.get_height(x, z)

                if self._is_near_or_inside_any_structure(x, z, min_clear_dist=2.2):
                    continue
                if self._is_near_any_tree_or_rock(x, z, min_clear_dist=1.95):
                    continue

                if h < WATER_LEVEL - 0.55:
                    self.animals.append(Animal(self._alloc_id(), "fish", x, WATER_LEVEL - 0.55, z, level=1))
                    break

                if h < BEACH_LEVEL + 0.35:
                    continue

                slope_deg = self.terrain.get_slope_degrees(x, z)
                if slope_deg > 42.0 and not self.terrain.is_narrow_peak_summit(x, z):
                    continue

                # На высоких горах и холмах может находиться ТОЛЬКО горный козел!
                if self.terrain.is_narrow_peak_summit(x, z):
                    if slope_deg <= GOAT_MAX_CLIMB_ANGLE_DEG:
                        lvl = max(1, int(dist_origin / 85.0) + crng.randint(1, 2))
                        goat = Animal(self._alloc_id(), "mountain_goat", x, h, z, level=lvl)
                        p_deg, r_deg, arc_y = self.terrain.get_body_tilt_angles(x, z, goat.yaw, 0.62 * goat.scale, 0.30 * goat.scale)
                        goat.pitch, goat.roll, goat.y = p_deg, r_deg, arc_y
                        self.animals.append(goat)
                        break
                    continue

                if self.terrain.is_high_mountain_or_hill(x, z):
                    continue

                temp, _, _ = self.terrain.get_biome_weights(x, z)
                pred_chance = self.get_adaptive_predator_spawn_chance(self.player.level)
                px_cur = self.player.x if hasattr(self, "player") and self.player is not None else 0.0
                pz_cur = self.player.z if hasattr(self, "player") and self.player is not None else 0.0
                dist_to_player = math.hypot(x - px_cur, z - pz_cur)
                want_predator = (dist_to_player >= 10.5) and (dist_origin >= 12.0) and (crng.random() < pred_chance)

                if want_predator and self._can_spawn_predator_at(x, z, self.player.level):
                    if temp < -0.22:
                        kind = "snow_leopard" if crng.random() < 0.72 else crng.choice(["wolf", "bear"])
                    elif temp > 0.15:
                        kind = "tiger"
                    else:
                        kind = crng.choice(["wolf", "tiger", "bear"])
                    lvl = max(1, int(dist_origin / 75.0) + crng.randint(1, 2))
                else:
                    if temp < -0.22 and crng.random() < 0.55:
                        continue
                    kind = crng.choice(["cow", "sheep", "chicken"])
                    lvl = max(1, int(dist_origin / 95.0) + crng.randint(1, 2))

                anim = Animal(self._alloc_id(), kind, x, h, z, level=lvl)
                p_deg, r_deg, arc_y = self.terrain.get_body_tilt_angles(x, z, anim.yaw, 0.62 * anim.scale, 0.30 * anim.scale)
                anim.pitch, anim.roll, anim.y = p_deg, r_deg, arc_y
                self.animals.append(anim)
                break

    def stream_infinite_chunks(self) -> None:
        pcx = int(math.floor(self.player.x / CHUNK_SIZE))
        pcz = int(math.floor(self.player.z / CHUNK_SIZE))
        rad_chunks = self.get_chunk_gen_radius()

        for dx in range(-rad_chunks, rad_chunks + 1):
            for dz in range(-rad_chunks, rad_chunks + 1):
                ncx, ncz = pcx + dx, pcz + dz
                if (ncx, ncz) not in self.terrain.populated_chunks:
                    self._populate_chunk_entities(ncx, ncz)
                    return

    def get_camera_pos(self) -> Tuple[float, float, float]:
        if self.player.in_water:
            bob_offset = math.sin(self.player.swim_stroke) * 0.05
        else:
            bob_offset = math.sin(self.player.walk_bob) * 0.065 if self.player.on_ground else 0.0
        return (self.player.x, self.player.y + self.player.eye_height + bob_offset, self.player.z)

    def get_forward_vector(self) -> Tuple[float, float, float]:
        yaw_rad = math.radians(self.player.yaw)
        pitch_rad = math.radians(self.player.pitch)
        cos_p = math.cos(pitch_rad)
        return (math.sin(yaw_rad) * cos_p, math.sin(pitch_rad), -math.cos(yaw_rad) * cos_p)

    def get_build_preview_transform(self) -> Tuple[float, float, float, float, BuildPieceSpec]:
        spec = BUILD_PIECES[self.selected_build_idx]
        yaw_rad = math.radians(self.player.yaw)
        dist = 4.4
        look_x = self.player.x + math.sin(yaw_rad) * dist
        look_z = self.player.z - math.cos(yaw_rad) * dist

        foundations = [st for st in self.structures if st.piece_id == "foundation"]
        nearest_found: Optional[BuiltStructure] = None
        best_f_dist = 5.5
        for f in foundations:
            d = math.hypot(look_x - f.x, look_z - f.z)
            if d < best_f_dist:
                best_f_dist = d
                nearest_found = f

        if spec.id == "foundation":
            bx = round(look_x / 4.0) * 4.0
            bz = round(look_z / 4.0) * 4.0
            neighbor_y: Optional[float] = None
            for f in foundations:
                if abs(f.x - bx) <= 4.1 and abs(f.z - bz) <= 4.1:
                    neighbor_y = f.y
                    break
            by = neighbor_y if neighbor_y is not None else (self.terrain.get_height(bx, bz) + spec.y_offset)
            return bx, by, bz, 0.0, spec

        if spec.id in ("wall", "window_wall", "doorway", "fence") and nearest_found is not None:
            fx, fy, fz = nearest_found.x, nearest_found.y, nearest_found.z
            dx = look_x - fx
            dz = look_z - fz
            edge_offset = 1.88
            if abs(dx) > abs(dz):
                bx = fx + (edge_offset if dx > 0 else -edge_offset)
                bz = fz
                rot = 90.0
            else:
                bx = fx
                bz = fz + (edge_offset if dz > 0 else -edge_offset)
                rot = 0.0
            by = fy + 0.22 + spec.y_offset
            for st in self.structures:
                if st.piece_id in ("wall", "window_wall", "doorway") and abs(st.x - bx) < 0.4 and abs(st.z - bz) < 0.4 and abs(st.y - by) < 0.5:
                    by += 3.0
            return bx, by, bz, rot, spec

        if spec.id == "roof" and nearest_found is not None:
            bx = nearest_found.x
            bz = nearest_found.z
            by = nearest_found.y + 0.22 + spec.y_offset
            return bx, by, bz, self.build_rotation, spec

        if spec.id == "stairs" and nearest_found is not None:
            fx, fy, fz = nearest_found.x, nearest_found.y, nearest_found.z
            dx = look_x - fx
            dz = look_z - fz
            if abs(dx) > abs(dz):
                bx = fx + (3.1 if dx > 0 else -3.1)
                bz = fz
                rot = 90.0 if dx > 0 else 270.0
            else:
                bx = fx
                bz = fz + (3.1 if dz > 0 else -3.1)
                rot = 0.0 if dz > 0 else 180.0
            by = fy - 0.15
            return bx, by, bz, rot, spec

        snap = 0.5 if spec.id in ("campfire", "bedroll", "chest", "workbench", "chimney_hearth", "torch_stand", "table_chair") else 2.0
        bx = round(look_x / snap) * snap
        bz = round(look_z / snap) * snap
        base_y = self.terrain.get_height(bx, bz)
        for f in foundations:
            if abs(f.x - bx) <= 2.05 and abs(f.z - bz) <= 2.05:
                base_y = max(base_y, f.y + 0.22)
        by = base_y + spec.y_offset
        return bx, by, bz, self.build_rotation, spec

    def remove_last_or_hovered_structure(self) -> None:
        target = self.hovered_structure
        if target is None and self.structures:
            target = self.structures[-1]
        if target is None:
            self.add_notification("Нет построек для разбора!", 2.5, (255, 160, 120))
            return
        if target in self.structures:
            self.structures.remove(target)
        self.player.inventory["wood"] += 2
        self.sound.play("build")
        self.add_notification(f"Разобрана постройка '{target.name}' (возвращено +2 Дерева).", 3.0, (255, 215, 120))

    def _update_crosshair_target(self) -> None:
        cx, cy, cz = self.get_camera_pos()
        fx, fy, fz = self.get_forward_vector()
        weapon = WEAPONS_DB.get(self.player.equipped_weapon, WEAPONS_DB["rock"])
        max_dist = max(6.5, weapon.reach + 1.0)

        best_dist = max_dist
        self.hovered_animal = None
        self.hovered_resource = None
        self.hovered_structure = None
        self.hovered_target_text = ""

        for anim in self.animals:
            if not anim.alive:
                continue
            dx = anim.x - cx
            dz = anim.z - cz
            if abs(dx) > max_dist or abs(dz) > max_dist:
                continue
            dy = (anim.y + 0.7 * anim.scale) - cy
            proj = dx * fx + dy * fy + dz * fz
            if 0.4 < proj < best_dist:
                perp_sq = (dx * dx + dy * dy + dz * dz) - proj * proj
                hit_r = anim.radius + 0.50
                if perp_sq <= hit_r * hit_r:
                    best_dist = proj
                    self.hovered_animal = anim

        if self.hovered_animal is not None:
            a = self.hovered_animal
            if a.aquatic:
                tag = "Водная фауна — ловите удочкой или копьем"
            elif a.mountain_mid_only:
                tag = "Обитатель вершин узких гор"
            else:
                tag = "ХИЩНИК" if a.hostile else "Мирное"
            self.hovered_target_text = f"{a.name} [Ур. {a.level} | {tag}] — HP: {int(a.hp)}/{int(a.max_hp)}"
            return

        for res in self.get_nearby_resources(cx, cz, cell_radius=1):
            if not res.alive or res.kind == "grass_tuft":
                continue
            dx = res.x - cx
            dy = (res.y + 1.2 * res.scale) - cy
            dz = res.z - cz
            proj = dx * fx + dy * fy + dz * fz
            if 0.4 < proj < best_dist:
                perp_sq = (dx * dx + dy * dy + dz * dz) - proj * proj
                hit_r = res.radius + 0.55
                if perp_sq <= hit_r * hit_r:
                    best_dist = proj
                    self.hovered_resource = res

        if self.hovered_resource is not None:
            r = self.hovered_resource
            if r.kind in ("berry_bush", "mushroom_patch"):
                self.hovered_target_text = f"{r.name}"
            elif r.kind == "cave_grotto":
                self.hovered_target_text = f"{r.name} (Залежи руд)"
            else:
                self.hovered_target_text = f"{r.name} — Прочность: {int(r.hp)}/{int(r.max_hp)}"
            return

        # Интерактивные объекты (включая Стол мастерской 'workbench', кровать, сундук, костер и дверь!)
        interactive_ids = ("workbench", "bedroll", "chest", "campfire", "chimney_hearth", "doorway")
        best_inter_score = 999.0
        best_inter_st: Optional[BuiltStructure] = None
        best_any_score = 999.0
        best_any_st: Optional[BuiltStructure] = None

        for st in self.structures:
            dx = st.x - cx
            dy = (st.y + 0.15) - cy
            dz = st.z - cz
            proj = dx * fx + dy * fy + dz * fz
            if 0.2 < proj < 6.0:
                perp_sq = max(0.0, (dx * dx + dy * dy + dz * dz) - proj * proj)
                hit_r = 2.35 if st.piece_id in interactive_ids else 2.15
                if perp_sq <= hit_r * hit_r:
                    score = perp_sq + proj * 0.15
                    if st.piece_id in interactive_ids:
                        if score < best_inter_score:
                            best_inter_score = score
                            best_inter_st = st
                    elif self.build_mode or self.player.equipped_weapon == "hammer":
                        if score < best_any_score:
                            best_any_score = score
                            best_any_st = st

        self.hovered_structure = best_inter_st if best_inter_st is not None else best_any_st
        if self.hovered_structure is not None:
            st = self.hovered_structure
            if st.piece_id == "workbench":
                self.hovered_target_text = "Стол мастерской (Верстак для крафта)"
            elif st.piece_id in ("campfire", "chimney_hearth"):
                self.hovered_target_text = st.name
            elif st.piece_id == "doorway":
                state_str = "Открыта" if st.door_open else "Закрыта"
                self.hovered_target_text = f"Дверь дома ({state_str})"
            elif st.piece_id == "bedroll":
                self.hovered_target_text = "Деревянная кровать"
            elif st.piece_id == "chest":
                cnt = sum(st.storage.values())
                self.hovered_target_text = f"{st.name} (Предметов: {cnt})"
            else:
                self.hovered_target_text = f"{st.name}"
            return

        # Если рядом на земле лежат выброшенные или потерянные при смерти предметы — показываем таймер до исчезновения!
        best_d_item: Optional[DroppedItem3D] = None
        best_d_dist = 3.6
        for ditem in self.dropped_items:
            d_it = math.hypot(ditem.x - self.player.x, ditem.z - self.player.z)
            if d_it < best_d_dist:
                best_d_dist = d_it
                best_d_item = ditem
        if best_d_item is not None:
            n_ru = WEAPONS_DB[best_d_item.item_id].name if best_d_item.item_id in WEAPONS_DB else RESOURCE_NAMES_RU.get(best_d_item.item_id, best_d_item.item_id)
            rem_s = max(0, int(math.ceil(best_d_item.despawn_timer)))
            mm_d, ss_d = divmod(rem_s, 60)
            self.hovered_target_text = f"На земле: {n_ru} (x{best_d_item.count}) [Исчезнет через {mm_d:02d}:{ss_d:02d} — нажмите F]"

    def spawn_particles(
        self,
        x: float,
        y: float,
        z: float,
        color: Tuple[float, float, float],
        count: int = 8,
        speed: float = 4.0,
    ) -> None:
        mult = GRAPHICS_PROFILES[self.graphics_profile_idx]["particles_mult"]
        actual_count = max(2, int(count * mult))
        for _ in range(actual_count):
            self.particles.append(
                Particle3D(
                    x=x + self.rng.uniform(-0.2, 0.2),
                    y=y + self.rng.uniform(-0.1, 0.3),
                    z=z + self.rng.uniform(-0.2, 0.2),
                    vx=self.rng.uniform(-speed, speed),
                    vy=self.rng.uniform(1.2, speed * 1.1),
                    vz=self.rng.uniform(-speed, speed),
                    color=color,
                    size=self.rng.uniform(0.08, 0.18),
                    ttl=self.rng.uniform(0.30, 0.65),
                )
            )

    def perform_primary_action(self) -> None:
        # 1. Если игрок смотрит прямо на установленный Стол мастерской (workbench) — ЛКМ открывает Крафт!
        if self.hovered_structure is not None and self.hovered_structure.piece_id == "workbench" and not self.build_mode:
            self.show_crafting = True
            self.show_inventory = False
            self.show_skills = False
            self.sound.play("build")
            return

        # 2. Если в руках Стол мастерской (workbench_item) — ЛКМ устанавливает его на землю!
        active_slot_item = self.player.hotbar[self.player.active_hotbar_slot]
        if self.player.equipped_weapon == "workbench_item" or active_slot_item == "workbench_item":
            self.place_workbench_from_hand()
            return

        # 3. Если в активном слоте хотбара находится еда или целебный бальзам — ЛКМ употребляет его!
        if active_slot_item is not None and active_slot_item not in WEAPONS_DB:
            self.consume_specific_item(active_slot_item)
            return

        if self.build_mode or self.player.equipped_weapon == "hammer":
            if not self.has_placed_workbench():
                self.add_notification(
                    "Строительство недоступно! Сначала добудьте 2 дерева камнем, создайте Стол мастерской в инвентаре и поставьте его!",
                    3.8,
                    (255, 135, 110),
                )
                return
            self.try_place_building()
            return

        if self.player.attack_timer > 0.0:
            return

        weapon = WEAPONS_DB.get(self.player.equipped_weapon, WEAPONS_DB["rock"])
        if self.player.stamina < weapon.stamina_cost:
            self.add_notification("Недостаточно выносливости для удара!", 2.0, (255, 120, 100))
            return

        self.player.stamina = max(0.0, self.player.stamina - weapon.stamina_cost)
        self.player.attack_timer = weapon.cooldown
        self.player.swing_anim = 1.0

        if weapon.category == "fishing":
            self.toggle_fishing_cast()
            return

        if weapon.category == "bow":
            if self.player.inventory.get("arrow", 0) <= 0:
                self.add_notification("Нет стрел! Скрафтите стрелы на Столе мастерской.", 2.5, (255, 150, 90))
                return
            self.player.inventory["arrow"] -= 1
            self.player.bow_pull_anim = 1.0
            cx, cy, cz = self.get_camera_pos()
            fx, fy, fz = self.get_forward_vector()
            arrow_speed = 40.0
            dmg = weapon.damage * (1.0 + (self.player.skills["hunter"] - 1) * 0.20)
            self.arrows.append(
                ArrowProjectile(
                    x=cx + fx * 0.8,
                    y=cy - 0.12 + fy * 0.8,
                    z=cz + fz * 0.8,
                    vx=fx * arrow_speed,
                    vy=fy * arrow_speed + 1.1,
                    vz=fz * arrow_speed,
                    damage=dmg,
                )
            )
            self.sound.play("bow")
            broke_msg = self.player.damage_active_tool(1.2)
            if broke_msg:
                self.add_notification(broke_msg, 3.5, (255, 115, 95))
            return

        self.sound.play("swing")
        cx, cy, cz = self.get_camera_pos()
        fx, fy, fz = self.get_forward_vector()

        hit_animal: Optional[Animal] = None
        best_dist = weapon.reach
        for anim in self.animals:
            if not anim.alive:
                continue
            dx = anim.x - cx
            dz = anim.z - cz
            if abs(dx) > best_dist + 2.0 or abs(dz) > best_dist + 2.0:
                continue
            dy = (anim.y + 0.7 * anim.scale) - cy
            proj = dx * fx + dy * fy + dz * fz
            if 0.2 < proj <= best_dist:
                perp_sq = (dx * dx + dy * dy + dz * dz) - proj * proj
                hit_r = anim.radius + 0.70
                if perp_sq <= hit_r * hit_r:
                    best_dist = proj
                    hit_animal = anim

        if hit_animal is not None:
            self._damage_animal(hit_animal, weapon.damage * self.player.melee_damage_multiplier)
            broke_msg = self.player.damage_active_tool(1.2)
            if broke_msg:
                self.add_notification(broke_msg, 3.5, (255, 115, 95))
            return

        hit_res: Optional[ResourceNode] = None
        best_res_dist = weapon.reach + 0.5
        for res in self.get_nearby_resources(cx, cz, cell_radius=1):
            if not res.alive or res.kind in ("cave_grotto", "grass_tuft"):
                continue
            dx = res.x - cx
            dy = (res.y + 1.1 * res.scale) - cy
            dz = res.z - cz
            proj = dx * fx + dy * fy + dz * fz
            if 0.2 < proj <= best_res_dist:
                perp_sq = (dx * dx + dy * dy + dz * dz) - proj * proj
                hit_r = res.radius + 0.68
                if perp_sq <= hit_r * hit_r:
                    best_res_dist = proj
                    hit_res = res

        if hit_res is not None:
            self._harvest_resource(hit_res, weapon)
            broke_msg = self.player.damage_active_tool(1.0)
            if broke_msg:
                self.add_notification(broke_msg, 3.5, (255, 115, 95))

    def _damage_animal(self, anim: Animal, base_dmg: float, is_ranged: bool = False) -> None:
        is_crit = self.rng.random() < self.player.crit_chance
        dmg = base_dmg * (1.85 if is_crit else 1.0)
        anim.hp -= dmg
        anim.hurt_flash = 0.35
        self.spawn_particles(anim.x, anim.y + 0.6 * anim.scale, anim.z, (0.85, 0.12, 0.12), count=10, speed=4.5)

        if anim.hostile:
            anim.state = "chase"
            self.sound.play("growl")
        else:
            anim.state = "flee"
            anim.state_timer = 6.0
            anim.yaw = math.degrees(math.atan2(anim.x - self.player.x, -(anim.z - self.player.z)))

        if anim.hp <= 0.0:
            anim.hp = 0.0
            anim.respawn_timer = 50.0
            self.player.stats_animals_hunted += 1
            if anim.hostile:
                self.player.stats_predators_slain += 1
            loot_parts: List[str] = []
            for item_key, (mn, mx) in anim.drops.items():
                cnt = self.rng.randint(mn, mx)
                if self.rng.random() < (self.player.skills["harvesting"] - 1) * 0.18:
                    cnt += 1
                self.player.inventory[item_key] = self.player.inventory.get(item_key, 0) + cnt
                loot_parts.append(f"{RESOURCE_NAMES_RU.get(item_key, item_key)} +{cnt}")
            xp_msgs = self.player.gain_xp(anim.xp_reward)
            self.add_notification(
                f"Добыт '{anim.name}'! Получено: {', '.join(loot_parts)} (+{anim.xp_reward} XP)",
                4.5,
                (140, 255, 160),
            )
            for m in xp_msgs:
                self.sound.play("levelup")
                self.add_notification(m, 6.0, (255, 220, 90))
        else:
            crit_str = " (КРИТ!)" if is_crit else ""
            self.add_notification(
                f"Удар по '{anim.name}': -{int(dmg)} HP{crit_str} (осталось {int(anim.hp)} HP)",
                2.2,
                (255, 195, 130),
            )

    def _harvest_resource(self, res: ResourceNode, weapon: WeaponSpec) -> None:
        if res.kind in ("cave_grotto", "grass_tuft"):
            return
        res.hit_shake = 0.28
        if res not in self.shaking_resources:
            self.shaking_resources.append(res)
        if res.kind in ("pine", "snow_pine", "oak", "birch", "autumn_oak", "apple_tree"):
            dmg = 22.0 * weapon.tree_mult * self.player.harvest_multiplier
            self.sound.play("chop")
            self.spawn_particles(res.x, res.y + 1.3, res.z, (0.62, 0.44, 0.24), count=8, speed=3.5)
        elif res.kind in ("berry_bush", "wild_bush", "mushroom_patch"):
            dmg = 35.0
            self.sound.play("chop")
            self.spawn_particles(res.x, res.y + 0.5, res.z, (0.85, 0.22, 0.25), count=7, speed=3.0)
        else:
            dmg = 22.0 * weapon.rock_mult * self.player.harvest_multiplier
            self.sound.play("mine")
            self.spawn_particles(res.x, res.y + 0.9, res.z, (0.68, 0.75, 0.85), count=8, speed=3.8)

        res.hp -= dmg
        if res.hp <= 0.0:
            res.hp = 0.0
            res.respawn_timer = 65.0
            self._mark_chunk_props_dirty(res.x, res.z)
            bonus = 1 if self.rng.random() < (self.player.skills["harvesting"] - 1) * 0.25 else 0
            if res.kind in ("pine", "snow_pine", "oak", "birch", "autumn_oak", "apple_tree"):
                wood_gain = self.rng.randint(2, 4) + (2 if weapon.category == "axe" else 0) + bonus
                self.player.inventory["wood"] += wood_gain
                self.player.stats_trees_cut += 1
                xp_gain = 22
                extra = ""
                if res.kind == "apple_tree":
                    app = self.rng.randint(2, 3)
                    self.player.inventory["apple"] += app
                    extra = f", Лесные яблоки +{app}"
                if not self.has_placed_workbench() and self.player.inventory["wood"] >= 2:
                    extra += " (Достаточно дерева для создания Стола мастерской в инвентаре!)"
                msg = f"Срублено '{res.name}': Дерево +{wood_gain}{extra} (+{xp_gain} XP)"
            elif res.kind in ("berry_bush", "wild_bush"):
                berry_gain = self.rng.randint(2, 4) + bonus
                self.player.inventory["berries"] += berry_gain
                if res.kind == "wild_bush":
                    self.player.inventory["wood"] += 1
                xp_gain = 14
                msg = f"Собран кустарник: Ягоды +{berry_gain} (+{xp_gain} XP)"
            elif res.kind == "mushroom_patch":
                mush_gain = self.rng.randint(2, 4) + bonus
                self.player.inventory["mushroom"] += mush_gain
                xp_gain = 16
                msg = f"Собраны белые лесные грибы: +{mush_gain} шт. (+{xp_gain} XP)"
            elif res.kind == "coal_vein":
                c_gain = self.rng.randint(2, 4) + bonus
                self.player.inventory["coal"] += c_gain
                self.player.inventory["stone"] += 2
                xp_gain = 28
                msg = f"Добыт уголь: Уголь +{c_gain}, Камень +2 (+{xp_gain} XP)"
            elif res.kind == "copper_vein":
                cop_gain = self.rng.randint(2, 4) + bonus
                self.player.inventory["copper"] += cop_gain
                self.player.inventory["stone"] += 2
                xp_gain = 32
                msg = f"Добыта медная руда: Медь +{cop_gain}, Камень +2 (+{xp_gain} XP)"
            elif res.kind == "iron_vein":
                iron_gain = self.rng.randint(2, 4) + (2 if weapon.id == "stone_pickaxe" else 0) + bonus
                self.player.inventory["iron"] += iron_gain
                self.player.inventory["stone"] += 2
                xp_gain = 38
                msg = f"Добыта железная руда: Железо +{iron_gain}, Камень +2 (+{xp_gain} XP)"
            elif res.kind == "gold_vein":
                g_gain = self.rng.randint(2, 3) + bonus
                self.player.inventory["gold"] += g_gain
                xp_gain = 55
                msg = f"Добыта золотая руда: Золото +{g_gain} (+{xp_gain} XP)"
            elif res.kind == "mythril_vein":
                m_gain = self.rng.randint(2, 3) + bonus
                self.player.inventory["mythril"] += m_gain
                xp_gain = 75
                msg = f"Добыт ледяной мифрил: Мифрил +{m_gain}! (+{xp_gain} XP)"
            else:
                stone_gain = self.rng.randint(3, 5) + bonus
                self.player.inventory["stone"] += stone_gain
                xp_gain = 20
                msg = f"Расколот валун: Камень +{stone_gain} (+{xp_gain} XP)"

            self.add_notification(msg, 4.2, (165, 245, 175))
            for lvl_msg in self.player.gain_xp(xp_gain):
                self.sound.play("levelup")
                self.add_notification(lvl_msg, 6.0, (255, 220, 90))

    def can_craft(self, recipe: CraftingRecipe) -> bool:
        for item_key, req_cnt in recipe.cost.items():
            if self.player.inventory.get(item_key, 0) < req_cnt:
                return False
        return True

    def craft_recipe(self, recipe_idx: int) -> bool:
        if not self.has_placed_workbench():
            self.add_notification("Для крафта нужен установленный Стол мастерской!", 3.2, (255, 130, 110))
            return False
        if not (0 <= recipe_idx < len(CRAFTING_RECIPES)):
            return False
        recipe = CRAFTING_RECIPES[recipe_idx]
        if not self.can_craft(recipe):
            missing = [
                f"{RESOURCE_NAMES_RU.get(k, k)} ({self.player.inventory.get(k, 0)}/{v})"
                for k, v in recipe.cost.items()
                if self.player.inventory.get(k, 0) < v
            ]
            self.add_notification(f"Не хватает ресурсов: {', '.join(missing)}", 3.2, (255, 130, 110))
            return False

        for item_key, req_cnt in recipe.cost.items():
            self.player.inventory[item_key] -= req_cnt

        if recipe.unlock_weapon is not None:
            self.player.unlocked_weapons.add(recipe.unlock_weapon)
            self.put_in_hotbar(recipe.unlock_weapon)
            self.player.equipped_weapon = recipe.unlock_weapon
        if recipe.result_item not in WEAPONS_DB or recipe.result_item == "arrow":
            self.player.inventory[recipe.result_item] = (
                self.player.inventory.get(recipe.result_item, 0) + recipe.result_count
            )

        self.sound.play("build")
        self.add_notification(f"Скрафчено на Столе: {recipe.name}! (+{recipe.xp_reward} XP)", 4.2, (130, 255, 190))
        for lvl_msg in self.player.gain_xp(recipe.xp_reward):
            self.sound.play("levelup")
            self.add_notification(lvl_msg, 6.0, (255, 220, 90))
        return True

    def can_build_piece(self, spec: BuildPieceSpec) -> bool:
        for item_key, req_cnt in spec.cost.items():
            if self.player.inventory.get(item_key, 0) < req_cnt:
                return False
        return True

    def try_place_building(self) -> bool:
        spec = BUILD_PIECES[self.selected_build_idx]
        if not self.has_placed_workbench() and spec.id != "workbench":
            self.add_notification(
                "Строительство закрыто! Сначала создайте Стол мастерской в инвентаре за 2 дерева и поставьте его!",
                3.8,
                (255, 140, 110),
            )
            return False
        bx, by, bz, rot, spec = self.get_build_preview_transform()
        if not self.can_build_piece(spec):
            missing = [
                f"{RESOURCE_NAMES_RU.get(k, k)} ({self.player.inventory.get(k, 0)}/{v})"
                for k, v in spec.cost.items()
                if self.player.inventory.get(k, 0) < v
            ]
            self.add_notification(f"Для постройки '{spec.name}' нужно: {', '.join(missing)}", 3.2, (255, 140, 110))
            return False

        for item_key, req_cnt in spec.cost.items():
            self.player.inventory[item_key] -= req_cnt

        st = BuiltStructure(
            id=self._alloc_id(),
            piece_id=spec.id,
            name=spec.name,
            x=bx,
            y=by,
            z=bz,
            rotation=rot,
            size=spec.size,
            is_solid=spec.is_solid,
            is_roof=spec.is_roof,
        )
        self.structures.append(st)
        self.player.stats_blocks_built += 1
        if spec.id == "bedroll":
            self.player.spawn_point = (bx, by + 0.5, bz)

        self.sound.play("build")
        self.spawn_particles(bx, by, bz, (0.78, 0.62, 0.36), count=10, speed=3.2)
        self.add_notification(f"Построено: {spec.name}! (+{spec.xp_reward} XP)", 3.5, (150, 240, 255))
        for lvl_msg in self.player.gain_xp(spec.xp_reward):
            self.sound.play("levelup")
            self.add_notification(lvl_msg, 6.0, (255, 220, 90))
        return True

    def toggle_fishing_cast(self) -> None:
        if self.bobber is not None:
            if self.bobber.biting:
                self.sound.play("heal")
                self.spawn_particles(self.bobber.x, WATER_LEVEL + 0.2, self.bobber.z, (0.4, 0.85, 1.0), count=12, speed=4.0)
                r = self.rng.random()
                if r < 0.72:
                    cnt = self.rng.randint(1, 2)
                    self.player.inventory["raw_fish"] = self.player.inventory.get("raw_fish", 0) + cnt
                    xp_gain = 35
                    self.add_notification(f"УЛОВ! Вы вытянули крупную Озерную Форель (+{cnt} Сырая рыба, +{xp_gain} XP)!", 4.2, (120, 255, 180))
                elif r < 0.90:
                    self.player.inventory["raw_fish"] = self.player.inventory.get("raw_fish", 0) + 2
                    self.player.inventory["cooked_fish"] = self.player.inventory.get("cooked_fish", 0) + 1
                    xp_gain = 50
                    self.add_notification("РЕДКИЙ УЛОВ! Королевский лосось (+2 Сырая рыба, +50 XP)!", 4.5, (120, 245, 255))
                else:
                    self.player.inventory["gold"] = self.player.inventory.get("gold", 0) + 2
                    self.player.inventory["raw_fish"] = self.player.inventory.get("raw_fish", 0) + 1
                    xp_gain = 70
                    self.add_notification("СОКРОВИЩЕ СО ДНА! Золотой карп и +2 Золотой руды (+70 XP)!", 4.8, (255, 225, 95))
                for m in self.player.gain_xp(xp_gain):
                    self.sound.play("levelup")
                    self.add_notification(m, 5.5, (255, 220, 90))
            else:
                self.add_notification("Вы смотали удочку раньше времени (дождитесь клева поплавка!).", 2.8, (220, 220, 220))
            self.bobber = None
            return

        cx, cy, cz = self.get_camera_pos()
        fx, fy, fz = self.get_forward_vector()
        self.bobber = FishingBobber(
            x=cx + fx * 1.2,
            y=cy - 0.1 + fy * 1.2,
            z=cz + fz * 1.2,
            vx=fx * 14.5,
            vy=max(2.5, fy * 12.0 + 3.8),
            vz=fz * 14.5,
            in_water=False,
            bite_timer=self.rng.uniform(1.8, 3.2),
            biting=False,
            bite_window=0.0,
        )
        self.sound.play("swing")
        self.add_notification("Поплавок заброшен! Дождитесь клева, чтобы подсечь рыбу!", 3.8, (145, 235, 255))

    def transfer_chest_item(
        self,
        to_chest: bool,
        item_key: Optional[str] = None,
        inv_slot_idx: Optional[int] = None,
        chest_slot_idx: Optional[int] = None,
    ) -> bool:
        """Переносит предмет между 25 ячейками Инвентаря и 15 ячейками Сундука."""
        if self.active_chest is None:
            return False
        if to_chest:
            src_i = inv_slot_idx if inv_slot_idx is not None else self.selected_inv_idx
            if not (0 <= src_i < MAX_INVENTORY_SLOTS) or self.player.slots[src_i] is None:
                if item_key is not None:
                    src_i = next(
                        (i for i in range(MAX_INVENTORY_SLOTS) if self.player.slots[i] is not None and self.player.slots[i].get("item") == item_key),
                        -1,
                    )
                else:
                    return False
            if src_i < 0 or self.player.slots[src_i] is None:
                return False
            sl = self.player.slots[src_i]
            k = str(sl["item"])
            cnt = int(sl.get("count", 1))
            # Ищем стек того же предмета в сундуке или свободную ячейку сундука
            target_c = chest_slot_idx
            if target_c is None:
                target_c = next(
                    (ci for ci in range(MAX_CHEST_SLOTS) if self.active_chest.chest_slots[ci] is not None and self.active_chest.chest_slots[ci].get("item") == k),
                    None,
                )
            if target_c is None:
                target_c = next((ci for ci in range(MAX_CHEST_SLOTS) if self.active_chest.chest_slots[ci] is None), None)
            if target_c is None:
                self.add_notification("Сундук полон!", 2.5, (255, 150, 120))
                return False
            return self.move_or_swap_slots(("inv", src_i), ("chest", target_c))
        else:
            src_c = chest_slot_idx
            if src_c is None and item_key is not None:
                src_c = next(
                    (ci for ci in range(MAX_CHEST_SLOTS) if self.active_chest.chest_slots[ci] is not None and self.active_chest.chest_slots[ci].get("item") == item_key),
                    None,
                )
            if src_c is None:
                src_c = next((ci for ci in range(MAX_CHEST_SLOTS) if self.active_chest.chest_slots[ci] is not None), None)
            if src_c is None or not (0 <= src_c < MAX_CHEST_SLOTS) or self.active_chest.chest_slots[src_c] is None:
                return False
            csl = self.active_chest.chest_slots[src_c]
            k = str(csl["item"])
            target_i = inv_slot_idx
            if target_i is None:
                target_i = next(
                    (i for i in range(MAX_INVENTORY_SLOTS) if self.player.slots[i] is not None and self.player.slots[i].get("item") == k and k not in WEAPONS_DB),
                    None,
                )
            if target_i is None:
                target_i = next((i for i in range(MAX_INVENTORY_SLOTS) if self.player.slots[i] is None), None)
            if target_i is None:
                self.add_notification("Все 25 ячеек инвентаря заняты!", 2.5, (255, 150, 120))
                return False
            return self.move_or_swap_slots(("chest", src_c), ("inv", target_i))

    def interact_world(self) -> None:
        if self.bobber is not None:
            self.toggle_fishing_cast()
            return

        # Подбор сброшенных на землю (или оставшихся на месте смерти) предметов по клавише [F]
        picked_summary: List[str] = []
        for ditem in list(self.dropped_items):
            if math.hypot(ditem.x - self.player.x, ditem.z - self.player.z) <= 3.6:
                if ditem.item_id in WEAPONS_DB and ditem.item_id != "workbench_item":
                    self.player.unlocked_weapons.add(ditem.item_id)
                if self.player.add_item_to_slots(ditem.item_id, ditem.count):
                    self.dropped_items.remove(ditem)
                    n_ru = WEAPONS_DB[ditem.item_id].name if ditem.item_id in WEAPONS_DB else RESOURCE_NAMES_RU.get(ditem.item_id, ditem.item_id)
                    picked_summary.append(f"{n_ru} (x{ditem.count})")
        if picked_summary:
            self.sound.play("build")
            if not any(d.is_death_drop for d in self.dropped_items):
                self.last_death_pos = None
                self.last_death_timer = 0.0
            shown = ", ".join(picked_summary[:4])
            if len(picked_summary) > 4:
                shown += f" и еще {len(picked_summary) - 4} предм."
            self.add_notification(f"Подобрано с земли: {shown}", 3.2, (150, 255, 185))
            return

        if self.hovered_resource is not None and self.hovered_resource.kind in ("berry_bush", "mushroom_patch"):
            self._harvest_resource(self.hovered_resource, WEAPONS_DB.get(self.player.equipped_weapon, WEAPONS_DB["rock"]))
            return

        interactive_ids = ("workbench", "bedroll", "chest", "campfire", "chimney_hearth", "doorway")
        target_st: Optional[BuiltStructure] = None
        if self.hovered_structure is not None and self.hovered_structure.piece_id in interactive_ids:
            target_st = self.hovered_structure
        else:
            best_d = 4.5
            for st in self.structures:
                if st.piece_id in interactive_ids:
                    d = math.hypot(st.x - self.player.x, st.z - self.player.z)
                    if d < best_d:
                        best_d = d
                        target_st = st

        if target_st is not None:
            if target_st.piece_id == "workbench":
                self.show_crafting = True
                self.show_inventory = False
                self.show_skills = False
                self.sound.play("build")
                self.add_notification("Открыт Стол мастерской: выберите рецепт мышью или стрелками!", 3.2, (150, 255, 195))
                return
            if target_st.piece_id == "doorway":
                target_st.door_open = not target_st.door_open
                self.sound.play("build")
                state = "открыта" if target_st.door_open else "закрыта"
                self.add_notification(f"Дверь дома {state}.", 2.2, (220, 240, 255))
                return
            if target_st.piece_id == "chest":
                self.active_chest = target_st
                target_st.door_open = True
                self.show_inventory = True
                self.show_crafting = False
                self.show_skills = False
                self.sound.play("build")
                self.add_notification(
                    f"Открыт '{target_st.name}': перетаскивайте предметы мышью или стрелками!",
                    4.0,
                    (255, 225, 120),
                )
                return
            if target_st.piece_id in ("campfire", "chimney_hearth"):
                if self.player.inventory.get("raw_fish", 0) > 0:
                    self.player.inventory["raw_fish"] -= 1
                    self.player.inventory["cooked_fish"] = self.player.inventory.get("cooked_fish", 0) + 1
                    self.player.stats_meat_cooked += 1
                    self.sound.play("heal")
                    self.spawn_particles(target_st.x, target_st.y + 0.5, target_st.z, (1.0, 0.65, 0.15), count=10)
                    self.add_notification(
                        "Вы запекли речную форель на углях костра! (+25 XP)",
                        3.8,
                        (140, 245, 255),
                    )
                    self.player.gain_xp(25)
                elif self.player.inventory.get("raw_meat", 0) > 0:
                    self.player.inventory["raw_meat"] -= 1
                    self.player.inventory["cooked_meat"] = self.player.inventory.get("cooked_meat", 0) + 1
                    self.player.stats_meat_cooked += 1
                    self.sound.play("heal")
                    self.spawn_particles(target_st.x, target_st.y + 0.5, target_st.z, (1.0, 0.65, 0.15), count=10)
                    self.add_notification(
                        "Вы поджарили сочный стейк на костре! (+25 XP)",
                        3.8,
                        (255, 210, 120),
                    )
                    self.player.gain_xp(25)
                else:
                    self.add_notification(
                        "У вас нет сырой рыбы или мяса! Наловите рыбу в озере/реке или добудьте зверя.",
                        3.2,
                        (255, 175, 120),
                    )
                return
            if target_st.piece_id == "bedroll":
                self.player.spawn_point = (target_st.x, target_st.y + 0.5, target_st.z)
                self.player.hp = self.player.max_hp
                self.player.stamina = self.player.max_stamina
                self.player.warmth = 100.0
                if self.time_of_day >= 19.5 or self.time_of_day < 5.5:
                    self.time_of_day = 7.0
                    self.day_number += 1
                    self.add_notification("Вы выспались на мягкой кровати до утра! Силы восстановлены.", 4.5, (160, 255, 190))
                else:
                    self.add_notification("Точка дома сохранена на кровати! Здоровье и бодрость восстановлены.", 3.5, (160, 255, 190))
                self.sound.play("heal")
                return

        if self.player.in_water or self.terrain.get_height(self.player.x, self.player.z) < BEACH_LEVEL + 0.6:
            self.player.thirst = min(100.0, self.player.thirst + 45.0)
            self.sound.play("heal")
            self.add_notification("Вы напились чистой воды из реки/озера (+45 Жажда).", 3.0, (130, 220, 255))
            return

        self.add_notification("Рядом нет Стола мастерской, костра, кровати, сундука или воды для взаимодействия.", 2.5, (210, 210, 210))

    def consume_specific_item(self, key: str) -> bool:
        """Употребляет конкретный предмет еды/бальзама или надевает предмет брони в 4 вертикальные ячейки экипировки."""
        if key in ITEM_TO_ARMOR_SLOT_IDX:
            if self.player.equip_armor_item(key):
                self.sound.play("build")
                self.add_notification(f"Экипировано: {RESOURCE_NAMES_RU.get(key, key)} (Защита: {int(self.player.armor_reduction * 100)}%)", 3.0, (145, 245, 255))
                return True
        inv = self.player.inventory
        if inv.get(key, 0) <= 0:
            return False
        if key == "salve":
            inv["salve"] -= 1
            self.player.hp = min(self.player.max_hp, self.player.hp + 50.0)
            self.sound.play("heal")
            self.add_notification("Использован целебный бальзам (+50 Здоровья)!", 3.0, (140, 255, 160))
            return True
        if key == "hunter_stew":
            inv["hunter_stew"] -= 1
            self.player.hunger = min(100.0, self.player.hunger + 70.0)
            self.player.thirst = min(100.0, self.player.thirst + 30.0)
            self.player.warmth = min(100.0, self.player.warmth + 50.0)
            self.player.hp = min(self.player.max_hp, self.player.hp + 45.0)
            self.sound.play("heal")
            self.add_notification("Вы съели Жаркое охотника (+70 Сытость, +45 HP, +50 Тепло)!", 3.5, (255, 220, 110))
            return True
        if key == "cooked_fish":
            inv["cooked_fish"] -= 1
            self.player.hunger = min(100.0, self.player.hunger + 42.0)
            self.player.hp = min(self.player.max_hp, self.player.hp + 25.0)
            self.player.stamina = min(self.player.max_stamina, self.player.stamina + 40.0)
            self.sound.play("heal")
            self.add_notification("Вы съели запеченную форель (+42 Сытость, +25 HP)!", 3.0, (140, 240, 255))
            return True
        if key == "cooked_meat":
            inv["cooked_meat"] -= 1
            self.player.hunger = min(100.0, self.player.hunger + 45.0)
            self.player.hp = min(self.player.max_hp, self.player.hp + 28.0)
            self.sound.play("heal")
            self.add_notification("Вы съели горячий жареный стейк (+45 Сытость, +28 HP)!", 3.0, (255, 215, 120))
            return True
        if key in ("apple", "berries", "mushroom", "raw_fish", "raw_meat"):
            inv[key] -= 1
            self.player.hunger = min(100.0, self.player.hunger + 20.0)
            self.player.thirst = min(100.0, self.player.thirst + 15.0)
            self.player.hp = min(self.player.max_hp, self.player.hp + 8.0)
            self.sound.play("heal")
            self.add_notification(f"Употреблено: {RESOURCE_NAMES_RU.get(key, key)} (+20 Сытость, +8 HP).", 2.5, (220, 245, 180))
            return True
        return False

    def consume_food_or_heal(self) -> None:
        inv = self.player.inventory
        for k in ("salve", "hunter_stew", "cooked_fish", "cooked_meat", "apple", "berries", "mushroom", "raw_fish", "raw_meat"):
            if k == "salve" and self.player.hp >= self.player.max_hp * 0.65:
                continue
            if inv.get(k, 0) > 0 and self.consume_specific_item(k):
                return
        if inv.get("salve", 0) > 0 and self.consume_specific_item("salve"):
            return
        self.add_notification("В рюкзаке нет еды или бальзама! Соберите ягоды, грибы, яблоки или рыбу.", 3.0, (255, 140, 120))

    def update(self, dt: float, move_forward: float, move_right: float, jump: bool, sprint: bool, dive: bool = False) -> None:
        if self.paused:
            return
        real_dt = max(0.0, float(dt))
        dt = min(real_dt, 0.08)
        self.anim_clock += dt

        self.time_of_day += dt * (24.0 / 600.0)
        if self.clouds_enabled:
            # Облака плывут по небу в мировых координатах по ветру (+3.5 м/с по X, +0.9 м/с по Z) НЕЗАВИСИМО от движения игрока!
            span = 520.0
            half_span = 260.0
            anchor_x = round(self.player.x / span) * span
            anchor_z = round(self.player.z / span) * span
            new_clouds = []
            for cx_c, cy_c, cz_c, sx_c, sz_c in self.clouds:
                nx_c = anchor_x + ((cx_c + dt * 3.5 - anchor_x + half_span) % span) - half_span
                nz_c = anchor_z + ((cz_c + dt * 0.9 - anchor_z + half_span) % span) - half_span
                new_clouds.append((nx_c, cy_c, nz_c, sx_c, sz_c))
            self.clouds = new_clouds
        if self.time_of_day >= 24.0:
            self.time_of_day -= 24.0
            self.day_number += 1
            self.add_notification(f"Наступил День {self.day_number} выживания! (+50 XP)", 5.0, (255, 230, 120))
            self.player.gain_xp(50)

        self.notifications = [
            (txt, rem - dt, col) for (txt, rem, col) in self.notifications if rem - dt > 0.0
        ]
        if self.player.attack_timer > 0.0:
            self.player.attack_timer = max(0.0, self.player.attack_timer - dt)
        if self.player.swing_anim > 0.0:
            self.player.swing_anim = max(0.0, self.player.swing_anim - dt * 3.2)
        if self.player.bow_pull_anim > 0.0:
            self.player.bow_pull_anim = max(0.0, self.player.bow_pull_anim - dt * 2.8)
        if self.player.damage_flash > 0.0:
            self.player.damage_flash = max(0.0, self.player.damage_flash - dt * 2.2)

        yaw_rad = math.radians(self.player.yaw)
        fx = math.sin(yaw_rad)
        fz = -math.cos(yaw_rad)
        rx = math.cos(yaw_rad)
        rz = math.sin(yaw_rad)

        wish_x = fx * move_forward + rx * move_right
        wish_z = fz * move_forward + rz * move_right
        wish_len = math.hypot(wish_x, wish_z)
        if wish_len > 1e-4:
            wish_x /= wish_len
            wish_z /= wish_len

        base_speed = 6.4 + (self.player.skills["endurance"] - 1) * 0.45
        if sprint and wish_len > 0.1 and self.player.stamina > 5.0:
            speed = base_speed * 1.52
            self.player.stamina = max(0.0, self.player.stamina - 13.0 * dt)
        else:
            speed = base_speed
            self.player.stamina = min(self.player.max_stamina, self.player.stamina + 16.5 * dt)

        if self.player.in_water:
            speed *= 0.80

        new_x = self.player.x + wish_x * speed * dt
        new_z = self.player.z + wish_z * speed * dt
        self.stream_infinite_chunks()

        # Физика подъема персонажа в гору: персонаж может взбираться только по склонам <= 65 градусов!
        if not self._collides_with_world(new_x, self.player.z, 0.55) and self.can_player_move_to(
            self.player.x, self.player.z, new_x, self.player.z
        ):
            self.player.x = new_x
        if not self._collides_with_world(self.player.x, new_z, 0.55) and self.can_player_move_to(
            self.player.x, self.player.z, self.player.x, new_z
        ):
            self.player.z = new_z

        # Если персонаж оказался на слишком отвесной скале (> 65 градусов) без постройки, он соскальзывает вниз!
        cur_slope_deg = self.terrain.get_slope_degrees(self.player.x, self.player.z)
        if cur_slope_deg > PLAYER_MAX_CLIMB_ANGLE_DEG and not self.player.in_water:
            on_structure = any(
                st.piece_id in ("foundation", "stairs", "bedroll")
                and abs(self.player.x - st.x) <= 2.30
                and abs(self.player.z - st.z) <= 2.30
                for st in self.structures
            )
            if not on_structure:
                gx, gz = self.terrain.get_gradient(self.player.x, self.player.z)
                glen = math.hypot(gx, gz)
                if glen > 1e-5:
                    slide_spd = 7.0 * ((cur_slope_deg - PLAYER_MAX_CLIMB_ANGLE_DEG) / 25.0 + 0.5)
                    sx = self.player.x - (gx / glen) * slide_spd * dt
                    sz = self.player.z - (gz / glen) * slide_spd * dt
                    if not self._collides_with_world(sx, sz, 0.55):
                        self.player.x = sx
                        self.player.z = sz

        if wish_len > 0.1:
            if self.player.in_water:
                self.player.swim_stroke += dt * 7.5
            elif self.player.on_ground:
                self.player.walk_bob += dt * (11.5 if sprint else 8.0)

        ground_y = self.terrain.get_height(self.player.x, self.player.z)
        self.player.is_sheltered = False
        self.player.near_campfire = False
        self.player.in_cave = False
        self.nearest_campfire_pos = None
        best_cf_dist = 32.0  # Увеличенный радиус освещения костра (до 32 метров!)

        for st in self.structures:
            if st.piece_id == "foundation":
                if abs(self.player.x - st.x) <= 2.10 and abs(self.player.z - st.z) <= 2.10:
                    ground_y = max(ground_y, st.y + 0.22)
            elif st.piece_id == "bedroll":
                if abs(self.player.x - st.x) <= 1.20 and abs(self.player.z - st.z) <= 0.80:
                    ground_y = max(ground_y, st.y + 0.22)
            elif st.piece_id == "stairs":
                if abs(self.player.x - st.x) <= 1.65 and abs(self.player.z - st.z) <= 1.65:
                    ground_y = max(ground_y, st.y + 0.55)
            elif st.is_roof:
                if abs(self.player.x - st.x) <= 2.45 and abs(self.player.z - st.z) <= 2.45:
                    self.player.is_sheltered = True
            elif st.piece_id in ("campfire", "chimney_hearth", "torch_stand"):
                cfd = math.hypot(self.player.x - st.x, self.player.z - st.z)
                if cfd <= 16.5:
                    self.player.near_campfire = True
                if cfd < best_cf_dist:
                    best_cf_dist = cfd
                    self.nearest_campfire_pos = (st.x, st.y + 1.8, st.z)

        for res in self.get_nearby_resources(self.player.x, self.player.z, cell_radius=1):
            if res.kind == "cave_grotto" and math.hypot(self.player.x - res.x, self.player.z - res.z) < 4.5:
                self.player.in_cave = True
                self.player.is_sheltered = True
                break

        self.player.in_water = ground_y < WATER_LEVEL - 0.30
        if self.player.in_water:
            self.player.fall_peak_y = self.player.y
            swim_surface_y = WATER_LEVEL - 1.15
            if jump:
                self.player.vy = 4.2
                if ground_y > WATER_LEVEL - 0.85:
                    self.player.vy = 6.8
            elif dive:
                self.player.vy = -3.8
            else:
                buoyancy = (swim_surface_y - self.player.y) * 5.5
                self.player.vy = self.player.vy * 0.85 + buoyancy * dt * 8.0
            self.player.y += self.player.vy * dt
            if self.player.y < ground_y:
                self.player.y = ground_y
                self.player.vy = 0.0
            self.player.on_ground = False
            self.player.head_underwater = (self.player.y + self.player.eye_height) < WATER_LEVEL
        else:
            self.player.head_underwater = False
            if jump and self.player.on_ground and self.player.stamina >= 8.0:
                self.player.vy = 8.8
                self.player.on_ground = False
                self.player.fall_peak_y = self.player.y
                self.player.stamina -= 8.0
            if self.player.y > ground_y + 0.18:
                if self.player.on_ground:
                    self.player.on_ground = False
                    self.player.fall_peak_y = self.player.y
                else:
                    self.player.fall_peak_y = max(self.player.fall_peak_y, self.player.y)
            self.player.vy -= GRAVITY * dt
            self.player.y += self.player.vy * dt
            if self.player.y <= ground_y:
                impact_speed = -self.player.vy
                fall_dist = max(0.0, self.player.fall_peak_y - ground_y)
                self.player.y = ground_y
                self.player.vy = 0.0
                if not self.player.on_ground and (fall_dist > 3.2 or impact_speed > 11.8):
                    self.apply_fall_damage(fall_dist, impact_speed)
                self.player.on_ground = True
                self.player.fall_peak_y = ground_y

        self.player.hunger = max(0.0, self.player.hunger - 0.40 * dt)
        self.player.thirst = max(0.0, self.player.thirst - 0.54 * dt)
        if self.player.in_water:
            self.player.thirst = min(100.0, self.player.thirst + 10.0 * dt)

        temp_val, _, cur_biome = self.terrain.get_biome_weights(self.player.x, self.player.z)
        is_winter = temp_val < -0.22 or "зимний" in cur_biome.lower() or "снежные" in cur_biome.lower()
        if is_winter and self.rng.random() < 0.68:
            for _ in range(2):
                s_ttl = self.rng.uniform(1.8, 2.8)
                self.particles.append(
                    Particle3D(
                        x=self.player.x + self.rng.uniform(-11.0, 11.0),
                        y=self.player.y + self.rng.uniform(3.5, 8.5),
                        z=self.player.z + self.rng.uniform(-11.0, 11.0),
                        vx=self.rng.uniform(-0.45, 0.45),
                        vy=self.rng.uniform(-2.1, -1.4),
                        vz=self.rng.uniform(-0.45, 0.45),
                        color=(0.96, 0.98, 1.0),
                        size=self.rng.uniform(0.055, 0.095),
                        ttl=s_ttl,
                        kind="snow",
                        max_ttl=s_ttl,
                    )
                )

        is_night = self.time_of_day < 6.0 or self.time_of_day > 20.0
        has_heat = (
            self.player.near_campfire
            or self.player.is_sheltered
            or self.player.equipped_weapon == "torch"
            or self.player.inventory.get("fur_armor", 0) > 0
            or any(asl is not None for asl in self.player.armor_slots)
        )
        if (is_night or is_winter) and not has_heat:
            cold_rate = 1.9 if is_winter else 1.2
            self.player.warmth = max(0.0, self.player.warmth - cold_rate * dt)
        else:
            self.player.warmth = min(100.0, self.player.warmth + 4.0 * dt)

        if self.player.hunger > 50.0 and self.player.thirst > 45.0 and self.player.warmth > 40.0:
            regen = 1.3 + (1.8 if self.player.is_sheltered else 0.0) + (1.4 if self.player.near_campfire else 0.0)
            self.player.hp = min(self.player.max_hp, self.player.hp + regen * dt)
        elif self.player.hunger <= 0.0 or self.player.thirst <= 0.0 or self.player.warmth <= 0.0:
            self.player.hp -= 2.0 * dt
            if self.player.hp <= 0.0:
                self._respawn_player()

        if self.bobber is not None:
            b = self.bobber
            b.ttl -= dt
            if b.ttl <= 0.0:
                self.bobber = None
            elif not b.in_water:
                b.vy -= GRAVITY * 0.65 * dt
                b.x += b.vx * dt
                b.y += b.vy * dt
                b.z += b.vz * dt
                th = self.terrain.get_height(b.x, b.z)
                if b.y <= WATER_LEVEL and th < WATER_LEVEL - 0.15:
                    b.in_water = True
                    b.y = WATER_LEVEL
                    b.vx = b.vy = b.vz = 0.0
                    self.spawn_particles(b.x, WATER_LEVEL + 0.1, b.z, (0.75, 0.92, 1.0), count=6, speed=2.2)
                elif b.y <= th:
                    self.add_notification("Поплавок упал на сушу! Забросьте удочку в озеро или реку.", 2.8, (255, 175, 120))
                    self.bobber = None
            else:
                if not b.biting:
                    b.y = WATER_LEVEL + math.sin(self.anim_clock * 4.5) * 0.04
                    b.bite_timer -= dt
                    if b.bite_timer <= 0.0:
                        b.biting = True
                        b.bite_window = 3.2
                        self.sound.play("chop")
                        self.spawn_particles(b.x, WATER_LEVEL + 0.15, b.z, (0.55, 0.90, 1.0), count=10, speed=3.0)
                        self.add_notification("КЛЮЕТ РЫБА! Подсекайте улов!", 2.8, (110, 255, 150))
                else:
                    b.y = WATER_LEVEL - 0.12 + math.sin(self.anim_clock * 18.0) * 0.10
                    b.bite_window -= dt
                    if b.bite_window <= 0.0:
                        self.add_notification("Рыба сорвалась с крючка! Забросьте удочку снова.", 2.8, (255, 150, 120))
                        self.bobber = None

        active_arrows: List[ArrowProjectile] = []
        for arr in self.arrows:
            arr.ttl -= dt
            if arr.ttl <= 0.0:
                continue
            arr.vy -= GRAVITY * 0.42 * dt
            arr.x += arr.vx * dt
            arr.y += arr.vy * dt
            arr.z += arr.vz * dt
            if arr.y <= self.terrain.get_height(arr.x, arr.z):
                continue
            hit = False
            for anim in self.animals:
                if not anim.alive:
                    continue
                if (
                    abs(arr.x - anim.x) <= anim.radius + 0.55
                    and abs(arr.z - anim.z) <= anim.radius + 0.55
                    and abs(arr.y - (anim.y + 0.7 * anim.scale)) <= 1.3 * anim.scale
                ):
                    self._damage_animal(anim, arr.damage, is_ranged=True)
                    hit = True
                    break
            if not hit:
                active_arrows.append(arr)
        self.arrows = active_arrows

        if self.shaking_resources:
            still_shaking: List[ResourceNode] = []
            for res in self.shaking_resources:
                res.hit_shake = max(0.0, res.hit_shake - dt)
                if res.hit_shake > 0.0 and res.alive:
                    still_shaking.append(res)
            self.shaking_resources = still_shaking

        self._update_animals(dt)

        for st in self.structures:
            if st.piece_id in ("campfire", "torch_stand", "chimney_hearth"):
                if math.hypot(st.x - self.player.x, st.z - self.player.z) > 48.0:
                    continue
                if st.piece_id == "campfire":
                    fy_base = st.y + 0.22
                    f_rad = 0.26
                elif st.piece_id == "torch_stand":
                    fy_base = st.y + 1.42
                    f_rad = 0.14
                else:
                    fy_base = st.y - 0.04
                    f_rad = 0.22

                # 1) Объемные языки пламени (kind='flame')
                if self.rng.random() < 0.65:
                    f_ttl = self.rng.uniform(0.38, 0.68)
                    self.particles.append(
                        Particle3D(
                            x=st.x + self.rng.uniform(-f_rad, f_rad),
                            y=fy_base,
                            z=st.z + self.rng.uniform(-f_rad, f_rad),
                            vx=self.rng.uniform(-0.22, 0.22),
                            vy=self.rng.uniform(1.35, 2.45),
                            vz=self.rng.uniform(-0.22, 0.22),
                            color=(1.0, self.rng.uniform(0.52, 0.92), 0.14),
                            size=self.rng.uniform(0.075, 0.125),
                            ttl=f_ttl,
                            kind="flame",
                            max_ttl=f_ttl,
                        )
                    )
                # 2) Яркие кружащиеся золотистые искры (kind='ember')
                if self.rng.random() < 0.42:
                    e_ttl = self.rng.uniform(0.65, 1.15)
                    self.particles.append(
                        Particle3D(
                            x=st.x + self.rng.uniform(-f_rad * 0.8, f_rad * 0.8),
                            y=fy_base + 0.18,
                            z=st.z + self.rng.uniform(-f_rad * 0.8, f_rad * 0.8),
                            vx=self.rng.uniform(-0.55, 0.55),
                            vy=self.rng.uniform(2.2, 3.8),
                            vz=self.rng.uniform(-0.55, 0.55),
                            color=(1.0, 0.88, 0.32),
                            size=self.rng.uniform(0.030, 0.052),
                            ttl=e_ttl,
                            kind="ember",
                            max_ttl=e_ttl,
                        )
                    )
                # 3) Мягкие клубы теплого дыма над огнем (kind='smoke')
                if self.rng.random() < 0.24:
                    sm_y = (st.y + 3.25) if st.piece_id == "chimney_hearth" else (fy_base + 0.55)
                    sm_ttl = self.rng.uniform(0.9, 1.5)
                    self.particles.append(
                        Particle3D(
                            x=st.x + self.rng.uniform(-0.16, 0.16),
                            y=sm_y,
                            z=st.z + self.rng.uniform(-0.16, 0.16),
                            vx=self.rng.uniform(-0.25, 0.25),
                            vy=self.rng.uniform(0.95, 1.55),
                            vz=self.rng.uniform(-0.25, 0.25),
                            color=(0.36, 0.35, 0.38),
                            size=self.rng.uniform(0.09, 0.15),
                            ttl=sm_ttl,
                            kind="smoke",
                            max_ttl=sm_ttl,
                        )
                    )

        alive_particles: List[Particle3D] = []
        for p in self.particles:
            p.ttl -= dt
            if p.ttl > 0.0:
                if p.kind == "snow":
                    p.x += (p.vx + math.sin(self.anim_clock * 2.6 + p.y * 1.3) * 0.35) * dt
                    p.y += p.vy * dt
                    p.z += (p.vz + math.cos(self.anim_clock * 2.2 + p.x * 1.1) * 0.35) * dt
                elif p.kind in ("flame", "ember", "smoke"):
                    swirl = math.sin(self.anim_clock * 8.0 + p.y * 4.0) * 0.25
                    p.x += (p.vx + swirl) * dt
                    p.y += p.vy * dt
                    p.z += (p.vz - swirl * 0.7) * dt
                else:
                    p.x += p.vx * dt
                    p.y += p.vy * dt
                    p.z += p.vz * dt
                    if p.vy > 0:
                        p.vy -= 4.5 * dt
                alive_particles.append(p)
        self.particles = alive_particles

        # Физика, вращение и 5-минутный (300 сек) таймер исчезновения сброшенных/потерянных при смерти предметов!
        expired_death_loot = False
        for ditem in list(self.dropped_items):
            ditem.despawn_timer -= real_dt
            if ditem.despawn_timer <= 0.0:
                if ditem.is_death_drop:
                    expired_death_loot = True
                self.dropped_items.remove(ditem)
                continue
            ditem.rotation = (ditem.rotation + dt * 95.0) % 360.0
            if ditem.pickup_delay > 0.0:
                ditem.pickup_delay = max(0.0, ditem.pickup_delay - dt)
            if ditem.vy != 0.0:
                ground_d = self.terrain.get_height(ditem.x, ditem.z)
                for st in self.structures:
                    if st.piece_id == "foundation" and abs(ditem.x - st.x) <= 2.05 and abs(ditem.z - st.z) <= 2.05:
                        ground_d = max(ground_d, st.y + 0.25)
                if ditem.y > ground_d + 0.22 or ditem.vy > 0.0:
                    ditem.vy -= GRAVITY * 0.65 * dt
                    ditem.y += ditem.vy * dt
                    if ditem.y <= ground_d + 0.22:
                        ditem.y = ground_d + 0.22
                        ditem.vy = 0.0

        if self.last_death_timer > 0.0:
            self.last_death_timer = max(0.0, self.last_death_timer - real_dt)
            if not any(d.is_death_drop for d in self.dropped_items):
                self.last_death_pos = None
                self.last_death_timer = 0.0
                if expired_death_loot:
                    self.add_notification(
                        "Прошло 5 минут после смерти — неподобранные предметы на месте гибели исчезли!",
                        5.0,
                        (255, 140, 115),
                    )

        self._update_crosshair_target()

    def apply_fall_damage(self, fall_dist: float, impact_speed: float = 0.0) -> float:
        """
        Наносит урон персонажу при падении или прыжке с большой высоты (> 3.2 м):
        чем больше высота падения, тем сильнее урон!
        """
        eff_drop = max(0.0, fall_dist - 3.0, (impact_speed - 11.2) * 0.75)
        if eff_drop <= 0.15:
            return 0.0
        dmg = round(eff_drop * 6.5 * (1.0 - self.player.armor_reduction * 0.35), 1)
        if dmg <= 0.5:
            return 0.0
        self.player.hp -= dmg
        self.player.damage_flash = 0.75
        self.sound.play("chop")
        self.add_notification(
            f"Падение с высоты ({max(fall_dist, 3.3):.1f} м)! Получено -{int(round(dmg))} HP урона!",
            3.5,
            (255, 95, 85),
        )
        if self.player.hp <= 0.0:
            self._respawn_player()
        return dmg

    def _collides_with_world(
        self,
        x: float,
        z: float,
        radius: float,
        entity_y: Optional[float] = None,
        is_animal: bool = False,
    ) -> bool:
        """
        Точная 3D-проверка коллизий с деревьями, камнями и всеми постройками:
          - Животные (is_animal=True) НЕ могут проходить сквозь стены, окна, закрытые двери, столы, сундуки, кровати и костры!
          - Единственный способ пройти внутрь построенного дома (и для игрока, и для животных) — через ОТКРЫТУЮ ДВЕРЬ (doorway с door_open=True)!
          - Стена 2-го этажа над открытой дверью (выше по Y) не мешает проходу на 1-м этаже.
        """
        ey = self.player.y if entity_y is None else entity_y
        ent_bottom = ey + 0.20
        ent_top = ey + 1.68

        for res in self.get_nearby_resources(x, z, cell_radius=1):
            if not res.alive or res.kind in ("berry_bush", "wild_bush", "mushroom_patch", "cave_grotto", "grass_tuft"):
                continue
            dx = x - res.x
            dz = z - res.z
            lim = radius + res.radius * 0.48
            if dx * dx + dz * dz < lim * lim:
                return True

        for st in self.structures:
            if st.is_roof:
                continue
            if not is_animal:
                if not st.is_solid or st.piece_id in ("foundation", "stairs"):
                    continue
            else:
                # Для животных все постройки непроходимы, кроме пола (foundation) и ступеней (stairs), по которым можно идти,
                # однако если фундамент стоит слишком высоко над землей (> 0.95 м) без лестницы — он тоже блокирует!
                if st.piece_id == "stairs":
                    continue
                if st.piece_id == "foundation":
                    if st.y - ey > 0.95:
                        dx_f = abs(x - st.x)
                        dz_f = abs(z - st.z)
                        if dx_f < 2.0 + radius * 0.6 and dz_f < 2.0 + radius * 0.6:
                            return True
                    continue

            # Проверяем пересечение по высоте Y:
            # Для игрока учитываем точную высоту этажа (чтобы стена 2-го этажа над открытой дверью не блокировала проход).
            # Для животных блокируем все наземные стены и постройки 1-го этажа (пропускаем только стены 2-го этажа на высоте > 2.9 м над животным).
            st_bottom = st.y - st.size[1] * 0.48
            st_top = st.y + st.size[1] * 0.48
            if not is_animal:
                if st_bottom >= ent_top or st_top <= ent_bottom:
                    continue
            else:
                if st_bottom >= ey + 2.65 or st_top <= ey - 1.50:
                    continue

            dx = x - st.x
            dz = z - st.z
            if abs(dx) > 4.6 or abs(dz) > 4.6:
                continue

            # Перевод мирового смещения (dx, dz) в локальные координаты постройки (lx, lz) для glRotatef(st.rotation, 0, 1, 0)
            rad = math.radians(st.rotation)
            lx = dx * math.cos(rad) - dz * math.sin(rad)
            lz = dx * math.sin(rad) + dz * math.cos(rad)

            # Если это входная стена с дверью (doorway) и дверь ОТКРЫТА — центральный дверной проем свободен!
            if st.piece_id == "doorway" and st.door_open:
                door_half_opening = 0.78 if is_animal else 0.98
                if abs(lx) < door_half_opening:
                    continue

            pad = radius * (0.78 if is_animal else 0.65)
            hx = st.size[0] * 0.5 + pad
            hz = st.size[2] * 0.5 + pad
            if abs(lx) < hx and abs(lz) < hz:
                return True
        return False

    def _can_animal_move_segment(self, x0: float, z0: float, x1: float, z1: float, radius: float, entity_y: float) -> bool:
        """
        Непрерывная проверка траектории шага животного (Swept Collision) от (x0, z0) до (x1, z1),
        чтобы даже быстрые хищники никогда не могли проскочить сквозь тонкую стену (0.42 м) или закрытую дверь!
        """
        dist = math.hypot(x1 - x0, z1 - z0)
        steps = max(1, int(math.ceil(dist / 0.18)))
        for i in range(1, steps + 1):
            t = i / float(steps)
            ix = x0 + (x1 - x0) * t
            iz = z0 + (z1 - z0) * t
            if self._collides_with_world(ix, iz, radius, entity_y=entity_y, is_animal=True):
                return False
        return True

    def _has_wall_between(self, x0: float, z0: float, x1: float, z1: float, entity_y: float) -> bool:
        """Проверяет, есть ли между животным и игроком глухая стена или закрытая дверь (чтобы хищник не кусал сквозь стену!)."""
        return not self._can_animal_move_segment(x0, z0, x1, z1, 0.25, entity_y)

    def _update_animals(self, dt: float) -> None:
        px, pz = self.player.x, self.player.z
        for anim in self.animals:
            if not anim.alive:
                anim.respawn_timer -= dt
                if anim.respawn_timer <= 0.0:
                    # Проверяем безопасную точку респавна: хищники не ближе 10 м от игрока, и никто не ближе 2 м от построек!
                    need_relocate = self._is_near_or_inside_any_structure(anim.x, anim.z, min_clear_dist=2.2)
                    if anim.hostile and math.hypot(anim.x - px, anim.z - pz) < 10.5:
                        need_relocate = True
                    if need_relocate:
                        for _ in range(16):
                            ang = self.rng.uniform(0.0, 2.0 * math.pi)
                            dist_r = self.rng.uniform(14.0, 32.0)
                            rx = px + math.cos(ang) * dist_r
                            rz = pz + math.sin(ang) * dist_r
                            rh = self.terrain.get_height(rx, rz)
                            if rh >= BEACH_LEVEL and not self._is_near_or_inside_any_structure(rx, rz, min_clear_dist=2.2):
                                if not anim.hostile or math.hypot(rx - px, rz - pz) >= 10.5:
                                    anim.x, anim.z, anim.y = rx, rz, rh
                                    break
                    if not self._is_near_or_inside_any_structure(anim.x, anim.z, min_clear_dist=2.2) and (
                        not anim.hostile or math.hypot(anim.x - px, anim.z - pz) >= 10.0
                    ):
                        anim.hp = anim.max_hp
                        anim.state = "wander"
                    else:
                        anim.respawn_timer = 5.0
                continue

            dx_p = px - anim.x
            dz_p = pz - anim.z
            dist_sq = dx_p * dx_p + dz_p * dz_p

            if dist_sq > 210.0 ** 2:
                continue
            # Адаптивный шаг ИИ (AI LOD): далекие животные (> 68 м) обновляют физику 15 раз в секунду без потери плавности!
            if dist_sq > 68.0 ** 2 and anim.state != "chase":
                anim.ai_sleep_accum += dt
                if anim.ai_sleep_accum < 0.065:
                    continue
                step_dt = anim.ai_sleep_accum
                anim.ai_sleep_accum = 0.0
            else:
                step_dt = dt

            # Автоматическое выталкивание животного из стволов деревьев и валунов, если оно оказалось внутри радиуса коллизии!
            if not anim.aquatic:
                for res in self.get_nearby_resources(anim.x, anim.z, cell_radius=1):
                    if not res.alive or res.kind in ("berry_bush", "wild_bush", "mushroom_patch", "cave_grotto", "grass_tuft"):
                        continue
                    rx_d = anim.x - res.x
                    rz_d = anim.z - res.z
                    min_sep = anim.radius * 0.65 + res.radius * 0.55 + 0.15
                    d_res = math.hypot(rx_d, rz_d)
                    if d_res < min_sep:
                        if d_res < 1e-4:
                            rx_d, rz_d, d_res = 1.0, 0.0, 1.0
                        anim.x = res.x + (rx_d / d_res) * (min_sep + 0.25)
                        anim.z = res.z + (rz_d / d_res) * (min_sep + 0.25)
                        anim.yaw = math.degrees(math.atan2(rx_d, -rz_d)) % 360.0

            if anim.hurt_flash > 0.0:
                anim.hurt_flash = max(0.0, anim.hurt_flash - step_dt)
            if anim.attack_cooldown > 0.0:
                anim.attack_cooldown = max(0.0, anim.attack_cooldown - step_dt)

            if anim.aquatic:
                anim.anim_phase += step_dt * 9.5
                anim.state_timer -= step_dt
                if anim.state_timer <= 0.0:
                    anim.yaw = (anim.yaw + self.rng.uniform(-75.0, 75.0)) % 360.0
                    anim.state_timer = self.rng.uniform(2.0, 5.0)
                spd = anim.chase_speed if anim.state == "flee" else anim.walk_speed
                rad = math.radians(anim.yaw)
                nx = anim.x + math.sin(rad) * spd * step_dt
                nz = anim.z - math.cos(rad) * spd * step_dt
                nh = self.terrain.get_height(nx, nz)
                if nh < WATER_LEVEL - 0.30 and self._can_animal_move_segment(anim.x, anim.z, nx, nz, anim.radius * 0.55, nh):
                    anim.x = nx
                    anim.z = nz
                    anim.y = WATER_LEVEL - 0.55 + math.sin(anim.anim_phase * 0.5) * 0.08
                else:
                    anim.yaw = (anim.yaw + 150.0) % 360.0
                continue

            dist_to_player = math.sqrt(dist_sq)

            if anim.hostile:
                eff_aggro = anim.aggro_range * (0.65 if self.player.equipped_weapon == "torch" else 1.0)
                if dist_to_player <= eff_aggro and not self.player.is_sheltered:
                    anim.state = "chase"
                elif dist_to_player > eff_aggro * 1.45 or self.player.is_sheltered:
                    if anim.state == "chase":
                        anim.state = "wander"
                        anim.state_timer = 3.5

            move_speed = 0.0
            if anim.state == "chase":
                anim.yaw = math.degrees(math.atan2(dx_p, -dz_p))
                if dist_to_player > anim.attack_range * 0.82:
                    move_speed = anim.chase_speed
                else:
                    if (
                        anim.attack_cooldown <= 0.0
                        and not self.player.is_sheltered
                        and not self._has_wall_between(anim.x, anim.z, px, pz, anim.y)
                    ):
                        anim.attack_cooldown = 1.35
                        raw_dmg = anim.damage * (1.0 - self.player.armor_reduction)
                        self.player.hp -= raw_dmg
                        self.player.damage_flash = 0.65
                        for b_msg in self.player.damage_equipped_armor(max(1.5, anim.damage * 0.14)):
                            self.add_notification(b_msg, 3.2, (255, 130, 95))
                        self.sound.play("growl")
                        self.add_notification(
                            f"{anim.name} [Ур. {anim.level}] атаковал вас! (-{int(raw_dmg)} HP)",
                            2.8,
                            (255, 95, 95),
                        )
                        if self.player.hp <= 0.0:
                            self._respawn_player()
                            return
            elif anim.state == "flee":
                anim.state_timer -= step_dt
                move_speed = anim.chase_speed
                if anim.state_timer <= 0.0:
                    anim.state = "wander"
                    anim.state_timer = 4.0
            elif anim.state == "wander":
                anim.state_timer -= step_dt
                move_speed = anim.walk_speed
                if anim.state_timer <= 0.0:
                    anim.state = "graze"
                    anim.state_timer = self.rng.uniform(2.0, 4.5)
            else:
                anim.state_timer -= step_dt
                move_speed = 0.0
                if anim.state_timer <= 0.0:
                    anim.state = "wander"
                    anim.yaw = self.rng.uniform(0.0, 360.0)
                    anim.state_timer = self.rng.uniform(3.0, 6.5)

            # Если обычное животное (НЕ горный козел) попыталось забраться на высокую гору/холм — оно падает и скатывается вниз!
            if anim.kind != "mountain_goat" and (
                anim.is_sliding_down or self.terrain.is_high_mountain_or_hill(anim.x, anim.z)
            ):
                if self.terrain.get_height(anim.x, anim.z) >= HIGH_MOUNTAIN_ELEVATION_MIN - 1.2 or self.terrain.is_high_mountain_or_hill(anim.x, anim.z):
                    anim.is_sliding_down = True
                    gx, gz = self.terrain.get_gradient(anim.x, anim.z)
                    glen = math.hypot(gx, gz)
                    if glen > 1e-5:
                        down_x, down_z = -gx / glen, -gz / glen
                    else:
                        down_x, down_z = -math.sin(math.radians(anim.yaw)), math.cos(math.radians(anim.yaw))
                    slide_speed = 8.2
                    anim.yaw = math.degrees(math.atan2(down_x, -down_z)) % 360.0
                    sx = anim.x + down_x * slide_speed * step_dt
                    sz = anim.z + down_z * slide_speed * step_dt
                    ground_h = self.terrain.get_height(sx, sz)
                    if self._can_animal_move_segment(anim.x, anim.z, sx, sz, anim.radius * 0.60, ground_h):
                        anim.x, anim.z = sx, sz
                    anim.vy = max(-18.0, anim.vy - GRAVITY * step_dt)
                    anim.y = max(ground_h, anim.y + anim.vy * step_dt)
                    if anim.y <= ground_h + 0.05:
                        anim.y = ground_h
                    p_deg, r_deg, arc_y = self.terrain.get_body_tilt_angles(
                        anim.x, anim.z, anim.yaw, 0.62 * anim.scale, 0.30 * anim.scale
                    )
                    anim.pitch, anim.roll, anim.y = p_deg, r_deg, arc_y
                    if not self.terrain.is_high_mountain_or_hill(anim.x, anim.z) and ground_h < HIGH_MOUNTAIN_ELEVATION_MIN - 1.2:
                        anim.is_sliding_down = False
                        anim.vy = 0.0
                        anim.state = "wander"
                    continue
                else:
                    anim.is_sliding_down = False
                    anim.vy = 0.0

            if move_speed > 0.01:
                # Животное идет/бежит — обычная плавная анимация ходьбы конечностями!
                anim.anim_phase = (anim.anim_phase + step_dt * move_speed * 2.4) % (2.0 * math.pi)
                anim.leg_swing = math.sin(anim.anim_phase) * 26.0
                rad = math.radians(anim.yaw)
                dir_x = math.sin(rad)
                dir_z = -math.cos(rad)
                nx = anim.x + dir_x * move_speed * step_dt
                nz = anim.z + dir_z * move_speed * step_dt
                curr_h = self.terrain.get_height(anim.x, anim.z)
                nh = self.terrain.get_height(nx, nz)
                step_dist = max(1e-5, math.hypot(nx - anim.x, nz - anim.z))
                climb_deg = math.degrees(math.atan2(nh - curr_h, step_dist)) if nh > curr_h else 0.0
                dest_slope_deg = self.terrain.get_slope_degrees(nx, nz)
                dir_slope_deg = self.terrain.get_directional_slope_degrees(anim.x, anim.z, dir_x, dir_z)
                uphill_deg = max(climb_deg, dest_slope_deg if nh > curr_h else 0.0, dir_slope_deg if nh > curr_h else 0.0)

                # Сначала проверяем, не преграждает ли путь постройка (стена, закрытая дверь, сундук, верстак)
                can_step_struct = self._can_animal_move_segment(anim.x, anim.z, nx, nz, anim.radius * 0.60, nh)

                if not can_step_struct:
                    # Если впереди закрытая дверь или стена — животное не может пройти и разворачивается (или обходит)!
                    anim.yaw = (anim.yaw + self.rng.uniform(95.0, 165.0)) % 360.0
                    if anim.state == "chase":
                        # Если хищник уперся в стену дома, он останавливается перед стеной (ноги прямые)
                        anim.leg_swing = 0.0
                # 1. Горные козлы взбираются вплоть до 85°, а остальные животные — вплоть до 70°!
                elif nh > curr_h and not self.can_animal_climb_angle(uphill_deg, anim.kind):
                    anim.yaw = (anim.yaw + 135.0) % 360.0
                    if anim.state == "chase":
                        anim.state = "wander"
                        anim.state_timer = 2.0
                # 2. Если обычное животное (не горный козел) пытается взобраться на высокую гору или крутой холм — оно срывается и падает вниз!
                elif anim.kind != "mountain_goat" and nh > curr_h and self.terrain.is_high_mountain_or_hill(nx, nz):
                    anim.x, anim.z, anim.y = nx, nz, nh
                    anim.is_sliding_down = True
                    anim.vy = -4.5
                # 3. Горные козлы держатся на вершинах и склонах гор
                elif anim.mountain_mid_only:
                    if self.terrain.is_narrow_peak_summit(nx, nz):
                        anim.x, anim.z, anim.y = nx, nz, nh
                    else:
                        anim.yaw = (anim.yaw + 145.0) % 360.0
                elif nh >= WATER_LEVEL + 0.2:
                    anim.x = nx
                    anim.z = nz
                    anim.y = nh
                else:
                    anim.yaw = (anim.yaw + 125.0) % 360.0

            else:
                # Если животное остановилось — его конечности обязательно прямые (0.0°), а углы наклона уже вычислены!
                anim.leg_swing = 0.0
                anim.anim_phase = 0.0
                continue

            # Выравниваем корпус движущегося сухопутного животного под дугу и угол горы
            target_pitch, target_roll, arc_y = self.terrain.get_body_tilt_angles(
                anim.x, anim.z, anim.yaw, half_len=0.62 * anim.scale, half_width=0.30 * anim.scale
            )
            for st in self.structures:
                if st.piece_id == "foundation" and abs(anim.x - st.x) <= 2.05 and abs(anim.z - st.z) <= 2.05:
                    if st.y + 0.22 >= arc_y:
                        arc_y = st.y + 0.22
                        target_pitch = 0.0
                        target_roll = 0.0
            blend = min(1.0, step_dt * 12.0)
            anim.pitch = anim.pitch + (target_pitch - anim.pitch) * blend
            anim.roll = anim.roll + (target_roll - anim.roll) * blend
            anim.y = arc_y

    def _respawn_player(self) -> None:
        """
        При гибели персонаж теряет ВСЕ предметы из хотбара (slots[0..8]), инвентаря (slots[9..24]) и ячеек брони!
        Все потерянные предметы остаются лежать на месте гибели ровно 5 минут (DEATH_LOOT_DESPAWN_SECONDS = 300 сек):
        если вернуться туда за 5 минут, их можно подобрать [F], а спустя 5 минут они бесследно исчезают!
        """
        death_x, death_y, death_z = float(self.player.x), float(self.player.y), float(self.player.z)
        ground_h = max(self.terrain.get_height(death_x, death_z), WATER_LEVEL - 0.15)
        for st in self.structures:
            if st.piece_id == "foundation" and abs(death_x - st.x) <= 2.05 and abs(death_z - st.z) <= 2.05:
                ground_h = max(ground_h, st.y + 0.25)

        lost_items: List[Tuple[str, int]] = []
        for idx in range(MAX_INVENTORY_SLOTS):
            sl = self.player.slots[idx]
            if sl is not None and int(sl.get("count", 0)) > 0:
                lost_items.append((str(sl["item"]), int(sl["count"])))
            self.player.slots[idx] = None

        for a_idx in range(4):
            asl = self.player.armor_slots[a_idx]
            if asl is not None and int(asl.get("count", 0)) > 0:
                lost_items.append((str(asl["item"]), int(asl["count"])))
            self.player.armor_slots[a_idx] = None

        self.player.unlocked_weapons.clear()
        self.player.active_hotbar_slot = 0
        self.player.sync_active_weapon_from_hotbar()
        self.build_mode = False
        self.show_inventory = False
        self.show_crafting = False
        self.show_skills = False
        self.active_chest = None
        self.dragged_item = None
        self.drag_source = None

        n_lost = len(lost_items)
        for i, (item_id, cnt) in enumerate(lost_items):
            ang = (2.0 * math.pi * i) / max(1, n_lost)
            rad = 0.35 + 0.18 * (i % 4) if n_lost > 1 else 0.0
            dx = death_x + math.cos(ang) * rad
            dz = death_z + math.sin(ang) * rad
            dy = max(death_y, ground_h) + 0.45
            self.dropped_items.append(
                DroppedItem3D(
                    id=self._alloc_id(),
                    item_id=item_id,
                    count=cnt,
                    x=dx,
                    y=dy,
                    z=dz,
                    vy=1.8,
                    rotation=(i * 47.0) % 360.0,
                    pickup_delay=0.0,
                    despawn_timer=DEATH_LOOT_DESPAWN_SECONDS,
                    is_death_drop=True,
                )
            )

        if n_lost > 0:
            self.last_death_pos = (death_x, ground_h, death_z)
            self.last_death_timer = DEATH_LOOT_DESPAWN_SECONDS

        sx, sy, sz = self.player.spawn_point
        self.player.x, self.player.y, self.player.z = sx, sy, sz
        self.player.vy = 0.0
        self.player.on_ground = True
        self.player.fall_peak_y = sy
        self.player.hp = self.player.max_hp
        self.player.stamina = self.player.max_stamina
        self.player.hunger = 80.0
        self.player.thirst = 80.0
        self.player.warmth = 100.0
        if n_lost > 0:
            self.add_notification(
                f"Вы погибли и потеряли все предметы ({n_lost} ячеек)! Они лежат на месте гибели ({int(death_x)}, {int(death_z)}) максимум 5 минут!",
                6.5,
                (255, 110, 95),
            )
        else:
            self.add_notification(
                "Вы потеряли сознание и очнулись в лагере. Берегитесь хищников и высоты!",
                5.5,
                (255, 130, 110),
            )

    def get_quest_tracker(self) -> List[Tuple[str, bool]]:
        has_wb = self.has_placed_workbench()
        has_axe_or_spear = (
            "stone_axe" in self.player.unlocked_weapons or "wooden_spear" in self.player.unlocked_weapons
        )
        return [
            ("1. Добыть камнем два дерева", self.player.stats_trees_cut >= 1 or self.player.inventory["wood"] >= 2 or has_wb),
            ("2. Создать Стол мастерской и поставить", has_wb),
            ("3. Создать оружие на Столе мастерской", has_axe_or_spear),
            ("4. Построить свой дом", self.player.stats_blocks_built >= 4),
            ("5. Пожарить рыбу или мясо на костре", self.player.stats_meat_cooked >= 1),
            ("6. Найти Снежного барса и Горного козла", self.player.stats_animals_hunted >= 1),
        ]

    def save_game(self, path: str = SAVE_FILE_PATH) -> None:
        data = {
            "time_of_day": self.time_of_day,
            "day_number": self.day_number,
            "player": {
                "x": self.player.x,
                "y": self.player.y,
                "z": self.player.z,
                "yaw": self.player.yaw,
                "pitch": self.player.pitch,
                "hp": self.player.hp,
                "stamina": self.player.stamina,
                "hunger": self.player.hunger,
                "thirst": self.player.thirst,
                "warmth": self.player.warmth,
                "level": self.player.level,
                "xp": self.player.xp,
                "xp_to_next": self.player.xp_to_next,
                "skill_points": self.player.skill_points,
                "skills": self.player.skills,
                "inventory": self.player.inventory.to_plain_dict(),
                "slots": self.player.slots,
                "armor_slots": self.player.armor_slots,
                "unlocked_weapons": list(self.player.unlocked_weapons),
                "equipped_weapon": self.player.equipped_weapon,
                "hotbar": list(self.player.hotbar),
            },
            "structures": [
                {
                    "id": s.id,
                    "piece_id": s.piece_id,
                    "name": s.name,
                    "x": s.x,
                    "y": s.y,
                    "z": s.z,
                    "rotation": s.rotation,
                    "size": list(s.size),
                    "is_solid": s.is_solid,
                    "is_roof": s.is_roof,
                    "door_open": s.door_open,
                    "storage": s.storage,
                }
                for s in self.structures
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.add_notification(f"Мир и персонаж успешно сохранены ({path})!", 3.5, (140, 255, 190))

    def load_game(self, path: str = SAVE_FILE_PATH) -> bool:
        if not os.path.exists(path):
            self.add_notification("Файл сохранения не найден! Нажмите [F5] для сохранения.", 3.0, (255, 160, 120))
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.time_of_day = data.get("time_of_day", 8.5)
        self.day_number = data.get("day_number", 1)
        pdata = data["player"]
        self.player.x = pdata["x"]
        self.player.y = pdata["y"]
        self.player.z = pdata["z"]
        self.player.yaw = pdata["yaw"]
        self.player.pitch = pdata["pitch"]
        self.player.hp = pdata["hp"]
        self.player.stamina = pdata["stamina"]
        self.player.hunger = pdata["hunger"]
        self.player.thirst = pdata["thirst"]
        self.player.warmth = pdata["warmth"]
        self.player.level = pdata["level"]
        self.player.xp = pdata["xp"]
        self.player.xp_to_next = pdata["xp_to_next"]
        self.player.skill_points = pdata["skill_points"]
        self.player.skills.update(pdata["skills"])
        if "armor_slots" in pdata and isinstance(pdata["armor_slots"], list):
            a_slots = pdata["armor_slots"][:4]
            while len(a_slots) < 4:
                a_slots.append(None)
            self.player.armor_slots = a_slots
        if "slots" in pdata and isinstance(pdata["slots"], list):
            loaded_slots = pdata["slots"][:MAX_INVENTORY_SLOTS]
            while len(loaded_slots) < MAX_INVENTORY_SLOTS:
                loaded_slots.append(None)
            self.player.slots = loaded_slots
        else:
            self.player.slots = [None] * MAX_INVENTORY_SLOTS
            for k, v in pdata.get("inventory", {}).items():
                if v > 0:
                    self.player.add_item_to_slots(k, int(v))
        self.player.unlocked_weapons = set(pdata["unlocked_weapons"])
        self.player.equipped_weapon = pdata["equipped_weapon"]
        self.player.sync_active_weapon_from_hotbar()

        self.structures.clear()
        for s in data.get("structures", []):
            self.structures.append(
                BuiltStructure(
                    id=s["id"],
                    piece_id=s["piece_id"],
                    name=s["name"],
                    x=s["x"],
                    y=s["y"],
                    z=s["z"],
                    rotation=s["rotation"],
                    size=tuple(s["size"]),
                    is_solid=s["is_solid"],
                    is_roof=s["is_roof"],
                    door_open=s.get("door_open", False),
                    storage=s.get("storage", {}),
                )
            )
        self.add_notification("Мир успешно загружен из сохранения!", 3.5, (140, 255, 190))
        return True

    def get_daylight_factor(self) -> float:
        """Возвращает плавный коэффициент дневного света (0.0 глубокой ночью .. 1.0 в полдень) без резких скачков."""
        t = self.time_of_day % 24.0
        sun_angle = (t - 6.0) / 24.0 * 2.0 * math.pi
        sun_elev = math.sin(sun_angle)
        u = max(0.0, min(1.0, (sun_elev + 0.32) / 0.72))
        return u * u * (3.0 - 2.0 * u)

    def get_atmosphere_colors(self) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], float]:
        """
        Плавный непрерывный переход дня, рассвета, заката, сумерек и ночи (C1 Smoothstep по опорным точкам суток)
        без единого резкого скачка цвета неба, тумана или освещения!
        """
        t = self.time_of_day % 24.0
        sun_angle = (t - 6.0) / 24.0 * 2.0 * math.pi
        sun_elev = math.sin(sun_angle)

        # Опорные точки суток: (час, sky_r, sky_g, sky_b, ambient)
        keyframes = [
            (0.0,  0.04, 0.07, 0.15, 0.24),
            (4.0,  0.06, 0.09, 0.19, 0.26),
            (5.5,  0.48, 0.34, 0.38, 0.44),
            (7.0,  0.76, 0.56, 0.48, 0.64),
            (9.0,  0.38, 0.66, 0.90, 0.84),
            (12.5, 0.42, 0.73, 0.96, 0.94),
            (16.5, 0.40, 0.68, 0.92, 0.85),
            (18.5, 0.82, 0.50, 0.36, 0.60),
            (20.2, 0.36, 0.24, 0.38, 0.38),
            (22.0, 0.07, 0.10, 0.20, 0.26),
            (24.0, 0.04, 0.07, 0.15, 0.24),
        ]
        sky = (0.42, 0.73, 0.96)
        ambient = 0.85
        for i in range(len(keyframes) - 1):
            t0, r0, g0, b0, a0 = keyframes[i]
            t1, r1, g1, b1, a1 = keyframes[i + 1]
            if t0 <= t <= t1:
                u = (t - t0) / max(1e-5, (t1 - t0))
                s = u * u * (3.0 - 2.0 * u)  # Плавная кубическая интерполяция Эрмита (smoothstep)
                sky = (r0 + (r1 - r0) * s, g0 + (g1 - g0) * s, b0 + (b1 - b0) * s)
                ambient = a0 + (a1 - a0) * s
                break

        smooth_elev = 0.20 + 0.80 * (0.5 + 0.5 * sun_elev)
        sun_dir = (math.cos(sun_angle), smooth_elev, 0.35)
        return sky, sun_dir, ambient


# ==============================================================================
# 7. ПРОЦЕДУРНЫЕ HD-ТЕКСТУРЫ, 3D-ПЕЩЕРЫ, КРОВАТЬ, КОЗЛЫ, РЫБА И АНИМАЦИИ
# ==============================================================================

class ProceduralTexturePack:
    """Генерирует бесшовные процедурные текстуры в памяти видеокарты с помощью NumPy."""

    def __init__(self) -> None:
        self.textures: Dict[str, int] = {}
        if HAS_OPENGL and HAS_PYGAME:
            self._build_all_textures()

    def _upload_rgb_array(self, rgb: np.ndarray) -> int:
        h, w, _ = rgb.shape
        alpha = np.full((h, w, 1), 255, dtype=np.uint8)
        rgba = np.concatenate([rgb, alpha], axis=-1)
        tex_id = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        try:
            # Включаем аппаратную анизотропную фильтрацию (GL_TEXTURE_MAX_ANISOTROPY_EXT = 0x84FE), если поддерживается GPU
            glTexParameteri(GL_TEXTURE_2D, 0x84FE, 8)
        except Exception:
            pass
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba.tobytes())
        return tex_id

    def _build_all_textures(self) -> None:
        """Генерирует бесшовные Ultra-HD текстуры 512x512 (262 144 текселей на текстуру) с 5 октавами микродетализации."""
        rng = np.random.default_rng(2026)
        size = 512
        u = np.linspace(0, 2 * np.pi, size, endpoint=False, dtype=np.float32)
        gx, gy = np.meshgrid(u, u, indexing="ij")

        # 1. HD-текстура почвы и травяного покрова (переплетение травинок, клевера и микрорельефа земли)
        blades = (
            0.88
            + 0.07 * np.sin(gx * 8.0 + np.cos(gy * 7.0) * 1.6)
            + 0.05 * np.cos(gx * 19.0 - gy * 17.0)
            + 0.03 * np.sin(gx * 37.0 + gy * 31.0)
            + rng.uniform(-0.04, 0.04, (size, size))
        )
        t_r = np.clip(blades * 244.0, 175, 255).astype(np.uint8)
        t_g = np.clip((blades + 0.02 * np.sin(gx * 12.0)) * 248.0, 180, 255).astype(np.uint8)
        t_b = np.clip((blades - 0.02) * 238.0, 168, 255).astype(np.uint8)
        self.textures["terrain"] = self._upload_rgb_array(np.stack([t_r, t_g, t_b], axis=-1))

        # 2. HD-текстура древесной коры (глубокие продольные трещины, сучки и волокна)
        grain = (
            0.86
            + 0.10 * np.sin(gy * 11.0 + np.sin(gx * 3.0) * 1.8)
            + 0.06 * np.cos(gy * 27.0 + np.sin(gx * 6.0) * 1.2)
            + 0.03 * np.sin(gx * 18.0 - gy * 9.0)
            + rng.uniform(-0.035, 0.035, (size, size))
        )
        bark_rgb = np.clip(grain * 246.0, 165, 255).astype(np.uint8)
        self.textures["bark"] = self._upload_rgb_array(np.stack([bark_rgb] * 3, axis=-1))

        # 3. HD-текстура густой листвы и хвои (кластеры листьев с прожилками и глубокой светотенью)
        leaf = (
            0.87
            + 0.08 * np.sin(gx * 9.0) * np.cos(gy * 9.0)
            + 0.06 * np.sin(gx * 21.0 + gy * 19.0)
            + 0.04 * np.cos(gx * 35.0 - gy * 33.0)
            + rng.uniform(-0.045, 0.045, (size, size))
        )
        foliage_rgb = np.clip(leaf * 248.0, 170, 255).astype(np.uint8)
        self.textures["foliage"] = self._upload_rgb_array(np.stack([foliage_rgb] * 3, axis=-1))

        # 4. HD-текстура гранитной скалы (трещины, кристаллическая зернистость и сколы породы)
        cracks = (
            0.86
            + 0.09 * np.cos(gx * 5.0 - gy * 5.0 + np.sin(gx * 3.0))
            + 0.06 * np.sin(gx * 16.0 + gy * 14.0)
            + 0.04 * np.cos(gx * 33.0 - gy * 29.0)
            + rng.uniform(-0.055, 0.055, (size, size))
        )
        rock_rgb = np.clip(cracks * 246.0, 160, 255).astype(np.uint8)
        self.textures["rock"] = self._upload_rgb_array(np.stack([rock_rgb] * 3, axis=-1))

        # 5. HD-текстура водной глади (каустика, пересекающиеся волны и солнечные блики)
        waves = (
            0.88
            + 0.07 * np.sin(gx * 7.0 + np.cos(gy * 6.0) * 1.5)
            + 0.05 * np.cos(gx * 15.0 - gy * 13.0)
        )
        w_r = np.clip(waves * 225.0, 165, 250).astype(np.uint8)
        w_g = np.clip(waves * 242.0, 190, 255).astype(np.uint8)
        w_b = np.clip(waves * 255.0, 215, 255).astype(np.uint8)
        self.textures["water"] = self._upload_rgb_array(np.stack([w_r, w_g, w_b], axis=-1))


class MeshBuilder3D:
    """
    Высокодетализированный генератор 3D-мешей:
      - Многогранные цилиндры, конусы, сферы и эллипсоиды.
      - Включает 3D-модели Горного козла (с крутыми рогами и бородкой) и Рыбы (с виляющим хвостом).
    """

    CUBE_TRIS = np.array(
        [
            [[-0.5, -0.5, 0.5], [0.5, -0.5, 0.5], [0.5, 0.5, 0.5]],
            [[-0.5, -0.5, 0.5], [0.5, 0.5, 0.5], [-0.5, 0.5, 0.5]],
            [[0.5, -0.5, -0.5], [-0.5, -0.5, -0.5], [-0.5, 0.5, -0.5]],
            [[0.5, -0.5, -0.5], [-0.5, 0.5, -0.5], [0.5, 0.5, -0.5]],
            [[0.5, -0.5, 0.5], [0.5, -0.5, -0.5], [0.5, 0.5, -0.5]],
            [[0.5, -0.5, 0.5], [0.5, 0.5, -0.5], [0.5, 0.5, 0.5]],
            [[-0.5, -0.5, -0.5], [-0.5, -0.5, 0.5], [-0.5, 0.5, 0.5]],
            [[-0.5, -0.5, -0.5], [-0.5, 0.5, 0.5], [-0.5, 0.5, -0.5]],
            [[-0.5, 0.5, 0.5], [0.5, 0.5, 0.5], [0.5, 0.5, -0.5]],
            [[-0.5, 0.5, 0.5], [0.5, 0.5, -0.5], [-0.5, 0.5, -0.5]],
            [[-0.5, -0.5, -0.5], [0.5, -0.5, -0.5], [0.5, -0.5, 0.5]],
            [[-0.5, -0.5, -0.5], [0.5, -0.5, 0.5], [-0.5, -0.5, 0.5]],
        ],
        dtype=np.float32,
    )

    CUBE_NORMALS = np.array(
        [
            [0, 0, 1], [0, 0, 1],
            [0, 0, -1], [0, 0, -1],
            [1, 0, 0], [1, 0, 0],
            [-1, 0, 0], [-1, 0, 0],
            [0, 1, 0], [0, 1, 0],
            [0, -1, 0], [0, -1, 0],
        ],
        dtype=np.float32,
    )

    # Глобальный множитель полигональной тесселяции (2.2 = High-Poly Ultra HD, 1.0 = Low-Poly режим)
    POLY_MULT: float = 2.2

    @staticmethod
    def emit_gl_ground_shadow_disc(
        ox: float,
        oy: float,
        oz: float,
        radius: float,
        alpha: float = 0.34,
        segments: int = 20,
    ) -> None:
        """Рисует мягкую двухкольцевую полупрозрачную проекционную тень на земле (20 сегментов)."""
        glDisable(GL_LIGHTING)
        glBegin(GL_TRIANGLES)
        inner_r = radius * 0.48
        for i in range(segments):
            a0 = (i / float(segments)) * 2.0 * math.pi
            a1 = ((i + 1) / float(segments)) * 2.0 * math.pi
            c0, s0 = math.cos(a0), math.sin(a0)
            c1, s1 = math.cos(a1), math.sin(a1)
            # Плотно затененное внутреннее ядро тени
            glColor4f(0.02, 0.04, 0.03, alpha)
            glVertex3f(ox, oy + 0.03, oz)
            glColor4f(0.02, 0.04, 0.03, alpha * 0.65)
            glVertex3f(ox + c1 * inner_r, oy + 0.03, oz + s1 * inner_r)
            glVertex3f(ox + c0 * inner_r, oy + 0.03, oz + s0 * inner_r)
            # Мягкая полутень (penumbra) по внешнему кольцу
            glColor4f(0.02, 0.04, 0.03, alpha * 0.65)
            glVertex3f(ox + c0 * inner_r, oy + 0.03, oz + s0 * inner_r)
            glVertex3f(ox + c1 * inner_r, oy + 0.03, oz + s1 * inner_r)
            glColor4f(0.02, 0.04, 0.03, 0.0)
            glVertex3f(ox + c1 * radius, oy + 0.03, oz + s1 * radius)

            glColor4f(0.02, 0.04, 0.03, alpha * 0.65)
            glVertex3f(ox + c0 * inner_r, oy + 0.03, oz + s0 * inner_r)
            glColor4f(0.02, 0.04, 0.03, 0.0)
            glVertex3f(ox + c1 * radius, oy + 0.03, oz + s1 * radius)
            glVertex3f(ox + c0 * radius, oy + 0.03, oz + s0 * radius)
        glEnd()
        glEnable(GL_LIGHTING)

    @staticmethod
    def emit_gl_cylinder(
        ox: float,
        oy: float,
        oz: float,
        r_bottom: float,
        r_top: float,
        height: float,
        color: Tuple[float, float, float],
        segments: int = 12,
        horizontal_x: bool = False,
        rings: int = 2,
    ) -> None:
        """
        Высокополигональный цилиндр / усеченный конус с автоматическим умножением граней (POLY_MULT),
        промежуточными кольцами по высоте и сплошными торцевыми крышками сверху и снизу!
        """
        eff_seg = max(4, int(round(segments * MeshBuilder3D.POLY_MULT)))
        eff_rings = max(1, rings if MeshBuilder3D.POLY_MULT >= 1.5 else 1)
        glColor3f(color[0], color[1], color[2])
        glBegin(GL_TRIANGLES)
        slope_ny = (r_bottom - r_top) / max(1e-4, height)

        for i in range(eff_seg):
            a0 = (i / float(eff_seg)) * 2.0 * math.pi
            a1 = ((i + 1) / float(eff_seg)) * 2.0 * math.pi
            c0, s0 = math.cos(a0), math.sin(a0)
            c1, s1 = math.cos(a1), math.sin(a1)
            u0 = i / float(eff_seg)
            u1 = (i + 1) / float(eff_seg)

            if not horizontal_x:
                for rk in range(eff_rings):
                    v0 = rk / float(eff_rings)
                    v1 = (rk + 1) / float(eff_rings)
                    rb0 = r_bottom + (r_top - r_bottom) * v0
                    rb1 = r_bottom + (r_top - r_bottom) * v1
                    yb = oy + height * v0
                    yt = oy + height * v1

                    x0b, z0b = ox + c0 * rb0, oz + s0 * rb0
                    x1b, z1b = ox + c1 * rb0, oz + s1 * rb0
                    x0t, z0t = ox + c0 * rb1, oz + s0 * rb1
                    x1t, z1t = ox + c1 * rb1, oz + s1 * rb1

                    glNormal3f(c0, slope_ny, s0)
                    glTexCoord2f(u0, v0)
                    glVertex3f(x0b, yb, z0b)
                    glNormal3f(c1, slope_ny, s1)
                    glTexCoord2f(u1, v0)
                    glVertex3f(x1b, yb, z1b)
                    glNormal3f(c1, slope_ny, s1)
                    glTexCoord2f(u1, v1)
                    glVertex3f(x1t, yt, z1t)

                    glNormal3f(c0, slope_ny, s0)
                    glTexCoord2f(u0, v0)
                    glVertex3f(x0b, yb, z0b)
                    glNormal3f(c1, slope_ny, s1)
                    glTexCoord2f(u1, v1)
                    glVertex3f(x1t, yt, z1t)
                    glNormal3f(c0, slope_ny, s0)
                    glTexCoord2f(u0, v1)
                    glVertex3f(x0t, yt, z0t)

                if r_top > 0.008:
                    yt_cap = oy + height
                    glNormal3f(0.0, 1.0, 0.0)
                    glVertex3f(ox, yt_cap, oz)
                    glVertex3f(ox + c1 * r_top, yt_cap, oz + s1 * r_top)
                    glVertex3f(ox + c0 * r_top, yt_cap, oz + s0 * r_top)
                if r_bottom > 0.008:
                    glNormal3f(0.0, -1.0, 0.0)
                    glVertex3f(ox, oy, oz)
                    glVertex3f(ox + c0 * r_bottom, oy, oz + s0 * r_bottom)
                    glVertex3f(ox + c1 * r_bottom, oy, oz + s1 * r_bottom)
            else:
                xb, xt = ox - height * 0.5, ox + height * 0.5
                y0b, z0b = oy + c0 * r_bottom, oz + s0 * r_bottom
                y1b, z1b = oy + c1 * r_bottom, oz + s1 * r_bottom

                glNormal3f(0.0, c0, s0)
                glTexCoord2f(0.0, u0)
                glVertex3f(xb, y0b, z0b)
                glNormal3f(0.0, c1, s1)
                glTexCoord2f(0.0, u1)
                glVertex3f(xb, y1b, z1b)
                glNormal3f(0.0, c1, s1)
                glTexCoord2f(1.0, u1)
                glVertex3f(xt, y1b, z1b)

                glNormal3f(0.0, c0, s0)
                glTexCoord2f(0.0, u0)
                glVertex3f(xb, y0b, z0b)
                glNormal3f(0.0, c1, s1)
                glTexCoord2f(1.0, u1)
                glVertex3f(xt, y1b, z1b)
                glNormal3f(0.0, c0, s0)
                glTexCoord2f(1.0, u0)
                glVertex3f(xt, y0b, z0b)

                if r_bottom > 0.008:
                    glNormal3f(-1.0, 0.0, 0.0)
                    glVertex3f(xb, oy, oz)
                    glVertex3f(xb, y1b, z1b)
                    glVertex3f(xb, y0b, z0b)
                    glNormal3f(1.0, 0.0, 0.0)
                    glVertex3f(xt, oy, oz)
                    glVertex3f(xt, y0b, z0b)
                    glVertex3f(xt, y1b, z1b)
        glEnd()

    @staticmethod
    def emit_gl_ellipsoid(
        ox: float,
        oy: float,
        oz: float,
        rx: float,
        ry: float,
        rz: float,
        color: Tuple[float, float, float],
        lat_steps: int = 8,
        lon_steps: int = 12,
        roughness: float = 0.0,
    ) -> None:
        """
        Высокополигональный 3D-эллипсоид с автоматическим умножением сегментов (POLY_MULT),
        микрорельефом поверхности (roughness для валунов, кроны деревьев и кустов) и плавным вершинным шейдингом!
        """
        eff_lat = max(4, int(round(lat_steps * MeshBuilder3D.POLY_MULT)))
        eff_lon = max(6, int(round(lon_steps * MeshBuilder3D.POLY_MULT)))
        r_base, g_base, b_base = color[0], color[1], color[2]

        def _disp_point(ux: float, uy: float, uz: float) -> Tuple[float, float, float, float]:
            if roughness <= 1e-4:
                return ux * rx, uy * ry, uz * rz, 1.0
            n_val = (
                0.60 * math.sin(ux * 5.0 + uy * 3.5 + ox * 1.3) * math.cos(uz * 5.0 - oz * 1.1)
                + 0.40 * math.cos(uy * 9.0 - ux * 7.0 + uz * 6.0)
            )
            d = 1.0 + roughness * n_val
            shade_mod = 0.94 + 0.08 * uy + roughness * 0.22 * n_val
            return ux * rx * d, uy * ry * d, uz * rz * d, shade_mod

        glBegin(GL_TRIANGLES)
        for i in range(eff_lat):
            lat0 = math.pi * (-0.5 + float(i) / eff_lat)
            lat1 = math.pi * (-0.5 + float(i + 1) / eff_lat)
            y0, r0 = math.sin(lat0), math.cos(lat0)
            y1, r1 = math.sin(lat1), math.cos(lat1)
            v0 = i / float(eff_lat)
            v1 = (i + 1) / float(eff_lat)

            for j in range(eff_lon):
                lon0 = 2.0 * math.pi * float(j) / eff_lon
                lon1 = 2.0 * math.pi * float(j + 1) / eff_lon
                u0 = j / float(eff_lon)
                u1 = (j + 1) / float(eff_lon)

                x00, z00 = math.cos(lon0) * r0, math.sin(lon0) * r0
                x10, z10 = math.cos(lon1) * r0, math.sin(lon1) * r0
                x01, z01 = math.cos(lon0) * r1, math.sin(lon0) * r1
                x11, z11 = math.cos(lon1) * r1, math.sin(lon1) * r1

                px00, py00, pz00, s00 = _disp_point(x00, y0, z00)
                px10, py10, pz10, s10 = _disp_point(x10, y0, z10)
                px01, py01, pz01, s01 = _disp_point(x01, y1, z01)
                px11, py11, pz11, s11 = _disp_point(x11, y1, z11)

                glColor3f(min(1.0, r_base * s00), min(1.0, g_base * s00), min(1.0, b_base * s00))
                glNormal3f(x00, y0, z00)
                glTexCoord2f(u0, v0)
                glVertex3f(ox + px00, oy + py00, oz + pz00)

                glColor3f(min(1.0, r_base * s10), min(1.0, g_base * s10), min(1.0, b_base * s10))
                glNormal3f(x10, y0, z10)
                glTexCoord2f(u1, v0)
                glVertex3f(ox + px10, oy + py10, oz + pz10)

                glColor3f(min(1.0, r_base * s11), min(1.0, g_base * s11), min(1.0, b_base * s11))
                glNormal3f(x11, y1, z11)
                glTexCoord2f(u1, v1)
                glVertex3f(ox + px11, oy + py11, oz + pz11)

                glColor3f(min(1.0, r_base * s00), min(1.0, g_base * s00), min(1.0, b_base * s00))
                glNormal3f(x00, y0, z00)
                glTexCoord2f(u0, v0)
                glVertex3f(ox + px00, oy + py00, oz + pz00)

                glColor3f(min(1.0, r_base * s11), min(1.0, g_base * s11), min(1.0, b_base * s11))
                glNormal3f(x11, y1, z11)
                glTexCoord2f(u1, v1)
                glVertex3f(ox + px11, oy + py11, oz + pz11)

                glColor3f(min(1.0, r_base * s01), min(1.0, g_base * s01), min(1.0, b_base * s01))
                glNormal3f(x01, y1, z01)
                glTexCoord2f(u0, v1)
                glVertex3f(ox + px01, oy + py01, oz + pz01)
        glEnd()

    @staticmethod
    def animal_parts(anim: Animal) -> List[Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float], float]]:
        s = anim.scale
        swing = anim.leg_swing
        c_body = (1.0, 0.25, 0.25) if anim.hurt_flash > 0.0 else anim.body_color
        c_acc = anim.accent_color
        c_dark = (max(0.05, c_body[0] * 0.55), max(0.05, c_body[1] * 0.55), max(0.05, c_body[2] * 0.55))
        parts = []

        # 1. РЫБА (Озерная и речная форель с анимированным хвостом и плавниками!)
        if anim.kind == "fish":
            tail_wiggle = math.sin(anim.anim_phase * 1.4) * 0.14 * s
            parts.append(((0.0, 0.25 * s, 0.0), (0.28 * s, 0.34 * s, 0.85 * s), c_body, 0.0))
            parts.append(((0.0, 0.24 * s, 0.0), (0.30 * s, 0.12 * s, 0.78 * s), c_acc, 0.0))  # розовая полоса форели
            parts.append(((0.0, 0.46 * s, 0.05 * s), (0.04 * s, 0.18 * s, 0.32 * s), c_acc, -18.0))  # спинной плавник
            parts.append(((tail_wiggle * 0.5, 0.25 * s, 0.52 * s), (0.16 * s, 0.24 * s, 0.34 * s), c_body, 0.0))
            parts.append(((tail_wiggle, 0.26 * s, 0.82 * s), (0.06 * s, 0.42 * s, 0.32 * s), c_acc, 15.0))  # хвостовой плавник
            return parts

        # 2. КУРИЦА
        if anim.kind == "chicken":
            parts.append(((0.0, 0.54 * s, 0.0), (0.52 * s, 0.46 * s, 0.72 * s), c_body, 0.0))
            parts.append(((-0.29 * s, 0.56 * s, 0.0), (0.08 * s, 0.34 * s, 0.52 * s), c_body, 0.0))
            parts.append(((0.29 * s, 0.56 * s, 0.0), (0.08 * s, 0.34 * s, 0.52 * s), c_body, 0.0))
            parts.append(((0.0, 0.68 * s, 0.38 * s), (0.24 * s, 0.32 * s, 0.28 * s), c_body, -25.0))
            parts.append(((0.0, 0.88 * s, -0.35 * s), (0.32 * s, 0.36 * s, 0.32 * s), c_body, 0.0))
            parts.append(((0.0, 1.12 * s, -0.36 * s), (0.09 * s, 0.19 * s, 0.24 * s), c_acc, 0.0))
            parts.append(((0.0, 0.74 * s, -0.48 * s), (0.08 * s, 0.14 * s, 0.10 * s), c_acc, 0.0))
            parts.append(((0.0, 0.86 * s, -0.58 * s), (0.12 * s, 0.10 * s, 0.20 * s), (0.96, 0.78, 0.14), 0.0))
            parts.append(((-0.16 * s, 0.22 * s, 0.0), (0.08 * s, 0.42 * s, 0.08 * s), (0.92, 0.70, 0.15), swing))
            parts.append(((0.16 * s, 0.22 * s, 0.0), (0.08 * s, 0.42 * s, 0.08 * s), (0.92, 0.70, 0.15), -swing))
            return parts

        # Четвероногие животные
        parts.append(((0.0, 0.85 * s, 0.05 * s), (0.82 * s, 0.70 * s, 1.55 * s), c_body, 0.0))
        parts.append(((0.0, 0.90 * s, -0.45 * s), (0.88 * s, 0.76 * s, 0.75 * s), c_body, 0.0))
        parts.append(((0.0, 1.05 * s, -0.82 * s), (0.48 * s, 0.54 * s, 0.46 * s), c_body, 18.0))

        if anim.kind == "mountain_goat":
            # ГОРНЫЙ КОЗЕЛ: крепкая шея, бородка, массивные загнутые назад крутые рога!
            parts.append(((0.0, 1.24 * s, -1.02 * s), (0.48 * s, 0.46 * s, 0.56 * s), c_body, 0.0))
            parts.append(((0.0, 0.94 * s, -1.24 * s), (0.12 * s, 0.30 * s, 0.14 * s), (0.88, 0.86, 0.82), 15.0))  # бородка
            # Крутые дугообразные рога горного козла (2 сегмента на каждый рог)
            parts.append(((-0.18 * s, 1.58 * s, -0.92 * s), (0.13 * s, 0.42 * s, 0.15 * s), c_acc, -28.0))
            parts.append(((0.18 * s, 1.58 * s, -0.92 * s), (0.13 * s, 0.42 * s, 0.15 * s), c_acc, -28.0))
            parts.append(((-0.20 * s, 1.72 * s, -0.62 * s), (0.11 * s, 0.16 * s, 0.38 * s), c_acc, -12.0))
            parts.append(((0.20 * s, 1.72 * s, -0.62 * s), (0.11 * s, 0.16 * s, 0.38 * s), c_acc, -12.0))
            parts.append(((0.0, 1.04 * s, 0.90 * s), (0.14 * s, 0.26 * s, 0.14 * s), c_body, 25.0))
        elif anim.kind == "cow":
            parts.append(((0.0, 0.92 * s, 0.12 * s), (0.90 * s, 0.46 * s, 0.65 * s), c_acc, 0.0))
            parts.append(((0.0, 1.20 * s, -1.04 * s), (0.54 * s, 0.50 * s, 0.58 * s), c_body, 0.0))
            parts.append(((0.0, 1.10 * s, -1.36 * s), (0.44 * s, 0.32 * s, 0.22 * s), (0.92, 0.72, 0.74), 0.0))
            parts.append(((-0.32 * s, 1.50 * s, -1.00 * s), (0.11 * s, 0.30 * s, 0.11 * s), (0.90, 0.88, 0.80), 12.0))
            parts.append(((0.32 * s, 1.50 * s, -1.00 * s), (0.11 * s, 0.30 * s, 0.11 * s), (0.90, 0.88, 0.80), 12.0))
            parts.append(((0.0, 0.82 * s, 0.92 * s), (0.10 * s, 0.55 * s, 0.10 * s), c_dark, -14.0))
        elif anim.kind == "sheep":
            parts.append(((0.0, 0.92 * s, 0.0), (1.06 * s, 0.88 * s, 1.68 * s), c_body, 0.0))
            parts.append(((0.0, 1.16 * s, -1.02 * s), (0.46 * s, 0.44 * s, 0.54 * s), c_acc, 0.0))
            parts.append(((0.0, 1.36 * s, -0.98 * s), (0.50 * s, 0.22 * s, 0.42 * s), c_body, 0.0))
            parts.append(((-0.28 * s, 1.18 * s, -0.96 * s), (0.16 * s, 0.10 * s, 0.12 * s), c_acc, 0.0))
            parts.append(((0.28 * s, 1.18 * s, -0.96 * s), (0.16 * s, 0.10 * s, 0.12 * s), c_acc, 0.0))
        elif anim.kind == "wolf":
            parts.append(((0.0, 1.16 * s, -1.00 * s), (0.48 * s, 0.46 * s, 0.56 * s), c_body, 0.0))
            parts.append(((0.0, 1.08 * s, -1.36 * s), (0.28 * s, 0.26 * s, 0.38 * s), c_acc, 0.0))
            parts.append(((-0.14 * s, 1.24 * s, -1.26 * s), (0.08 * s, 0.08 * s, 0.08 * s), (1.0, 0.88, 0.15), 0.0))
            parts.append(((0.14 * s, 1.24 * s, -1.26 * s), (0.08 * s, 0.08 * s, 0.08 * s), (1.0, 0.88, 0.15), 0.0))
            parts.append(((-0.18 * s, 1.46 * s, -0.92 * s), (0.12 * s, 0.26 * s, 0.12 * s), c_acc, 0.0))
            parts.append(((0.18 * s, 1.46 * s, -0.92 * s), (0.12 * s, 0.26 * s, 0.12 * s), c_acc, 0.0))
            parts.append(((0.0, 0.90 * s, 1.08 * s), (0.22 * s, 0.22 * s, 0.74 * s), c_acc, -22.0))
        elif anim.kind == "tiger":
            parts.append(((0.0, 0.90 * s, -0.38 * s), (0.92 * s, 0.76 * s, 0.18 * s), c_acc, 0.0))
            parts.append(((0.0, 0.88 * s, 0.05 * s), (0.86 * s, 0.72 * s, 0.18 * s), c_acc, 0.0))
            parts.append(((0.0, 0.88 * s, 0.45 * s), (0.86 * s, 0.72 * s, 0.18 * s), c_acc, 0.0))
            parts.append(((0.0, 1.20 * s, -1.06 * s), (0.58 * s, 0.54 * s, 0.58 * s), c_body, 0.0))
            parts.append(((0.0, 1.08 * s, -1.38 * s), (0.38 * s, 0.30 * s, 0.30 * s), (0.95, 0.92, 0.86), 0.0))
            parts.append(((-0.16 * s, 1.28 * s, -1.32 * s), (0.09 * s, 0.09 * s, 0.09 * s), (0.98, 0.92, 0.18), 0.0))
            parts.append(((0.16 * s, 1.28 * s, -1.32 * s), (0.09 * s, 0.09 * s, 0.09 * s), (0.98, 0.92, 0.18), 0.0))
            parts.append(((0.0, 0.94 * s, 1.18 * s), (0.16 * s, 0.16 * s, 0.92 * s), c_body, -16.0))
        elif anim.kind == "bear":
            parts.append(((0.0, 1.08 * s, -0.35 * s), (1.08 * s, 0.92 * s, 0.95 * s), c_body, 0.0))
            parts.append(((0.0, 1.20 * s, -1.06 * s), (0.68 * s, 0.62 * s, 0.64 * s), c_body, 0.0))
            parts.append(((0.0, 1.10 * s, -1.42 * s), (0.40 * s, 0.36 * s, 0.36 * s), c_acc, 0.0))
            parts.append(((-0.26 * s, 1.56 * s, -0.98 * s), (0.16 * s, 0.16 * s, 0.12 * s), c_body, 0.0))
            parts.append(((0.26 * s, 1.56 * s, -0.98 * s), (0.16 * s, 0.16 * s, 0.12 * s), c_body, 0.0))

        leg_col = c_acc if anim.kind in ("sheep", "wolf") else c_body
        leg_coords = [
            (-0.30 * s, 0.36 * s, -0.58 * s, swing),
            (0.30 * s, 0.36 * s, -0.58 * s, -swing),
            (-0.30 * s, 0.36 * s, 0.58 * s, -swing),
            (0.30 * s, 0.36 * s, 0.58 * s, swing),
        ]
        for lx, ly, lz, ang in leg_coords:
            parts.append(((lx, ly, lz), (0.22 * s, 0.66 * s, 0.22 * s), leg_col, ang))
            parts.append(((lx, 0.08 * s, lz), (0.25 * s, 0.14 * s, 0.28 * s), c_dark, ang))

        return parts


class GLTextCache:
    """Высокоскоростной LRU-кеш текстовых текстур для OpenGL HUD и Pygame Surface (Android SDL2)."""

    def __init__(self, max_entries: int = 512) -> None:
        self.max_entries = max_entries
        self.cache: Dict[Tuple[int, str, Tuple[int, int, int]], Tuple[int, int, int]] = {}
        self.surf_cache: Dict[Tuple[int, str, Tuple[int, int, int]], Tuple[object, int, int]] = {}
        self.order: deque[Tuple[int, str, Tuple[int, int, int]]] = deque()

    def draw_text(
        self,
        font: object,
        text: str,
        x: float,
        y: float,
        color: Tuple[int, int, int] = (240, 245, 255),
        center: bool = False,
    ) -> Tuple[int, int]:
        if not text or font is None:
            return (0, 0)
        key = (id(font), text, (int(color[0]), int(color[1]), int(color[2])))
        active_surf = DualRenderer3D._ACTIVE_SURF
        if active_surf is not None:
            s_entry = self.surf_cache.get(key)
            if s_entry is None:
                surf = font.render(text, True, key[2])
                tw, th = surf.get_size()
                s_entry = (surf, tw, th)
                if len(self.surf_cache) > self.max_entries:
                    self.surf_cache.clear()
                self.surf_cache[key] = s_entry
            else:
                surf, tw, th = s_entry
            dx = x - tw * 0.5 if center else x
            dy = y - th * 0.5 if center else y
            active_surf.blit(surf, (int(dx), int(dy)))
            return (tw, th)

        entry = self.cache.get(key)
        if entry is None:
            surf = font.render(text, True, key[2])
            tw, th = surf.get_size()
            raw = pygame.image.tostring(surf, "RGBA", False)
            tex_id = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_2D, tex_id)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, tw, th, 0, GL_RGBA, GL_UNSIGNED_BYTE, raw)
            entry = (tex_id, tw, th)
            self.cache[key] = entry
            self.order.append(key)
            if len(self.order) > self.max_entries:
                old_key = self.order.popleft()
                old_entry = self.cache.pop(old_key, None)
                if old_entry is not None:
                    glDeleteTextures([old_entry[0]])
        else:
            tex_id, tw, th = entry

        dx = x - tw * 0.5 if center else x
        dy = y - th * 0.5 if center else y

        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glBegin(GL_QUADS)
        glTexCoord2f(0.0, 0.0)
        glVertex2f(dx, dy)
        glTexCoord2f(1.0, 0.0)
        glVertex2f(dx + tw, dy)
        glTexCoord2f(1.0, 1.0)
        glVertex2f(dx + tw, dy + th)
        glTexCoord2f(0.0, 1.0)
        glVertex2f(dx, dy + th)
        glEnd()
        glDisable(GL_TEXTURE_2D)
        return (tw, th)


# ==============================================================================
# 8. HD 3D-РЕНДЕРЕР: СТОЛ МАСТЕРСКОЙ, 3D-ТРАВА, СНЕЖНЫЙ БАРС, DRAG & DROP МЫШЬЮ
# ==============================================================================

class DualRenderer3D:
    """
    Высокодетализированный 3D-рендерер:
      - Скульптурные 3D-модели всех 9 видов животных (включая Снежного барса и Горного козла).
      - Объемная 3D-трава (grass_tuft), Стол мастерской (workbench) и кованые сундуки.
      - Увеличенный радиус освещения костра (до 32 м) с плавным затуханием света.
      - Нефиксированный хотбар 1..9 и полноценный Drag & Drop предметов мышью в Инвентаре [I].
    """

    _ACTIVE_SURF: Optional[object] = None

    def __init__(self, game: SurvivalRPGGame, use_opengl: bool) -> None:
        self.game = game
        self.use_opengl = use_opengl and HAS_OPENGL and HAS_PYGAME
        self.gl_text = GLTextCache() if HAS_PYGAME else None
        self.tex_pack = None
        self.gl_cube_list: Optional[int] = None
        self.gl_shadow_disc_list: Optional[int] = None
        self.gl_resource_lists: Dict[str, int] = {}
        self.gl_resource_lists_low: Dict[str, int] = {}
        self.gl_resource_lists_tiers: Dict[int, Dict[str, int]] = {0: {}, 1: {}, 2: {}, 3: {}}
        self.gl_structure_lists: Dict[Tuple[str, bool], int] = {}
        self.gl_animal_torso_lists: Dict[str, int] = {}
        self.gl_animal_leg_lists: Dict[str, int] = {}
        self.gl_animal_torso_tiers: Dict[int, Dict[str, int]] = {0: {}, 1: {}, 2: {}, 3: {}}
        self.gl_animal_leg_tiers: Dict[int, Dict[str, int]] = {0: {}, 1: {}, 2: {}, 3: {}}
        self.gl_hand_list: Optional[int] = None
        self.gl_left_hand_list: Optional[int] = None
        self.gl_arrow_3d_list: Optional[int] = None
        self.gl_bow_riser_list: Optional[int] = None
        self.gl_bow_upper_limb_list: Optional[int] = None
        self.gl_bow_lower_limb_list: Optional[int] = None
        self.gl_snowflake_list: Optional[int] = None
        self.gl_fire_particle_list: Optional[int] = None
        self.gl_flame_cone_list: Optional[int] = None
        self.gl_weapon_lists: Dict[str, int] = {}
        self.gl_cloud_list_day: Optional[int] = None
        self.gl_cloud_list_night: Optional[int] = None
        self.ui_fullscreen_btn_rect: Optional[Tuple[float, float, float, float]] = None

        # Прямоугольники элементов UI для кликов и перетаскивания мышью (Drag & Drop)
        self.ui_hotbar_rects: List[Tuple[int, float, float, float, float]] = []
        self.ui_inv_card_rects: List[Tuple[int, float, float, float, float]] = []
        self.ui_armor_slot_rects: List[Tuple[int, float, float, float, float]] = []
        self.ui_drop_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_craft_confirm_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_chest_card_rects: List[Tuple[int, float, float, float, float]] = []
        self.ui_inv_box_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_chest_box_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_workbench_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_recipe_row_rects: List[Tuple[int, float, float, float, float]] = []
        self.ui_help_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_help_close_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_settings_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_settings_close_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_settings_action_rects: List[Tuple[str, float, float, float, float]] = []
        self.ui_skill_upgrade_rects: List[Tuple[str, float, float, float, float]] = []
        self.ui_mobile_toggle_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_quests_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_modal_close_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_inv_use_btn_rect: Optional[Tuple[float, float, float, float]] = None
        self.ui_mobile_joy_circle: Tuple[float, float, float] = (128.0, 440.0, 68.0)
        self.ui_mobile_buttons: List[Tuple[str, float, float, float, str]] = []  # (act_id, cx, cy, radius, label)
        self.ui_mobile_rect_buttons: List[Tuple[str, float, float, float, float, str]] = []  # (act_id, x, y, w, h, label)

        if HAS_PYGAME:
            pygame.font.init()
            self.font_sm = pygame.font.SysFont("DejaVu Sans", 14, bold=False)
            self.font_md = pygame.font.SysFont("DejaVu Sans", 17, bold=True)
            self.font_lg = pygame.font.SysFont("DejaVu Sans", 22, bold=True)

        if self.use_opengl:
            try:
                self.tex_pack = ProceduralTexturePack()
                self._init_opengl()
            except Exception:
                # На Android с чистым OpenGL ES (без GL4ES) автоматически переключаемся на быстрый SDL2 3D-рендерер
                self.use_opengl = False
                self.tex_pack = None

    def _init_opengl(self) -> None:
        glViewport(0, 0, self.game.width, self.game.height)
        try:
            # Включаем аппаратное сглаживание краев полигонов 4x MSAA (GL_MULTISAMPLE = 0x809D)
            glEnable(0x809D)
        except Exception:
            pass
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        glShadeModel(GL_SMOOTH)
        glEnable(GL_NORMALIZE)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_FOG)
        glFogi(GL_FOG_MODE, GL_EXP2)

        self.gl_cube_list = glGenLists(1)
        glNewList(self.gl_cube_list, GL_COMPILE)
        glBegin(GL_TRIANGLES)
        for i in range(12):
            n = MeshBuilder3D.CUBE_NORMALS[i]
            glNormal3f(float(n[0]), float(n[1]), float(n[2]))
            for v in MeshBuilder3D.CUBE_TRIS[i]:
                glVertex3f(float(v[0]), float(v[1]), float(v[2]))
        glEnd()
        glEndList()

        self._compile_detailed_resource_meshes()
        self._compile_detailed_structure_meshes()
        self._compile_sculpted_animals()
        self._compile_sculpted_hand_and_weapons()
        self._compile_pending_chunks(max_per_frame=120)

    def _compile_pending_chunks(self, max_per_frame: int = 2) -> None:
        compiled = 0
        tex_terrain = self.tex_pack.textures.get("terrain", 0)
        while self.game.terrain.compile_queue and compiled < max_per_frame:
            key = self.game.terrain.compile_queue.popleft()
            chunk = self.game.terrain.generated_chunks.get(key)
            if chunk is None or chunk.gl_list_id is not None:
                continue
            lid = glGenLists(1)
            glNewList(lid, GL_COMPILE)
            if tex_terrain:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tex_terrain)
            glBegin(GL_TRIANGLES)
            verts = chunk.verts
            norms = chunk.norms
            cols = chunk.cols
            uvs = chunk.uvs
            for i in range(len(verts)):
                for k in range(3):
                    c = cols[i, k]
                    n = norms[i, k]
                    u = uvs[i, k]
                    v = verts[i, k]
                    glColor3f(float(c[0]), float(c[1]), float(c[2]))
                    glNormal3f(float(n[0]), float(n[1]), float(n[2]))
                    glTexCoord2f(float(u[0]), float(u[1]))
                    glVertex3f(float(v[0]), float(v[1]), float(v[2]))
            glEnd()
            if tex_terrain:
                glDisable(GL_TEXTURE_2D)
            glEndList()
            chunk.gl_list_id = lid
            self._compile_chunk_foliage_lists(chunk)
            compiled += 1

    def _compile_chunk_foliage_lists(self, chunk: TerrainChunkData) -> None:
        """
        Компилирует статическую флору/камни/руды чанка и 3D-траву (с цветами и мягкими тенями на Высоких/Ультра,
        либо облегченные Low-Poly меши на Низких/Средних настройках) в GPU Display Lists!
        """
        ckey = (chunk.cx, chunk.cz)
        res_list = self.game.chunk_resources.get(ckey, ())
        det_idx = max(0, min(3, int(self.game.detail_quality_idx)))
        sh_on = self.game.shadows_enabled
        active_dict = self.gl_resource_lists_tiers.get(det_idx, self.gl_resource_lists)

        need_props = (
            chunk.props_dirty
            or chunk.gl_props_list_id is None
            or chunk.compiled_detail_idx != det_idx
            or chunk.compiled_shadows != sh_on
        )
        if need_props:
            if chunk.gl_props_list_id is None:
                chunk.gl_props_list_id = glGenLists(1)
            p_cnt = 0
            glNewList(chunk.gl_props_list_id, GL_COMPILE)
            for res in res_list:
                if not res.alive or res.kind == "grass_tuft":
                    continue
                lid = active_dict.get(res.kind, active_dict["stone_rock"])
                glPushMatrix()
                glTranslatef(res.x, res.y, res.z)
                if sh_on and self.gl_shadow_disc_list is not None and res.kind != "mushroom_patch":
                    sh_scale = res.radius * res.scale * (1.85 if "pine" in res.kind or "oak" in res.kind or "tree" in res.kind or "birch" in res.kind else 1.25)
                    glPushMatrix()
                    glScalef(sh_scale, 1.0, sh_scale)
                    glCallList(self.gl_shadow_disc_list)
                    glPopMatrix()
                glRotatef(res.rotation, 0.0, 1.0, 0.0)
                glScalef(res.scale, res.scale, res.scale)
                glCallList(lid)
                glPopMatrix()
                p_cnt += 1
            glEndList()
            chunk.prop_count = p_cnt
            chunk.props_dirty = False

        if (
            chunk.compiled_grass_idx != self.game.grass_density_idx
            or chunk.compiled_detail_idx != det_idx
            or chunk.gl_grass_list_id is None
        ):
            if chunk.gl_grass_list_id is None:
                chunk.gl_grass_list_id = glGenLists(1)
            grass_mult = self.game.get_grass_density_multiplier()
            g_cnt = 0
            glNewList(chunk.gl_grass_list_id, GL_COMPILE)
            if grass_mult > 0.01:
                lid_grass = active_dict["grass_tuft"]
                lid_fl1 = active_dict.get("grass_flower_1", lid_grass)
                lid_fl2 = active_dict.get("grass_flower_2", lid_grass)
                extra_offsets = (
                    []
                    if grass_mult <= 1.05
                    else ([(0.52, 0.38, 45.0)] if grass_mult < 1.75 else [(0.52, 0.38, 45.0), (-0.48, 0.44, 115.0)])
                )
                for res in res_list:
                    if not res.alive or res.kind != "grass_tuft":
                        continue
                    if grass_mult < 1.0 and (res.id % 10) >= int(grass_mult * 10):
                        continue
                    use_lid = lid_fl1 if (det_idx >= 2 and res.id % 6 == 0) else (lid_fl2 if (det_idx >= 2 and res.id % 9 == 0) else lid_grass)
                    glPushMatrix()
                    glTranslatef(res.x, res.y, res.z)
                    glRotatef(res.rotation, 0.0, 1.0, 0.0)
                    glScalef(res.scale, res.scale, res.scale)
                    glCallList(use_lid)
                    glPopMatrix()
                    g_cnt += 1
                    for ox, oz, orot in extra_offsets:
                        ex_x = res.x + ox
                        ex_z = res.z + oz
                        ex_y = self.game.terrain.get_height(ex_x, ex_z)
                        glPushMatrix()
                        glTranslatef(ex_x, ex_y, ex_z)
                        glRotatef(res.rotation + orot, 0.0, 1.0, 0.0)
                        glScalef(res.scale * 0.92, res.scale * 0.92, res.scale * 0.92)
                        glCallList(lid_grass)
                        glPopMatrix()
                        g_cnt += 1
            glEndList()
            chunk.grass_count = g_cnt
            chunk.compiled_grass_idx = self.game.grass_density_idx

        chunk.compiled_detail_idx = det_idx
        chunk.compiled_shadows = sh_on

    def _compile_sculpted_animals(self) -> None:
        for tier_idx, tier_mult in ((0, 0.65), (1, 1.10), (2, 1.65), (3, 2.35)):
            MeshBuilder3D.POLY_MULT = tier_mult
            self._compile_sculpted_animals_for_tier(tier_idx)
        MeshBuilder3D.POLY_MULT = 2.2
        self.gl_animal_torso_lists = dict(self.gl_animal_torso_tiers[3])
        self.gl_animal_leg_lists = dict(self.gl_animal_leg_tiers[3])

    def _compile_sculpted_animals_for_tier(self, tier_idx: int) -> None:
        el = MeshBuilder3D.emit_gl_ellipsoid
        cyl = MeshBuilder3D.emit_gl_cylinder

        for kind, spec in Animal.SPECS.items():
            cb = spec["body_color"]
            ca = spec["accent_color"]
            cd = (max(0.05, cb[0] * 0.52), max(0.05, cb[1] * 0.52), max(0.05, cb[2] * 0.52))

            tid = glGenLists(1)
            glNewList(tid, GL_COMPILE)
            if kind == "fish":
                el(0.0, 0.25, 0.0, 0.16, 0.20, 0.48, cb, 6, 10)
                el(0.0, 0.25, 0.0, 0.17, 0.06, 0.42, ca, 4, 8)
                el(0.0, 0.42, 0.05, 0.03, 0.12, 0.18, ca, 4, 6)
                el(-0.14, 0.28, -0.28, 0.03, 0.03, 0.03, (0.98, 0.98, 0.98), 4, 6)
                el(0.14, 0.28, -0.28, 0.03, 0.03, 0.03, (0.98, 0.98, 0.98), 4, 6)
            elif kind == "chicken":
                el(0.0, 0.54, 0.0, 0.28, 0.26, 0.38, cb, 7, 10)
                el(-0.26, 0.55, 0.0, 0.08, 0.18, 0.28, (0.90, 0.88, 0.78), 5, 8)
                el(0.26, 0.55, 0.0, 0.08, 0.18, 0.28, (0.90, 0.88, 0.78), 5, 8)
                el(0.0, 0.70, 0.34, 0.12, 0.20, 0.16, cb, 5, 8)
                cyl(0.0, 0.65, -0.26, 0.13, 0.11, 0.24, cb, segments=8)
                el(0.0, 0.92, -0.32, 0.16, 0.16, 0.17, cb, 6, 8)
                el(0.0, 1.10, -0.32, 0.04, 0.10, 0.13, ca, 5, 6)
                el(0.0, 0.76, -0.44, 0.04, 0.08, 0.05, ca, 4, 6)
                el(0.0, 0.90, -0.52, 0.06, 0.05, 0.11, (0.98, 0.78, 0.12), 4, 6)
                el(-0.13, 0.95, -0.38, 0.025, 0.025, 0.025, (0.10, 0.10, 0.12), 4, 6)
                el(0.13, 0.95, -0.38, 0.025, 0.025, 0.025, (0.10, 0.10, 0.12), 4, 6)
            else:
                # Высокополигональная мускулатура: грудная клетка, живот, рельефные лопатки (плечи), мощные бедра и спинной хребет!
                el(0.0, 0.86, 0.06, 0.44, 0.38, 0.82, cb, 9, 14)
                el(0.0, 0.90, -0.42, 0.47, 0.42, 0.48, cb, 9, 14)
                el(0.0, 0.88, 0.56, 0.42, 0.38, 0.42, cb, 8, 12)
                for side_m in (-1.0, 1.0):
                    # Рельефные мышцы плеча (scapula) и бедра (femur)
                    el(side_m * 0.34, 0.82, -0.46, 0.18, 0.28, 0.26, cb, 7, 10)
                    el(side_m * 0.32, 0.84, 0.48, 0.17, 0.27, 0.26, cb, 7, 10)
                cyl(0.0, 0.92, -0.78, 0.24, 0.19, 0.38, cb, segments=12)
                # Череп, лобные надбровные дуги, переносица, нижняя челюсть и ноздри
                el(0.0, 1.24, -0.98, 0.27, 0.25, 0.32, cb, 9, 14)
                el(0.0, 1.16, -1.28, 0.18, 0.16, 0.24, ca if kind in ("sheep", "bear", "wolf") else (0.92, 0.74, 0.74), 8, 12)
                el(0.0, 1.07, -1.22, 0.14, 0.08, 0.18, cd, 6, 10)  # нижняя челюсть
                eye_col = (0.45, 0.88, 1.0) if kind == "snow_leopard" else ((1.0, 0.88, 0.16) if kind in ("wolf", "tiger", "mountain_goat") else (0.98, 0.98, 0.98))
                for ex in (-0.21, 0.21):
                    el(ex * 0.95, 1.35, -1.08, 0.065, 0.032, 0.065, cd, 5, 8)  # надбровная дуга
                    el(ex, 1.30, -1.10, 0.046, 0.046, 0.046, eye_col, 6, 8)
                    el(ex * 1.08, 1.30, -1.13, 0.024, 0.024, 0.024, (0.05, 0.05, 0.07), 5, 8)
                    el(ex * 1.12, 1.315, -1.14, 0.010, 0.010, 0.010, (1.0, 1.0, 1.0), 4, 6)  # живой блик в глазу
                el(0.0, 1.20, -1.48, 0.065, 0.052, 0.045, (0.12, 0.10, 0.10), 6, 8)
                for nx_n in (-0.035, 0.035):
                    el(nx_n, 1.20, -1.51, 0.018, 0.022, 0.015, (0.04, 0.04, 0.05), 4, 6)  # ноздри

                if kind == "cow":
                    el(-0.22, 0.94, 0.05, 0.28, 0.28, 0.38, ca, 6, 8)
                    el(0.24, 0.90, 0.32, 0.25, 0.24, 0.32, ca, 6, 8)
                    el(0.0, 0.52, 0.35, 0.18, 0.12, 0.22, (0.94, 0.72, 0.76), 5, 8)
                    for hx in (-0.24, 0.24):
                        el(hx * 1.15, 1.28, -0.92, 0.12, 0.06, 0.06, cb, 4, 6)
                        cyl(hx, 1.42, -0.95, 0.065, 0.015, 0.34, (0.92, 0.90, 0.82), segments=8)
                    cyl(0.0, 0.48, 0.92, 0.035, 0.05, 0.45, cd, segments=6)
                elif kind == "sheep":
                    for wx, wy, wz, wr in [
                        (0.0, 0.94, 0.0, 0.52),
                        (-0.26, 0.92, -0.25, 0.38),
                        (0.26, 0.92, -0.25, 0.38),
                        (-0.24, 0.92, 0.32, 0.38),
                        (0.24, 0.92, 0.32, 0.38),
                        (0.0, 1.08, -0.35, 0.40),
                        (0.0, 1.42, -0.95, 0.20),
                    ]:
                        el(wx, wy, wz, wr, wr * 0.88, wr * 1.05, cb, 6, 8)
                    el(-0.26, 1.22, -0.96, 0.10, 0.05, 0.06, ca, 4, 6)
                    el(0.26, 1.22, -0.96, 0.10, 0.05, 0.06, ca, 4, 6)
                elif kind == "mountain_goat":
                    cyl(0.0, 0.84, -1.28, 0.02, 0.06, 0.26, (0.92, 0.90, 0.86), segments=6)
                    for hx in (-0.17, 0.17):
                        cyl(hx, 1.42, -0.94, 0.075, 0.050, 0.38, ca, segments=8)
                        el(hx * 1.1, 1.76, -0.76, 0.055, 0.065, 0.22, ca, 5, 8)
                        el(hx * 1.15, 1.66, -0.54, 0.040, 0.090, 0.12, ca, 5, 8)
                    el(0.0, 1.06, 0.92, 0.08, 0.14, 0.10, cb, 4, 6)
                elif kind == "wolf":
                    el(0.0, 0.98, -0.58, 0.50, 0.45, 0.36, ca, 6, 8)
                    for wx in (-0.16, 0.16):
                        cyl(wx, 1.44, -0.90, 0.07, 0.01, 0.24, ca, segments=6)
                        cyl(wx * 0.65, 1.04, -1.36, 0.01, 0.025, 0.09, (0.98, 0.98, 0.98), segments=6)
                    el(0.0, 0.82, 1.14, 0.13, 0.14, 0.42, ca, 5, 8)
                elif kind == "snow_leopard":
                    # СНЕЖНЫЙ БАРС (Ирбис): серебристо-снежная шерсть с дымчатыми розетками-пятнами и длинным пушистым хвостом!
                    for sx, sy, sz in [
                        (-0.32, 0.95, -0.25), (0.32, 0.95, -0.25),
                        (-0.30, 0.92, 0.18), (0.30, 0.92, 0.18),
                        (0.0, 1.12, 0.05), (0.0, 1.10, 0.45),
                    ]:
                        el(sx, sy, sz, 0.16, 0.14, 0.16, ca, 5, 6)
                    for tx in (-0.18, 0.18):
                        el(tx, 1.46, -0.92, 0.07, 0.07, 0.05, cb, 4, 6)
                        cyl(tx * 0.65, 0.98, -1.38, 0.012, 0.032, 0.14, (0.98, 0.98, 1.0), segments=6)
                    # Длинный толстый пушистый хвост снежного барса
                    el(0.0, 0.86, 1.24, 0.14, 0.14, 0.56, cb, 6, 8)
                    el(0.0, 0.86, 1.45, 0.15, 0.15, 0.18, ca, 5, 6)
                elif kind == "tiger":
                    for sz in (-0.42, -0.10, 0.22, 0.52):
                        el(0.0, 0.90, sz, 0.48, 0.41, 0.07, ca, 6, 8)
                    el(-0.24, 1.18, -1.06, 0.10, 0.10, 0.12, (0.96, 0.94, 0.90), 5, 6)
                    el(0.24, 1.18, -1.06, 0.10, 0.10, 0.12, (0.96, 0.94, 0.90), 5, 6)
                    for tx in (-0.18, 0.18):
                        el(tx, 1.48, -0.92, 0.07, 0.07, 0.05, cb, 4, 6)
                        cyl(tx * 0.65, 0.98, -1.38, 0.012, 0.032, 0.14, (0.98, 0.98, 0.96), segments=6)
                    el(0.0, 0.92, 1.22, 0.09, 0.09, 0.48, cb, 5, 8)
                elif kind == "bear":
                    el(0.0, 1.06, -0.36, 0.56, 0.50, 0.52, cb, 7, 10)
                    el(0.0, 0.94, 0.15, 0.54, 0.48, 0.65, cb, 7, 10)
                    for bx in (-0.24, 0.24):
                        el(bx, 1.52, -0.94, 0.09, 0.09, 0.06, cb, 5, 6)
                        cyl(bx * 0.55, 1.00, -1.38, 0.015, 0.035, 0.12, (0.98, 0.96, 0.92), segments=6)
            glEndList()
            self.gl_animal_torso_tiers[tier_idx][kind] = tid

            lid = glGenLists(1)
            glNewList(lid, GL_COMPILE)
            if kind == "chicken":
                cyl(0.0, -0.36, 0.0, 0.03, 0.04, 0.36, (0.95, 0.72, 0.14), segments=6)
                el(0.0, -0.36, -0.04, 0.06, 0.025, 0.09, (0.95, 0.72, 0.14), 4, 6)
            else:
                # Детализированная многосуставная лапа/нога: бедро, коленный сустав, голень, путовый сустав и раздвоенное копыто / лапа с когтями!
                leg_c = ca if kind in ("sheep", "wolf") else cb
                el(0.0, -0.04, 0.0, 0.13, 0.12, 0.14, leg_c, 6, 8)
                cyl(0.0, -0.34, 0.0, 0.092, 0.135, 0.35, leg_c, segments=10)
                el(0.0, -0.34, 0.01, 0.102, 0.092, 0.105, leg_c, 6, 8)
                cyl(0.0, -0.64, 0.0, 0.074, 0.092, 0.32, leg_c, segments=10)
                el(0.0, -0.63, 0.0, 0.085, 0.065, 0.090, cd, 5, 8)
                if kind in ("wolf", "snow_leopard", "tiger", "bear"):
                    el(0.0, -0.68, -0.04, 0.11, 0.065, 0.14, leg_c, 6, 8)
                    for cx_t in (-0.055, 0.0, 0.055):
                        el(cx_t, -0.69, -0.15, 0.028, 0.035, 0.045, leg_c, 5, 6)
                        cyl(cx_t, -0.70, -0.19, 0.012, 0.002, 0.045, (0.14, 0.14, 0.16), segments=5)
                else:
                    # Раздвоенное копыто травоядных и горных козлов
                    el(-0.042, -0.68, -0.03, 0.048, 0.070, 0.12, cd, 5, 8)
                    el(0.042, -0.68, -0.03, 0.048, 0.070, 0.12, cd, 5, 8)
            glEndList()
            self.gl_animal_leg_tiers[tier_idx][kind] = lid

    def _compile_sculpted_hand_and_weapons(self) -> None:
        el = MeshBuilder3D.emit_gl_ellipsoid
        cyl = MeshBuilder3D.emit_gl_cylinder

        # Детализированные объемные кучевые 3D-облака (из 8 пушистых куполов со светотенью!)
        for is_day_cloud in (True, False):
            cid = glGenLists(1)
            glNewList(cid, GL_COMPILE)
            c_top = (0.98, 0.99, 1.00) if is_day_cloud else (0.28, 0.33, 0.44)
            c_mid = (0.91, 0.94, 0.98) if is_day_cloud else (0.22, 0.26, 0.36)
            c_bot = (0.78, 0.83, 0.90) if is_day_cloud else (0.16, 0.19, 0.28)
            # Широкое основание облака с мягкой тенью снизу
            el(0.0, -0.45, 0.0, 9.5, 1.45, 5.8, c_bot, 6, 10)
            # Боковые и центральные пышные купола кучевого облака
            el(-4.8, 0.35, 0.4, 5.2, 2.2, 4.2, c_mid, 6, 10)
            el(4.6, 0.30, -0.3, 5.0, 2.1, 4.0, c_mid, 6, 10)
            el(-1.8, 0.65, -2.2, 4.5, 2.0, 3.8, c_mid, 6, 10)
            el(2.2, 0.60, 2.1, 4.4, 1.9, 3.6, c_mid, 6, 10)
            # Высокие освещенные солнцем вершины облака
            el(-1.4, 1.45, 0.2, 5.4, 2.6, 4.4, c_top, 7, 10)
            el(2.0, 1.25, -0.2, 4.6, 2.3, 3.9, c_top, 7, 10)
            el(0.2, 2.05, 0.0, 3.8, 2.1, 3.4, c_top, 7, 10)
            glEndList()
            if is_day_cloud:
                self.gl_cloud_list_day = cid
            else:
                self.gl_cloud_list_night = cid

        # Правая рука персонажа от первого лица
        hid = glGenLists(1)
        glNewList(hid, GL_COMPILE)
        el(0.05, -0.22, 0.28, 0.062, 0.060, 0.20, (0.86, 0.68, 0.54), 6, 8)
        el(0.05, -0.22, 0.24, 0.068, 0.066, 0.12, (0.42, 0.25, 0.13), 6, 8)
        el(0.05, -0.22, 0.15, 0.070, 0.068, 0.025, (0.82, 0.68, 0.25), 5, 8)
        el(0.01, -0.12, 0.04, 0.058, 0.052, 0.068, (0.88, 0.70, 0.56), 6, 8)
        for fi in range(4):
            fz = 0.01 - fi * 0.024
            el(-0.035, -0.095, fz, 0.028, 0.018, 0.014, (0.85, 0.66, 0.52), 4, 6)
        el(0.042, -0.075, 0.02, 0.022, 0.032, 0.024, (0.86, 0.68, 0.54), 4, 6)
        glEndList()
        self.gl_hand_list = hid

        # Вторая (левая) рука лучника с кожаным наручем, удерживающая рукоять лука
        lhid = glGenLists(1)
        glNewList(lhid, GL_COMPILE)
        el(-0.18, -0.16, 0.24, 0.060, 0.058, 0.22, (0.86, 0.68, 0.54), 6, 8)
        el(-0.14, -0.13, 0.16, 0.066, 0.064, 0.13, (0.38, 0.23, 0.12), 6, 8)
        el(-0.10, -0.10, 0.08, 0.068, 0.066, 0.025, (0.82, 0.68, 0.25), 5, 8)
        el(-0.02, -0.03, -0.02, 0.052, 0.050, 0.062, (0.88, 0.70, 0.56), 6, 8)
        for fi in range(4):
            fy_f = -0.05 + fi * 0.022
            el(0.025, fy_f, -0.04, 0.026, 0.014, 0.018, (0.84, 0.65, 0.50), 4, 6)
        el(-0.035, 0.035, -0.01, 0.022, 0.028, 0.022, (0.86, 0.68, 0.54), 4, 6)
        glEndList()
        self.gl_left_hand_list = lhid

        # Детализированная 3D-стрела (гладкое древко, стальной граненый наконечник, 3 пера оперения и ушко-хвостовик)
        arr_lid = glGenLists(1)
        glNewList(arr_lid, GL_COMPILE)
        glPushMatrix()
        # Направляем цилиндрическое древко вдоль оси -Z (вперед от тетивы к цели, от z=+0.22 до z=-0.56)
        glRotatef(-90.0, 1.0, 0.0, 0.0)
        cyl(0.0, -0.22, 0.0, 0.010, 0.009, 0.76, (0.82, 0.67, 0.38), segments=10)
        # Металлическая втулка и острый кованый наконечник стрелы (broadhead)
        cyl(0.0, 0.52, 0.0, 0.013, 0.012, 0.05, (0.42, 0.45, 0.50), segments=8)
        cyl(0.0, 0.56, 0.0, 0.026, 0.002, 0.14, (0.82, 0.86, 0.92), segments=8)
        el(0.0, 0.61, 0.0, 0.030, 0.055, 0.008, (0.90, 0.94, 0.98), 5, 8)
        el(0.0, 0.61, 0.0, 0.008, 0.055, 0.030, (0.76, 0.80, 0.88), 5, 8)
        # Обмотка у оперения и 3 гусиных пера (красно-белое оперение)
        cyl(0.0, -0.14, 0.0, 0.0115, 0.0115, 0.04, (0.32, 0.18, 0.10), segments=8)
        el(0.0, -0.17, 0.022, 0.004, 0.058, 0.022, (0.92, 0.22, 0.22), 5, 6)
        el(0.019, -0.17, -0.012, 0.020, 0.058, 0.004, (0.95, 0.95, 0.92), 5, 6)
        el(-0.019, -0.17, -0.012, 0.020, 0.058, 0.004, (0.95, 0.95, 0.92), 5, 6)
        # Костяной хвостовик (nock) для фиксации на тетиве
        cyl(0.0, -0.24, 0.0, 0.012, 0.010, 0.03, (0.94, 0.92, 0.85), segments=8)
        glPopMatrix()
        glEndList()
        self.gl_arrow_3d_list = arr_lid

        # ПРЕДКОМПИЛИРОВАННЫЙ 3D-ЛУК В VIDEO RAM (устраняет просадку FPS со 100 до 30 при взятии лука в руки!):
        c_wood_bow = (0.58, 0.36, 0.16)
        c_limb_bow = (0.68, 0.44, 0.20)
        c_grip_bow = (0.34, 0.20, 0.11)
        c_horn_bow = (0.88, 0.85, 0.76)

        bow_riser = glGenLists(1)
        glNewList(bow_riser, GL_COMPILE)
        cyl(0.0, -0.10, -0.02, 0.022, 0.022, 0.20, c_grip_bow, segments=8)
        el(0.0, 0.04, -0.02, 0.026, 0.018, 0.032, c_wood_bow, 5, 7)
        el(0.0, -0.08, -0.02, 0.025, 0.016, 0.028, (0.82, 0.68, 0.25), 5, 7)
        el(0.0, 0.09, -0.02, 0.025, 0.016, 0.028, (0.82, 0.68, 0.25), 5, 7)
        glEndList()
        self.gl_bow_riser_list = bow_riser

        bow_up = glGenLists(1)
        glNewList(bow_up, GL_COMPILE)
        up_static = [
            (0.0, 0.00, 0.00, 0.021),
            (0.0, 0.12, 0.01, 0.018),
            (0.0, 0.24, 0.05, 0.015),
            (0.0, 0.34, 0.11, 0.011),
            (0.0, 0.40, 0.15, 0.008),
        ]
        for si in range(len(up_static) - 1):
            x0_s, y0_s, z0_s, r0_s = up_static[si]
            x1_s, y1_s, z1_s, r1_s = up_static[si + 1]
            dy_s, dz_s = y1_s - y0_s, z1_s - z0_s
            s_len = math.hypot(dy_s, dz_s)
            ang_x = math.degrees(math.atan2(dz_s, dy_s))
            glPushMatrix()
            glTranslatef(x0_s, y0_s, z0_s)
            glRotatef(ang_x, 1.0, 0.0, 0.0)
            cyl(0.0, 0.0, 0.0, r0_s, r1_s, s_len, c_limb_bow if si < 2 else c_wood_bow, segments=7)
            glPopMatrix()
        el(0.0, 0.40, 0.15, 0.012, 0.022, 0.014, c_horn_bow, 4, 6)
        glEndList()
        self.gl_bow_upper_limb_list = bow_up

        bow_dn = glGenLists(1)
        glNewList(bow_dn, GL_COMPILE)
        dn_static = [
            (0.0, 0.00, 0.00, 0.021),
            (0.0, -0.12, 0.01, 0.018),
            (0.0, -0.24, 0.05, 0.015),
            (0.0, -0.34, 0.11, 0.011),
            (0.0, -0.40, 0.15, 0.008),
        ]
        for si in range(len(dn_static) - 1):
            x0_s, y0_s, z0_s, r0_s = dn_static[si]
            x1_s, y1_s, z1_s, r1_s = dn_static[si + 1]
            dy_s, dz_s = y1_s - y0_s, z1_s - z0_s
            s_len = math.hypot(dy_s, dz_s)
            ang_x = math.degrees(math.atan2(dz_s, dy_s))
            glPushMatrix()
            glTranslatef(x0_s, y0_s, z0_s)
            glRotatef(ang_x, 1.0, 0.0, 0.0)
            cyl(0.0, 0.0, 0.0, r0_s, r1_s, s_len, c_limb_bow if si < 2 else c_wood_bow, segments=7)
            glPopMatrix()
        el(0.0, -0.40, 0.15, 0.012, 0.022, 0.014, c_horn_bow, 4, 6)
        glEndList()
        self.gl_bow_lower_limb_list = bow_dn

        # ПРЕДКОМПИЛИРОВАННАЯ КРУГЛАЯ 3D-СНЕЖИНКА И ЯЗЫК ПЛАМЕНИ (чтобы снег был круглым, а огонь детализированным!)
        prev_pm = MeshBuilder3D.POLY_MULT
        MeshBuilder3D.POLY_MULT = 1.0
        sn_lid = glGenLists(1)
        glNewList(sn_lid, GL_COMPILE)
        glBegin(GL_TRIANGLES)
        lat_s, lon_s = 6, 10
        for i in range(lat_s):
            la0 = math.pi * (-0.5 + float(i) / lat_s)
            la1 = math.pi * (-0.5 + float(i + 1) / lat_s)
            y0_s, r0_s = math.sin(la0), math.cos(la0)
            y1_s, r1_s = math.sin(la1), math.cos(la1)
            for j in range(lon_s):
                lo0 = 2.0 * math.pi * float(j) / lon_s
                lo1 = 2.0 * math.pi * float(j + 1) / lon_s
                x00, z00 = math.cos(lo0) * r0_s, math.sin(lo0) * r0_s
                x10, z10 = math.cos(lo1) * r0_s, math.sin(lo1) * r0_s
                x01, z01 = math.cos(lo0) * r1_s, math.sin(lo0) * r1_s
                x11, z11 = math.cos(lo1) * r1_s, math.sin(lo1) * r1_s
                glVertex3f(x00, y0_s, z00)
                glVertex3f(x10, y0_s, z10)
                glVertex3f(x11, y1_s, z11)
                glVertex3f(x00, y0_s, z00)
                glVertex3f(x11, y1_s, z11)
                glVertex3f(x01, y1_s, z01)
        glEnd()
        glEndList()
        self.gl_snowflake_list = sn_lid

        fl_cone = glGenLists(1)
        glNewList(fl_cone, GL_COMPILE)
        glBegin(GL_TRIANGLES)
        segs_f = 10
        for i in range(segs_f):
            a0 = (i / float(segs_f)) * 2.0 * math.pi
            a1 = ((i + 1) / float(segs_f)) * 2.0 * math.pi
            c0, s0 = math.cos(a0), math.sin(a0)
            c1, s1 = math.cos(a1), math.sin(a1)
            glVertex3f(0.0, 1.0, 0.0)
            glVertex3f(c0 * 0.45, 0.18, s0 * 0.45)
            glVertex3f(c1 * 0.45, 0.18, s1 * 0.45)
            glVertex3f(0.0, 0.0, 0.0)
            glVertex3f(c1 * 0.45, 0.18, s1 * 0.45)
            glVertex3f(c0 * 0.45, 0.18, s0 * 0.45)
        glEnd()
        glEndList()
        self.gl_flame_cone_list = fl_cone
        MeshBuilder3D.POLY_MULT = prev_pm

        # 1. 3D-модели всего оружия и инструментов в руке
        for wid, wspec in WEAPONS_DB.items():
            lid = glGenLists(1)
            glNewList(lid, GL_COMPILE)
            wc = wspec.color
            if wid == "rock":
                el(0.0, 0.04, -0.02, 0.11, 0.09, 0.12, wc, 5, 7)
                el(0.03, 0.08, -0.05, 0.08, 0.07, 0.08, (0.46, 0.45, 0.44), 4, 6)
            elif wid == "workbench_item":
                self._draw_gl_box(0.0, 0.12, -0.12, 0.34, 0.06, 0.24, (0.68, 0.46, 0.24))
                for lx in (-0.14, 0.14):
                    for lz in (-0.20, -0.04):
                        cyl(lx, -0.12, lz, 0.02, 0.02, 0.24, (0.48, 0.30, 0.15), segments=6)
            elif wspec.category == "axe":
                cyl(0.0, -0.24, 0.0, 0.028, 0.024, 0.72, (0.56, 0.36, 0.18), segments=10)
                cyl(0.0, -0.25, 0.0, 0.034, 0.034, 0.05, (0.35, 0.22, 0.12), segments=8)
                cyl(0.0, 0.34, 0.0, 0.036, 0.036, 0.11, (0.36, 0.22, 0.12), segments=8)
                el(0.0, 0.40, -0.08, 0.035, 0.11, 0.16, wc, 6, 8)
                el(0.0, 0.40, -0.18, 0.015, 0.15, 0.08, (0.88, 0.92, 0.96) if wid == "iron_axe" else (0.75, 0.73, 0.70), 6, 8)
                if wid == "iron_axe":
                    el(0.0, 0.40, 0.10, 0.025, 0.10, 0.12, wc, 6, 8)
            elif wid == "stone_pickaxe":
                cyl(0.0, -0.24, 0.0, 0.026, 0.024, 0.70, (0.54, 0.35, 0.17), segments=10)
                cyl(0.0, 0.36, 0.0, 0.038, 0.038, 0.09, (0.32, 0.34, 0.38), segments=8)
                el(0.0, 0.40, -0.14, 0.028, 0.042, 0.20, wc, 5, 8)
                el(0.0, 0.37, 0.14, 0.025, 0.038, 0.18, wc, 5, 8)
            elif wspec.category == "spear":
                # ИСПРАВЛЕННОЕ ЦЕЛЬНОЕ 3D-КОПЬЕ: единое прямое древко, кожаная обмотка и острый листовидный наконечник!
                glPushMatrix()
                glTranslatef(0.0, -0.06, 0.06)
                glRotatef(-68.0, 1.0, 0.0, 0.0)
                cyl(0.0, -0.42, 0.0, 0.022, 0.019, 1.52, (0.58, 0.38, 0.20), segments=10)
                cyl(0.0, -0.08, 0.0, 0.026, 0.026, 0.26, (0.34, 0.20, 0.11), segments=10)
                cyl(0.0, 1.04, 0.0, 0.026, 0.024, 0.07, (0.36, 0.38, 0.42), segments=10)
                cyl(0.0, 1.10, 0.0, 0.040, 0.002, 0.32, (0.82, 0.86, 0.92), segments=8)
                el(0.0, 1.18, 0.0, 0.046, 0.10, 0.016, (0.88, 0.92, 0.96), 5, 8)
                glPopMatrix()
            elif wspec.category == "sword":
                cyl(0.0, -0.22, 0.0, 0.024, 0.024, 0.24, (0.36, 0.20, 0.11), segments=8)
                el(0.0, -0.24, 0.0, 0.038, 0.038, 0.038, (0.88, 0.72, 0.24), 5, 8)
                el(0.0, 0.02, 0.0, 0.15, 0.028, 0.042, (0.88, 0.72, 0.24), 5, 8)
                el(0.0, 0.02, 0.0, 0.038, 0.038, 0.048, (0.25, 0.88, 1.00) if wid == "mythril_blade" else (0.92, 0.25, 0.22), 5, 6)
                el(0.0, 0.44, 0.0, 0.022, 0.42, 0.055, wc, 6, 8)
                cyl(0.0, 0.78, 0.0, 0.042, 0.002, 0.24, (0.94, 0.98, 1.00), segments=6)
            elif wid == "fishing_rod":
                # ИСПРАВЛЕННАЯ ЦЕЛЬНАЯ 3D-УДОЧКА: единое гладкое конусное удилище без разрывов, с катушкой, кольцами и леской!
                glPushMatrix()
                glTranslatef(0.0, -0.05, 0.04)
                glRotatef(-52.0, 1.0, 0.0, 0.0)
                # Пробковая/деревянная рукоять удочки
                cyl(0.0, -0.32, 0.0, 0.026, 0.023, 0.38, (0.44, 0.27, 0.14), segments=10)
                cyl(0.0, 0.04, 0.0, 0.025, 0.022, 0.06, (0.32, 0.35, 0.40), segments=10)
                # Инерционная рыболовная катушка сбоку рукояти с золотистой шпулей и ручкой
                el(0.045, -0.02, -0.03, 0.032, 0.056, 0.056, (0.74, 0.78, 0.84), 6, 8)
                el(0.062, -0.02, -0.03, 0.018, 0.040, 0.040, (0.94, 0.78, 0.24), 5, 8)
                cyl(0.072, -0.02, -0.03, 0.008, 0.008, 0.06, (0.28, 0.30, 0.34), segments=6)
                # Единый плавно сужающийся бланк удилища (от комля y=0.08 до самой вершинки y=1.42 без ступенек и разрывов!)
                cyl(0.0, 0.08, 0.0, 0.019, 0.011, 0.68, wc, segments=10)
                cyl(0.0, 0.74, 0.0, 0.011, 0.004, 0.68, (0.86, 0.72, 0.40), segments=10)
                # Пропускные кольца вдоль удилища
                for gy_r, gr_r in [(0.42, 0.018), (0.78, 0.015), (1.12, 0.012), (1.38, 0.010)]:
                    el(0.0, gy_r, -0.018, gr_r, gr_r * 0.45, gr_r, (0.82, 0.86, 0.92), 4, 6)
                glPopMatrix()
            elif wid == "hammer":
                cyl(0.0, -0.22, 0.0, 0.026, 0.024, 0.62, (0.54, 0.35, 0.17), segments=8)
                MeshBuilder3D.emit_gl_cylinder(0.0, 0.34, 0.0, 0.085, 0.085, 0.34, wc, segments=10, horizontal_x=True)
            elif wspec.category == "bow":
                # 3D-модель Охотничьего лука со стрелой (для отображения выброшенного на землю лука!)
                glPushMatrix()
                glRotatef(75.0, 0.0, 0.0, 1.0)
                c_wood_b = (0.58, 0.36, 0.16)
                c_limb_b = (0.68, 0.44, 0.20)
                c_grip_b = (0.34, 0.20, 0.11)
                c_horn_b = (0.88, 0.85, 0.76)
                cyl(0.0, -0.10, 0.0, 0.024, 0.024, 0.20, c_grip_b, segments=10)
                up_b = [(0.0, 0.08, 0.0, 0.022), (0.0, 0.22, 0.02, 0.019), (0.0, 0.36, 0.07, 0.015), (0.0, 0.48, 0.14, 0.010)]
                dn_b = [(0.0, -0.08, 0.0, 0.022), (0.0, -0.22, 0.02, 0.019), (0.0, -0.36, 0.07, 0.015), (0.0, -0.48, 0.14, 0.010)]
                for s_pts in (up_b, dn_b):
                    for si in range(len(s_pts) - 1):
                        x0_s, y0_s, z0_s, r0_s = s_pts[si]
                        x1_s, y1_s, z1_s, r1_s = s_pts[si + 1]
                        dy_s, dz_s = y1_s - y0_s, z1_s - z0_s
                        s_len = math.hypot(dy_s, dz_s)
                        ang_x = math.degrees(math.atan2(dz_s, dy_s))
                        glPushMatrix()
                        glTranslatef(x0_s, y0_s, z0_s)
                        glRotatef(ang_x, 1.0, 0.0, 0.0)
                        cyl(0.0, 0.0, 0.0, r0_s, r1_s, s_len, c_limb_b if si < 2 else c_wood_b, segments=8)
                        glPopMatrix()
                el(0.0, 0.48, 0.14, 0.014, 0.022, 0.016, c_horn_b, 4, 6)
                el(0.0, -0.48, 0.14, 0.014, 0.022, 0.016, c_horn_b, 4, 6)
                glDisable(GL_LIGHTING)
                glColor3f(0.95, 0.94, 0.88)
                glLineWidth(2.0)
                glBegin(GL_LINES)
                glVertex3f(0.0, 0.48, 0.14)
                glVertex3f(0.0, -0.48, 0.14)
                glEnd()
                glEnable(GL_LIGHTING)
                glPopMatrix()
            elif wid == "torch":
                cyl(0.0, -0.22, 0.0, 0.028, 0.032, 0.48, (0.48, 0.30, 0.14), segments=8)
                el(0.0, 0.28, 0.0, 0.06, 0.09, 0.06, (1.0, 0.58, 0.12), 5, 8)
            glEndList()
            self.gl_weapon_lists[wid] = lid

        # 2. 3D-модели ВСЕХ ресурсов, руд, еды и предметов в руке (чтобы при переключении со слота копья на золотую руду в руке была именно золотая руда!)
        for rkey in RESOURCE_NAMES_RU:
            if rkey in self.gl_weapon_lists:
                continue
            lid = glGenLists(1)
            glNewList(lid, GL_COMPILE)
            ic = RESOURCE_ICON_COLORS.get(rkey, (180, 180, 180))
            fc = (ic[0] / 255.0, ic[1] / 255.0, ic[2] / 255.0)
            if rkey == "wood":
                cyl(0.0, -0.08, -0.04, 0.065, 0.065, 0.38, (0.55, 0.35, 0.18), segments=10)
                el(0.0, 0.30, -0.04, 0.064, 0.012, 0.064, (0.86, 0.72, 0.48), 4, 8)
            elif rkey in ("stone", "coal", "copper", "iron", "gold", "mythril"):
                # Кусок породы с яркими кристаллами соответствующей руды в ладони!
                base_rock = (0.22, 0.24, 0.28) if rkey == "coal" else (0.48, 0.49, 0.52)
                el(0.0, 0.05, -0.04, 0.11, 0.095, 0.11, base_rock, 6, 8)
                if rkey != "stone":
                    for cx_o, cy_o, cz_o, r_o in [
                        (-0.04, 0.11, -0.06, 0.048),
                        (0.05, 0.09, -0.02, 0.044),
                        (0.01, 0.06, -0.11, 0.042),
                    ]:
                        el(cx_o, cy_o, cz_o, r_o, r_o * 1.35, r_o, fc, 5, 7)
            elif rkey == "berries":
                el(0.0, 0.09, -0.04, 0.08, 0.04, 0.08, (0.20, 0.65, 0.25), 5, 7)
                for bx_o, by_o, bz_o in [(-0.04, 0.05, -0.04), (0.04, 0.05, -0.04), (0.0, 0.03, -0.08)]:
                    el(bx_o, by_o, bz_o, 0.048, 0.048, 0.048, (0.92, 0.16, 0.26), 5, 7)
            elif rkey == "mushroom":
                cyl(0.0, -0.06, -0.04, 0.035, 0.028, 0.16, (0.94, 0.90, 0.82), segments=8)
                el(0.0, 0.11, -0.04, 0.10, 0.055, 0.10, (0.84, 0.26, 0.18), 6, 8)
            elif rkey == "apple":
                el(0.0, 0.05, -0.04, 0.095, 0.095, 0.095, (0.92, 0.18, 0.16), 6, 8)
                cyl(0.0, 0.13, -0.04, 0.010, 0.008, 0.05, (0.45, 0.28, 0.14), segments=6)
            elif rkey in ("raw_fish", "cooked_fish"):
                el(0.0, 0.06, -0.05, 0.055, 0.085, 0.19, fc, 6, 8)
                el(0.0, 0.06, 0.14, 0.02, 0.09, 0.07, fc, 4, 6)
            elif rkey in ("raw_meat", "cooked_meat"):
                el(0.0, 0.05, -0.04, 0.11, 0.055, 0.14, fc, 6, 8)
                el(0.0, 0.06, -0.04, 0.035, 0.062, 0.035, (0.96, 0.94, 0.88), 5, 6)
            elif rkey == "hunter_stew":
                cyl(0.0, -0.02, -0.04, 0.09, 0.12, 0.10, (0.54, 0.34, 0.18), segments=10)
                el(0.0, 0.07, -0.04, 0.105, 0.025, 0.105, (0.96, 0.72, 0.22), 5, 8)
            elif rkey == "salve":
                cyl(0.0, -0.04, -0.04, 0.065, 0.065, 0.14, (0.24, 0.88, 0.48), segments=10)
                cyl(0.0, 0.10, -0.04, 0.030, 0.030, 0.05, (0.68, 0.48, 0.26), segments=8)
            elif rkey == "fur_armor":
                self._draw_gl_box(0.0, 0.06, -0.05, 0.22, 0.14, 0.18, fc)
                self._draw_gl_box(0.0, 0.06, -0.05, 0.23, 0.04, 0.19, (0.36, 0.22, 0.12))
            elif rkey == "arrow":
                glPushMatrix()
                glRotatef(-55.0, 1.0, 0.0, 0.0)
                cyl(0.0, -0.20, 0.0, 0.012, 0.012, 0.65, (0.78, 0.64, 0.38), segments=8)
                cyl(0.0, 0.45, 0.0, 0.026, 0.002, 0.12, (0.78, 0.82, 0.88), segments=6)
                glPopMatrix()
            else:
                el(0.0, 0.05, -0.04, 0.10, 0.08, 0.11, fc, 6, 8)
            glEndList()
            self.gl_weapon_lists[rkey] = lid

    def _compile_detailed_resource_meshes(self) -> None:
        """
        Компилирует 4 ПОЛНОСТЬЮ РАЗЛИЧАЮЩИХСЯ уровня 3D-детализации для всех объектов природы (self.gl_resource_lists_tiers[0..3]):
          - Уровень 0 (Низкая): угловатые Low-Poly примитивы (POLY_MULT=0.65, без текстур, 1 купол кроны, 2 травинки, 1 валун без мха).
          - Уровень 1 (Средняя): стандартные 3D-модели с текстурами (POLY_MULT=1.10, 3 яруса хвои / 3 купола кроны, 4 травинки, 2 валуна, без корней и цветов).
          - Уровень 2 (Высокая): детальные 3D-модели (POLY_MULT=1.65, 3 корня, 2 ветви, 5 ярусов хвои / 5 куполов кроны, 7 травинок + ромашки/васильки, мох на камнях).
          - Уровень 3 (Ультра HD): максимальный реализм и полигонаж (POLY_MULT=2.40, 6 мощных корней, 4 ветви, 7 ярусов хвои с шишками / 9 рельефных куполов кроны, 10 яблок с листочками, 10 травинок + ромашки, васильки, маки и лютики, 5-глыбовые скалы с россыпью камней и 6 кристаллами руды)!
        """
        tex_bark = self.tex_pack.textures.get("bark", 0)
        tex_foliage = self.tex_pack.textures.get("foliage", 0)
        tex_rock = self.tex_pack.textures.get("rock", 0)
        cyl = MeshBuilder3D.emit_gl_cylinder
        el = MeshBuilder3D.emit_gl_ellipsoid

        sh_lid = glGenLists(1)
        glNewList(sh_lid, GL_COMPILE)
        MeshBuilder3D.emit_gl_ground_shadow_disc(0.0, 0.0, 0.0, 1.0, alpha=0.32, segments=20)
        glEndList()
        self.gl_shadow_disc_list = sh_lid

        ore_configs = [
            ("stone_rock", (0.53, 0.54, 0.56), None),
            ("coal_vein", (0.40, 0.41, 0.44), (0.11, 0.12, 0.14)),
            ("copper_vein", (0.48, 0.46, 0.44), (0.90, 0.50, 0.24)),
            ("iron_vein", (0.45, 0.44, 0.48), (0.80, 0.62, 0.46)),
            ("gold_vein", (0.46, 0.45, 0.42), (1.00, 0.84, 0.18)),
            ("mythril_vein", (0.38, 0.46, 0.55), (0.28, 0.90, 1.00)),
        ]

        for tier in (0, 1, 2, 3):
            MeshBuilder3D.POLY_MULT = (0.65, 1.10, 1.65, 2.40)[tier]
            tdict: Dict[str, int] = {}
            use_tex = tier >= 1

            # 1. Трава (2 стебля на Низкой, 4 на Средней, 7 на Высокой, 10 на Ультра HD)
            all_blades = [
                (0.0, 0.0, 0.66, (0.22, 0.64, 0.20)),
                (-0.17, 0.11, 0.56, (0.18, 0.55, 0.18)),
                (0.17, -0.10, 0.60, (0.28, 0.70, 0.23)),
                (-0.11, -0.15, 0.50, (0.20, 0.60, 0.20)),
                (0.13, 0.15, 0.54, (0.31, 0.73, 0.25)),
                (-0.22, -0.02, 0.44, (0.17, 0.52, 0.17)),
                (0.04, 0.21, 0.48, (0.26, 0.68, 0.22)),
                (0.21, 0.04, 0.46, (0.24, 0.65, 0.21)),
                (-0.06, 0.24, 0.52, (0.25, 0.67, 0.22)),
                (0.19, -0.19, 0.49, (0.21, 0.59, 0.19)),
            ]
            blade_count = (2, 4, 7, 10)[tier]
            lid = glGenLists(1)
            glNewList(lid, GL_COMPILE)
            for gx, gz, gh, gc in all_blades[:blade_count]:
                cyl(gx, -0.05, gz, 0.055, 0.004, gh, gc, segments=5)
            glEndList()
            tdict["grass_tuft"] = lid

            # Цветы: на Низкой (0) и Средней (1) цветов нет; на Высокой (2) — ромашки и васильки; на Ультра HD (3) — многолепестковые ромашки, васильки, маки и лютики!
            if tier <= 1:
                tdict["grass_flower_1"] = lid
                tdict["grass_flower_2"] = lid
            else:
                fl1 = glGenLists(1)
                glNewList(fl1, GL_COMPILE)
                glCallList(lid)
                cyl(-0.08, -0.04, 0.06, 0.018, 0.014, 0.58, (0.20, 0.58, 0.18), segments=6)
                if tier == 2:
                    el(-0.08, 0.55, 0.06, 0.11, 0.035, 0.11, (0.98, 0.98, 0.96), 4, 8)
                else:
                    for p_i in range(6):
                        pa = p_i * math.pi / 3.0
                        el(-0.08 + math.cos(pa) * 0.075, 0.55, 0.06 + math.sin(pa) * 0.075, 0.048, 0.022, 0.048, (0.99, 0.99, 0.97), 5, 8)
                el(-0.08, 0.57, 0.06, 0.046, 0.036, 0.046, (0.98, 0.82, 0.14), 5, 8)
                cyl(0.12, -0.04, -0.08, 0.016, 0.012, 0.50, (0.18, 0.54, 0.18), segments=6)
                el(0.12, 0.47, -0.08, 0.090, 0.058, 0.090, (0.32, 0.54, 0.98), 5, 8)
                glEndList()
                tdict["grass_flower_1"] = fl1

                if tier == 2:
                    tdict["grass_flower_2"] = fl1
                else:
                    fl2 = glGenLists(1)
                    glNewList(fl2, GL_COMPILE)
                    glCallList(lid)
                    cyl(0.06, -0.04, 0.05, 0.018, 0.014, 0.60, (0.20, 0.58, 0.18), segments=6)
                    for p_i in range(5):
                        pa = p_i * 2.0 * math.pi / 5.0
                        el(0.06 + math.cos(pa) * 0.065, 0.57, 0.05 + math.sin(pa) * 0.065, 0.055, 0.032, 0.055, (0.95, 0.16, 0.18), 5, 8)
                    el(0.06, 0.59, 0.05, 0.040, 0.034, 0.040, (0.14, 0.11, 0.11), 5, 8)
                    cyl(-0.13, -0.04, -0.06, 0.015, 0.012, 0.48, (0.20, 0.58, 0.18), segments=6)
                    el(-0.13, 0.45, -0.06, 0.082, 0.045, 0.082, (0.99, 0.85, 0.12), 5, 8)
                    glEndList()
                    tdict["grass_flower_2"] = fl2

            # 2. Сосна (pine) и Заснеженная ель (snow_pine) — ПОДНЯТАЯ ВЫШЕ ХВОЯ И ВИДИМЫЕ НИЖНИЕ ВЕТВИ!
            for is_snow in (False, True):
                lid = glGenLists(1)
                glNewList(lid, GL_COMPILE)
                if use_tex:
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, tex_bark)
                p_trunk_c = (0.38, 0.25, 0.16) if is_snow else (0.44, 0.28, 0.15)
                cyl(0, -0.05, 0, 0.44, 0.16, 4.35, p_trunk_c, segments=8)
                if tier >= 1:
                    p_branches = [(25.0, 52.0, 1.85), (145.0, 50.0, 2.05), (265.0, 54.0, 2.25)]
                    if tier >= 2:
                        p_branches.extend([(85.0, 48.0, 2.45), (205.0, 50.0, 2.60), (325.0, 46.0, 2.75)])
                    for b_yaw, b_pitch, b_y in p_branches:
                        glPushMatrix()
                        glTranslatef(0.0, b_y, 0.0)
                        glRotatef(b_yaw, 0.0, 1.0, 0.0)
                        glRotatef(b_pitch, 1.0, 0.0, 0.0)
                        cyl(0.0, 0.0, 0.0, 0.11, 0.04, 1.15, p_trunk_c, segments=6)
                        glPopMatrix()
                if tier >= 2:
                    roots_p = [(0.26, 0.0), (-0.24, 0.12), (0.08, -0.25)] if tier == 2 else [
                        (0.28, 0.0), (-0.26, 0.14), (0.10, -0.27), (-0.12, 0.26), (0.22, 0.20), (-0.22, -0.20)
                    ]
                    for rx_r, rz_r in roots_p:
                        el(rx_r, 0.08, rz_r, 0.25, 0.14, 0.18, (0.36, 0.22, 0.12), 5, 7)
                if use_tex:
                    glBindTexture(GL_TEXTURE_2D, tex_foliage)
                if tier == 0:
                    cyl(0, 2.55, 0, 1.65, 0.05, 3.8, (0.88, 0.94, 0.99) if is_snow else (0.15, 0.46, 0.20), segments=5)
                elif tier == 1:
                    for y_t, rb, ht in [(2.55, 1.70, 1.65), (3.75, 1.32, 1.55), (4.90, 0.85, 1.45)]:
                        cyl(0, y_t, 0, rb, rb * 0.12, ht, (0.16, 0.44, 0.28) if is_snow else (0.15, 0.46, 0.20), segments=7)
                        if is_snow:
                            cyl(0, y_t + 0.3, 0, rb * 0.90, rb * 0.10, ht * 0.75, (0.93, 0.97, 1.0), segments=7)
                else:
                    pine_tiers = [
                        (2.50, 1.85, 0.35, 1.32, (0.09, 0.32, 0.14), (0.14, 0.44, 0.19)),
                        (3.32, 1.62, 0.30, 1.28, (0.11, 0.36, 0.16), (0.16, 0.48, 0.21)),
                        (4.12, 1.36, 0.24, 1.22, (0.13, 0.40, 0.18), (0.19, 0.53, 0.24)),
                        (4.88, 1.08, 0.18, 1.18, (0.15, 0.44, 0.20), (0.22, 0.58, 0.26)),
                        (5.60, 0.78, 0.08, 1.12, (0.18, 0.48, 0.22), (0.25, 0.62, 0.29)),
                    ]
                    if tier == 3:
                        pine_tiers.append((6.25, 0.48, 0.01, 1.05, (0.20, 0.52, 0.24), (0.28, 0.66, 0.32)))
                    for y_t, rb, rt, ht, c_sh, c_lit in pine_tiers:
                        cyl(0, y_t - 0.08, 0, rb * 0.96, rt, ht * 0.45, c_sh, segments=10)
                        cyl(0, y_t, 0, rb, rt, ht, (0.94, 0.98, 1.0) if is_snow else c_lit, segments=10)
                    if tier == 3 and not is_snow:
                        for pc_x, pc_y, pc_z in [(0.95, 2.65, 0.65), (-0.88, 2.70, -0.72), (0.62, 3.45, -0.85), (-0.70, 3.50, 0.78)]:
                            el(pc_x, pc_y, pc_z, 0.09, 0.16, 0.09, (0.38, 0.23, 0.12), 5, 7)
                if use_tex:
                    glDisable(GL_TEXTURE_2D)
                glEndList()
                tdict["snow_pine" if is_snow else "pine"] = lid

            # 3. Лиственные деревья: Дуб (oak), Яблоня (apple_tree), Осенний клен (autumn_oak), Береза (birch)
            # Листва поднята на +1.25 м выше, а из ствола расходятся длинные раскидистые ветви и развилки сучьев, полностью открытые взгляду!
            for t_kind in ("oak", "apple_tree", "autumn_oak", "birch"):
                lid = glGenLists(1)
                glNewList(lid, GL_COMPILE)
                if use_tex:
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, tex_bark)
                if t_kind == "birch":
                    b_col = (0.94, 0.92, 0.88)
                    cyl(0, -0.05, 0, 0.30, 0.14, 4.25, b_col, segments=8)
                    if tier >= 1:
                        cyl(0, -0.05, 0, 0.31, 0.25, 0.65, (0.24, 0.23, 0.22), segments=8)
                    if tier >= 2:
                        bands = (1.0, 1.8, 2.6, 3.3) if tier == 2 else (0.85, 1.35, 1.85, 2.35, 2.85, 3.35, 3.80)
                        for by_b in bands:
                            rb = max(0.14, 0.26 - by_b * 0.025)
                            cyl(0, by_b, 0, rb, rb * 0.98, 0.08, (0.18, 0.17, 0.16), segments=8)
                    b_branches = [(30.0, 42.0, 2.55, 1.35), (155.0, 40.0, 2.80, 1.30), (275.0, 44.0, 3.05, 1.25)]
                    if tier >= 2:
                        b_branches.extend([(95.0, 38.0, 3.25, 1.20), (215.0, 42.0, 3.40, 1.15)])
                    for b_yaw, b_pitch, b_y, b_len in b_branches[: (2 if tier == 0 else len(b_branches))]:
                        glPushMatrix()
                        glTranslatef(0.0, b_y, 0.0)
                        glRotatef(b_yaw, 0.0, 1.0, 0.0)
                        glRotatef(b_pitch, 1.0, 0.0, 0.0)
                        cyl(0.0, 0.0, 0.0, 0.10, 0.04, b_len, b_col, segments=6)
                        glPopMatrix()
                else:
                    t_col = (0.38, 0.24, 0.13) if t_kind == "oak" else ((0.42, 0.26, 0.14) if t_kind == "apple_tree" else (0.34, 0.21, 0.12))
                    cyl(0, -0.05, 0, 0.50, 0.22, 3.85, t_col, segments=8)
                    if tier >= 2:
                        r_list = [(0.34, 0.08), (-0.32, 0.14), (0.06, -0.34)] if tier == 2 else [
                            (0.36, 0.08), (-0.34, 0.14), (0.06, -0.36), (-0.12, 0.34), (0.28, -0.24), (-0.28, -0.22)
                        ]
                        for rx_r, rz_r in r_list:
                            el(rx_r, 0.10, rz_r, 0.28, 0.16, 0.22, t_col, 5, 7)
                    br_list = [
                        (25.0, 48.0, 2.35, 1.65),
                        (115.0, 46.0, 2.55, 1.60),
                        (205.0, 50.0, 2.45, 1.65),
                        (295.0, 47.0, 2.65, 1.55),
                        (68.0, 40.0, 3.05, 1.40),
                        (248.0, 42.0, 3.15, 1.40),
                    ]
                    use_br_cnt = 2 if tier == 0 else (3 if tier == 1 else (4 if tier == 2 else 6))
                    for b_yaw, b_pitch, b_y, b_len in br_list[:use_br_cnt]:
                        glPushMatrix()
                        glTranslatef(0.0, b_y, 0.0)
                        glRotatef(b_yaw, 0.0, 1.0, 0.0)
                        glRotatef(b_pitch, 1.0, 0.0, 0.0)
                        cyl(0.0, 0.0, 0.0, 0.18, 0.07, b_len, t_col, segments=7)
                        if tier >= 2:
                            glTranslatef(0.0, b_len * 0.58, 0.0)
                            glRotatef(28.0, 0.0, 0.0, 1.0)
                            cyl(0.0, 0.0, 0.0, 0.09, 0.04, b_len * 0.55, t_col, segments=6)
                        glPopMatrix()

                if use_tex:
                    glBindTexture(GL_TEXTURE_2D, tex_foliage)

                if t_kind == "autumn_oak":
                    all_lobes = [
                        (0.0, 4.85, 0.0, 1.75, (0.86, 0.48, 0.12)),
                        (-0.98, 4.55, -0.58, 1.22, (0.80, 0.30, 0.10)),
                        (0.95, 4.65, 0.60, 1.24, (0.92, 0.58, 0.14)),
                        (0.0, 5.55, 0.18, 1.38, (0.98, 0.72, 0.16)),
                        (-0.48, 5.85, -0.25, 1.08, (0.95, 0.64, 0.15)),
                        (0.72, 4.75, -0.88, 1.14, (0.84, 0.40, 0.11)),
                        (-0.75, 4.80, 0.86, 1.14, (0.90, 0.52, 0.13)),
                        (0.45, 5.95, 0.30, 1.04, (1.00, 0.78, 0.18)),
                    ]
                elif t_kind == "birch":
                    all_lobes = [
                        (0.0, 4.85, 0.0, 1.32, (0.34, 0.65, 0.22)),
                        (-0.62, 5.25, -0.35, 0.96, (0.40, 0.70, 0.25)),
                        (0.58, 5.50, 0.30, 0.94, (0.46, 0.75, 0.28)),
                        (0.52, 4.65, -0.50, 0.92, (0.32, 0.62, 0.20)),
                        (-0.55, 4.70, 0.52, 0.92, (0.38, 0.68, 0.24)),
                        (0.0, 5.95, 0.0, 0.88, (0.50, 0.78, 0.30)),
                    ]
                else:
                    all_lobes = [
                        (0.0, 4.75, 0.0, 1.80, (0.16, 0.46, 0.15)),
                        (-1.12, 4.55, 0.68, 1.24, (0.18, 0.50, 0.17)),
                        (1.12, 4.60, -0.62, 1.24, (0.20, 0.54, 0.18)),
                        (0.0, 5.50, 0.0, 1.56, (0.24, 0.59, 0.21)),
                        (-0.62, 4.70, -0.98, 1.18, (0.17, 0.48, 0.16)),
                        (0.72, 4.75, 0.96, 1.18, (0.22, 0.56, 0.19)),
                        (-0.65, 5.75, 0.35, 1.12, (0.27, 0.63, 0.23)),
                        (0.48, 6.00, -0.22, 1.14, (0.31, 0.67, 0.25)),
                    ]

                lobe_cnt = (1, 3, 5, len(all_lobes))[tier]
                rough_v = (0.0, 0.0, 0.05, 0.10)[tier]
                for cx_l, cy_l, cz_l, r_l, col_l in all_lobes[:lobe_cnt]:
                    el(cx_l, cy_l, cz_l, r_l, r_l * 0.76, r_l, col_l, 7, 10, roughness=rough_v)
                if use_tex:
                    glDisable(GL_TEXTURE_2D)

                if t_kind == "apple_tree" and tier >= 1:
                    apples = [
                        (-1.12, 4.25, 0.92), (1.08, 4.42, -0.82), (0.42, 3.95, 1.26), (-0.52, 5.08, -1.02),
                        (1.22, 4.15, 0.52), (-1.18, 4.35, -0.48), (0.18, 4.95, 1.16), (0.72, 5.25, 0.55),
                        (-0.78, 5.35, 0.68), (0.88, 5.05, -0.58),
                    ]
                    ap_cnt = (0, 3, 6, 10)[tier]
                    for ax, ay, az in apples[:ap_cnt]:
                        el(ax, ay, az, 0.17, 0.18, 0.17, (0.94, 0.15, 0.15), 5, 7)
                glEndList()
                tdict[t_kind] = lid

            # 4. Кусты и грибы
            for b_kind, is_berry in (("berry_bush", True), ("wild_bush", False)):
                lid = glGenLists(1)
                glNewList(lid, GL_COMPILE)
                if use_tex:
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, tex_foliage)
                b_lobes = [(0.0, 0.52, 0.0, 0.84, (0.18, 0.50, 0.18)), (0.38, 0.44, 0.26, 0.56, (0.22, 0.56, 0.22)), (-0.38, 0.44, -0.24, 0.55, (0.20, 0.53, 0.20)), (0.0, 0.78, 0.0, 0.54, (0.26, 0.62, 0.24))]
                for bx_l, by_l, bz_l, br_l, bc_l in b_lobes[:(1, 2, 3, 4)[tier]]:
                    el(bx_l, by_l, bz_l, br_l, br_l * 0.70, br_l, bc_l, 6, 9, roughness=(0.0, 0.0, 0.05, 0.09)[tier])
                if use_tex:
                    glDisable(GL_TEXTURE_2D)
                if is_berry and tier >= 1:
                    berries = [(-0.35, 0.75, 0.35), (0.35, 0.80, -0.25), (0.10, 0.95, 0.30), (-0.25, 0.65, -0.38), (0.45, 0.58, 0.32), (-0.42, 0.62, 0.12)]
                    for bx, by, bz in berries[:(0, 2, 4, 6)[tier]]:
                        el(bx, by, bz, 0.12, 0.12, 0.12, (0.94, 0.14, 0.22), 5, 7)
                glEndList()
                tdict[b_kind] = lid

            lid = glGenLists(1)
            glNewList(lid, GL_COMPILE)
            m_list = [
                (0.0, 0.0, 1.05, (0.56, 0.35, 0.17), False),
                (0.38, 0.28, 0.82, (0.88, 0.20, 0.16), True),
                (-0.32, 0.24, 0.75, (0.62, 0.40, 0.20), False),
                (0.12, -0.34, 0.65, (0.86, 0.22, 0.18), True),
            ]
            for mx, mz, mscale, cap_col, is_amanita in m_list[:(1, 2, 3, 4)[tier]]:
                cyl(mx, -0.02, mz, 0.10 * mscale, 0.075 * mscale, 0.40 * mscale, (0.95, 0.92, 0.85), segments=7)
                el(mx, 0.40 * mscale, mz, 0.27 * mscale, 0.15 * mscale, 0.27 * mscale, cap_col, 6, 9)
                if is_amanita and tier >= 2:
                    for sx_d, sz_d in [(-0.08, 0.05), (0.08, -0.04), (0.0, 0.09)]:
                        el(mx + sx_d * mscale, 0.50 * mscale, mz + sz_d * mscale, 0.04 * mscale, 0.025 * mscale, 0.04 * mscale, (0.98, 0.98, 0.96), 4, 5)
            glEndList()
            tdict["mushroom_patch"] = lid

            # 5. Камни и рудные жилы (1 глыба на Низкой, 2 на Средней, 3 со мхом на Высокой, 5 с россыпью камней и 6 кристаллами на Ультра HD!)
            for okind, base_c, vein_c in ore_configs:
                lid = glGenLists(1)
                glNewList(lid, GL_COMPILE)
                if use_tex:
                    glEnable(GL_TEXTURE_2D)
                    glBindTexture(GL_TEXTURE_2D, tex_rock)
                r_rough = (0.0, 0.04, 0.10, 0.16)[tier]
                el(0.0, 0.52, 0.0, 0.98, 0.76, 0.88, base_c, 7, 10, roughness=r_rough)
                if tier >= 1:
                    el(0.46, 0.36, 0.26, 0.60, 0.50, 0.56, (base_c[0] * 0.90, base_c[1] * 0.90, base_c[2] * 0.92), 6, 9, roughness=r_rough)
                if tier >= 2:
                    el(-0.42, 0.30, -0.24, 0.52, 0.42, 0.48, (base_c[0] * 0.84, base_c[1] * 0.84, base_c[2] * 0.86), 6, 8, roughness=r_rough)
                if tier == 3:
                    el(0.18, 0.22, -0.58, 0.40, 0.30, 0.38, (base_c[0] * 0.78, base_c[1] * 0.78, base_c[2] * 0.80), 6, 8, roughness=r_rough)
                    el(-0.56, 0.18, 0.36, 0.34, 0.25, 0.32, (base_c[0] * 0.76, base_c[1] * 0.76, base_c[2] * 0.78), 5, 7, roughness=r_rough)
                if use_tex:
                    glDisable(GL_TEXTURE_2D)
                if okind == "stone_rock" and tier >= 2:
                    el(-0.12, 1.08, 0.08, 0.52, 0.16, 0.46, (0.22, 0.52, 0.20), 5, 8)
                    if tier == 3:
                        el(0.38, 0.72, 0.22, 0.32, 0.12, 0.28, (0.25, 0.56, 0.22), 5, 7)
                if vein_c is not None:
                    crystals = [
                        (0.24, 0.44, 0.18, 0.28, 0.86),
                        (-0.28, 0.38, -0.22, 0.25, 0.76),
                        (0.05, 0.58, -0.28, 0.22, 0.70),
                        (-0.15, 0.62, 0.26, 0.18, 0.64),
                        (0.42, 0.32, -0.12, 0.16, 0.58),
                        (-0.36, 0.28, 0.18, 0.15, 0.54),
                    ]
                    for vx, vy, vz, vr, vh in crystals[:(1, 2, 4, 6)[tier]]:
                        cyl(vx, vy, vz, vr, 0.02, vh, vein_c, segments=6)
                glEndList()
                tdict[okind] = lid

            # 6. Горная пещера
            lid = glGenLists(1)
            glNewList(lid, GL_COMPILE)
            if use_tex:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tex_rock)
            el(-2.4, 1.8, 0.0, 1.35, 2.25, 3.25, (0.34, 0.35, 0.38), 6, 9)
            el(2.4, 1.8, 0.0, 1.35, 2.25, 3.25, (0.34, 0.35, 0.38), 6, 9)
            el(0.0, 3.6, 0.0, 3.25, 1.25, 3.45, (0.38, 0.39, 0.42), 6, 9)
            el(0.0, 1.8, -2.8, 2.85, 2.25, 1.25, (0.20, 0.21, 0.24), 6, 9)
            if use_tex:
                glDisable(GL_TEXTURE_2D)
            if tier >= 1:
                for sx, sz in [(-1.1, 0.8), (0.9, 1.1), (0.0, -0.6), (-0.8, -1.2), (1.1, -0.9)][: (2 if tier == 1 else 5)]:
                    cyl(sx, 2.3, sz, 0.03, 0.22, 0.95, (0.28, 0.30, 0.34), segments=6)
            cyl(-1.4, 0.2, -1.2, 0.24, 0.02, 0.95, (0.25, 0.90, 1.00), segments=6)
            cyl(1.4, 0.2, -1.0, 0.22, 0.02, 0.90, (1.00, 0.84, 0.20), segments=6)
            glEndList()
            tdict["cave_grotto"] = lid

            self.gl_resource_lists_tiers[tier] = tdict

        MeshBuilder3D.POLY_MULT = 2.2
        self.gl_resource_lists = dict(self.gl_resource_lists_tiers[3])
        self.gl_resource_lists_low = dict(self.gl_resource_lists_tiers[0])

    def _compile_detailed_structure_meshes(self) -> None:
        """
        Компилирует детализированные бревенчатые и каменные 3D-меши для ВСЕХ строительных частей дома:
          - wall: 7 горизонтальных бревен с текстурой коры и торцевыми спилами.
          - foundation: каменные угловые опоры, бревенчатая обвязка по периметру и 9 текстурированных половых бревен/досок.
          - window_wall: 7 горизонтальных бревен (как у обычной стены) с проемом под окно, резной рамой, переплетом и ставнями!
          - doorway + door_leaf: 7 горизонтальных бревен с дверным проемом, косяками и навесной 3D-дверью из досок с ручкой и петлями!
          - roof: настоящая двускатная бревенчатая крыша из наклонных бревенчатых скатов, треугольных фронтонов, конькового бревна и печной трубы!
          - stairs: резная бревенчатая лестница из полубревен с тетивами и перилами.
          - workbench, bedroll, campfire, chest: детализированная мебель и кованый сундук.
        """
        tex_bark = self.tex_pack.textures.get("bark", 0)
        tex_rock = self.tex_pack.textures.get("rock", 0)
        cyl = MeshBuilder3D.emit_gl_cylinder
        el = MeshBuilder3D.emit_gl_ellipsoid

        # 1. ОБЫЧНАЯ БРЕВЕНЧАТАЯ СТЕНА (wall) — 7 текстурированных бревен с торцами и угловыми замками
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        for i in range(7):
            ly = -1.28 + i * 0.42
            col = (0.64, 0.45, 0.25) if i % 2 == 0 else (0.58, 0.40, 0.22)
            cyl(0.0, ly, 0.0, 0.22, 0.22, 4.16, col, segments=10, horizontal_x=True)
            # Светлые спилы на торцах бревен
            el(-2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
            el(2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
        glDisable(GL_TEXTURE_2D)
        glEndList()
        self.gl_structure_lists[("wall", False)] = lid

        # 2. ДЕРЕВЯННЫЙ ФУНДАМЕНТ (foundation) — каменные угловые опоры + бревенчатый венец + настил из 9 бревенчатых половиц
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_rock)
        for fx_c in (-1.82, 1.82):
            for fz_c in (-1.82, 1.82):
                cyl(fx_c, -0.32, fz_c, 0.30, 0.26, 0.48, (0.48, 0.49, 0.52), segments=8)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        # Продольные бревна обвязки и бревенчатый настил пола
        for i in range(9):
            fz_p = -1.76 + i * 0.44
            col = (0.64, 0.45, 0.25) if i % 2 == 0 else (0.56, 0.38, 0.20)
            cyl(0.0, 0.02, fz_p, 0.23, 0.23, 4.08, col, segments=8, horizontal_x=True)
            el(-2.04, 0.02, fz_p, 0.03, 0.21, 0.21, (0.84, 0.70, 0.46), 4, 8)
            el(2.04, 0.02, fz_p, 0.03, 0.21, 0.21, (0.84, 0.70, 0.46), 4, 8)
        # Боковые поперечные балки обвязки
        self._draw_gl_box(-1.94, -0.02, 0.0, 0.24, 0.42, 4.06, (0.46, 0.30, 0.16))
        self._draw_gl_box(1.94, -0.02, 0.0, 0.24, 0.42, 4.06, (0.46, 0.30, 0.16))
        glDisable(GL_TEXTURE_2D)
        glEndList()
        self.gl_structure_lists[("foundation", False)] = lid

        # 3. БРЕВЕНЧАТАЯ СТЕНА С РЕЗНЫМ ОКНОМ И СТАВНЯМИ (window_wall) — те же 7 рядов бревен, что и у обычной стены!
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        for i in range(7):
            ly = -1.28 + i * 0.42
            col = (0.64, 0.45, 0.25) if i % 2 == 0 else (0.58, 0.40, 0.22)
            if i in (0, 1, 5, 6):
                # Нижние 2 и верхние 2 бревна идут на всю ширину стены (4.16 м)
                cyl(0.0, ly, 0.0, 0.22, 0.22, 4.16, col, segments=10, horizontal_x=True)
                el(-2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
                el(2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
            else:
                # Средние 3 ряда бревен распилены слева и справа от оконного проема
                cyl(-1.42, ly, 0.0, 0.22, 0.22, 1.32, col, segments=10, horizontal_x=True)
                cyl(1.42, ly, 0.0, 0.22, 0.22, 1.32, col, segments=10, horizontal_x=True)
                el(-2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
                el(2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
        glDisable(GL_TEXTURE_2D)
        # Массивная резная оконная коробка (подоконник, вершник, боковые обсады и крестовина рамы)
        self._draw_gl_box(0.0, -0.62, 0.0, 1.68, 0.14, 0.50, (0.42, 0.26, 0.13))  # подоконник
        self._draw_gl_box(0.0, 0.62, 0.0, 1.68, 0.14, 0.50, (0.42, 0.26, 0.13))   # верхний наличник
        self._draw_gl_box(-0.76, 0.0, 0.0, 0.14, 1.24, 0.48, (0.42, 0.26, 0.13))  # левый откос
        self._draw_gl_box(0.76, 0.0, 0.0, 0.14, 1.24, 0.48, (0.42, 0.26, 0.13))   # правый откос
        self._draw_gl_box(0.0, 0.0, 0.0, 1.48, 0.07, 0.18, (0.36, 0.22, 0.11))    # горизонтальная перекладина рамы
        self._draw_gl_box(0.0, 0.0, 0.0, 0.07, 1.18, 0.18, (0.36, 0.22, 0.11))    # вертикальная перекладина рамы
        # Резные деревянные ставни по бокам окна
        for side_s in (-1.0, 1.0):
            self._draw_gl_box(side_s * 1.02, 0.0, 0.23, 0.34, 1.16, 0.06, (0.50, 0.32, 0.16))
            self._draw_gl_box(side_s * 1.02, 0.0, -0.23, 0.34, 1.16, 0.06, (0.50, 0.32, 0.16))
        glEndList()
        self.gl_structure_lists[("window_wall", False)] = lid

        # 4. ВХОДНАЯ БРЕВЕНЧАТАЯ СТЕНА С ДВЕРЬЮ (doorway) — 7 рядов бревен + косяки + отдельная навесная 3D-дверь!
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        for i in range(7):
            ly = -1.28 + i * 0.42
            col = (0.64, 0.45, 0.25) if i % 2 == 0 else (0.58, 0.40, 0.22)
            if i >= 5:
                # Верхние 2 бревна идут над дверным проемом во всю ширину (4.16 м)
                cyl(0.0, ly, 0.0, 0.22, 0.22, 4.16, col, segments=10, horizontal_x=True)
                el(-2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
                el(2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
            else:
                # Нижние 5 рядов бревен образуют левый и правый бревенчатые простенки по бокам двери
                cyl(-1.44, ly, 0.0, 0.22, 0.22, 1.28, col, segments=10, horizontal_x=True)
                cyl(1.44, ly, 0.0, 0.22, 0.22, 1.28, col, segments=10, horizontal_x=True)
                el(-2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
                el(2.08, ly, 0.0, 0.03, 0.20, 0.20, (0.84, 0.70, 0.46), 4, 8)
        glDisable(GL_TEXTURE_2D)
        # Массивная дверная коробка (левый и правый стояки и верхняя притолока)
        self._draw_gl_box(-0.78, -0.24, 0.0, 0.16, 2.08, 0.48, (0.42, 0.26, 0.13))
        self._draw_gl_box(0.78, -0.24, 0.0, 0.16, 2.08, 0.48, (0.42, 0.26, 0.13))
        self._draw_gl_box(0.0, 0.62, 0.0, 1.72, 0.16, 0.50, (0.42, 0.26, 0.13))
        glEndList()
        self.gl_structure_lists[("doorway", False)] = lid

        # Отдельное полотно 3D-Двери (вращается на петлях вокруг левого косяка x = -0.72!)
        dlid = glGenLists(1)
        glNewList(dlid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        for pi in range(5):
            px_d = 0.14 + pi * 0.28
            pcol = (0.54, 0.35, 0.18) if pi % 2 == 0 else (0.48, 0.30, 0.15)
            self._draw_gl_box(px_d, 0.0, 0.0, 0.27, 1.98, 0.14, pcol)
        glDisable(GL_TEXTURE_2D)
        # Кованые железные поперечины-стяжки, петли и золотая дверная ручка с обеих сторон
        self._draw_gl_box(0.70, 0.52, 0.0, 1.36, 0.10, 0.18, (0.28, 0.30, 0.34))
        self._draw_gl_box(0.70, -0.52, 0.0, 1.36, 0.10, 0.18, (0.28, 0.30, 0.34))
        self._draw_gl_box(0.06, 0.52, 0.0, 0.14, 0.18, 0.22, (0.22, 0.24, 0.28))
        self._draw_gl_box(0.06, -0.52, 0.0, 0.14, 0.18, 0.22, (0.22, 0.24, 0.28))
        el(1.22, -0.05, 0.13, 0.06, 0.06, 0.08, (0.95, 0.80, 0.22), 5, 8)
        el(1.22, -0.05, -0.13, 0.06, 0.06, 0.08, (0.95, 0.80, 0.22), 5, 8)
        glEndList()
        self.gl_structure_lists[("door_leaf", False)] = dlid

        # 5. ИСПРАВЛЕННАЯ СПЛОШНАЯ ДВУСКАТНАЯ КРЫША (roof) — плотные наклонные скаты из теса и бревен, стропила, карнизы и ровные фронтоны без дыр-колец!
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        # Сплошные наклонные кровельные щиты (левый и правый скаты под углом 36 градусов)
        self._draw_gl_box(0.0, 0.38, 1.08, 4.38, 0.18, 2.76, (0.52, 0.34, 0.18), pitch=35.5)
        self._draw_gl_box(0.0, 0.38, -1.08, 4.38, 0.18, 2.76, (0.52, 0.34, 0.18), pitch=-35.5)
        # Черепично-тесовые продольные планки поверх скатов для рельефа деревянной кровли
        for i in range(7):
            t_r = i / 6.0
            ry = -0.30 + t_r * 1.38
            rz = 2.02 * (1.0 - t_r)
            col = (0.60, 0.41, 0.22) if i % 2 == 0 else (0.48, 0.31, 0.16)
            self._draw_gl_box(0.0, ry + 0.08, rz, 4.42, 0.12, 0.38, col, pitch=35.5)
            self._draw_gl_box(0.0, ry + 0.08, -rz, 4.42, 0.12, 0.38, col, pitch=-35.5)
        # Массивный коньковый брус со спилами на вершине крыши и карнизные балки по краям
        cyl(0.0, 1.18, 0.0, 0.20, 0.20, 4.48, (0.42, 0.27, 0.14), segments=10, horizontal_x=True)
        el(-2.24, 1.18, 0.0, 0.03, 0.19, 0.19, (0.84, 0.70, 0.46), 4, 8)
        el(2.24, 1.18, 0.0, 0.03, 0.19, 0.19, (0.84, 0.70, 0.46), 4, 8)
        self._draw_gl_box(0.0, -0.36, 2.08, 4.42, 0.22, 0.22, (0.44, 0.28, 0.14))
        self._draw_gl_box(0.0, -0.36, -2.08, 4.42, 0.22, 0.22, (0.44, 0.28, 0.14))
        # Сплошные треугольные бревенчатые фронтоны спереди и сзади (x = -1.94 и x = +1.94) + резные причелины
        for gx_end in (-1.94, 1.94):
            for gi in range(7):
                gy = -0.32 + gi * 0.22
                gw = max(0.32, 3.96 * (1.0 - gi / 6.8))
                gcol = (0.62, 0.43, 0.24) if gi % 2 == 0 else (0.55, 0.37, 0.20)
                self._draw_gl_box(gx_end, gy, 0.0, 0.24, 0.23, gw, gcol)
            # Наклонные торцевые стропила-причелины, закрывающие стык ската
            self._draw_gl_box(gx_end * 1.08, 0.40, 1.06, 0.14, 0.22, 2.78, (0.42, 0.26, 0.13), pitch=35.5)
            self._draw_gl_box(gx_end * 1.08, 0.40, -1.06, 0.14, 0.22, 2.78, (0.42, 0.26, 0.13), pitch=-35.5)
        glDisable(GL_TEXTURE_2D)
        glEndList()
        self.gl_structure_lists[("roof", False)] = lid

        # 6. СТОЛ МАСТЕРСКОЙ (Верстак с 4 точеными ножками, столешницей, тисками и инструментами!)
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        for lx in (-0.68, 0.68):
            for lz in (-0.42, 0.42):
                cyl(lx, -0.45, lz, 0.08, 0.08, 0.78, (0.45, 0.28, 0.14), segments=8)
        self._draw_gl_box(0.0, -0.20, 0.0, 1.42, 0.08, 0.86, (0.50, 0.32, 0.16))
        self._draw_gl_box(0.0, 0.36, 0.0, 1.66, 0.14, 1.12, (0.68, 0.46, 0.24))
        self._draw_gl_box(-0.78, 0.38, 0.25, 0.16, 0.18, 0.28, (0.32, 0.35, 0.40))
        self._draw_gl_box(0.35, 0.45, -0.15, 0.38, 0.04, 0.14, (0.76, 0.80, 0.86))
        self._draw_gl_box(-0.25, 0.45, 0.10, 0.12, 0.08, 0.26, (0.55, 0.36, 0.18))
        glEndList()
        self.gl_structure_lists[("workbench", False)] = lid

        # 7. ДЕРЕВЯННАЯ КРОВАТЬ С ПОДУШКОЙ И ПЛЕДОМ (bedroll)
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        for lx in (-1.02, 1.02):
            for lz in (-0.62, 0.62):
                cyl(lx, -0.42, lz, 0.09, 0.09, 0.72, (0.42, 0.26, 0.14), segments=8)
        self._draw_gl_box(-1.05, 0.34, 0.0, 0.14, 0.76, 1.38, (0.48, 0.30, 0.16))
        self._draw_gl_box(0.0, -0.08, 0.0, 2.18, 0.18, 1.40, (0.55, 0.36, 0.19))
        self._draw_gl_box(0.04, 0.08, 0.0, 2.02, 0.20, 1.28, (0.94, 0.92, 0.86))
        el(-0.68, 0.25, 0.0, 0.24, 0.10, 0.48, (0.98, 0.98, 1.00), 5, 8)
        self._draw_gl_box(0.32, 0.12, 0.0, 1.38, 0.22, 1.32, (0.76, 0.22, 0.24))
        self._draw_gl_box(-0.34, 0.13, 0.0, 0.16, 0.23, 1.33, (0.88, 0.78, 0.62))
        glEndList()
        self.gl_structure_lists[("bedroll", False)] = lid

        # 8. РЕЗНАЯ БРЕВЕНЧАТАЯ ЛЕСТНИЦА С ПЕРИЛАМИ (stairs)
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        for step_i in range(6):
            sy = -0.48 + step_i * 0.22
            sz = -1.05 + step_i * 0.42
            col = (0.64, 0.45, 0.25) if step_i % 2 == 0 else (0.56, 0.38, 0.20)
            cyl(0.0, sy, sz, 0.14, 0.14, 2.24, col, segments=8, horizontal_x=True)
        glDisable(GL_TEXTURE_2D)
        for sx_rail in (-1.08, 1.08):
            self._draw_gl_box(sx_rail, 0.06, 0.0, 0.14, 0.26, 2.75, (0.46, 0.30, 0.16), pitch=-24.0)
            cyl(sx_rail, -0.52, -1.10, 0.07, 0.07, 1.05, (0.44, 0.28, 0.14), segments=8)
            cyl(sx_rail, 0.48, 1.10, 0.07, 0.07, 1.05, (0.44, 0.28, 0.14), segments=8)
            self._draw_gl_box(sx_rail, 0.92, 0.0, 0.10, 0.10, 2.65, (0.58, 0.39, 0.21), pitch=-24.0)
        glEndList()
        self.gl_structure_lists[("stairs", False)] = lid

        # 9. ДЕТАЛИЗИРОВАННЫЙ КОСТЕР (campfire): кольцо из 10 тесаных камней, зольник, раскаленные угли и шалаш из 6 бревен!
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_rock)
        for i in range(10):
            ang = i * (2.0 * math.pi / 10.0)
            r_stone = 0.60 + (0.04 if i % 2 == 0 else -0.02)
            el(math.cos(ang) * r_stone, -0.14, math.sin(ang) * r_stone, 0.21, 0.16, 0.20, (0.46, 0.47, 0.50), 5, 7)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        for i in range(6):
            ang_l = i * (math.pi / 3.0) + 0.25
            glPushMatrix()
            glRotatef(math.degrees(ang_l), 0.0, 1.0, 0.0)
            glTranslatef(0.0, -0.10, 0.12)
            glRotatef(-28.0, 1.0, 0.0, 0.0)
            cyl(0.0, 0.0, 0.0, 0.075, 0.055, 0.54, (0.40, 0.25, 0.13), segments=7)
            glPopMatrix()
        glDisable(GL_TEXTURE_2D)
        el(0.0, -0.15, 0.0, 0.44, 0.08, 0.44, (0.24, 0.18, 0.16), 5, 8)
        for ex_c, ez_c, ec_col in [
            (0.0, 0.0, (0.98, 0.36, 0.08)),
            (-0.16, 0.12, (0.92, 0.26, 0.06)),
            (0.18, -0.10, (1.00, 0.48, 0.10)),
            (-0.10, -0.16, (0.88, 0.22, 0.05)),
        ]:
            el(ex_c, -0.11, ez_c, 0.14, 0.06, 0.14, ec_col, 4, 6)
        glEndList()
        self.gl_structure_lists[("campfire", False)] = lid

        # 10. КАМЕННАЯ ПЕЧЬ-КАМИН С ВЫСОКИМ ДЫМОХОДОМ (chimney_hearth)
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_rock)
        self._draw_gl_box(0.0, -0.32, 0.0, 1.56, 0.24, 1.36, (0.44, 0.45, 0.48))
        self._draw_gl_box(-0.56, 0.26, 0.0, 0.36, 1.05, 1.24, (0.50, 0.51, 0.54))
        self._draw_gl_box(0.56, 0.26, 0.0, 0.36, 1.05, 1.24, (0.50, 0.51, 0.54))
        self._draw_gl_box(0.0, 0.26, -0.44, 0.84, 1.05, 0.36, (0.38, 0.39, 0.42))
        self._draw_gl_box(0.0, 0.88, 0.0, 1.62, 0.26, 1.38, (0.46, 0.47, 0.50))
        cyl(0.0, 0.98, -0.10, 0.38, 0.30, 2.15, (0.48, 0.49, 0.53), segments=10)
        cyl(0.0, 3.08, -0.10, 0.40, 0.40, 0.18, (0.34, 0.35, 0.38), segments=10)
        glDisable(GL_TEXTURE_2D)
        self._draw_gl_box(0.0, -0.12, 0.08, 0.56, 0.12, 0.56, (0.95, 0.42, 0.10))
        glEndList()
        self.gl_structure_lists[("chimney_hearth", False)] = lid

        # 11. БРЕВЕНЧАТЫЙ ЗАБОР / ОГРАДА (fence)
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        for px_f in (-1.85, -0.62, 0.62, 1.85):
            cyl(px_f, -0.68, 0.0, 0.13, 0.11, 1.32, (0.52, 0.35, 0.18), segments=8)
            cyl(px_f, 0.64, 0.0, 0.11, 0.02, 0.18, (0.68, 0.48, 0.26), segments=8)
        cyl(0.0, 0.26, 0.0, 0.08, 0.08, 3.96, (0.62, 0.43, 0.23), segments=8, horizontal_x=True)
        cyl(0.0, -0.22, 0.0, 0.08, 0.08, 3.96, (0.58, 0.39, 0.21), segments=8, horizontal_x=True)
        glDisable(GL_TEXTURE_2D)
        glEndList()
        self.gl_structure_lists[("fence", False)] = lid

        # 12. ДЕТАЛИЗИРОВАННАЯ УЛИЧНАЯ ЖАРОВНЯ-ФАКЕЛ НА СТОЛБЕ (torch_stand):
        # Каменный пьедестал, резной столб с коваными кольцами, железная корзина-жаровня с прутьями и тлеющими углями!
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_rock)
        cyl(0.0, -0.45, 0.0, 0.36, 0.28, 0.22, (0.46, 0.47, 0.50), segments=10)
        cyl(0.0, -0.25, 0.0, 0.26, 0.18, 0.14, (0.52, 0.53, 0.56), segments=10)
        glBindTexture(GL_TEXTURE_2D, tex_bark)
        cyl(0.0, -0.14, 0.0, 0.11, 0.085, 1.34, (0.48, 0.31, 0.15), segments=10)
        glDisable(GL_TEXTURE_2D)
        for by_ring in (0.18, 0.68, 1.12):
            cyl(0.0, by_ring, 0.0, 0.105, 0.105, 0.05, (0.22, 0.24, 0.28), segments=10)
        cyl(0.0, 1.16, 0.0, 0.11, 0.28, 0.22, (0.24, 0.26, 0.30), segments=10)
        cyl(0.0, 1.36, 0.0, 0.29, 0.31, 0.05, (0.18, 0.20, 0.24), segments=10)
        for rib_i in range(6):
            ra = rib_i * (math.pi / 3.0)
            rx_b, rz_b = math.cos(ra) * 0.26, math.sin(ra) * 0.26
            cyl(rx_b, 1.24, rz_b, 0.022, 0.026, 0.24, (0.20, 0.22, 0.26), segments=6)
        el(0.0, 1.34, 0.0, 0.23, 0.08, 0.23, (0.95, 0.34, 0.08), 5, 8)
        el(0.0, 1.38, 0.0, 0.16, 0.07, 0.16, (1.00, 0.65, 0.14), 5, 8)
        glEndList()
        self.gl_structure_lists[("torch_stand", False)] = lid

        # 13. ДУБОВЫЙ СТОЛ СО СКАМЬЯМИ (table_chair)
        lid = glGenLists(1)
        glNewList(lid, GL_COMPILE)
        self._draw_gl_box(0.0, 0.32, 0.0, 1.65, 0.10, 0.95, (0.64, 0.44, 0.23))
        for lx_t in (-0.70, 0.70):
            for lz_t in (-0.36, 0.36):
                cyl(lx_t, -0.42, lz_t, 0.06, 0.06, 0.72, (0.46, 0.29, 0.14), segments=8)
        for bz_s in (-0.64, 0.64):
            self._draw_gl_box(0.0, -0.02, bz_s, 1.48, 0.08, 0.32, (0.58, 0.38, 0.20))
            cyl(-0.58, -0.42, bz_s, 0.05, 0.05, 0.40, (0.42, 0.26, 0.13), segments=6)
            cyl(0.58, -0.42, bz_s, 0.05, 0.05, 0.40, (0.42, 0.26, 0.13), segments=6)
        cyl(-0.32, 0.37, 0.08, 0.08, 0.08, 0.14, (0.52, 0.34, 0.18), segments=8)
        el(0.24, 0.39, -0.06, 0.20, 0.03, 0.20, (0.90, 0.88, 0.82), 4, 8)
        glEndList()
        self.gl_structure_lists[("table_chair", False)] = lid

    def sync_viewport_size(self) -> Tuple[int, int]:
        """
        Определяет реальный клиентский размер окна (через pygame.display.get_window_size() и Win32 GetClientRect)
        и обновляет glViewport(0, 0, sw, sh) в каждом кадре!
        Это полностью устраняет баг при нажатии кнопки 'Развернуть во весь экран' [□] в Windows,
        растягивает 3D-сцену и интерфейс на весь экран и гарантирует 100% совпадение курсора и Drag & Drop!
        """
        if HAS_PYGAME and pygame.display.get_init():
            sw, sh = 0, 0
            # 1. В Pygame 2 get_window_size() возвращает реальный размер развернутого OpenGL-окна (в отличие от get_surface().get_size())
            if hasattr(pygame.display, "get_window_size"):
                try:
                    w_sz = pygame.display.get_window_size()
                    if w_sz and w_sz[0] > 0 and w_sz[1] > 0:
                        sw, sh = int(w_sz[0]), int(w_sz[1])
                except Exception:
                    pass
            # 2. Дополнительная проверка через Win32 GetClientRect(hwnd) на Windows
            if sys.platform == "win32":
                try:
                    import ctypes
                    from ctypes import wintypes
                    wm_info = pygame.display.get_wm_info()
                    hwnd = wm_info.get("window")
                    if hwnd:
                        rect = wintypes.RECT()
                        if ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(rect)):
                            cw = int(rect.right - rect.left)
                            ch = int(rect.bottom - rect.top)
                            if cw > 0 and ch > 0:
                                sw, sh = cw, ch
                except Exception:
                    pass
            # 3. Запасной вариант через поверхность дисплея
            if sw <= 0 or sh <= 0:
                surf = pygame.display.get_surface()
                if surf is not None:
                    sw, sh = surf.get_size()

            if sw > 0 and sh > 0:
                prev_vp = getattr(self, "_last_vp_size", None)
                self.game.width, self.game.height = sw, sh
                if self.use_opengl and prev_vp != (sw, sh):
                    glViewport(0, 0, sw, sh)
                    self._last_vp_size = (sw, sh)
        return self.game.width, self.game.height

    def apply_antialiasing_gl(self) -> None:
        """Применяет выбранный режим сглаживания (Выкл / 2x Линии / MSAA 4x / Ultra MSAA 8x) на видеокарте."""
        if not self.use_opengl:
            return
        aa_idx = self.game.antialias_idx
        try:
            if aa_idx == 0:
                glDisable(0x809D)  # GL_MULTISAMPLE
                glDisable(0x0B20)  # GL_LINE_SMOOTH
            elif aa_idx == 1:
                glDisable(0x809D)
                glEnable(0x0B20)
            else:
                glEnable(0x809D)
                glEnable(0x0B20)
        except Exception:
            pass

    def change_screen_resolution(self, delta_idx: int) -> None:
        """Изменяет разрешение экрана из списка SCREEN_RESOLUTIONS и обновляет окно и OpenGL Viewport."""
        self.game.resolution_idx = (self.game.resolution_idx + delta_idx) % len(SCREEN_RESOLUTIONS)
        new_w, new_h, res_lbl = SCREEN_RESOLUTIONS[self.game.resolution_idx]
        self.game.width, self.game.height = new_w, new_h
        self._saved_window_size = (new_w, new_h)
        if HAS_PYGAME and pygame.display.get_init() and not self.game.is_fullscreen:
            try:
                if sys.platform == "win32":
                    import ctypes
                    user32 = ctypes.windll.user32
                    hwnd = pygame.display.get_wm_info().get("window")
                    if hwnd:
                        mon_w = int(user32.GetSystemMetrics(0))
                        mon_h = int(user32.GetSystemMetrics(1))
                        pos_x = max(0, (mon_w - new_w) // 2)
                        pos_y = max(0, (mon_h - new_h) // 2)
                        user32.SetWindowPos(hwnd, 0, pos_x, pos_y, new_w, new_h, 0x0020)
                else:
                    flags = DOUBLEBUF | RESIZABLE | (OPENGL if self.use_opengl else 0)
                    pygame.display.set_mode((new_w, new_h), flags)
            except Exception:
                pass
            if self.use_opengl:
                glViewport(0, 0, new_w, new_h)
                self._last_vp_size = (new_w, new_h)
        self.game.add_notification(f"Разрешение экрана: {res_lbl}", 2.8, (150, 245, 255))

    def toggle_fullscreen(self) -> None:
        """
        Переключает игру между оконным режимом и полноценным полноэкранным режимом (Полный экран [F11])
        без потери OpenGL-контекста и со 100% совпадением координат мыши!
        """
        self.game.is_fullscreen = not self.game.is_fullscreen
        if not (HAS_PYGAME and pygame.display.get_init()):
            return
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hwnd = pygame.display.get_wm_info().get("window")
                if hwnd:
                    GWL_STYLE = -16
                    WS_POPUP = 0x80000000
                    WS_VISIBLE = 0x10000000
                    WS_OVERLAPPEDWINDOW = 0x00CF0000
                    SWP_FRAMECHANGED = 0x0020
                    if self.game.is_fullscreen:
                        self._saved_window_size = (self.game.width, self.game.height)
                        mon_w = int(user32.GetSystemMetrics(0))
                        mon_h = int(user32.GetSystemMetrics(1))
                        user32.SetWindowLongW(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE)
                        user32.SetWindowPos(hwnd, 0, 0, 0, mon_w, mon_h, SWP_FRAMECHANGED)
                        self.game.width, self.game.height = mon_w, mon_h
                    else:
                        prev_w, prev_h = getattr(self, "_saved_window_size", (1280, 720))
                        if prev_w >= int(user32.GetSystemMetrics(0)):
                            prev_w, prev_h = 1280, 720
                        mon_w = int(user32.GetSystemMetrics(0))
                        mon_h = int(user32.GetSystemMetrics(1))
                        pos_x = max(0, (mon_w - prev_w) // 2)
                        pos_y = max(0, (mon_h - prev_h) // 2)
                        user32.SetWindowLongW(hwnd, GWL_STYLE, WS_OVERLAPPEDWINDOW | WS_VISIBLE)
                        user32.SetWindowPos(hwnd, 0, pos_x, pos_y, prev_w, prev_h, SWP_FRAMECHANGED)
                    self.sync_viewport_size()
                    return
            except Exception:
                pass
        try:
            pygame.display.toggle_fullscreen()
            self.sync_viewport_size()
        except Exception:
            pass

    def render_frame(self, screen: Optional[object] = None) -> None:
        self.sync_viewport_size()
        if self.use_opengl:
            self._compile_pending_chunks(max_per_frame=8)
            self._render_opengl_3d()
            self._render_opengl_hud()
        elif screen is not None:
            self._render_software_3d(screen)
            self._render_software_hud(screen)

    def _draw_gl_box(
        self,
        ox: float,
        oy: float,
        oz: float,
        sx: float,
        sy: float,
        sz: float,
        color: Tuple[float, float, float],
        alpha: float = 1.0,
        pitch: float = 0.0,
    ) -> None:
        glPushMatrix()
        glTranslatef(ox, oy, oz)
        if abs(pitch) > 0.01:
            glRotatef(pitch, 1.0, 0.0, 0.0)
        glScalef(sx, sy, sz)
        glColor4f(color[0], color[1], color[2], alpha)
        glCallList(self.gl_cube_list)
        glPopMatrix()

    def _render_gl_sculpted_animal(self, anim: Animal) -> None:
        s = anim.scale
        swing = anim.leg_swing
        glPushMatrix()
        glTranslatef(anim.x, anim.y, anim.z)
        if self.game.shadows_enabled and not anim.aquatic and self.gl_shadow_disc_list is not None:
            glPushMatrix()
            glScalef(s * 0.95, 1.0, s * 1.15)
            glCallList(self.gl_shadow_disc_list)
            glPopMatrix()
        glRotatef(-anim.yaw, 0.0, 1.0, 0.0)
        if not anim.aquatic:
            # Наклон туловища животного вдоль дуги и угла горы (pitch — подъем/спуск, roll — боковой уклон)
            glRotatef(anim.pitch, 1.0, 0.0, 0.0)
            glRotatef(anim.roll, 0.0, 0.0, 1.0)
        glScalef(s, s, s)

        det_tier = max(0, min(3, int(self.game.detail_quality_idx)))
        torso_dict = self.gl_animal_torso_tiers.get(det_tier) or self.gl_animal_torso_lists
        leg_dict = self.gl_animal_leg_tiers.get(det_tier) or self.gl_animal_leg_lists
        glCallList(torso_dict[anim.kind])

        if anim.kind == "fish":
            wiggle = math.sin(anim.anim_phase * 1.6) * 24.0
            glPushMatrix()
            glTranslatef(0.0, 0.25, 0.44)
            glRotatef(wiggle, 0.0, 1.0, 0.0)
            MeshBuilder3D.emit_gl_ellipsoid(0.0, 0.0, 0.16, 0.04, 0.18, 0.18, anim.accent_color, 4, 6)
            glPopMatrix()
        elif anim.kind == "chicken":
            leg_lid = leg_dict["chicken"]
            for lx, ang in ((-0.12, swing), (0.12, -swing)):
                glPushMatrix()
                glTranslatef(lx, 0.36, 0.0)
                glRotatef(ang, 1.0, 0.0, 0.0)
                glCallList(leg_lid)
                glPopMatrix()
        else:
            leg_lid = leg_dict[anim.kind]
            leg_coords = [
                (-0.28, 0.66, -0.52, swing),
                (0.28, 0.66, -0.52, -swing),
                (-0.28, 0.66, 0.52, -swing),
                (0.28, 0.66, 0.52, swing),
            ]
            for lx, ly, lz, ang in leg_coords:
                glPushMatrix()
                glTranslatef(lx, ly, lz)
                glRotatef(ang, 1.0, 0.0, 0.0)
                glCallList(leg_lid)
                glPopMatrix()

        glPopMatrix()

    def _render_opengl_3d(self) -> None:
        prof = GRAPHICS_PROFILES[self.game.graphics_profile_idx]
        max_dist = self.game.get_effective_render_dist()
        max_dist_sq = max_dist * max_dist
        grass_mult = self.game.get_grass_density_multiplier()
        t_anim = self.game.anim_clock

        sky_col, sun_dir, ambient = self.game.get_atmosphere_colors()
        if self.game.player.head_underwater:
            sky_col = (0.06, 0.32, 0.56)
        glClearColor(sky_col[0], sky_col[1], sky_col[2], 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(70.0, self.game.width / float(self.game.height), 0.20, max_dist + 55.0)

        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        cx, cy, cz = self.game.get_camera_pos()
        glRotatef(-self.game.player.pitch, 1.0, 0.0, 0.0)
        glRotatef(self.game.player.yaw, 0.0, 1.0, 0.0)
        glTranslatef(-cx, -cy, -cz)

        fog_d = 0.035 if self.game.player.head_underwater else prof["fog_density"]
        glFogf(GL_FOG_DENSITY, fog_d)
        glFogfv(GL_FOG_COLOR, [sky_col[0], sky_col[1], sky_col[2], 1.0])
        glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [ambient * 0.56, ambient * 0.57, ambient * 0.62, 1.0])
        glLightfv(GL_LIGHT0, GL_POSITION, [sun_dir[0], sun_dir[1], sun_dir[2], 0.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [ambient * 1.04, ambient * 0.98, ambient * 0.91, 1.0])
        if self.game.detail_quality_idx >= 2:
            glLightfv(GL_LIGHT0, GL_SPECULAR, [ambient * 0.45, ambient * 0.43, ambient * 0.38, 1.0])
            glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, [0.18, 0.18, 0.18, 1.0])
            glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, 28.0)
        else:
            glLightfv(GL_LIGHT0, GL_SPECULAR, [0.0, 0.0, 0.0, 1.0])

        # УВЕЛИЧЕННЫЙ РАДИУС ОСВЕЩЕНИЯ КОСТРА (до 32 метров!) и факела
        if self.game.nearest_campfire_pos is not None or self.game.player.equipped_weapon == "torch":
            glEnable(GL_LIGHT1)
            flicker = 1.15 + 0.16 * math.sin(t_anim * 13.0)
            if self.game.nearest_campfire_pos is not None:
                lx, ly, lz = self.game.nearest_campfire_pos
            else:
                lx, ly, lz = cx, cy + 0.6, cz
            glLightfv(GL_LIGHT1, GL_POSITION, [lx, ly, lz, 1.0])
            glLightfv(GL_LIGHT1, GL_DIFFUSE, [1.0 * flicker, 0.72 * flicker, 0.28 * flicker, 1.0])
            glLightfv(GL_LIGHT1, GL_CONSTANT_ATTENUATION, [0.45])
            glLightfv(GL_LIGHT1, GL_LINEAR_ATTENUATION, [0.022])
            glLightfv(GL_LIGHT1, GL_QUADRATIC_ATTENUATION, [0.0008])
        else:
            glDisable(GL_LIGHT1)

        yaw_rad = math.radians(self.game.player.yaw)
        fwd_x = math.sin(yaw_rad)
        fwd_z = -math.cos(yaw_rad)

        self._render_gl_sky_elements(cx, cy, cz, self.game.clouds_enabled)

        vis_chunks = 0
        vis_entities = 0
        chunk_max_sq = (max_dist + 64.0) ** 2
        water_chunks: List[TerrainChunkData] = []
        rendered_chunk_keys: set[Tuple[int, int]] = set()
        for chunk in self.game.terrain.generated_chunks.values():
            if chunk.gl_list_id is None:
                continue
            dx = chunk.center_x - cx
            dz = chunk.center_z - cz
            d2 = dx * dx + dz * dz
            if d2 > chunk_max_sq:
                continue
            if d2 > 54.0 ** 2 and (dx * fwd_x + dz * fwd_z) < -42.0:
                continue
            glCallList(chunk.gl_list_id)
            if (
                chunk.props_dirty
                or chunk.gl_props_list_id is None
                or chunk.compiled_grass_idx != self.game.grass_density_idx
                or chunk.compiled_detail_idx != self.game.detail_quality_idx
                or chunk.compiled_shadows != self.game.shadows_enabled
            ):
                self._compile_chunk_foliage_lists(chunk)
            if chunk.gl_props_list_id is not None and chunk.prop_count > 0:
                glCallList(chunk.gl_props_list_id)
                vis_entities += chunk.prop_count
            if grass_mult > 0.01 and chunk.gl_grass_list_id is not None and chunk.grass_count > 0:
                glCallList(chunk.gl_grass_list_id)
                vis_entities += chunk.grass_count
            rendered_chunk_keys.add((chunk.cx, chunk.cz))
            vis_chunks += 1
            if chunk.has_water:
                water_chunks.append(chunk)
        self.game.visible_chunks_count = vis_chunks

        # Отрисовка покачивания только для того дерева или камня, по которому прямо сейчас нанесен удар (hit_shake > 0)
        for res in self.game.shaking_resources:
            if res.alive and res.hit_shake > 0.0:
                shake_ang = math.sin(res.hit_shake * 45.0) * 6.0
                lid = self.gl_resource_lists.get(res.kind, self.gl_resource_lists["stone_rock"])
                glPushMatrix()
                glTranslatef(res.x, res.y, res.z)
                glRotatef(res.rotation + shake_ang, 0.0, 1.0, 0.0)
                glScalef(res.scale * 1.02, res.scale * 1.02, res.scale * 1.02)
                glCallList(lid)
                glPopMatrix()

        for st in self.game.structures:
            dx_st = st.x - cx
            dz_st = st.z - cz
            if dx_st * dx_st + dz_st * dz_st > max_dist_sq:
                continue
            scx = int(math.floor(st.x / CHUNK_SIZE))
            scz = int(math.floor(st.z / CHUNK_SIZE))
            if (scx, scz) not in rendered_chunk_keys:
                continue
            self._render_gl_structure(st, alpha=1.0)

        if (self.game.build_mode or self.game.player.equipped_weapon == "hammer") and self.game.has_placed_workbench():
            bx, by, bz, rot, spec = self.game.get_build_preview_transform()
            can_b = self.game.can_build_piece(spec)
            ghost = BuiltStructure(
                id=0,
                piece_id=spec.id,
                name=spec.name,
                x=bx,
                y=by,
                z=bz,
                rotation=rot,
                size=spec.size,
                is_solid=spec.is_solid,
                is_roof=spec.is_roof,
            )
            self._render_gl_structure(
                ghost,
                alpha=0.52,
                override_color=(0.25, 0.95, 0.45) if can_b else (0.95, 0.25, 0.25),
            )

        for anim in self.game.animals:
            if not anim.alive:
                continue
            dx = anim.x - cx
            dz = anim.z - cz
            d2 = dx * dx + dz * dz
            if d2 > max_dist_sq:
                continue
            if d2 > 18.0 and (dx * fwd_x + dz * fwd_z) < -4.5:
                continue
            vis_entities += 1
            self._render_gl_sculpted_animal(anim)

        self.game.visible_entities_count = vis_entities

        if self.game.bobber is not None:
            b = self.game.bobber
            MeshBuilder3D.emit_gl_ellipsoid(b.x, b.y + 0.08, b.z, 0.14, 0.18, 0.14, (0.95, 0.18, 0.18), 5, 8)
            MeshBuilder3D.emit_gl_ellipsoid(b.x, b.y - 0.04, b.z, 0.13, 0.12, 0.13, (0.98, 0.98, 0.98), 5, 8)
            glDisable(GL_LIGHTING)
            glColor4f(0.90, 0.95, 1.0, 0.85)
            glLineWidth(1.6)
            fx, fy, fz = self.game.get_forward_vector()
            glBegin(GL_LINES)
            glVertex3f(cx + fx * 0.9, cy - 0.1 + fy * 0.9, cz + fz * 0.9)
            glVertex3f(b.x, b.y + 0.16, b.z)
            glEnd()
            glEnable(GL_LIGHTING)

        if water_chunks:
            glDepthMask(False)
            shimmer = 0.05 * math.sin(t_anim * 3.0)
            wave_y = WATER_LEVEL + 0.04 * math.sin(t_anim * 2.4)
            tex_water = self.tex_pack.textures.get("water", 0) if self.game.detail_quality_idx >= 2 else 0
            if tex_water:
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tex_water)
            u_scroll = (t_anim * 0.18) % 1.0
            v_scroll = (t_anim * 0.12) % 1.0
            glColor4f(0.09, 0.54 + shimmer, 0.84 + shimmer, 0.72)
            glNormal3f(0.0, 1.0, 0.0)
            glBegin(GL_QUADS)
            for ch in water_chunks:
                x0 = ch.cx * CHUNK_SIZE
                z0 = ch.cz * CHUNK_SIZE
                x1 = x0 + CHUNK_SIZE
                z1 = z0 + CHUNK_SIZE
                glTexCoord2f(u_scroll, v_scroll)
                glVertex3f(x0, wave_y, z0)
                glTexCoord2f(u_scroll, v_scroll + 4.0)
                glVertex3f(x0, wave_y, z1)
                glTexCoord2f(u_scroll + 4.0, v_scroll + 4.0)
                glVertex3f(x1, wave_y, z1)
                glTexCoord2f(u_scroll + 4.0, v_scroll)
                glVertex3f(x1, wave_y, z0)
            glEnd()
            if tex_water:
                glDisable(GL_TEXTURE_2D)
            # Второй переливающийся слой солнечных бликов на воде (если включены Тени и Блики в настройках)
            if self.game.shadows_enabled and self.game.detail_quality_idx >= 1:
                day_f_w = self.game.get_daylight_factor()
                glDisable(GL_LIGHTING)
                glColor4f(0.85, 0.95, 1.00, 0.14 * day_f_w + 0.04 * math.sin(t_anim * 5.2))
                glBegin(GL_QUADS)
                for ch in water_chunks:
                    x0 = ch.cx * CHUNK_SIZE
                    z0 = ch.cz * CHUNK_SIZE
                    x1 = x0 + CHUNK_SIZE
                    z1 = z0 + CHUNK_SIZE
                    glVertex3f(x0, wave_y + 0.02, z0)
                    glVertex3f(x0, wave_y + 0.02, z1)
                    glVertex3f(x1, wave_y + 0.02, z1)
                    glVertex3f(x1, wave_y + 0.02, z0)
                glEnd()
                glEnable(GL_LIGHTING)
            glDepthMask(True)

        # Летящие 3D-стрелы, повернутые строго по вектору своей 3D-скорости (vx, vy, vz)!
        for arr in self.game.arrows:
            glPushMatrix()
            glTranslatef(arr.x, arr.y, arr.z)
            horiz_spd = math.hypot(arr.vx, arr.vz)
            yaw_a = math.degrees(math.atan2(arr.vx, -arr.vz))
            pitch_a = math.degrees(math.atan2(arr.vy, max(1e-4, horiz_spd)))
            glRotatef(-yaw_a, 0.0, 1.0, 0.0)
            glRotatef(pitch_a, 1.0, 0.0, 0.0)
            if self.gl_arrow_3d_list is not None:
                glScalef(1.35, 1.35, 1.35)
                glCallList(self.gl_arrow_3d_list)
            else:
                self._draw_gl_box(0.0, 0.0, 0.0, 0.05, 0.05, 0.72, (0.85, 0.72, 0.42))
            glPopMatrix()

        # Сброшенные из инвентаря 3D-предметы на земле (плавно покачиваются и вращаются)
        for ditem in self.game.dropped_items:
            bob_d = math.sin(t_anim * 3.5 + ditem.id) * 0.06
            glPushMatrix()
            glTranslatef(ditem.x, ditem.y + bob_d, ditem.z)
            glRotatef(ditem.rotation, 0.0, 1.0, 0.0)
            glScalef(1.35, 1.35, 1.35)
            if ditem.item_id in self.gl_weapon_lists:
                glCallList(self.gl_weapon_lists[ditem.item_id])
            else:
                ic = RESOURCE_ICON_COLORS.get(ditem.item_id, (215, 185, 110))
                self._draw_gl_box(0.0, 0.0, 0.0, 0.24, 0.24, 0.24, (ic[0] / 255.0, ic[1] / 255.0, ic[2] / 255.0))
            glPopMatrix()

        # Отрисовка частиц: КРУГЛЫЕ 3D-снежинки (gl_snowflake_list), объемные языки пламени, золотые искры и мягкий дым!
        glDisable(GL_LIGHTING)
        for p in self.game.particles:
            life_ratio = max(0.0, min(1.0, p.ttl / max(0.05, p.max_ttl)))
            glPushMatrix()
            glTranslatef(p.x, p.y, p.z)
            if p.kind == "snow" and self.gl_snowflake_list is not None:
                glScalef(p.size, p.size, p.size)
                glColor4f(p.color[0], p.color[1], p.color[2], 0.92)
                glCallList(self.gl_snowflake_list)
            elif p.kind == "flame" and self.gl_flame_cone_list is not None:
                s_fl = p.size * (0.55 + 0.65 * life_ratio)
                glScalef(s_fl, s_fl * 1.95, s_fl)
                glColor4f(1.0, max(0.18, 0.92 * life_ratio), 0.08 * life_ratio, min(0.95, life_ratio * 1.25))
                glCallList(self.gl_flame_cone_list)
            elif p.kind == "ember" and self.gl_snowflake_list is not None:
                s_em = p.size * (0.5 + 0.5 * life_ratio)
                glScalef(s_em, s_em, s_em)
                glColor4f(1.0, 0.55 + 0.42 * life_ratio, 0.15, min(1.0, life_ratio * 1.4))
                glCallList(self.gl_snowflake_list)
            elif p.kind == "smoke" and self.gl_snowflake_list is not None:
                s_sm = p.size * (1.5 - 0.5 * life_ratio)
                glScalef(s_sm, s_sm * 0.85, s_sm)
                glColor4f(p.color[0], p.color[1], p.color[2], 0.42 * life_ratio)
                glCallList(self.gl_snowflake_list)
            elif self.gl_snowflake_list is not None:
                glScalef(p.size, p.size, p.size)
                glColor4f(p.color[0], p.color[1], p.color[2], 0.90)
                glCallList(self.gl_snowflake_list)
            else:
                glScalef(p.size, p.size, p.size)
                glColor4f(p.color[0], p.color[1], p.color[2], 0.90)
                glCallList(self.gl_cube_list)
            glPopMatrix()
        glEnable(GL_LIGHTING)

        self._render_gl_held_weapon()

    def _render_gl_sky_elements(self, cx: float, cy: float, cz: float, clouds_enabled: bool) -> None:
        glDisable(GL_LIGHTING)
        glDisable(GL_FOG)
        sun_angle = (self.game.time_of_day - 6.0) / 24.0 * 2.0 * math.pi
        day_f = self.game.get_daylight_factor()

        # Атмосферный градиентный пояс горизонта (Sky Horizon Glow) на Высоких/Ультра настройках
        if self.game.detail_quality_idx >= 2 and not self.game.player.head_underwater:
            sky_col, _, _ = self.game.get_atmosphere_colors()
            sunset_w = max(0.0, 1.0 - abs(day_f - 0.45) * 2.8)
            h_r = min(1.0, sky_col[0] * 1.18 + 0.35 * sunset_w)
            h_g = min(1.0, sky_col[1] * 1.10 + 0.16 * sunset_w)
            h_b = min(1.0, sky_col[2] * 1.06 + 0.05 * sunset_w)
            glDepthMask(False)
            glBegin(GL_QUADS)
            segs_sky = 16
            rad_sky = 170.0
            for i in range(segs_sky):
                a0 = (i / float(segs_sky)) * 2.0 * math.pi
                a1 = ((i + 1) / float(segs_sky)) * 2.0 * math.pi
                x0_s, z0_s = cx + math.cos(a0) * rad_sky, cz + math.sin(a0) * rad_sky
                x1_s, z1_s = cx + math.cos(a1) * rad_sky, cz + math.sin(a1) * rad_sky
                glColor4f(h_r, h_g, h_b, 0.38)
                glVertex3f(x0_s, cy - 12.0, z0_s)
                glVertex3f(x1_s, cy - 12.0, z1_s)
                glColor4f(sky_col[0], sky_col[1], sky_col[2], 0.0)
                glVertex3f(x1_s, cy + 58.0, z1_s)
                glVertex3f(x0_s, cy + 58.0, z0_s)
            glEnd()
            glDepthMask(True)

        sx = cx + math.cos(sun_angle) * 145.0
        sy = cy + math.sin(sun_angle) * 115.0
        sz = cz - 40.0
        if sy > cy - 22.0:
            sun_alpha = max(0.0, min(1.0, (sy - (cy - 22.0)) / 28.0))
            if self.game.detail_quality_idx >= 2:
                MeshBuilder3D.emit_gl_ellipsoid(sx, sy, sz, 16.0, 16.0, 16.0, (1.0, 0.78, 0.32), 6, 10)
            self._draw_gl_box(sx, sy, sz, 15.0, 15.0, 15.0, (1.0, 0.85, 0.42), alpha=0.35 * sun_alpha)
            self._draw_gl_box(sx, sy, sz, 9.0, 9.0, 9.0, (1.0, 0.96, 0.74), alpha=sun_alpha)
        mx_sky = cx - math.cos(sun_angle) * 140.0
        my_sky = cy - math.sin(sun_angle) * 110.0
        if my_sky > cy - 22.0:
            night_alpha = max(0.0, min(1.0, 1.0 - day_f * 1.15))
            if night_alpha > 0.02:
                self._draw_gl_box(mx_sky, my_sky, sz, 11.5, 11.5, 11.5, (0.55, 0.68, 0.95), alpha=0.25 * night_alpha)
                self._draw_gl_box(mx_sky, my_sky, sz, 7.5, 7.5, 7.5, (0.90, 0.94, 1.0), alpha=night_alpha)
                for st_x, st_y, st_z in self.game.stars:
                    self._draw_gl_box(cx + st_x * 0.8, st_y, cz + st_z * 0.8, 0.55, 0.55, 0.55, (0.95, 0.96, 1.0), alpha=night_alpha)
        glEnable(GL_FOG)

        glEnable(GL_LIGHTING)
        if clouds_enabled:
            # Плавное освещение облаков за счет глобального GL_LIGHT0 и мягкого смешивания без резкого переключения!
            cloud_lid = self.gl_cloud_list_day if day_f >= 0.35 else self.gl_cloud_list_night
            if cloud_lid is not None:
                for cl_x, cl_y, cl_z, cl_sx, cl_sz in self.game.clouds:
                    glPushMatrix()
                    glTranslatef(cl_x, cl_y, cl_z)
                    glScalef(cl_sx / 18.0, 1.15, cl_sz / 12.0)
                    glCallList(cloud_lid)
                    glPopMatrix()

    def _render_animated_fire_gl(self, ox: float, oy: float, oz: float, scale: float = 0.75, phase: float = 0.0) -> None:
        """
        Отрисовывает детализированное живое многослойное 3D-пламя (для костра, уличной жаровни-факела, камина и ручного факела):
        6 танцующих конусных языков пламени (багрово-оранжевые внешние, золотисто-янтарные средние и бело-желтое ядро) + кружащиеся искры!
        """
        if self.gl_flame_cone_list is None:
            return
        glDisable(GL_LIGHTING)
        glPushMatrix()
        glTranslatef(ox, oy, oz)
        glScalef(scale, scale, scale)

        tongues = [
            (0.0, 0.0, 0.0, 0.58, 1.05, (1.0, 0.36, 0.06, 0.86), 11.0, 0.0),
            (-0.14, 0.02, 0.10, 0.44, 0.88, (1.0, 0.52, 0.10, 0.88), 13.5, 1.2),
            (0.15, 0.02, -0.09, 0.42, 0.84, (1.0, 0.48, 0.08, 0.88), 12.2, 2.5),
            (0.08, 0.03, 0.14, 0.38, 0.78, (1.0, 0.72, 0.16, 0.92), 15.0, 3.8),
            (-0.10, 0.04, -0.12, 0.36, 0.74, (1.0, 0.82, 0.22, 0.92), 14.2, 4.9),
            (0.0, 0.06, 0.0, 0.26, 0.62, (1.0, 0.97, 0.68, 0.96), 17.5, 0.7),
        ]
        for tx, ty, tz, r_w, h_base, col, spd, off in tongues:
            h_cur = h_base + 0.22 * math.sin(phase * spd + off)
            tilt_x = math.sin(phase * (spd * 0.8) + off) * 14.0
            tilt_z = math.cos(phase * (spd * 0.75) + off) * 14.0
            glPushMatrix()
            glTranslatef(tx, ty, tz)
            glRotatef(tilt_x, 1.0, 0.0, 0.0)
            glRotatef(tilt_z, 0.0, 0.0, 1.0)
            glScalef(r_w, h_cur, r_w)
            glColor4f(col[0], col[1], col[2], col[3])
            glCallList(self.gl_flame_cone_list)
            glPopMatrix()

        if self.gl_snowflake_list is not None:
            for sp_i in range(3):
                sp_t = (phase * 1.9 + sp_i * 0.33) % 1.0
                sp_ang = phase * 5.5 + sp_i * 2.1
                sp_r = 0.18 + 0.14 * math.sin(sp_ang)
                sx_p = math.cos(sp_ang) * sp_r
                sz_p = math.sin(sp_ang) * sp_r
                sy_p = 0.35 + sp_t * 1.15
                sz_sc = 0.055 * (1.0 - sp_t * 0.65)
                glPushMatrix()
                glTranslatef(sx_p, sy_p, sz_p)
                glScalef(sz_sc, sz_sc, sz_sc)
                glColor4f(1.0, 0.92 - 0.4 * sp_t, 0.25, 1.0 - sp_t)
                glCallList(self.gl_snowflake_list)
                glPopMatrix()

        glPopMatrix()
        glEnable(GL_LIGHTING)

    def _render_gl_structure(
        self,
        st: BuiltStructure,
        alpha: float = 1.0,
        override_color: Optional[Tuple[float, float, float]] = None,
    ) -> None:
        glPushMatrix()
        glTranslatef(st.x, st.y, st.z)
        glRotatef(st.rotation, 0.0, 1.0, 0.0)
        sx, sy, sz = st.size
        c_wood = override_color or (0.62, 0.43, 0.24)
        c_dark = override_color or (0.44, 0.29, 0.15)
        t_anim = self.game.anim_clock

        if st.piece_id == "chest":
            c_iron = override_color or (0.24, 0.26, 0.30)
            c_gold = override_color or (0.95, 0.80, 0.22)
            self._draw_gl_box(0.0, -0.14, 0.0, 1.22, 0.52, 0.82, c_wood, alpha)
            self._draw_gl_box(-0.46, -0.14, 0.0, 0.10, 0.54, 0.85, c_iron, alpha)
            self._draw_gl_box(0.46, -0.14, 0.0, 0.10, 0.54, 0.85, c_iron, alpha)
            is_open = (self.game.active_chest is st) and self.game.show_inventory
            lid_angle = -68.0 if is_open else 0.0
            glPushMatrix()
            glTranslatef(0.0, 0.12, -0.38)
            glRotatef(lid_angle, 1.0, 0.0, 0.0)
            self._draw_gl_box(0.0, 0.12, 0.38, 1.24, 0.26, 0.84, c_dark, alpha)
            self._draw_gl_box(-0.46, 0.13, 0.38, 0.11, 0.28, 0.86, c_iron, alpha)
            self._draw_gl_box(0.46, 0.13, 0.38, 0.11, 0.28, 0.86, c_iron, alpha)
            self._draw_gl_box(0.0, 0.04, 0.81, 0.16, 0.20, 0.08, c_gold, alpha)
            glPopMatrix()
            glPopMatrix()
            return

        if st.piece_id == "campfire":
            if override_color is None and ("campfire", False) in self.gl_structure_lists:
                glCallList(self.gl_structure_lists[("campfire", False)])
                self._render_animated_fire_gl(0.0, -0.05, 0.0, scale=0.82, phase=t_anim + st.x * 0.37 + st.z * 0.23)
            else:
                self._draw_gl_box(0, -0.1, 0, 1.3, 0.25, 1.3, override_color or (0.45, 0.45, 0.48), alpha)
                self._draw_gl_box(0, 0.15, 0, 0.65, 0.45, 0.65, override_color or (1.0, 0.52, 0.12), alpha)
            glPopMatrix()
            return

        if st.piece_id == "torch_stand":
            if override_color is None and ("torch_stand", False) in self.gl_structure_lists:
                glCallList(self.gl_structure_lists[("torch_stand", False)])
                self._render_animated_fire_gl(0.0, 1.36, 0.0, scale=0.48, phase=t_anim * 1.15 + st.x * 0.51)
            else:
                self._draw_gl_box(0.0, 0.45, 0.0, 0.24, 1.65, 0.24, c_wood, alpha)
                self._draw_gl_box(0.0, 1.30, 0.0, 0.52, 0.32, 0.52, c_dark, alpha)
            glPopMatrix()
            return

        if st.piece_id == "stairs" and override_color is not None:
            # НАГЛЯДНЫЙ 3D-ПРЕДПРОСМОТР ЛЕСТНИЦЫ: отчетливо видны все 6 ступеней, косоуры, перила и яркая стрелка направления подъема (снизу -Z -> наверх +Z)!
            for step_i in range(6):
                sy_s = -0.48 + step_i * 0.22
                sz_s = -1.05 + step_i * 0.42
                t_step = step_i / 5.0
                scol = (
                    min(1.0, c_wood[0] * (0.75 + 0.45 * t_step)),
                    min(1.0, c_wood[1] * (0.75 + 0.35 * t_step)),
                    min(1.0, c_wood[2] + 0.35 * t_step),
                )
                self._draw_gl_box(0.0, sy_s, sz_s, 2.24, 0.16, 0.34, scol, alpha=0.72)
            for sx_rail in (-1.08, 1.08):
                self._draw_gl_box(sx_rail, 0.06, 0.0, 0.14, 0.24, 2.75, c_dark, alpha=0.65, pitch=-24.0)
                self._draw_gl_box(sx_rail, 0.90, 0.0, 0.10, 0.10, 2.65, c_wood, alpha=0.72, pitch=-24.0)
            glDisable(GL_LIGHTING)
            self._draw_gl_box(0.0, 0.42, -0.15, 0.18, 0.08, 1.65, (1.0, 0.92, 0.22), alpha=0.92, pitch=-24.0)
            glColor4f(1.0, 0.95, 0.25, 0.96)
            glBegin(GL_TRIANGLES)
            glVertex3f(0.0, 0.92, 1.18)
            glVertex3f(-0.42, 0.68, 0.56)
            glVertex3f(0.42, 0.68, 0.56)
            glEnd()
            glEnable(GL_LIGHTING)
            glPopMatrix()
            return

        if override_color is None and (st.piece_id, False) in self.gl_structure_lists:
            glCallList(self.gl_structure_lists[(st.piece_id, False)])
            if st.piece_id == "chimney_hearth":
                self._render_animated_fire_gl(0.0, -0.12, 0.08, scale=0.55, phase=t_anim + st.x)
            if st.piece_id == "doorway" and ("door_leaf", False) in self.gl_structure_lists:
                glPushMatrix()
                glTranslatef(-0.70, -0.26, 0.0)
                if st.door_open:
                    glRotatef(-84.0, 0.0, 1.0, 0.0)
                glCallList(self.gl_structure_lists[("door_leaf", False)])
                glPopMatrix()
            glPopMatrix()
            return

        if st.piece_id == "workbench":
            self._draw_gl_box(0.0, 0.36, 0.0, 1.66, 0.14, 1.12, c_wood, alpha)
            self._draw_gl_box(0.0, -0.10, 0.0, 1.42, 0.65, 0.86, c_dark, alpha)
        elif st.piece_id == "bedroll":
            self._draw_gl_box(-1.05, 0.32, 0.0, 0.14, 0.72, 1.38, c_dark, alpha)
            self._draw_gl_box(0.0, -0.08, 0.0, 2.18, 0.18, 1.40, c_wood, alpha)
            self._draw_gl_box(0.04, 0.10, 0.0, 2.02, 0.22, 1.30, c_wood, alpha)
            self._draw_gl_box(-0.68, 0.24, 0.0, 0.44, 0.14, 0.92, c_dark, alpha)
        elif st.piece_id == "window_wall":
            self._draw_gl_box(0, -sy * 0.30, 0, sx, sy * 0.40, sz, c_wood, alpha)
            self._draw_gl_box(0, sy * 0.35, 0, sx, sy * 0.30, sz, c_wood, alpha)
            self._draw_gl_box(-sx * 0.35, 0, 0, sx * 0.30, sy, sz, c_wood, alpha)
            self._draw_gl_box(sx * 0.35, 0, 0, sx * 0.30, sy, sz, c_wood, alpha)
            self._draw_gl_box(0, 0.05, 0, sx * 0.42, 0.06, sz * 0.5, c_dark, alpha)
            self._draw_gl_box(0, 0.05, 0, 0.06, sy * 0.36, sz * 0.5, c_dark, alpha)
        elif st.piece_id == "doorway":
            self._draw_gl_box(-sx * 0.36, 0, 0, sx * 0.28, sy, sz, c_wood, alpha)
            self._draw_gl_box(sx * 0.36, 0, 0, sx * 0.28, sy, sz, c_wood, alpha)
            self._draw_gl_box(0, sy * 0.38, 0, sx * 0.44, sy * 0.24, sz, c_wood, alpha)
            if not st.door_open:
                self._draw_gl_box(0, -sy * 0.10, 0, sx * 0.42, sy * 0.76, sz * 0.65, c_dark, alpha)
                self._draw_gl_box(sx * 0.14, -sy * 0.10, sz * 0.42, 0.08, 0.08, 0.12, (0.85, 0.75, 0.25), alpha)
        elif st.piece_id == "roof":
            self._draw_gl_box(0, -0.25, 0, sx, 0.55, sz, c_dark, alpha)
            self._draw_gl_box(0, 0.25, 0, sx * 0.76, 0.55, sz * 0.76, c_wood, alpha)
            self._draw_gl_box(0, 0.72, 0, sx * 0.48, 0.48, sz * 0.48, c_dark, alpha)
            self._draw_gl_box(0, 1.08, 0, sx * 0.22, 0.32, sz * 0.98, c_wood, alpha)
        else:
            self._draw_gl_box(0, 0, 0, sx, sy, sz, c_wood, alpha)
        glPopMatrix()

    def _render_gl_held_weapon(self) -> None:
        """
        Отрисовывает в 3D-руке от первого лица ИМЕННО ТОТ ПРЕДМЕТ, который сейчас выбран в активном слоте хотбара:
          - Если выбран слот с оружием/инструментом — рисует это оружие (включая ровное цельное копье).
          - Если выбран слот с рудой, деревом, едой, броней — рисует 3D-модель этой руды/предмета в ладони!
          - Если выбран пустой слот — рисует только пустую ладонь без старого оружия!
        """
        glClear(GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()
        p = self.game.player
        active_sl = p.slots[p.active_hotbar_slot] if 0 <= p.active_hotbar_slot < 9 else None
        held_id = str(active_sl["item"]) if active_sl is not None else None
        weapon = WEAPONS_DB.get(held_id) if held_id is not None else None

        t_anim = self.game.anim_clock
        idle_y = math.sin(t_anim * 2.2) * 0.008
        bob_x = math.cos(p.walk_bob * 0.5) * 0.025
        bob_y = abs(math.sin(p.walk_bob)) * 0.03 + idle_y
        swing = math.sin(p.swing_anim * math.pi)

        if weapon is not None and weapon.category == "bow":
            # УЛЬТРА-БЫСТРЫЙ СКОМПИЛИРОВАННЫЙ В GPU DISPLAY LISTS 3D-ЛУК (100+ FPS без малейших просадок!)
            pull = math.sin(p.bow_pull_anim * math.pi) * 0.28 + 0.045 * (0.5 + 0.5 * math.sin(t_anim * 2.4))
            glTranslatef(0.18 + bob_x * 0.6, -0.22 - bob_y * 0.6, -0.72)
            glRotatef(-4.0, 1.0, 0.0, 0.0)
            glRotatef(10.0, 0.0, 1.0, 0.0)
            glRotatef(-12.0, 0.0, 0.0, 1.0)

            if self.gl_left_hand_list is not None:
                glCallList(self.gl_left_hand_list)

            if self.gl_bow_riser_list is not None:
                glCallList(self.gl_bow_riser_list)

            bend_deg = pull * 36.0
            rad_b = math.radians(bend_deg)
            dy_tip = 0.40 * math.cos(rad_b) - 0.15 * math.sin(rad_b)
            dz_tip = 0.40 * math.sin(rad_b) + 0.15 * math.cos(rad_b)
            tip_top_y, tip_top_z = 0.08 + dy_tip, -0.02 + dz_tip
            tip_bot_y, tip_bot_z = -0.08 - dy_tip, -0.02 + dz_tip

            if self.gl_bow_upper_limb_list is not None:
                glPushMatrix()
                glTranslatef(0.0, 0.08, -0.02)
                glRotatef(bend_deg, 1.0, 0.0, 0.0)
                glCallList(self.gl_bow_upper_limb_list)
                glPopMatrix()

            if self.gl_bow_lower_limb_list is not None:
                glPushMatrix()
                glTranslatef(0.0, -0.08, -0.02)
                glRotatef(-bend_deg, 1.0, 0.0, 0.0)
                glCallList(self.gl_bow_lower_limb_list)
                glPopMatrix()

            nock_y = 0.02
            nock_z = 0.15 + pull * 1.15
            glDisable(GL_LIGHTING)
            glColor3f(0.95, 0.94, 0.88)
            glLineWidth(2.4)
            glBegin(GL_LINES)
            glVertex3f(0.0, tip_top_y, tip_top_z)
            glVertex3f(0.0, nock_y, nock_z)
            glVertex3f(0.0, nock_y, nock_z)
            glVertex3f(0.0, tip_bot_y, tip_bot_z)
            glEnd()
            glEnable(GL_LIGHTING)

            if p.inventory.get("arrow", 0) > 0 and self.gl_arrow_3d_list is not None:
                glPushMatrix()
                glTranslatef(0.012, nock_y, nock_z - 0.22)
                glCallList(self.gl_arrow_3d_list)
                glPopMatrix()

            glPushMatrix()
            glTranslatef(0.06, nock_y + 0.09, nock_z + 0.02)
            glRotatef(-12.0, 1.0, 0.0, 0.0)
            glRotatef(-16.0, 0.0, 1.0, 0.0)
            if self.gl_hand_list is not None:
                glCallList(self.gl_hand_list)
            glPopMatrix()
            return

        if weapon is not None and weapon.category == "spear":
            glTranslatef(0.38 + bob_x - swing * 0.05, -0.32 - bob_y + swing * 0.03, -0.68 - swing * 0.48)
            glRotatef(-8.0 - swing * 6.0, 1.0, 0.0, 0.0)
            glRotatef(8.0, 0.0, 1.0, 0.0)
        else:
            glTranslatef(0.42 + bob_x - swing * 0.18, -0.36 - bob_y + swing * 0.10, -0.78 - swing * 0.30)
            glRotatef(-18.0 - swing * 58.0, 1.0, 0.0, 0.0)
            glRotatef(14.0 + swing * 26.0, 0.0, 1.0, 0.0)

        if self.gl_hand_list is not None:
            glCallList(self.gl_hand_list)

        if held_id is None:
            return

        if held_id == "torch":
            if "torch" in self.gl_weapon_lists:
                glCallList(self.gl_weapon_lists["torch"])
            self._render_animated_fire_gl(0.0, 0.26, 0.0, scale=0.34, phase=t_anim * 1.35)
        elif held_id in self.gl_weapon_lists:
            glCallList(self.gl_weapon_lists[held_id])
            if held_id == "fishing_rod":
                # Рисуем натянутую леску вдоль удилища и свисающий с кончика красно-белый поплавок, когда удочка в руках!
                tip_x, tip_y, tip_z = 0.0, 0.82, -1.08
                glDisable(GL_LIGHTING)
                glColor4f(0.92, 0.96, 1.0, 0.90)
                glLineWidth(1.6)
                glBegin(GL_LINES)
                glVertex3f(0.04, -0.04, 0.02)
                glVertex3f(tip_x, tip_y, tip_z)
                if self.game.bobber is None:
                    sway_b = math.sin(t_anim * 3.2) * 0.025
                    glVertex3f(tip_x, tip_y, tip_z)
                    glVertex3f(tip_x + sway_b, tip_y - 0.34, tip_z)
                glEnd()
                glEnable(GL_LIGHTING)
                if self.game.bobber is None:
                    sway_b = math.sin(t_anim * 3.2) * 0.025
                    MeshBuilder3D.emit_gl_ellipsoid(tip_x + sway_b, tip_y - 0.34, tip_z, 0.036, 0.048, 0.036, (0.95, 0.18, 0.18), 5, 8)
                    MeshBuilder3D.emit_gl_ellipsoid(tip_x + sway_b, tip_y - 0.38, tip_z, 0.034, 0.036, 0.034, (0.98, 0.98, 0.98), 5, 8)

    @staticmethod
    def _gl_rect(x: float, y: float, w: float, h: float, color: Tuple[int, int, int, int]) -> None:
        surf = DualRenderer3D._ACTIVE_SURF
        if surf is not None:
            iw, ih = max(1, int(round(w))), max(1, int(round(h)))
            ix, iy = int(round(x)), int(round(y))
            alpha = int(color[3]) if len(color) > 3 else 255
            rgb = (int(color[0]), int(color[1]), int(color[2]))
            if alpha >= 245:
                pygame.draw.rect(surf, rgb, (ix, iy, iw, ih))
            elif alpha > 4:
                tmp = pygame.Surface((iw, ih), pygame.SRCALPHA)
                tmp.fill((rgb[0], rgb[1], rgb[2], alpha))
                surf.blit(tmp, (ix, iy))
            return
        glColor4f(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, color[3] / 255.0)
        glBegin(GL_QUADS)
        glVertex2f(x, y)
        glVertex2f(x + w, y)
        glVertex2f(x + w, y + h)
        glVertex2f(x, y + h)
        glEnd()

    @staticmethod
    def _gl_border(x: float, y: float, w: float, h: float, color: Tuple[int, int, int, int], width: float = 1.5) -> None:
        surf = DualRenderer3D._ACTIVE_SURF
        if surf is not None:
            pygame.draw.rect(
                surf,
                (int(color[0]), int(color[1]), int(color[2])),
                (int(round(x)), int(round(y)), max(1, int(round(w))), max(1, int(round(h)))),
                max(1, int(round(width))),
            )
            return
        glLineWidth(width)
        glColor4f(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, color[3] / 255.0)
        glBegin(GL_LINE_LOOP)
        glVertex2f(x, y)
        glVertex2f(x + w, y)
        glVertex2f(x + w, y + h)
        glVertex2f(x, y + h)
        glEnd()

    @staticmethod
    def _gl_poly(pts: List[Tuple[float, float]], color: Tuple[int, int, int, int]) -> None:
        if len(pts) < 3:
            return
        surf = DualRenderer3D._ACTIVE_SURF
        if surf is not None:
            ipts = [(int(round(px)), int(round(py))) for px, py in pts]
            pygame.draw.polygon(surf, (int(color[0]), int(color[1]), int(color[2])), ipts)
            return
        glColor4f(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, color[3] / 255.0)
        glBegin(GL_TRIANGLES)
        p0 = pts[0]
        for i in range(1, len(pts) - 1):
            glVertex2f(p0[0], p0[1])
            glVertex2f(pts[i][0], pts[i][1])
            glVertex2f(pts[i + 1][0], pts[i + 1][1])
        glEnd()

    @staticmethod
    def _gl_line(x1: float, y1: float, x2: float, y2: float, color: Tuple[int, int, int, int], width: float = 2.0) -> None:
        surf = DualRenderer3D._ACTIVE_SURF
        if surf is not None:
            pygame.draw.line(
                surf,
                (int(color[0]), int(color[1]), int(color[2])),
                (int(round(x1)), int(round(y1))),
                (int(round(x2)), int(round(y2))),
                max(1, int(round(width))),
            )
            return
        glLineWidth(width)
        glColor4f(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, color[3] / 255.0)
        glBegin(GL_LINES)
        glVertex2f(x1, y1)
        glVertex2f(x2, y2)
        glEnd()

    @staticmethod
    def _gl_oval(cx: float, cy: float, rx: float, ry: float, color: Tuple[int, int, int, int], segments: int = 20) -> None:
        """Рисует гладкий скругленный 2D-эллипс / круг (включая полупрозрачные круги джойстика и кнопок на Android)."""
        surf = DualRenderer3D._ACTIVE_SURF
        if surf is not None:
            irx, iry = max(1, int(round(rx))), max(1, int(round(ry)))
            rect = (int(round(cx - irx)), int(round(cy - iry)), irx * 2, iry * 2)
            alpha = int(color[3]) if len(color) > 3 else 255
            rgb = (int(color[0]), int(color[1]), int(color[2]))
            if alpha >= 240:
                pygame.draw.ellipse(surf, rgb, rect)
            elif alpha > 4:
                tmp = pygame.Surface((irx * 2, iry * 2), pygame.SRCALPHA)
                pygame.draw.ellipse(tmp, (rgb[0], rgb[1], rgb[2], alpha), (0, 0, irx * 2, iry * 2))
                surf.blit(tmp, (rect[0], rect[1]))
            return
        glColor4f(color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, color[3] / 255.0)
        glBegin(GL_TRIANGLES)
        for i in range(segments):
            a0 = (i / float(segments)) * 2.0 * math.pi
            a1 = ((i + 1) / float(segments)) * 2.0 * math.pi
            glVertex2f(cx, cy)
            glVertex2f(cx + math.cos(a0) * rx, cy + math.sin(a0) * ry)
            glVertex2f(cx + math.cos(a1) * rx, cy + math.sin(a1) * ry)
        glEnd()

    def _gl_capsule(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        r0: float,
        r1: float,
        color: Tuple[int, int, int, int],
    ) -> None:
        """Рисует плавно сужающуюся анатомическую конечность со скругленными суставами на обоих концах."""
        dx = x1 - x0
        dy = y1 - y0
        length = max(1e-4, math.hypot(dx, dy))
        nx = -dy / length
        ny = dx / length
        pts = [
            (x0 + nx * r0, y0 + ny * r0),
            (x1 + nx * r1, y1 + ny * r1),
            (x1 - nx * r1, y1 - ny * r1),
            (x0 - nx * r0, y0 - ny * r0),
        ]
        self._gl_poly(pts, color)
        self._gl_oval(x0, y0, r0, r0, color, segments=14)
        self._gl_oval(x1, y1, r1, r1, color, segments=14)

    def _draw_slot_durability_bar_gl(
        self,
        sl: Optional[Dict[str, object]],
        bx: float,
        by: float,
        bw: float,
        bh: float = 5.0,
    ) -> None:
        """Рисует цветную полоску прочности снизу ячейки для любого инструмента, оружия или одежды/брони."""
        ratio = get_slot_durability_ratio(sl)
        if ratio is None:
            return
        self._gl_rect(bx, by, bw, bh, (18, 22, 28, 240))
        if ratio > 0.60:
            col = (68, 238, 102, 250)
        elif ratio > 0.30:
            col = (250, 200, 48, 250)
        else:
            col = (248, 65, 65, 250)
        self._gl_rect(bx, by, max(2.0, bw * ratio), bh, col)
        self._gl_border(bx, by, bw, bh, (90, 115, 140, 190), 1.0)

    def _draw_item_icon_gl(self, item_id: str, x: float, y: float, size: float) -> None:
        """
        Рисует детализированную векторную 2D-иконку любого предмета (оружия, инструмента, ресурса, руды, еды, брони)
        в ячейках хотбара 1..9, в окне инвентаря, сундуке и при перетаскивании мышью.
        """
        def px(u: float) -> float:
            return x + u * size

        def py(v: float) -> float:
            return y + v * size

        # Тонкая подложка слота иконки
        self._gl_rect(x + 1, y + 1, size - 2, size - 2, (20, 28, 40, 185))

        if item_id == "rock":
            # Камень выжившего: граненый серый булыжник с бликом и тенью
            self._gl_poly([(px(0.20), py(0.76)), (px(0.14), py(0.42)), (px(0.38), py(0.18)), (px(0.75), py(0.24)), (px(0.86), py(0.56)), (px(0.64), py(0.84))], (138, 142, 148, 255))
            self._gl_poly([(px(0.22), py(0.44)), (px(0.38), py(0.22)), (px(0.68), py(0.28)), (px(0.52), py(0.52))], (185, 190, 198, 255))
            self._gl_poly([(px(0.52), py(0.52)), (px(0.68), py(0.28)), (px(0.84), py(0.56)), (px(0.64), py(0.82))], (96, 100, 106, 255))
        elif item_id in ("stone_axe", "iron_axe"):
            # Топор: диагональное топорище и лезвие топора
            blade_c = (205, 220, 238, 255) if item_id == "iron_axe" else (155, 160, 168, 255)
            edge_c = (242, 248, 255, 255) if item_id == "iron_axe" else (205, 210, 218, 255)
            self._gl_poly([(px(0.16), py(0.80)), (px(0.24), py(0.86)), (px(0.78), py(0.26)), (px(0.70), py(0.18))], (158, 102, 52, 255))
            self._gl_poly([(px(0.50), py(0.22)), (px(0.78), py(0.14)), (px(0.88), py(0.38)), (px(0.66), py(0.54))], blade_c)
            self._gl_poly([(px(0.74), py(0.14)), (px(0.88), py(0.38)), (px(0.72), py(0.52))], edge_c)
        elif item_id == "wooden_spear":
            # Длинное копье с каменным/стальным наконечником
            self._gl_poly([(px(0.12), py(0.84)), (px(0.19), py(0.89)), (px(0.72), py(0.34)), (px(0.65), py(0.28))], (172, 118, 64, 255))
            self._gl_poly([(px(0.62), py(0.28)), (px(0.88), py(0.12)), (px(0.74), py(0.40))], (195, 205, 215, 255))
        elif item_id == "stone_pickaxe":
            # Рудокопная кирка с двурогой головкой
            self._gl_poly([(px(0.16), py(0.82)), (px(0.24), py(0.88)), (px(0.72), py(0.32)), (px(0.64), py(0.26))], (155, 100, 50, 255))
            self._gl_poly([(px(0.34), py(0.16)), (px(0.64), py(0.22)), (px(0.86), py(0.48)), (px(0.78), py(0.56)), (px(0.58), py(0.32)), (px(0.30), py(0.26))], (150, 160, 175, 255))
        elif item_id in ("copper_sword", "mythril_blade"):
            # Меч (медный или мифриловый)
            blade_c = (75, 228, 255, 255) if item_id == "mythril_blade" else (232, 134, 72, 255)
            core_c = (210, 252, 255, 255) if item_id == "mythril_blade" else (255, 185, 125, 255)
            self._gl_poly([(px(0.32), py(0.62)), (px(0.80), py(0.14)), (px(0.88), py(0.12)), (px(0.86), py(0.20)), (px(0.38), py(0.68))], blade_c)
            self._gl_line(px(0.36), py(0.64), px(0.84), py(0.16), core_c, 1.8)
            self._gl_poly([(px(0.22), py(0.54)), (px(0.46), py(0.78)), (px(0.40), py(0.82)), (px(0.18), py(0.60))], (240, 195, 65, 255))
            self._gl_poly([(px(0.14), py(0.78)), (px(0.22), py(0.86)), (px(0.34), py(0.72)), (px(0.26), py(0.64))], (125, 75, 42, 255))
        elif item_id == "hunting_bow":
            # Охотничий лук с тетивой и стрелой
            self._gl_line(px(0.26), py(0.16), px(0.62), py(0.32), (168, 108, 52, 255), 3.0)
            self._gl_line(px(0.62), py(0.32), px(0.68), py(0.50), (168, 108, 52, 255), 3.0)
            self._gl_line(px(0.68), py(0.50), px(0.62), py(0.68), (168, 108, 52, 255), 3.0)
            self._gl_line(px(0.62), py(0.68), px(0.26), py(0.84), (168, 108, 52, 255), 3.0)
            self._gl_line(px(0.26), py(0.16), px(0.26), py(0.84), (235, 240, 245, 240), 1.4)
            self._gl_line(px(0.18), py(0.50), px(0.84), py(0.50), (215, 180, 105, 255), 2.0)
            self._gl_poly([(px(0.74), py(0.42)), (px(0.88), py(0.50)), (px(0.74), py(0.58))], (200, 210, 220, 255))
        elif item_id == "fishing_rod":
            # Удочка с леской и красно-белым поплавком
            self._gl_line(px(0.16), py(0.84), px(0.76), py(0.16), (175, 122, 62, 255), 2.8)
            self._gl_line(px(0.76), py(0.16), px(0.76), py(0.64), (220, 235, 250, 220), 1.2)
            self._gl_rect(px(0.70), py(0.60), size * 0.12, size * 0.10, (240, 55, 55, 255))
            self._gl_rect(px(0.70), py(0.70), size * 0.12, size * 0.08, (245, 245, 250, 255))
        elif item_id == "torch":
            # Горящий факел с многослойным пламенем
            self._gl_poly([(px(0.44), py(0.46)), (px(0.56), py(0.46)), (px(0.54), py(0.88)), (px(0.46), py(0.88))], (148, 92, 46, 255))
            self._gl_poly([(px(0.30), py(0.46)), (px(0.50), py(0.10)), (px(0.70), py(0.46))], (255, 115, 25, 255))
            self._gl_poly([(px(0.38), py(0.46)), (px(0.50), py(0.20)), (px(0.62), py(0.46))], (255, 220, 55, 255))
        elif item_id == "hammer":
            # Строительный молот
            self._gl_poly([(px(0.44), py(0.38)), (px(0.56), py(0.38)), (px(0.56), py(0.86)), (px(0.44), py(0.86))], (155, 100, 48, 255))
            self._gl_rect(px(0.22), py(0.18), size * 0.56, size * 0.24, (175, 135, 85, 255))
            self._gl_border(px(0.22), py(0.18), size * 0.56, size * 0.24, (235, 205, 145, 255), 1.4)
        elif item_id == "workbench_item":
            # Стол мастерской (Верстак с ножками и тисками)
            self._gl_rect(px(0.14), py(0.26), size * 0.72, size * 0.16, (195, 135, 72, 255))
            self._gl_rect(px(0.20), py(0.42), size * 0.12, size * 0.42, (138, 88, 44, 255))
            self._gl_rect(px(0.68), py(0.42), size * 0.12, size * 0.42, (138, 88, 44, 255))
            self._gl_rect(px(0.22), py(0.58), size * 0.56, size * 0.10, (158, 104, 54, 255))
            self._gl_rect(px(0.10), py(0.22), size * 0.12, size * 0.14, (150, 165, 185, 255))
        elif item_id == "wood":
            # Дерево: два бревна со светлыми годовыми кольцами на спиле
            self._gl_rect(px(0.16), py(0.50), size * 0.56, size * 0.24, (152, 96, 48, 255))
            self._gl_rect(px(0.66), py(0.50), size * 0.16, size * 0.24, (225, 185, 125, 255))
            self._gl_rect(px(0.22), py(0.24), size * 0.54, size * 0.22, (172, 112, 58, 255))
            self._gl_rect(px(0.70), py(0.24), size * 0.14, size * 0.22, (235, 198, 138, 255))
        elif item_id == "stone":
            # Камень: горка серых булыжников
            self._gl_poly([(px(0.14), py(0.78)), (px(0.24), py(0.46)), (px(0.54), py(0.44)), (px(0.62), py(0.78))], (135, 142, 150, 255))
            self._gl_poly([(px(0.44), py(0.80)), (px(0.52), py(0.50)), (px(0.82), py(0.52)), (px(0.86), py(0.80))], (158, 165, 175, 255))
            self._gl_poly([(px(0.30), py(0.52)), (px(0.44), py(0.22)), (px(0.70), py(0.26)), (px(0.74), py(0.52))], (182, 188, 198, 255))
        elif item_id == "coal":
            # Уголь: черные антрацитовые кристаллы с бликами
            self._gl_poly([(px(0.16), py(0.78)), (px(0.24), py(0.32)), (px(0.58), py(0.22)), (px(0.84), py(0.52)), (px(0.74), py(0.82))], (38, 42, 50, 255))
            self._gl_poly([(px(0.28), py(0.38)), (px(0.56), py(0.26)), (px(0.52), py(0.52))], (82, 90, 105, 255))
        elif item_id in ("copper", "iron", "gold", "mythril"):
            # Руды и кристаллы (медь, железо, золото, мифрил)
            vein_cols = {
                "copper": (238, 128, 62, 255),
                "iron": (210, 222, 238, 255),
                "gold": (255, 215, 45, 255),
                "mythril": (65, 235, 255, 255),
            }
            vc = vein_cols[item_id]
            self._gl_poly([(px(0.14), py(0.76)), (px(0.22), py(0.34)), (px(0.52), py(0.20)), (px(0.84), py(0.42)), (px(0.78), py(0.82))], (108, 112, 120, 255))
            self._gl_poly([(px(0.28), py(0.62)), (px(0.36), py(0.28)), (px(0.52), py(0.44))], vc)
            self._gl_poly([(px(0.52), py(0.68)), (px(0.66), py(0.30)), (px(0.78), py(0.58))], vc)
            self._gl_poly([(px(0.40), py(0.76)), (px(0.50), py(0.48)), (px(0.62), py(0.74))], (255, 250, 215, 255) if item_id == "gold" else vc)
        elif item_id == "berries":
            # Лесные ягоды с зелеными листочками
            self._gl_poly([(px(0.32), py(0.28)), (px(0.50), py(0.14)), (px(0.68), py(0.28)), (px(0.50), py(0.36))], (55, 185, 75, 255))
            self._gl_rect(px(0.22), py(0.42), size * 0.24, size * 0.24, (235, 42, 70, 255))
            self._gl_rect(px(0.52), py(0.42), size * 0.24, size * 0.24, (220, 35, 62, 255))
            self._gl_rect(px(0.37), py(0.58), size * 0.26, size * 0.26, (248, 58, 86, 255))
        elif item_id == "mushroom":
            # Лесной гриб с ножкой и шляпкой в крапинку
            self._gl_rect(px(0.40), py(0.48), size * 0.20, size * 0.36, (238, 228, 205, 255))
            self._gl_poly([(px(0.16), py(0.52)), (px(0.30), py(0.22)), (px(0.70), py(0.22)), (px(0.84), py(0.52))], (212, 68, 48, 255))
            self._gl_rect(px(0.34), py(0.30), size * 0.08, size * 0.08, (250, 245, 235, 255))
            self._gl_rect(px(0.56), py(0.34), size * 0.08, size * 0.08, (250, 245, 235, 255))
        elif item_id == "apple":
            # Спелое красное яблоко с черенком и листком
            self._gl_poly([(px(0.22), py(0.34)), (px(0.48), py(0.28)), (px(0.78), py(0.34)), (px(0.82), py(0.64)), (px(0.64), py(0.86)), (px(0.36), py(0.86)), (px(0.18), py(0.64))], (235, 48, 42, 255))
            self._gl_line(px(0.50), py(0.28), px(0.52), py(0.14), (135, 85, 40, 255), 2.0)
            self._gl_poly([(px(0.52), py(0.18)), (px(0.74), py(0.12)), (px(0.66), py(0.28))], (75, 205, 85, 255))
        elif item_id in ("raw_fish", "cooked_fish"):
            # Рыба (сырая голубая форель или запеченная золотистая рыба)
            fc = (238, 152, 72, 255) if item_id == "cooked_fish" else (85, 192, 232, 255)
            self._gl_poly([(px(0.14), py(0.50)), (px(0.42), py(0.28)), (px(0.70), py(0.46)), (px(0.42), py(0.72))], fc)
            self._gl_poly([(px(0.66), py(0.48)), (px(0.88), py(0.28)), (px(0.84), py(0.50)), (px(0.88), py(0.72))], fc)
            self._gl_rect(px(0.24), py(0.44), size * 0.06, size * 0.06, (20, 24, 30, 255))
        elif item_id in ("raw_meat", "cooked_meat"):
            # Мясной стейк на косточке (сырой или прожаренный с полосками гриля)
            mc = (192, 108, 52, 255) if item_id == "cooked_meat" else (218, 68, 68, 255)
            self._gl_poly([(px(0.18), py(0.36)), (px(0.62), py(0.22)), (px(0.84), py(0.48)), (px(0.68), py(0.78)), (px(0.22), py(0.72))], mc)
            self._gl_rect(px(0.38), py(0.42), size * 0.16, size * 0.16, (245, 240, 228, 255))
            if item_id == "cooked_meat":
                self._gl_line(px(0.28), py(0.36), px(0.56), py(0.68), (115, 58, 26, 255), 1.8)
                self._gl_line(px(0.48), py(0.30), px(0.74), py(0.60), (115, 58, 26, 255), 1.8)
        elif item_id == "hunter_stew":
            # Миска горячего жаркого охотника с паром
            self._gl_poly([(px(0.16), py(0.48)), (px(0.84), py(0.48)), (px(0.72), py(0.82)), (px(0.28), py(0.82))], (148, 92, 48, 255))
            self._gl_rect(px(0.20), py(0.42), size * 0.60, size * 0.10, (248, 188, 62, 255))
            self._gl_line(px(0.36), py(0.34), px(0.38), py(0.16), (235, 245, 255, 210), 1.5)
            self._gl_line(px(0.58), py(0.34), px(0.60), py(0.16), (235, 245, 255, 210), 1.5)
        elif item_id == "salve":
            # Целебный бальзам (изумрудный флакон с крестом исцеления)
            self._gl_rect(px(0.42), py(0.14), size * 0.16, size * 0.12, (168, 118, 68, 255))
            self._gl_poly([(px(0.26), py(0.36)), (px(0.40), py(0.26)), (px(0.60), py(0.26)), (px(0.74), py(0.36)), (px(0.74), py(0.82)), (px(0.26), py(0.82))], (68, 228, 125, 255))
            self._gl_rect(px(0.46), py(0.42), size * 0.08, size * 0.28, (245, 255, 248, 255))
            self._gl_rect(px(0.36), py(0.52), size * 0.28, size * 0.08, (245, 255, 248, 255))
        elif item_id == "fur_helmet":
            # Теплая меховая шапка-ушанка с меховой опушкой
            self._gl_poly([(px(0.20), py(0.54)), (px(0.26), py(0.22)), (px(0.50), py(0.14)), (px(0.74), py(0.22)), (px(0.80), py(0.54))], (178, 132, 88, 255))
            self._gl_rect(px(0.22), py(0.44), size * 0.56, size * 0.16, (238, 232, 218, 255))
            self._gl_rect(px(0.16), py(0.48), size * 0.14, size * 0.34, (162, 118, 76, 255))
            self._gl_rect(px(0.70), py(0.48), size * 0.14, size * 0.34, (162, 118, 76, 255))
        elif item_id == "fur_armor":
            # Теплая меховая броня (кираса с наплечниками и поясом)
            self._gl_poly([(px(0.16), py(0.24)), (px(0.38), py(0.18)), (px(0.50), py(0.30)), (px(0.62), py(0.18)), (px(0.84), py(0.24)), (px(0.76), py(0.46)), (px(0.72), py(0.84)), (px(0.28), py(0.84)), (px(0.24), py(0.46))], (172, 126, 86, 255))
            self._gl_rect(px(0.28), py(0.56), size * 0.44, size * 0.10, (95, 58, 32, 255))
            self._gl_rect(px(0.44), py(0.55), size * 0.12, size * 0.12, (245, 205, 75, 255))
        elif item_id == "fur_pants":
            # Кожаные штаны охотника с ремнем и наколенниками
            self._gl_rect(px(0.26), py(0.18), size * 0.48, size * 0.14, (92, 56, 30, 255))
            self._gl_poly([(px(0.26), py(0.30)), (px(0.74), py(0.30)), (px(0.78), py(0.86)), (px(0.54), py(0.86)), (px(0.50), py(0.48)), (px(0.46), py(0.86)), (px(0.22), py(0.86))], (148, 100, 58, 255))
            self._gl_rect(px(0.26), py(0.54), size * 0.18, size * 0.12, (112, 74, 42, 255))
            self._gl_rect(px(0.56), py(0.54), size * 0.18, size * 0.12, (112, 74, 42, 255))
        elif item_id == "wool_socks":
            # Теплые шерстяные носки и охотничьи сапоги
            self._gl_rect(px(0.26), py(0.18), size * 0.22, size * 0.48, (238, 232, 215, 255))
            self._gl_rect(px(0.26), py(0.24), size * 0.22, size * 0.08, (215, 68, 68, 255))
            self._gl_poly([(px(0.24), py(0.54)), (px(0.52), py(0.54)), (px(0.78), py(0.68)), (px(0.78), py(0.84)), (px(0.24), py(0.84))], (138, 88, 46, 255))
        elif item_id == "arrow":
            # Стрела с оперением и наконечником
            self._gl_line(px(0.18), py(0.82), px(0.78), py(0.22), (205, 170, 102, 255), 2.2)
            self._gl_poly([(px(0.68), py(0.18)), (px(0.86), py(0.14)), (px(0.82), py(0.32))], (205, 215, 228, 255))
            self._gl_poly([(px(0.14), py(0.74)), (px(0.28), py(0.72)), (px(0.26), py(0.86))], (235, 75, 75, 255))
        elif item_id == "wool":
            # Пушистое облачко овечьей шерсти
            self._gl_rect(px(0.22), py(0.36), size * 0.56, size * 0.40, (242, 242, 235, 255))
            self._gl_rect(px(0.32), py(0.24), size * 0.36, size * 0.48, (250, 250, 246, 255))
        elif item_id == "feather":
            # Птичье перо
            self._gl_poly([(px(0.24), py(0.78)), (px(0.42), py(0.28)), (px(0.78), py(0.16)), (px(0.66), py(0.54))], (225, 240, 255, 255))
            self._gl_line(px(0.18), py(0.84), px(0.76), py(0.18), (255, 255, 255, 255), 1.6)
        elif item_id == "fang":
            # Изогнутый клык / рог хищника
            self._gl_poly([(px(0.28), py(0.78)), (px(0.36), py(0.38)), (px(0.74), py(0.16)), (px(0.58), py(0.56)), (px(0.46), py(0.82))], (248, 242, 218, 255))
        else:
            # Кожа / Шкура зверя
            ic = RESOURCE_ICON_COLORS.get(item_id, (170, 120, 78))
            self._gl_poly([(px(0.20), py(0.22)), (px(0.80), py(0.22)), (px(0.86), py(0.52)), (px(0.76), py(0.82)), (px(0.24), py(0.82)), (px(0.14), py(0.52))], (ic[0], ic[1], ic[2], 255))
            self._gl_line(px(0.32), py(0.34), px(0.68), py(0.68), (95, 62, 38, 220), 1.6)

    def _render_opengl_hud(self) -> None:
        w, h = self.sync_viewport_size()
        p = self.game.player
        tcache = self.gl_text

        if self.use_opengl and DualRenderer3D._ACTIVE_SURF is None:
            glMatrixMode(GL_PROJECTION)
            glPushMatrix()
            glLoadIdentity()
            glOrtho(0, w, h, 0, -1, 1)
            glMatrixMode(GL_MODELVIEW)
            glPushMatrix()
            glLoadIdentity()
            glDisable(GL_LIGHTING)
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_FOG)

        if p.head_underwater:
            self._gl_rect(0, 0, w, h, (15, 95, 165, 85))

        cx, cy = w * 0.5, h * 0.5
        is_hostile = bool(self.game.hovered_animal and self.game.hovered_animal.hostile)
        ch_col = (255, 90, 90, 242) if is_hostile else (235, 250, 235, 242)
        self._gl_line(cx - 10, cy, cx - 3, cy, ch_col, 2.0)
        self._gl_line(cx + 3, cy, cx + 10, cy, ch_col, 2.0)
        self._gl_line(cx, cy - 10, cx, cy - 3, ch_col, 2.0)
        self._gl_line(cx, cy + 3, cx, cy + 10, ch_col, 2.0)

        if self.game.hovered_target_text:
            self._gl_rect(cx - 240, cy + 16, 480, 26, (14, 20, 28, 205))
            tcache.draw_text(self.font_md, self.game.hovered_target_text, cx, cy + 29, (255, 242, 180), center=True)

        # Верхняя информационная панель
        self._gl_rect(14, 10, 540, 44, (14, 20, 28, 215))
        self._gl_border(14, 10, 540, 44, (80, 130, 170, 230))

        fps_val = int(round(self.game.current_fps))
        fps_col = (110, 255, 140) if fps_val >= 50 else ((255, 215, 90) if fps_val >= 30 else (255, 100, 100))
        fps_txt = (
            f"FPS: {fps_val} ({self.game.frame_ms:.1f} ms) | Чанков: {len(self.game.terrain.generated_chunks)} "
            f"| Обзор: {int(self.game.get_effective_render_dist())}м"
        )
        tcache.draw_text(self.font_md, fps_txt, 24, 15, fps_col)

        hh = int(self.game.time_of_day)
        mm = int((self.game.time_of_day - hh) * 60)
        biome_str = self.game.terrain.get_biome(p.x, p.z)
        status_tags = []
        if p.in_water:
            status_tags.append("ПЛАВАНИЕ")
        if p.in_cave:
            status_tags.append("В ПЕЩЕРЕ")
        elif p.is_sheltered:
            status_tags.append("В ДОМЕ")
        if p.near_campfire:
            status_tags.append("У КОСТРА")
        tag_str = f" | {' + '.join(status_tags)}" if status_tags else ""
        info_txt = (
            f"День {self.game.day_number} ({hh:02d}:{mm:02d}) | ({int(p.x)}, {int(p.z)}) | "
            f"{biome_str} | Ур. {p.level}{tag_str}"
        )
        tcache.draw_text(self.font_sm, info_txt, 24, 34, (220, 238, 255))

        # ОТДЕЛЬНАЯ КНОПКА НАСТРОЕК (FPS, Дальность прорисовки, Количество травы и кустов)
        sb_x, sb_y, sb_w, sb_h = 560, 10, 152, 44
        self.ui_settings_btn_rect = (sb_x, sb_y, sb_w, sb_h)
        sb_bg = (42, 88, 72, 240) if self.game.show_settings else (22, 42, 38, 225)
        sb_border = (120, 255, 180, 255) if self.game.show_settings else (95, 195, 145, 235)
        self._gl_rect(sb_x, sb_y, sb_w, sb_h, sb_bg)
        self._gl_border(sb_x, sb_y, sb_w, sb_h, sb_border, 1.8)
        tcache.draw_text(self.font_sm, "Настройки", sb_x + sb_w * 0.5, sb_y + 15, (245, 255, 248), center=True)
        tcache.draw_text(self.font_sm, "FPS / Обзор / Трава", sb_x + sb_w * 0.5, sb_y + 31, (165, 245, 195), center=True)

        # ОТДЕЛЬНАЯ КНОПКА ПОЛНОГО ЭКРАНА (Fullscreen [F11])
        fb_x, fb_y, fb_w, fb_h = 718, 10, 118, 44
        self.ui_fullscreen_btn_rect = (fb_x, fb_y, fb_w, fb_h)
        fb_bg = (68, 52, 98, 240) if self.game.is_fullscreen else (28, 26, 46, 225)
        fb_border = (215, 175, 255, 255) if self.game.is_fullscreen else (135, 120, 195, 235)
        self._gl_rect(fb_x, fb_y, fb_w, fb_h, fb_bg)
        self._gl_border(fb_x, fb_y, fb_w, fb_h, fb_border, 1.8)
        fs_lbl = "Оконный" if self.game.is_fullscreen else "Во весь экран"
        tcache.draw_text(self.font_sm, fs_lbl, fb_x + fb_w * 0.5, fb_y + 15, (248, 245, 255), center=True)
        tcache.draw_text(self.font_sm, "[ F11 ] Экран", fb_x + fb_w * 0.5, fb_y + 31, (205, 185, 255), center=True)

        # ОТДЕЛЬНАЯ КНОПКА ВЫЗОВА ВСЕХ ПОДСКАЗОК ПО КЛАВИШАМ
        hb_x, hb_y, hb_w, hb_h = 842, 10, 132, 44
        self.ui_help_btn_rect = (hb_x, hb_y, hb_w, hb_h)
        hb_bg = (42, 84, 118, 240) if self.game.show_controls_help else (22, 38, 56, 225)
        hb_border = (255, 225, 95, 255) if self.game.show_controls_help else (105, 175, 230, 235)
        self._gl_rect(hb_x, hb_y, hb_w, hb_h, hb_bg)
        self._gl_border(hb_x, hb_y, hb_w, hb_h, hb_border, 1.8)
        tcache.draw_text(self.font_sm, "Клавиши", hb_x + hb_w * 0.5, hb_y + 15, (245, 250, 255), center=True)
        tcache.draw_text(self.font_sm, "[ ? ] Справка", hb_x + hb_w * 0.5, hb_y + 31, (165, 220, 255), center=True)

        # ОТДЕЛЬНАЯ КНОПКА ВКЛЮЧЕНИЯ / ОТКЛЮЧЕНИЯ УПРАВЛЕНИЯ ДЛЯ ТЕЛЕФОНА (СЕНСОРНЫЙ HUD)
        mb_x, mb_y, mb_w, mb_h = 980, 10, 142, 44
        self.ui_mobile_toggle_btn_rect = (mb_x, mb_y, mb_w, mb_h)
        mb_on = self.game.mobile_controls_enabled
        mb_bg = (36, 98, 68, 242) if mb_on else (34, 38, 48, 225)
        mb_border = (115, 255, 175, 255) if mb_on else (120, 135, 155, 225)
        self._gl_rect(mb_x, mb_y, mb_w, mb_h, mb_bg)
        self._gl_border(mb_x, mb_y, mb_w, mb_h, mb_border, 1.8)
        tcache.draw_text(
            self.font_sm,
            "Телефон: ВКЛ" if mb_on else "Телефон: ВЫКЛ",
            mb_x + mb_w * 0.5,
            mb_y + 15,
            (245, 255, 248) if mb_on else (215, 225, 235),
            center=True,
        )
        tcache.draw_text(
            self.font_sm,
            "Сенсорный экран",
            mb_x + mb_w * 0.5,
            mb_y + 31,
            (155, 255, 195) if mb_on else (165, 180, 198),
            center=True,
        )

        # ЛЕВЫЙ СТОЛБЕЦ СОСТОЯНИЯ ПЕРСОНАЖА (включая 6-ю полоску 'Состояние брони'!)
        panel_y = h - 190
        self._gl_rect(16, panel_y, 296, 174, (14, 20, 28, 218))
        self._gl_border(16, panel_y, 296, 174, (75, 115, 145, 225))

        bars = [
            ("Здоровье (HP)", p.hp, p.max_hp, (220, 55, 60, 245)),
            ("Выносливость", p.stamina, p.max_stamina, (65, 195, 95, 245)),
            ("Сытость (Еда)", p.hunger, 100.0, (230, 155, 45, 245)),
            ("Жажда (Вода)", p.thirst, 100.0, (55, 165, 235, 245)),
            ("Тепло тела", p.warmth, 100.0, (235, 105, 185, 245)),
            ("Состояние брони", p.armor_status_value, 100.0, (85, 215, 250, 245)),
        ]
        for idx, (label, val, mx, col) in enumerate(bars):
            by = panel_y + 10 + idx * 26
            disp_val = int(round(val))
            tcache.draw_text(self.font_sm, f"{label}: {disp_val}/{int(mx)}", 26, by, (235, 240, 245))
            self._gl_rect(172, by + 3, 126, 12, (38, 44, 52, 235))
            ratio = max(0.0, min(1.0, val / max(1.0, mx)))
            self._gl_rect(172, by + 3, 126 * ratio, 12, col)

        # НАД ХОТБАРОМ — ТОЛЬКО НАЗВАНИЕ ТЕКУЩЕГО ПРЕДМЕТА В РУКАХ
        hotbar_w = 9 * 64 + 12
        hx = (w - hotbar_w) * 0.5
        hy = h - 72
        held_item_title = self.game.get_held_item_display_name()
        self._gl_rect(w * 0.5 - 165, hy - 30, 330, 25, (14, 20, 28, 215))
        self._gl_border(w * 0.5 - 165, hy - 30, 330, 25, (90, 140, 180, 210), 1.2)
        tcache.draw_text(self.font_md, held_item_title, w * 0.5, hy - 17, (255, 238, 165), center=True)

        # ЯЧЕЙКИ ХОТБАРА 1..9 (с полоской прочности снизу каждой ячейки инструмента/оружия/одежды!)
        self._gl_rect(hx, hy, hotbar_w, 58, (14, 20, 28, 225))
        self.ui_hotbar_rects.clear()
        for i in range(9):
            sx = hx + 8 + i * 64
            sy = hy + 5
            self.ui_hotbar_rects.append((i, sx, sy, 56, 48))
            sl = p.slots[i]
            item_id = str(sl["item"]) if sl is not None else None
            selected = i == p.active_hotbar_slot
            border_c = (255, 215, 70, 255) if selected else ((110, 155, 195, 230) if item_id else (65, 72, 82, 180))
            bg_c = (42, 62, 86, 240) if selected else ((24, 34, 48, 220) if item_id else (16, 20, 26, 175))
            self._gl_rect(sx, sy, 56, 48, bg_c)
            self._gl_border(sx, sy, 56, 48, border_c, 2.2 if selected else 1.0)
            if item_id is not None and sl is not None:
                self._draw_item_icon_gl(item_id, sx + 10, sy + 4, 34)
                cnt = int(sl.get("count", 1))
                if item_id not in WEAPONS_DB or cnt > 1:
                    tcache.draw_text(self.font_sm, f"x{cnt}", sx + 30, sy + 24, (165, 255, 185))
                self._draw_slot_durability_bar_gl(sl, sx + 4, sy + 41, 48, 4)
            tcache.draw_text(self.font_sm, str(i + 1), sx + 4, sy + 2, border_c[:3])

        # КНОПКА "ЗАДАНИЯ" В ПРАВОМ ВЕРХНЕМ УГЛУ (полный блок "Цели выживания и РПГ" отображается ТОЛЬКО при нажатии!)
        quests_list = self.game.get_quest_tracker()
        done_q_cnt = sum(1 for _, d in quests_list if d)
        qb_w, qb_h = 142, 44
        qb_x, qb_y = w - qb_w - 14, 10
        self.ui_quests_btn_rect = (qb_x, qb_y, qb_w, qb_h)
        qb_open = self.game.show_quests
        qb_bg = (58, 76, 34, 242) if qb_open else (24, 34, 48, 228)
        qb_border = (255, 225, 95, 255) if qb_open else (110, 175, 225, 235)
        self._gl_rect(qb_x, qb_y, qb_w, qb_h, qb_bg)
        self._gl_border(qb_x, qb_y, qb_w, qb_h, qb_border, 1.8)
        arrow_q = "▲" if qb_open else "▼"
        tcache.draw_text(self.font_sm, f"Задания [{arrow_q}]", qb_x + qb_w * 0.5, qb_y + 15, (255, 235, 130), center=True)
        tcache.draw_text(self.font_sm, f"Выполнено: {done_q_cnt}/{len(quests_list)}", qb_x + qb_w * 0.5, qb_y + 31, (165, 245, 195), center=True)

        if qb_open:
            qx_panel, qy_panel, qw_panel, qh_panel = w - 348, 60, 334, 176
            self._gl_rect(qx_panel, qy_panel, qw_panel, qh_panel, (14, 20, 28, 236))
            self._gl_border(qx_panel, qy_panel, qw_panel, qh_panel, (255, 215, 90, 240), 1.8)
            tcache.draw_text(self.font_md, "Цели выживания и РПГ:", qx_panel + 12, qy_panel + 8, (255, 220, 110))
            for qi, (q_text, done) in enumerate(quests_list):
                mark = "[x]" if done else "[ ]"
                col = (125, 245, 145) if done else (215, 225, 235)
                tcache.draw_text(self.font_sm, f"{mark} {q_text}", qx_panel + 12, qy_panel + 34 + qi * 21, col)

        # Панель СТРОИТЕЛЬСТВО (смещается ниже, если открыт блок заданий)
        if (self.game.build_mode or p.equipped_weapon == "hammer") and self.game.has_placed_workbench():
            _, _, _, rot, bspec = self.game.get_build_preview_transform()
            cost_str = ", ".join(f"{RESOURCE_NAMES_RU.get(k, k)}: {v}" for k, v in bspec.cost.items())
            by_build_panel = 244 if qb_open else 62
            self._gl_rect(w - 348, by_build_panel, 334, 68, (20, 42, 36, 230))
            self._gl_border(w - 348, by_build_panel, 334, 68, (95, 235, 160, 255), 2.0)
            tcache.draw_text(self.font_md, f"СТРОИТЕЛЬСТВО: {bspec.name}", w - 336, by_build_panel + 8, (150, 255, 190))
            tcache.draw_text(self.font_sm, f"Цена: {cost_str} | Угол: {int(rot)}°", w - 336, by_build_panel + 36, (235, 245, 240))

        for ni, (ntxt, _, ncol) in enumerate(self.game.notifications):
            ny = 62 + ni * 25
            self._gl_rect(14, ny, 660, 22, (12, 16, 24, 195))
            tcache.draw_text(self.font_sm, ntxt, 22, ny + 3, ncol)

        self._render_gl_minimap(w, h)

        if self.game.mobile_controls_enabled and not (
            self.game.show_inventory
            or self.game.show_crafting
            or self.game.show_skills
            or self.game.show_settings
            or self.game.show_controls_help
        ):
            self._render_gl_mobile_controls(w, h)

        if self.game.show_inventory:
            self._render_gl_inventory_and_chest_modal(w, h)
        if self.game.show_crafting:
            self._render_gl_crafting_modal(w, h)
        if self.game.show_skills:
            self._render_gl_skills_modal(w, h)
        if self.game.show_settings:
            self._render_gl_settings_modal(w, h)
        if self.game.show_controls_help:
            self._render_gl_controls_help_modal(w, h)

        # Отрисовка перетаскиваемого мышью предмета ТОЧНО В ТОЧКЕ ЗАХВАТА (mx - off_x, my - off_y)!
        if self.game.dragged_item is not None and self.game.drag_source is not None and HAS_PYGAME:
            mx, my = pygame.mouse.get_pos()
            d_key = self.game.dragged_item
            d_cnt = self.game.dragged_count
            off_x, off_y = self.game.drag_offset
            cw, ch = self.game.drag_card_size
            dx = mx - off_x
            dy = my - off_y
            d_name = WEAPONS_DB[d_key].name if d_key in WEAPONS_DB else RESOURCE_NAMES_RU.get(d_key, d_key)
            self._gl_rect(dx, dy, cw, ch, (42, 72, 108, 242))
            self._gl_border(dx, dy, cw, ch, (255, 225, 85, 255), 2.4)
            icon_sz = min(36.0, ch - 12.0)
            self._draw_item_icon_gl(d_key, dx + 6, dy + (ch - icon_sz) * 0.5, icon_sz)
            if cw >= 95:
                tcache.draw_text(self.font_sm, d_name[:12], dx + icon_sz + 10, dy + 8, (255, 248, 205))
                if d_key not in WEAPONS_DB or d_cnt > 1:
                    tcache.draw_text(self.font_sm, f"x{d_cnt}", dx + icon_sz + 10, dy + 28, (150, 255, 180))

        if self.use_opengl and DualRenderer3D._ACTIVE_SURF is None:
            glEnable(GL_FOG)
            glEnable(GL_DEPTH_TEST)
            glEnable(GL_LIGHTING)
            glPopMatrix()
            glMatrixMode(GL_PROJECTION)
            glPopMatrix()
            glMatrixMode(GL_MODELVIEW)

    def _render_gl_settings_modal(self, w: int, h: int) -> None:
        """Отдельное окно со всеми настройками графики, детализации 3D-моделей, сглаживания, чанков, разрешения и FPS."""
        bw, bh = 740, 560
        bx = (w - bw) * 0.5
        by = max(8.0, (h - bh) * 0.5)
        self._gl_rect(bx, by, bw, bh, (14, 22, 32, 248))
        self._gl_border(bx, by, bw, bh, (110, 235, 175, 255), 2.4)

        self.gl_text.draw_text(
            self.font_lg,
            "НАСТРОЙКИ КАЧЕСТВА ГРАФИКИ, ДЕТАЛИЗАЦИИ И FPS",
            bx + 22,
            by + 12,
            (150, 255, 195),
        )
        close_x, close_y, close_w, close_h = bx + bw - 128, by + 10, 112, 28
        self.ui_settings_close_rect = (close_x, close_y, close_w, close_h)
        self._gl_rect(close_x, close_y, close_w, close_h, (125, 42, 48, 245))
        self._gl_border(close_x, close_y, close_w, close_h, (255, 150, 150, 255), 1.6)
        self.gl_text.draw_text(self.font_sm, "Закрыть [X]", close_x + close_w * 0.5, close_y + 14, (255, 245, 245), center=True)

        self.ui_settings_action_rects.clear()

        cap_val = FPS_CAPS[self.game.fps_cap_idx]
        cap_str = f"{cap_val} FPS" if cap_val > 0 else "Без лимита (Макс. FPS)"
        r_dist = int(self.game.get_effective_render_dist())
        grass_lbl, grass_mult = GRASS_DENSITY_PRESETS[self.game.grass_density_idx]
        prof_name = GRAPHICS_PROFILES[self.game.graphics_profile_idx]["name"]
        det_lbl, _ = DETAIL_QUALITY_PRESETS[self.game.detail_quality_idx]
        aa_lbl, _ = ANTIALIAS_PRESETS[self.game.antialias_idx]
        _, chunk_lbl = CHUNK_GEN_PRESETS[self.game.chunk_gen_idx]
        _, _, res_lbl = SCREEN_RESOLUTIONS[self.game.resolution_idx]
        shadows_str = "Вкл (Тени + Блики воды)" if self.game.shadows_enabled else "Выкл (Повышает FPS)"
        clouds_str = "Включены (Объемные 3D)" if self.game.clouds_enabled else "Отключены (Макс. FPS)"

        rows = [
            ("Общий профиль графики", prof_name, "prof_prev", "prof_next", (self.game.graphics_profile_idx + 1) / float(len(GRAPHICS_PROFILES))),
            ("Детализация 3D-моделей и шейдинга", det_lbl, "detail_minus", "detail_plus", self.game.detail_quality_idx / 3.0),
            ("Сглаживание (Anti-Aliasing)", aa_lbl, "aa_minus", "aa_plus", self.game.antialias_idx / 3.0),
            ("Генерация чанков вокруг игрока", chunk_lbl, "chunk_minus", "chunk_plus", (self.game.chunk_gen_idx + 1) / float(len(CHUNK_GEN_PRESETS))),
            ("Разрешение экрана", res_lbl, "res_prev", "res_next", (self.game.resolution_idx + 1) / float(len(SCREEN_RESOLUTIONS))),
            ("Мягкие тени и блики на воде", shadows_str, "shadows_toggle", "shadows_toggle", 1.0 if self.game.shadows_enabled else 0.0),
            ("Дальность прорисовки мира", f"{r_dist} метров", "dist_minus", "dist_plus", (r_dist - 60.0) / 150.0),
            ("Количество 3D-травы и цветов", grass_lbl, "grass_minus", "grass_plus", grass_mult / 2.0),
            ("Лимит частоты кадров (FPS)", cap_str, "fps_prev", "fps_next", (cap_val / 144.0) if cap_val > 0 else 1.0),
            ("Объемные 3D-облака на небе", clouds_str, "clouds_toggle", "clouds_toggle", 1.0 if self.game.clouds_enabled else 0.0),
        ]

        for idx, (label, val_txt, act_minus, act_plus, ratio) in enumerate(rows):
            ry = by + 46 + idx * 48
            self._gl_rect(bx + 18, ry, bw - 36, 43, (22, 34, 48, 235))
            self._gl_border(bx + 18, ry, bw - 36, 43, (75, 125, 165, 200), 1.0)
            self.gl_text.draw_text(self.font_md, label, bx + 28, ry + 3, (235, 245, 255))
            self.gl_text.draw_text(self.font_sm, f"Сейчас: {val_txt}", bx + 28, ry + 23, (145, 245, 185))

            bar_x, bar_y, bar_w, bar_h = bx + 380, ry + 13, 130, 16
            self._gl_rect(bar_x, bar_y, bar_w, bar_h, (35, 45, 58, 240))
            self._gl_rect(bar_x, bar_y, bar_w * max(0.0, min(1.0, ratio)), bar_h, (75, 215, 145, 245))
            self._gl_border(bar_x, bar_y, bar_w, bar_h, (130, 185, 220, 220), 1.0)

            b1_x, b1_y, b1_w, b1_h = bx + 525, ry + 7, 84, 29
            b2_x, b2_y, b2_w, b2_h = bx + 618, ry + 7, 84, 29
            self.ui_settings_action_rects.append((act_minus, b1_x, b1_y, b1_w, b1_h))
            self.ui_settings_action_rects.append((act_plus, b2_x, b2_y, b2_w, b2_h))

            self._gl_rect(b1_x, b1_y, b1_w, b1_h, (44, 64, 92, 245))
            self._gl_border(b1_x, b1_y, b1_w, b1_h, (140, 205, 255, 245), 1.5)
            self.gl_text.draw_text(self.font_md, "- Ниже", b1_x + b1_w * 0.5, b1_y + 14, (245, 250, 255), center=True)

            self._gl_rect(b2_x, b2_y, b2_w, b2_h, (38, 88, 64, 245))
            self._gl_border(b2_x, b2_y, b2_w, b2_h, (130, 255, 180, 245), 1.5)
            self.gl_text.draw_text(self.font_md, "+ Выше", b2_x + b2_w * 0.5, b2_y + 14, (245, 255, 248), center=True)

        self.gl_text.draw_text(
            self.font_sm,
            "Совет: все 4 уровня 'Детализации 3D-моделей' (Низкая / Средняя / Высокая / Ультра HD) имеют разную геометрию!",
            bx + bw * 0.5,
            by + bh - 16,
            (215, 235, 250),
            center=True,
        )

    def _render_gl_controls_help_modal(self, w: int, h: int) -> None:
        """Отдельное окно, которое полностью показывает все подсказки по клавишам и управлению при нажатии кнопки."""
        bw, bh = 740, 500
        bx = (w - bw) * 0.5
        by = (h - bh) * 0.5
        self._gl_rect(bx, by, bw, bh, (14, 20, 32, 248))
        self._gl_border(bx, by, bw, bh, (115, 205, 255, 255), 2.4)

        self.gl_text.draw_text(
            self.font_lg,
            "ПОЛНЫЙ СПРАВОЧНИК ПО КЛАВИШАМ И УПРАВЛЕНИЮ",
            bx + 22,
            by + 14,
            (255, 225, 110),
        )
        close_x, close_y, close_w, close_h = bx + bw - 128, by + 12, 112, 30
        self.ui_help_close_rect = (close_x, close_y, close_w, close_h)
        self._gl_rect(close_x, close_y, close_w, close_h, (125, 42, 48, 245))
        self._gl_border(close_x, close_y, close_w, close_h, (255, 150, 150, 255), 1.6)
        self.gl_text.draw_text(self.font_sm, "Закрыть [X]", close_x + close_w * 0.5, close_y + 15, (255, 245, 245), center=True)

        help_rows = [
            ("W, A, S, D", "Передвижение персонажа по миру (подъем по горам до 75°)"),
            ("Колесико мыши / 1 .. 9", "Быстрое переключение предметов в хотбаре (1..9)"),
            ("Shift / Пробел / Ctrl", "Быстрый бег (спринт) / Прыжок и всплытие / Ныряние в воде"),
            ("ЛКМ (Левая кнопка мыши)", "Добыча дерева и руды, атака, стрельба, установка Стола, открытие Стола"),
            ("ПКМ или клавиша E", "Быстрая установка выбранной постройки или взаимодействие"),
            ("I или Tab", "Открыть / закрыть Инвентарь (25 свободных ячеек, связанных с хотбаром)"),
            ("M (или кнопка в Инвентаре)", "Создать Стол мастерской в инвентаре за 2 Дерева"),
            ("F", "Взаимодействие (Стол мастерской, костер, сундук, кровать, дверь, вода)"),
            ("B", "Режим строительства дома (доступен после установки Стола мастерской)"),
            ("Z / X", "Выбор строительной детали в режиме строительства"),
            ("R / Backspace", "Повернуть деталь постройки на 90° / Разобрать постройку"),
            ("H", "Быстро съесть еду или использовать целебный бальзам"),
            ("K", "Открыть меню РПГ-характеристик и прокачки навыков"),
            ("O (или кнопка Настройки)", "Открыть окно настроек FPS, дальности прорисовки и количества травы"),
            ("F5 / F9 / Esc", "Быстрое сохранение / Быстрая загрузка / Курсор мыши или выход из меню"),
            ("F1 (или кнопка сверху)", "Открыть / скрыть это окно подсказок по клавишам"),
        ]
        for idx, (k_str, desc_str) in enumerate(help_rows):
            ry = by + 54 + idx * 27
            row_bg = (24, 34, 50, 225) if idx % 2 == 0 else (18, 26, 40, 225)
            self._gl_rect(bx + 18, ry, bw - 36, 24, row_bg)
            self.gl_text.draw_text(self.font_sm, k_str, bx + 28, ry + 4, (135, 245, 185))
            self.gl_text.draw_text(self.font_sm, desc_str, bx + 245, ry + 4, (230, 240, 250))

    def _draw_character_preview_gl(self, x: float, y: float, w: float, h: float) -> None:
        """
        Отрисовывает в окне Инвентаря анатомически скругленного, детализированного персонажа (без квадратных углов!).
        Когда броня не надета в 4 слота справа — персонаж изображен обнаженным (в одних набедренных плавках) с прорисовкой
        мышц груди, пресса, ключиц, коленей и пальцев, а при экипировке брони она надевается поверх тела!
        """
        p = self.game.player
        self._gl_rect(x, y, w, h, (18, 28, 42, 235))
        self._gl_border(x, y, w, h, (90, 155, 210, 225), 1.6)
        self.gl_text.draw_text(self.font_sm, "Персонаж", x + w * 0.5, y + 12, (215, 238, 255), center=True)

        cx = x + w * 0.5
        cy_top = y + 34

        has_helmet = p.armor_slots[0] is not None
        has_chest = p.armor_slots[1] is not None
        has_pants = p.armor_slots[2] is not None
        has_socks = p.armor_slots[3] is not None

        skin_lit = (234, 190, 154, 255)
        skin_mid = (218, 172, 136, 255)
        skin_shd = (188, 142, 108, 255)
        skin_line = (162, 116, 86, 220)

        # Мягкая овальная тень под ступнями
        self._gl_oval(cx, y + h - 34, 30, 6, (8, 12, 18, 210), segments=20)

        # 1. АНАТОМИЧЕСКИЕ НОГИ (скругленные бедра, колени, икры и щиколотки)
        for side in (-1.0, 1.0):
            hip_x = cx + side * 10.5
            knee_x = cx + side * 11.0
            ankle_x = cx + side * 10.5
            if has_pants:
                # Кожаные штаны охотника со скругленными наколенниками
                self._gl_capsule(hip_x, cy_top + 122, knee_x, cy_top + 150, 8.2, 6.8, (142, 95, 54, 255))
                self._gl_capsule(knee_x, cy_top + 150, ankle_x, cy_top + 176, 6.6, 5.2, (130, 86, 48, 255))
                self._gl_oval(knee_x, cy_top + 150, 6.5, 5.0, (104, 68, 38, 255), segments=14)
            else:
                # Обнаженные мускулистые ноги (бедро, коленная чашечка, икроножная мышца)
                self._gl_capsule(hip_x, cy_top + 122, knee_x, cy_top + 150, 7.8, 6.2, skin_mid)
                self._gl_oval(hip_x - side * 1.0, cy_top + 134, 4.2, 10.0, skin_lit, segments=12)
                self._gl_oval(knee_x, cy_top + 150, 5.6, 4.5, skin_shd, segments=12)
                self._gl_oval(knee_x, cy_top + 149, 4.2, 3.2, skin_lit, segments=12)
                self._gl_capsule(knee_x, cy_top + 150, ankle_x, cy_top + 177, 6.2, 4.4, skin_mid)
                self._gl_oval(knee_x + side * 1.2, cy_top + 160, 4.0, 8.0, skin_lit, segments=12)

        # Набедренные плавки / повязка (или пояс штанов)
        if has_pants:
            self._gl_capsule(cx - 13, cy_top + 118, cx + 13, cy_top + 118, 6.5, 6.5, (92, 56, 30, 255))
            self._gl_oval(cx, cy_top + 118, 4.5, 4.0, (235, 195, 70, 255), segments=12)
        else:
            self._gl_poly([
                (cx - 17, cy_top + 113), (cx + 17, cy_top + 113),
                (cx + 14, cy_top + 124), (cx + 3, cy_top + 128),
                (cx - 3, cy_top + 128), (cx - 14, cy_top + 124),
            ], (72, 64, 58, 255))
            self._gl_line(cx - 16, cy_top + 114, cx + 16, cy_top + 114, (110, 96, 82, 255), 1.6)

        # 2. СТУПНИ / НОСКИ И САПОГИ (4-я вертикальная ячейка)
        for side in (-1.0, 1.0):
            ax = cx + side * 10.5
            fx = cx + side * 13.0
            if has_socks:
                self._gl_capsule(ax, cy_top + 171, ax, cy_top + 182, 5.6, 6.0, (238, 232, 215, 255))
                self._gl_line(ax - 5.5, cy_top + 171, ax + 5.5, cy_top + 171, (215, 65, 65, 255), 2.2)
                self._gl_capsule(ax, cy_top + 183, fx, cy_top + 186, 6.2, 5.2, (128, 82, 42, 255))
            else:
                # Босые ступни с пальцами ног
                self._gl_oval(ax, cy_top + 183, 5.5, 4.2, skin_mid, segments=14)
                self._gl_oval(fx, cy_top + 185, 6.8, 3.8, skin_lit, segments=14)
                for ti in range(4):
                    tx = fx + side * (4.5 - ti * 2.0)
                    self._gl_oval(tx, cy_top + 187, 1.4, 1.4, skin_shd, segments=8)

        # 3. ШЕЯ, ТРАПЕЦИИ, ОКРУГЛЫЙ ТОРС И МЫШЦЫ ГРУДИ/ПРЕССА (или Меховой Доспех)
        # Трапеции и шея
        self._gl_oval(cx, cy_top + 53, 14.0, 5.5, skin_mid, segments=16)
        self._gl_capsule(cx, cy_top + 41, cx, cy_top + 52, 6.8, 7.4, skin_mid)
        self._gl_oval(cx, cy_top + 47, 5.0, 5.5, skin_lit, segments=12)

        if has_chest:
            # Скругленная меховая кираса с меховыми наплечниками и поясом
            self._gl_poly([
                (cx - 22, cy_top + 54), (cx + 22, cy_top + 54),
                (cx + 19, cy_top + 88), (cx + 17, cy_top + 116),
                (cx - 17, cy_top + 116), (cx - 19, cy_top + 88),
            ], (172, 126, 84, 255))
            self._gl_oval(cx - 21, cy_top + 58, 8.5, 6.5, (232, 224, 206, 255), segments=16)
            self._gl_oval(cx + 21, cy_top + 58, 8.5, 6.5, (232, 224, 206, 255), segments=16)
            self._gl_capsule(cx - 16, cy_top + 54, cx + 16, cy_top + 54, 5.2, 5.2, (238, 230, 212, 255))
            self._gl_line(cx - 16, cy_top + 58, cx + 14, cy_top + 106, (105, 66, 36, 255), 3.0)
            self._gl_capsule(cx - 16, cy_top + 106, cx + 16, cy_top + 106, 4.2, 4.2, (92, 56, 30, 255))
            self._gl_oval(cx, cy_top + 106, 5.5, 5.0, (245, 205, 75, 255), segments=14)
        else:
            # Анатомический обнаженный торс (V-образный силуэт, грудные мышцы, ребра, пресс и пупок)
            self._gl_oval(cx - 19, cy_top + 59, 8.0, 7.5, skin_mid, segments=16)  # левая дельта плеча
            self._gl_oval(cx + 19, cy_top + 59, 8.0, 7.5, skin_mid, segments=16)  # правая дельта плеча
            self._gl_poly([
                (cx - 21, cy_top + 55), (cx + 21, cy_top + 55),
                (cx + 19, cy_top + 76), (cx + 14, cy_top + 96),
                (cx + 16, cy_top + 114), (cx - 16, cy_top + 114),
                (cx - 14, cy_top + 96), (cx - 19, cy_top + 76),
            ], skin_mid)
            # Рельефные грудные мышцы (пекторальные) и ключицы
            self._gl_oval(cx - 9.5, cy_top + 68, 9.2, 7.2, skin_lit, segments=16)
            self._gl_oval(cx + 9.5, cy_top + 68, 9.2, 7.2, skin_lit, segments=16)
            self._gl_line(cx - 15, cy_top + 56, cx - 3, cy_top + 58, skin_line, 1.5)
            self._gl_line(cx + 3, cy_top + 58, cx + 15, cy_top + 56, skin_line, 1.5)
            self._gl_line(cx - 16, cy_top + 74, cx - 2, cy_top + 75, skin_line, 1.5)
            self._gl_line(cx + 2, cy_top + 75, cx + 16, cy_top + 74, skin_line, 1.5)
            self._gl_oval(cx - 11.5, cy_top + 71, 1.6, 1.4, (175, 118, 98, 235), segments=8)
            self._gl_oval(cx + 11.5, cy_top + 71, 1.6, 1.4, (175, 118, 98, 235), segments=8)
            # Кубики пресса и пупок
            self._gl_line(cx, cy_top + 62, cx, cy_top + 104, skin_line, 1.3)
            for row_ab in range(3):
                ay_ab = cy_top + 81 + row_ab * 8.5
                self._gl_oval(cx - 5.2, ay_ab, 4.4, 3.4, skin_lit, segments=12)
                self._gl_oval(cx + 5.2, ay_ab, 4.4, 3.4, skin_lit, segments=12)
            self._gl_oval(cx, cy_top + 106, 1.8, 2.0, skin_shd, segments=10)

        # 4. ОКРУГЛЫЕ АНАТОМИЧЕСКИЕ РУКИ (бицепс, локоть, предплечье, кисть и пальцы)
        for side in (-1.0, 1.0):
            sh_x = cx + side * 22.0
            elb_x = cx + side * 26.5
            wr_x = cx + side * 25.0
            if has_chest:
                self._gl_capsule(sh_x, cy_top + 60, elb_x, cy_top + 84, 5.8, 5.0, (158, 112, 72, 255))
            else:
                self._gl_capsule(sh_x, cy_top + 60, elb_x, cy_top + 84, 5.5, 4.6, skin_mid)
                self._gl_oval((sh_x + elb_x) * 0.5, cy_top + 72, 4.2, 7.0, skin_lit, segments=12)
            self._gl_capsule(elb_x, cy_top + 84, wr_x, cy_top + 108, 4.6, 3.6, skin_lit)
            # Округлая ладонь и пальцы
            self._gl_oval(wr_x, cy_top + 113, 4.6, 5.0, skin_lit, segments=14)
            self._gl_oval(wr_x - side * 3.8, cy_top + 112, 1.8, 3.0, skin_mid, segments=8)
            for fi in range(4):
                fx_f = wr_x + (fi - 1.5) * 1.9
                self._gl_oval(fx_f, cy_top + 117.5, 1.1, 2.4, skin_mid, segments=8)

        # 5. СКУЛЬПТУРНАЯ ОВАЛЬНАЯ ГОЛОВА, УШИ, ЛИЦО И ПРИЧЕСКА / ШАПКА
        head_cy = cy_top + 26
        # Уши по бокам головы
        self._gl_oval(cx - 16.5, head_cy + 1.0, 3.2, 5.0, skin_shd, segments=12)
        self._gl_oval(cx + 16.5, head_cy + 1.0, 3.2, 5.0, skin_shd, segments=12)
        # Овальный череп и скругленный подбородок
        self._gl_oval(cx, head_cy - 2.0, 15.8, 16.5, skin_lit, segments=24)
        self._gl_oval(cx, head_cy + 7.5, 12.2, 10.5, skin_lit, segments=20)
        # Легкий румянец на щеках и линия носа
        self._gl_oval(cx - 8.5, head_cy + 3.5, 3.5, 2.2, (226, 162, 134, 180), segments=10)
        self._gl_oval(cx + 8.5, head_cy + 3.5, 3.5, 2.2, (226, 162, 134, 180), segments=10)
        self._gl_line(cx, head_cy - 2.0, cx - 1.2, head_cy + 4.5, skin_shd, 1.6)
        self._gl_oval(cx, head_cy + 4.8, 2.4, 1.6, skin_shd, segments=10)
        # Выразительные глаза (белок, радужка, зрачок и живой белый блик) и брови
        for side_e in (-1.0, 1.0):
            ex = cx + side_e * 6.5
            ey = head_cy - 1.5
            self._gl_line(ex - 4.2, ey - 4.5, ex + 4.2, ey - 4.0, (72, 48, 32, 255), 2.0)  # бровь
            self._gl_oval(ex, ey, 3.8, 2.6, (245, 248, 252, 255), segments=12)
            self._gl_oval(ex, ey, 2.2, 2.2, (54, 112, 158, 255), segments=12)
            self._gl_oval(ex, ey, 1.2, 1.2, (18, 22, 28, 255), segments=10)
            self._gl_oval(ex + 0.8, ey - 0.8, 0.7, 0.7, (255, 255, 255, 255), segments=8)
        # Естественные губы
        self._gl_capsule(cx - 3.8, head_cy + 9.8, cx + 3.8, head_cy + 9.8, 1.5, 1.5, (182, 112, 96, 255))
        self._gl_line(cx - 3.5, head_cy + 9.8, cx + 3.5, head_cy + 9.8, (135, 76, 64, 240), 1.2)

        if has_helmet:
            # Скругленная меховая шапка-ушанка на голове
            self._gl_oval(cx, head_cy - 10.5, 18.5, 10.5, (178, 132, 88, 255), segments=20)
            self._gl_capsule(cx - 14, head_cy - 6.5, cx + 14, head_cy - 6.5, 4.5, 4.5, (240, 235, 220, 255))
            self._gl_capsule(cx - 17.5, head_cy - 4.0, cx - 16.5, head_cy + 9.0, 3.8, 3.2, (162, 118, 76, 255))
            self._gl_capsule(cx + 17.5, head_cy - 4.0, cx + 16.5, head_cy + 9.0, 3.8, 3.2, (162, 118, 76, 255))
        else:
            # Объемная скругленная прическа с прядями волос
            self._gl_oval(cx, head_cy - 11.5, 16.5, 8.0, (74, 48, 30, 255), segments=20)
            self._gl_oval(cx - 11.0, head_cy - 8.5, 6.5, 5.5, (64, 42, 26, 255), segments=14)
            self._gl_oval(cx + 11.0, head_cy - 8.5, 6.5, 5.5, (64, 42, 26, 255), segments=14)
            self._gl_oval(cx - 3.0, head_cy - 10.0, 8.0, 4.5, (88, 58, 36, 255), segments=14)

        # 6. Отображение текущего предмета в руке персонажа
        held_slot = p.slots[p.active_hotbar_slot] if 0 <= p.active_hotbar_slot < 9 else None
        if held_slot is not None:
            self._draw_item_icon_gl(str(held_slot["item"]), cx + 14, cy_top + 98, 28)

        def_pct = int(round(p.armor_reduction * 100))
        self.gl_text.draw_text(
            self.font_sm,
            f"Защита: {def_pct}%",
            cx,
            y + h - 16,
            (135, 255, 185),
            center=True,
        )

    def _render_gl_inventory_and_chest_modal(self, w: int, h: int) -> None:
        """
        Отрисовывает:
          1) Слева — модель самого персонажа в полный рост + 4 отдельные вертикальные ячейки брони/одежды
             (Голова/Шапка, Торс/Доспех, Штаны, Носки/Обувь).
          2) В центре — 25 свободных ячеек основного Инвентаря (5x5), где ячейки 1..9 напрямую связаны с Хотбаром 1..9!
          3) Кнопку сброса предмета из инвентаря на землю [Q].
          4) Справа (если открыт сундук) — 15 свободных ячеек Сундука (3x5).
        """
        p = self.game.player
        chest = self.game.active_chest
        has_chest = chest is not None
        bw = 1190 if has_chest else 860
        bh = 510
        bx = (w - bw) * 0.5
        by = (h - bh) * 0.5

        self._gl_rect(bx, by, bw, bh, (14, 20, 30, 246))
        self._gl_border(bx, by, bw, bh, (110, 195, 255, 255), 2.2)

        title = f"ИНВЕНТАРЬ И ПЕРСОНАЖ  +  {chest.name.upper()}" if has_chest else "ИНВЕНТАРЬ И ЭКИПИРОВКА ПЕРСОНАЖА"
        self.gl_text.draw_text(self.font_lg, title, bx + 20, by + 12, (255, 225, 110))

        # Кнопка закрытия окна инвентаря (особенно удобна на телефоне!)
        cl_x, cl_y, cl_w, cl_h = bx + bw - 126, by + 10, 108, 28
        self.ui_modal_close_btn_rect = (cl_x, cl_y, cl_w, cl_h)
        self._gl_rect(cl_x, cl_y, cl_w, cl_h, (125, 42, 48, 245))
        self._gl_border(cl_x, cl_y, cl_w, cl_h, (255, 150, 150, 255), 1.6)
        self.gl_text.draw_text(self.font_sm, "Закрыть [X]", cl_x + cl_w * 0.5, cl_y + 14, (255, 245, 245), center=True)

        # КНОПКА СОЗДАНИЯ СТОЛА МАСТЕРСКОЙ В ИНВЕНТАРЕ (За 2 Дерева!)
        wb_btn_x, wb_btn_y, wb_btn_w, wb_btn_h = bx + 20, by + 44, 415, 34
        self.ui_workbench_btn_rect = (wb_btn_x, wb_btn_y, wb_btn_w, wb_btn_h)
        can_make_wb = p.inventory.get("wood", 0) >= 2
        btn_bg = (32, 82, 54, 245) if can_make_wb else (48, 34, 34, 230)
        btn_border = (110, 255, 160, 255) if can_make_wb else (185, 95, 95, 220)
        self._gl_rect(wb_btn_x, wb_btn_y, wb_btn_w, wb_btn_h, btn_bg)
        self._gl_border(wb_btn_x, wb_btn_y, wb_btn_w, wb_btn_h, btn_border, 2.0)
        wb_txt = f"СОЗДАТЬ СТОЛ (2 Дерева | Сейчас: {p.inventory.get('wood', 0)})"
        self.gl_text.draw_text(self.font_sm, wb_txt, wb_btn_x + wb_btn_w * 0.5, wb_btn_y + 17, (245, 255, 245), center=True)

        # КНОПКА ИСПОЛЬЗОВАТЬ / НАДЕТЬ БРОНЮ / В СУНДУК (замена ПКМ для телефона!)
        use_x, use_y, use_w, use_h = bx + 442, by + 44, 206, 34
        self.ui_inv_use_btn_rect = (use_x, use_y, use_w, use_h)
        self._gl_rect(use_x, use_y, use_w, use_h, (36, 74, 108, 244))
        self._gl_border(use_x, use_y, use_w, use_h, (125, 220, 255, 248), 1.8)
        use_lbl = "В сундук / Из сундука" if has_chest else "Надеть / Съесть"
        self.gl_text.draw_text(self.font_sm, use_lbl, use_x + use_w * 0.5, use_y + 17, (240, 252, 255), center=True)

        # КНОПКА СБРОСА ПРЕДМЕТА ИЗ ИНВЕНТАРЯ НА ЗЕМЛЮ [Q]
        dr_x, dr_y, dr_w, dr_h = bx + 655, by + 44, 185, 34
        self.ui_drop_btn_rect = (dr_x, dr_y, dr_w, dr_h)
        self._gl_rect(dr_x, dr_y, dr_w, dr_h, (96, 44, 36, 242))
        self._gl_border(dr_x, dr_y, dr_w, dr_h, (255, 155, 120, 245), 1.8)
        self.gl_text.draw_text(self.font_sm, "Выбросить [Q]", dr_x + dr_w * 0.5, dr_y + 17, (255, 240, 230), center=True)

        # 1. ПАНЕЛЬ ПЕРСОНАЖА + 4 ОТДЕЛЬНЫЕ ВЕРТИКАЛЬНЫЕ ЯЧЕЙКИ ЭКИПИРОВКИ СЛЕВА
        char_x = bx + 18
        char_y = by + 88
        self._draw_character_preview_gl(char_x, char_y, 116, 278)

        self.ui_armor_slot_rects.clear()
        armor_x = char_x + 124
        armor_w = 108
        armor_h = 64
        for a_idx in range(4):
            ay = char_y + a_idx * (armor_h + 7)
            self.ui_armor_slot_rects.append((a_idx, armor_x, ay, armor_w, armor_h))
            asl = p.armor_slots[a_idx]
            a_bg = (34, 54, 78, 242) if asl is not None else (18, 26, 38, 210)
            a_bd = (120, 235, 255, 245) if asl is not None else (75, 105, 138, 195)
            self._gl_rect(armor_x, ay, armor_w, armor_h, a_bg)
            self._gl_border(armor_x, ay, armor_w, armor_h, a_bd, 1.8 if asl is not None else 1.2)
            self.gl_text.draw_text(self.font_sm, ARMOR_SLOT_TITLES[a_idx][:12], armor_x + 5, ay + 3, (175, 225, 255))
            if asl is not None:
                ak = str(asl["item"])
                aname = RESOURCE_NAMES_RU.get(ak, ak)
                self._draw_item_icon_gl(ak, armor_x + 4, ay + 19, 34)
                self.gl_text.draw_text(self.font_sm, aname[:8], armor_x + 42, ay + 21, (245, 255, 250))
                self.gl_text.draw_text(self.font_sm, "Надето", armor_x + 42, ay + 37, (130, 255, 175))
                self._draw_slot_durability_bar_gl(asl, armor_x + 5, ay + armor_h - 8, armor_w - 10, 5)
            else:
                self.gl_text.draw_text(self.font_sm, "Пусто", armor_x + 32, ay + 34, (95, 112, 132))

        # 2. 25 СВОБОДНЫХ ЯЧЕЕК ОСНОВНОГО ИНВЕНТАРЯ (сетка 5x5 справа от панели персонажа)
        self.ui_inv_card_rects.clear()
        cols_count = 5
        card_w = 108
        card_h = 64
        start_x = bx + 262
        start_y = by + 88
        self.ui_inv_box_rect = (start_x - 4, start_y - 4, 5 * (card_w + 6) + 4, 5 * (card_h + 7) + 4)

        for idx in range(MAX_INVENTORY_SLOTS):
            row = idx // cols_count
            col = idx % cols_count
            cx_card = start_x + col * (card_w + 6)
            cy_card = start_y + row * (card_h + 7)
            self.ui_inv_card_rects.append((idx, cx_card, cy_card, card_w, card_h))

            sl = p.slots[idx]
            is_hotbar_linked = idx < 9
            is_sel = idx == self.game.selected_inv_idx

            if is_sel:
                bg_col = (46, 72, 104, 245)
                border_col = (255, 225, 85, 255)
            elif sl is not None:
                bg_col = (28, 44, 64, 238) if is_hotbar_linked else (22, 34, 50, 235)
                border_col = (225, 190, 85, 235) if is_hotbar_linked else (95, 145, 190, 220)
            else:
                bg_col = (18, 24, 34, 195) if is_hotbar_linked else (15, 20, 28, 180)
                border_col = (95, 115, 140, 180) if is_hotbar_linked else (52, 62, 76, 160)

            self._gl_rect(cx_card, cy_card, card_w, card_h, bg_col)
            self._gl_border(cx_card, cy_card, card_w, card_h, border_col, 2.0 if (is_sel or is_hotbar_linked) else 1.0)

            slot_title = f"Хотбар {idx + 1}" if is_hotbar_linked else f"Ячейка {idx + 1}"
            slot_title_col = (255, 215, 95) if is_hotbar_linked else (120, 138, 160)
            self.gl_text.draw_text(self.font_sm, slot_title, cx_card + 5, cy_card + 3, slot_title_col)

            if sl is not None:
                item_k = str(sl["item"])
                cnt = int(sl.get("count", 1))
                is_weapon = item_k in WEAPONS_DB and item_k != "workbench_item"
                name_ru = WEAPONS_DB[item_k].name if item_k in WEAPONS_DB else RESOURCE_NAMES_RU.get(item_k, item_k)
                self._draw_item_icon_gl(item_k, cx_card + 4, cy_card + 19, 34)
                self.gl_text.draw_text(self.font_sm, name_ru[:9], cx_card + 42, cy_card + 21, (245, 250, 255))
                sub_lbl = "Оружие" if is_weapon else ("Броня" if item_k in ITEM_TO_ARMOR_SLOT_IDX else f"x{cnt}")
                self.gl_text.draw_text(self.font_sm, sub_lbl, cx_card + 42, cy_card + 37, (140, 255, 175))
                self._draw_slot_durability_bar_gl(sl, cx_card + 5, cy_card + card_h - 8, card_w - 10, 5)

        self.gl_text.draw_text(
            self.font_sm,
            "Слева — персонаж и 4 вертикальные ячейки брони (ПКМ или Drag&Drop). Клавиша [Q] или перенос за окно — выбросить предмет!",
            bx + 20,
            by + bh - 24,
            (255, 225, 135),
        )

        # 3. 15 СВОБОДНЫХ ЯЧЕЕК СУНДУКА (сетка 3x5 справа, если открыт сундук)
        self.ui_chest_card_rects.clear()
        if has_chest:
            sx_chest = bx + 840
            sy_chest = by + 44
            self.ui_chest_box_rect = (sx_chest, sy_chest, 334, 420)
            self._gl_rect(sx_chest, sy_chest, 334, 420, (20, 28, 40, 242))
            self._gl_border(sx_chest, sy_chest, 334, 420, (240, 195, 90, 255), 1.8)
            self.gl_text.draw_text(self.font_md, "ЯЧЕЙКИ СУНДУКА:", sx_chest + 12, sy_chest + 10, (255, 220, 115))

            c_cols = 3
            c_w = 102
            c_h = 64
            c_start_x = sx_chest + 9
            c_start_y = sy_chest + 44
            for ci in range(MAX_CHEST_SLOTS):
                crow = ci // c_cols
                ccol = ci % c_cols
                cx_c = c_start_x + ccol * (c_w + 6)
                cy_c = c_start_y + crow * (c_h + 7)
                self.ui_chest_card_rects.append((ci, cx_c, cy_c, c_w, c_h))

                csl = chest.chest_slots[ci]
                c_bg = (30, 44, 62, 238) if csl is not None else (16, 22, 32, 185)
                c_bd = (240, 195, 90, 225) if csl is not None else (62, 74, 90, 165)
                self._gl_rect(cx_c, cy_c, c_w, c_h, c_bg)
                self._gl_border(cx_c, cy_c, c_w, c_h, c_bd, 1.4 if csl is not None else 1.0)
                self.gl_text.draw_text(self.font_sm, f"Сундук {ci + 1}", cx_c + 5, cy_c + 3, (215, 190, 120))

                if csl is not None:
                    ck = str(csl["item"])
                    cv = int(csl.get("count", 1))
                    cname = WEAPONS_DB[ck].name if ck in WEAPONS_DB else RESOURCE_NAMES_RU.get(ck, ck)
                    self._draw_item_icon_gl(ck, cx_c + 4, cy_c + 19, 34)
                    self.gl_text.draw_text(self.font_sm, cname[:8], cx_c + 40, cy_c + 21, (245, 250, 255))
                    self.gl_text.draw_text(self.font_sm, f"x{cv}", cx_c + 40, cy_c + 37, (150, 255, 180))
                    self._draw_slot_durability_bar_gl(csl, cx_c + 5, cy_c + c_h - 8, c_w - 10, 5)
        else:
            self.ui_chest_box_rect = None

    def _render_gl_mobile_controls(self, w: int, h: int) -> None:
        """
        Отрисовывает полноценное сенсорное управление для телефона:
          1) Слева (над блоком состояния) — плавный виртуальный 360° джойстик движения с авто-бегом у края.
          2) Справа — эргономичный кластер круглых сенсорных кнопок:
             - Большая кнопка [УДАР / ДОБЫЧА / ВЫСТРЕЛ / ПОСТРОИТЬ]
             - Кнопка [ПРЫЖОК] (и [НЫРНУТЬ] в воде)
             - Кнопка [ДЕЙСТВ. F] (костер, верстак, сундук, дверь, подбор вещей, вода)
             - Кнопка [БЕГ] (фиксация спринта)
             - Кнопка [ЕДА / ХИЛ]
          3) Быстрые кнопки меню [РЮКЗАК], [СТРОЙКА], [НАВЫКИ], [БРОСИТЬ] и панель выбора/поворота блоков в режиме строительства!
        """
        p = self.game.player
        tcache = self.gl_text
        self.ui_mobile_buttons.clear()
        self.ui_mobile_rect_buttons.clear()

        # 1. ВИРТУАЛЬНЫЙ ДЖОЙСТИК ДВИЖЕНИЯ СЛЕВА (не перекрывает 6 полосок состояния!)
        joy_r = 64.0
        joy_cx = 112.0
        joy_cy = max(210.0, h - 276.0)
        self.ui_mobile_joy_circle = (joy_cx, joy_cy, joy_r)

        # Полупрозрачное кольцо базы джойстика + 4 направляющих маркера
        self._gl_oval(joy_cx, joy_cy, joy_r, joy_r, (14, 22, 34, 155), segments=28)
        self._gl_oval(joy_cx, joy_cy, joy_r * 0.96, joy_r * 0.96, (28, 44, 64, 115), segments=28)
        self._gl_line(joy_cx - joy_r + 10, joy_cy, joy_cx + joy_r - 10, joy_cy, (95, 155, 205, 110), 1.4)
        self._gl_line(joy_cx, joy_cy - joy_r + 10, joy_cx, joy_cy + joy_r - 10, (95, 155, 205, 110), 1.4)
        tcache.draw_text(self.font_sm, "W", joy_cx, joy_cy - joy_r + 12, (175, 220, 255), center=True)
        tcache.draw_text(self.font_sm, "S", joy_cx, joy_cy + joy_r - 12, (175, 220, 255), center=True)
        tcache.draw_text(self.font_sm, "A", joy_cx - joy_r + 12, joy_cy, (175, 220, 255), center=True)
        tcache.draw_text(self.font_sm, "D", joy_cx + joy_r - 12, joy_cy, (175, 220, 255), center=True)

        knob_x = joy_cx + self.game.touch_joy_dx * (joy_r * 0.68)
        knob_y = joy_cy + self.game.touch_joy_dy * (joy_r * 0.68)
        knob_active = self.game.touch_joy_active
        knob_col = (95, 225, 255, 235) if knob_active else (75, 155, 215, 195)
        self._gl_oval(knob_x, knob_y, 26.0, 26.0, knob_col, segments=22)
        self._gl_oval(knob_x, knob_y, 18.0, 18.0, (220, 248, 255, 230) if knob_active else (165, 215, 245, 185), segments=18)
        tcache.draw_text(self.font_sm, "ХОДЬБА", joy_cx, joy_cy + joy_r + 12, (185, 225, 255), center=True)

        # 2. КЛАСТЕР КРУГЛЫХ СЕНСОРНЫХ КНОПОК ДЕЙСТВИЙ СПРАВА
        # Размещаем кнопки левее миникарты и над ней, чтобы удобно нажимать большим пальцем правой руки
        held_id = p.hotbar[p.active_hotbar_slot]
        if self.game.build_mode or held_id == "hammer":
            atk_label = "СТРОИТЬ"
            atk_col = (42, 165, 98, 225)
        elif held_id == "hunting_bow":
            atk_label = "ВЫСТРЕЛ"
            atk_col = (215, 135, 42, 225)
        elif held_id == "fishing_rod":
            atk_label = "УДОЧКА"
            atk_col = (48, 155, 215, 225)
        elif held_id == "workbench_item":
            atk_label = "ПОСТАВИТЬ"
            atk_col = (52, 175, 110, 225)
        else:
            atk_label = "УДАР"
            atk_col = (215, 68, 62, 225)

        # Координаты кнопок справа
        atk_cx, atk_cy, atk_r = w - 235.0, h - 108.0, 44.0
        jmp_cx, jmp_cy, jmp_r = w - 125.0, h - 215.0, 34.0
        use_cx, use_cy, use_r = w - 215.0, h - 208.0, 34.0
        run_cx, run_cy, run_r = w - 322.0, h - 88.0, 30.0
        eat_cx, eat_cy, eat_r = w - 310.0, h - 172.0, 30.0

        circle_btns = [
            ("attack", atk_cx, atk_cy, atk_r, atk_label, atk_col, self.game.touch_attack_held),
            ("jump", jmp_cx, jmp_cy, jmp_r, "ПРЫЖОК", (58, 152, 225, 215), self.game.touch_jump_held),
            ("interact", use_cx, use_cy, use_r, "ДЕЙСТВ. F", (225, 168, 48, 220), False),
            (
                "sprint",
                run_cx,
                run_cy,
                run_r,
                "БЕГ: ВКЛ" if self.game.touch_sprint_locked else "БЕГ",
                (48, 195, 108, 235) if self.game.touch_sprint_locked else (42, 68, 92, 205),
                self.game.touch_sprint_locked,
            ),
            ("heal", eat_cx, eat_cy, eat_r, "ЕДА / ХИЛ", (195, 72, 132, 215), False),
        ]
        if p.in_water:
            circle_btns.append(("dive", w - 48.0, h - 215.0, 30.0, "НЫРНУТЬ", (38, 118, 195, 220), self.game.touch_dive_held))

        for act_id, bcx, bcy, br, blbl, bcol, is_pressed in circle_btns:
            self.ui_mobile_buttons.append((act_id, bcx, bcy, br, blbl))
            outer_c = (255, 238, 120, 245) if is_pressed else (195, 230, 255, 215)
            fill_c = (min(255, bcol[0] + 35), min(255, bcol[1] + 35), min(255, bcol[2] + 35), 245) if is_pressed else bcol
            self._gl_oval(bcx, bcy, br + 2.5, br + 2.5, outer_c, segments=24)
            self._gl_oval(bcx, bcy, br, br, fill_c, segments=24)
            tcache.draw_text(self.font_sm, blbl, bcx, bcy, (255, 255, 255), center=True)

        # 3. МОБИЛЬНЫЕ КНОПКИ МЕНЮ, СОХРАНЕНИЯ И ЗАГРУЗКИ ДЛЯ ТЕЛЕФОНА
        menu_pills = [
            ("inv_toggle", 215.0, h - 252.0, 114.0, 32.0, "РЮКЗАК [I]", (36, 78, 118, 225)),
            ("build_toggle", 215.0, h - 290.0, 114.0, 32.0, "СТРОЙКА [B]", (38, 98, 72, 225) if self.game.build_mode else (32, 58, 78, 215)),
            ("skills_toggle", 215.0, h - 328.0, 114.0, 32.0, f"НАВЫКИ ({p.skill_points})", (128, 96, 36, 225) if p.skill_points > 0 else (44, 54, 72, 215)),
            ("drop_item", 215.0, h - 366.0, 114.0, 32.0, "БРОСИТЬ [Q]", (108, 46, 42, 215)),
            ("save_game", 215.0, h - 404.0, 114.0, 32.0, "СОХРАНИТЬ", (30, 96, 68, 232)),
            ("load_game", 215.0, h - 442.0, 114.0, 32.0, "ЗАГРУЗИТЬ", (46, 72, 116, 232)),
        ]
        for act_id, rx, ry, rw, rh, rlbl, rcol in menu_pills:
            self.ui_mobile_rect_buttons.append((act_id, rx, ry, rw, rh, rlbl))
            self._gl_rect(rx, ry, rw, rh, rcol)
            self._gl_border(rx, ry, rw, rh, (150, 215, 255, 230), 1.5)
            tcache.draw_text(self.font_sm, rlbl, rx + rw * 0.5, ry + rh * 0.5, (245, 252, 255), center=True)

        # 4. ЕСЛИ АКТИВЕН РЕЖИМ СТРОИТЕЛЬСТВА — СЕНСОРНЫЕ КНОПКИ ВЫБОРА ДЕТАЛИ, ПОВОРОТА 90° И СНОСА НАД ХОТБАРОМ!
        if (self.game.build_mode or held_id == "hammer") and self.game.has_placed_workbench():
            by_b = h - 144.0
            cx_mid = w * 0.5
            build_btns = [
                ("build_prev", cx_mid - 230.0, by_b, 104.0, 32.0, "< Пред. блок", (34, 72, 96, 235)),
                ("build_rot", cx_mid - 118.0, by_b, 114.0, 32.0, "Поворот 90°", (44, 92, 68, 235)),
                ("build_next", cx_mid + 4.0, by_b, 104.0, 32.0, "След. блок >", (34, 72, 96, 235)),
                ("build_del", cx_mid + 116.0, by_b, 114.0, 32.0, "Снести блок", (118, 44, 44, 235)),
            ]
            for act_id, rx, ry, rw, rh, rlbl, rcol in build_btns:
                self.ui_mobile_rect_buttons.append((act_id, rx, ry, rw, rh, rlbl))
                self._gl_rect(rx, ry, rw, rh, rcol)
                self._gl_border(rx, ry, rw, rh, (145, 245, 190, 240), 1.6)
                tcache.draw_text(self.font_sm, rlbl, rx + rw * 0.5, ry + rh * 0.5, (248, 255, 248), center=True)

    def _trigger_mobile_button_action(self, act_id: str, pressed: bool) -> None:
        """Выполняет действие при нажатии или отпускании сенсорной кнопки телефона."""
        g = self.game
        if act_id == "attack":
            g.touch_attack_held = pressed
            if pressed:
                g.perform_primary_action()
        elif act_id == "jump":
            g.touch_jump_held = pressed
        elif act_id == "dive":
            g.touch_dive_held = pressed
        elif act_id == "interact" and pressed:
            g.interact_world()
        elif act_id == "sprint" and pressed:
            g.touch_sprint_locked = not g.touch_sprint_locked
        elif act_id == "heal" and pressed:
            g.consume_food_or_heal()
        elif act_id == "inv_toggle" and pressed:
            g.show_inventory = not g.show_inventory
            if not g.show_inventory:
                g.active_chest = None
            else:
                g.show_crafting = False
                g.show_skills = False
        elif act_id == "build_toggle" and pressed:
            if not g.has_placed_workbench():
                g.add_notification("Сначала создайте Стол мастерской в рюкзаке (за 2 дерева) и поставьте его!", 3.5, (255, 145, 115))
            else:
                g.build_mode = not g.build_mode
                g.sound.play("build")
        elif act_id == "skills_toggle" and pressed:
            g.show_skills = not g.show_skills
            g.show_inventory = False
            g.show_crafting = False
        elif act_id == "drop_item" and pressed:
            g.drop_item_from_slot("inv", g.player.active_hotbar_slot, drop_all=True)
        elif act_id == "save_game" and pressed:
            g.save_game()
            g.sound.play("heal")
        elif act_id == "load_game" and pressed:
            if g.load_game():
                g.sound.play("heal")
        elif act_id == "build_prev" and pressed:
            g.selected_build_idx = (g.selected_build_idx - 1) % len(BUILD_PIECES)
            g.sound.play("build")
        elif act_id == "build_next" and pressed:
            g.selected_build_idx = (g.selected_build_idx + 1) % len(BUILD_PIECES)
            g.sound.play("build")
        elif act_id == "build_rot" and pressed:
            g.build_rotation = (g.build_rotation + 90.0) % 360.0
            g.sound.play("build")
        elif act_id == "build_del" and pressed:
            g.remove_last_or_hovered_structure()

    def _update_joystick_from_point(self, px: float, py: float) -> None:
        """Обновляет вектор отклонения виртуального джойстика (-1..+1) по точке касания (px, py)."""
        jcx, jcy, jr = self.ui_mobile_joy_circle
        dx = px - jcx
        dy = py - jcy
        dist = math.hypot(dx, dy)
        max_r = max(12.0, jr)
        if dist > max_r:
            dx = (dx / dist) * max_r
            dy = (dy / dist) * max_r
        self.game.touch_joy_dx = dx / max_r
        self.game.touch_joy_dy = dy / max_r

    def handle_touch_or_Look_motion(self, px: float, py: float, dx: float, dy: float, pointer_id: int = -1) -> bool:
        """Обрабатывает движение пальца или мыши для виртуального джойстика и 360° обзора камерой."""
        g = self.game
        if not g.mobile_controls_enabled:
            return False
        if g.touch_joy_active and g.touch_joy_pointer_id == pointer_id:
            self._update_joystick_from_point(px, py)
            return True
        if g.touch_look_active and g.touch_look_pointer_id == pointer_id:
            sens = 0.28
            g.player.yaw = (g.player.yaw + dx * sens) % 360.0
            g.player.pitch = max(-84.0, min(84.0, g.player.pitch - dy * sens))
            g.touch_look_last_pos = (px, py)
            return True
        return False

    def handle_touch_or_pointer_up(self, pointer_id: int = -1) -> None:
        """Сбрасывает удержание джойстика, обзора или кнопки удара/прыжка при отпускании пальца."""
        g = self.game
        if g.touch_joy_active and (g.touch_joy_pointer_id == pointer_id or pointer_id == -1):
            g.touch_joy_active = False
            g.touch_joy_pointer_id = None
            g.touch_joy_dx = 0.0
            g.touch_joy_dy = 0.0
        if g.touch_look_active and (g.touch_look_pointer_id == pointer_id or pointer_id == -1):
            g.touch_look_active = False
            g.touch_look_pointer_id = None
        if g.touch_active_button is not None:
            self._trigger_mobile_button_action(g.touch_active_button, False)
            g.touch_active_button = None

    def _render_gl_minimap(self, w: int, h: int) -> None:
        map_size = 144
        mx0 = w - map_size - 16
        my0 = h - map_size - 16
        self._gl_rect(mx0, my0, map_size, map_size, (12, 18, 26, 225))
        self._gl_border(mx0, my0, map_size, map_size, (90, 145, 185, 235), 2.0)

        p = self.game.player
        scale = (map_size * 0.45) / 85.0
        mcx = mx0 + map_size * 0.5
        mcy = my0 + map_size * 0.5

        for st in self.game.structures:
            dx = (st.x - p.x) * scale
            dz = (st.z - p.z) * scale
            if abs(dx) < map_size * 0.44 and abs(dz) < map_size * 0.44:
                self._gl_rect(mcx + dx - 3, mcy + dz - 3, 6, 6, (255, 215, 90, 255))

        for anim in self.game.animals:
            if not anim.alive:
                continue
            dx = (anim.x - p.x) * scale
            dz = (anim.z - p.z) * scale
            if abs(dx) < map_size * 0.44 and abs(dz) < map_size * 0.44:
                if anim.aquatic:
                    col = (80, 200, 255, 255)
                elif anim.hostile:
                    col = (255, 75, 75, 255)
                else:
                    col = (110, 245, 130, 255)
                self._gl_rect(mcx + dx - 2, mcy + dz - 2, 5, 5, col)

        # Метка места гибели и оставшегося времени (5 минут) на миникарте и над ней!
        if self.game.last_death_pos is not None and self.game.last_death_timer > 0.0:
            ddx = (self.game.last_death_pos[0] - p.x) * scale
            ddz = (self.game.last_death_pos[2] - p.z) * scale
            if abs(ddx) < map_size * 0.44 and abs(ddz) < map_size * 0.44:
                self._gl_line(mcx + ddx - 5, mcy + ddz - 5, mcx + ddx + 5, mcy + ddz + 5, (255, 75, 75, 255), 2.4)
                self._gl_line(mcx + ddx - 5, mcy + ddz + 5, mcx + ddx + 5, mcy + ddz - 5, (255, 75, 75, 255), 2.4)
            rem_sec = int(math.ceil(self.game.last_death_timer))
            mm_r, ss_r = divmod(rem_sec, 60)
            self._gl_rect(mx0 - 76, my0 - 28, map_size + 76, 24, (58, 18, 22, 230))
            self._gl_border(mx0 - 76, my0 - 28, map_size + 76, 24, (255, 110, 100, 245), 1.5)
            self.gl_text.draw_text(
                self.font_sm,
                f"Вещи ({int(self.game.last_death_pos[0])},{int(self.game.last_death_pos[2])}): {mm_r:02d}:{ss_r:02d}",
                mx0 - 68,
                my0 - 24,
                (255, 215, 195),
            )

        self._gl_rect(mcx - 3, mcy - 3, 6, 6, (255, 255, 255, 255))
        yaw_r = math.radians(p.yaw)
        self._gl_line(mcx, mcy, mcx + math.sin(yaw_r) * 14, mcy - math.cos(yaw_r) * 14, (255, 240, 115, 255), 2.0)

    def _render_gl_crafting_modal(self, w: int, h: int) -> None:
        """
        ЯЧЕЕЧНОЕ (СЕТОЧНОЕ) МЕНЮ КРАФТА НА СТОЛЕ МАСТЕРСКОЙ:
        Все рецепты оружия, инструментов, брони и припасов отображаются в виде сетки ячеек (4x4) с крупными иконками,
        а в нижней панели выводятся подробные требования и кнопка создания выбранного предмета!
        """
        bw, bh = 740, 520
        bx = (w - bw) * 0.5
        by = (h - bh) * 0.5
        self._gl_rect(bx, by, bw, bh, (14, 20, 30, 246))
        self._gl_border(bx, by, bw, bh, (110, 195, 250, 255), 2.2)

        self.gl_text.draw_text(
            self.font_lg,
            "СТОЛ МАСТЕРСКОЙ — ЯЧЕЕЧНЫЙ ВЫБОР КРАФТА",
            bx + 20,
            by + 12,
            (255, 225, 115),
        )
        cl_x, cl_y, cl_w, cl_h = bx + bw - 126, by + 10, 108, 28
        self.ui_modal_close_btn_rect = (cl_x, cl_y, cl_w, cl_h)
        self._gl_rect(cl_x, cl_y, cl_w, cl_h, (125, 42, 48, 245))
        self._gl_border(cl_x, cl_y, cl_w, cl_h, (255, 150, 150, 255), 1.6)
        self.gl_text.draw_text(self.font_sm, "Закрыть [X]", cl_x + cl_w * 0.5, cl_y + 14, (255, 245, 245), center=True)
        self.gl_text.draw_text(
            self.font_sm,
            "Выберите предмет кликом ЛКМ по ячейке, а для создания нажмите кнопку 'СОЗДАТЬ' внизу (или Enter):",
            bx + 20,
            by + 38,
            (190, 220, 245),
        )

        self.ui_recipe_row_rects.clear()
        cols = 4
        cell_w = 168
        cell_h = 74
        start_x = bx + 20
        start_y = by + 64

        for i, rec in enumerate(CRAFTING_RECIPES):
            row = i // cols
            col = i % cols
            cx_c = start_x + col * (cell_w + 9)
            cy_c = start_y + row * (cell_h + 8)
            self.ui_recipe_row_rects.append((i, cx_c, cy_c, cell_w, cell_h))

            is_sel = i == self.game.selected_recipe_idx
            can_c = self.game.can_craft(rec)
            if is_sel:
                bg_c = (44, 74, 108, 245) if can_c else (68, 42, 48, 245)
                bd_c = (255, 225, 85, 255)
            else:
                bg_c = (24, 42, 58, 235) if can_c else (24, 26, 36, 215)
                bd_c = (95, 215, 145, 225) if can_c else (85, 75, 88, 185)

            self._gl_rect(cx_c, cy_c, cell_w, cell_h, bg_c)
            self._gl_border(cx_c, cy_c, cell_w, cell_h, bd_c, 2.2 if is_sel else 1.2)

            icon_key = rec.unlock_weapon if rec.unlock_weapon else rec.result_item
            self._draw_item_icon_gl(icon_key, cx_c + 6, cy_c + 18, 44)
            self.gl_text.draw_text(self.font_sm, f"Ячейка #{i + 1}", cx_c + 6, cy_c + 2, (215, 200, 130) if is_sel else (130, 150, 175))
            self.gl_text.draw_text(self.font_sm, rec.name[:13], cx_c + 54, cy_c + 18, (245, 250, 255))
            short_cost = " ".join(f"{RESOURCE_NAMES_RU.get(k, k)[:3]}:{v}" for k, v in rec.cost.items())
            self.gl_text.draw_text(self.font_sm, short_cost[:16], cx_c + 54, cy_c + 36, (185, 215, 235))
            status_lbl = "Доступно" if can_c else "Нет рес."
            status_col = (130, 255, 165) if can_c else (255, 135, 125)
            self.gl_text.draw_text(self.font_sm, status_lbl, cx_c + 54, cy_c + 54, status_col)

        # Нижняя панель подробностей выбранной ячейки рецепта + кнопка СОЗДАТЬ
        if 0 <= self.game.selected_recipe_idx < len(CRAFTING_RECIPES):
            sel_rec = CRAFTING_RECIPES[self.game.selected_recipe_idx]
            can_sel = self.game.can_craft(sel_rec)
            py_det = by + bh - 112
            self._gl_rect(bx + 20, py_det, bw - 40, 96, (20, 30, 44, 242))
            self._gl_border(bx + 20, py_det, bw - 40, 96, (110, 185, 235, 230), 1.5)

            sel_icon = sel_rec.unlock_weapon if sel_rec.unlock_weapon else sel_rec.result_item
            self._draw_item_icon_gl(sel_icon, bx + 32, py_det + 16, 62)
            self.gl_text.draw_text(self.font_md, f"{sel_rec.name} (+{sel_rec.xp_reward} XP)", bx + 106, py_det + 12, (255, 230, 120))
            self.gl_text.draw_text(self.font_sm, sel_rec.description, bx + 106, py_det + 36, (215, 232, 248))

            req_parts = [
                f"{RESOURCE_NAMES_RU.get(k, k)}: {self.game.player.inventory.get(k, 0)}/{v}"
                for k, v in sel_rec.cost.items()
            ]
            req_col = (140, 255, 175) if can_sel else (255, 150, 135)
            self.gl_text.draw_text(self.font_sm, "Требуется: " + " | ".join(req_parts), bx + 106, py_det + 62, req_col)

            cbtn_x, cbtn_y, cbtn_w, cbtn_h = bx + bw - 210, py_det + 24, 175, 48
            self.ui_craft_confirm_btn_rect = (cbtn_x, cbtn_y, cbtn_w, cbtn_h)
            cbtn_bg = (36, 98, 62, 248) if can_sel else (58, 38, 42, 235)
            cbtn_bd = (130, 255, 175, 255) if can_sel else (195, 105, 105, 220)
            self._gl_rect(cbtn_x, cbtn_y, cbtn_w, cbtn_h, cbtn_bg)
            self._gl_border(cbtn_x, cbtn_y, cbtn_w, cbtn_h, cbtn_bd, 2.0)
            self.gl_text.draw_text(self.font_md, "СОЗДАТЬ", cbtn_x + cbtn_w * 0.5, cbtn_y + 24, (245, 255, 248), center=True)

    def _render_gl_skills_modal(self, w: int, h: int) -> None:
        p = self.game.player
        bx, by, bw, bh = w * 0.5 - 300, h * 0.5 - 185, 600, 360
        self._gl_rect(bx, by, bw, bh, (18, 22, 34, 242))
        self._gl_border(bx, by, bw, bh, (240, 195, 90, 255), 2.0)
        self.gl_text.draw_text(
            self.font_lg,
            f"СИСТЕМА РПГ — УРОВЕНЬ {p.level} (Очков навыков: {p.skill_points})",
            bx + 22,
            by + 16,
            (255, 225, 110),
        )
        cl_x, cl_y, cl_w, cl_h = bx + bw - 124, by + 12, 106, 28
        self.ui_modal_close_btn_rect = (cl_x, cl_y, cl_w, cl_h)
        self._gl_rect(cl_x, cl_y, cl_w, cl_h, (125, 42, 48, 245))
        self._gl_border(cl_x, cl_y, cl_w, cl_h, (255, 150, 150, 255), 1.6)
        self.gl_text.draw_text(self.font_sm, "Закрыть [X]", cl_x + cl_w * 0.5, cl_y + 14, (255, 245, 245), center=True)
        rows = [
            ("strength", "Сила (Strength)", p.skills["strength"], "+16% к урону топором, мечом и копьем за уровень"),
            ("vitality", "Живучесть (Vitality)", p.skills["vitality"], "+25 к макс. Здоровью и защита от хищников"),
            ("endurance", "Выносливость (Endurance)", p.skills["endurance"], "+20 к Выносливости и скорость бега/плавания"),
            ("harvesting", "Мастер добычи (Harvesting)", p.skills["harvesting"], "+25% к рубке деревьев/руды и бонус ресурсов"),
            ("hunter", "Инстинкт охотника (Hunter)", p.skills["hunter"], "+20% к урону лука и шанс крит. удара"),
        ]
        self.ui_skill_upgrade_rects.clear()
        for idx, (skey, title, val, desc) in enumerate(rows):
            ry = by + 68 + idx * 52
            self.ui_skill_upgrade_rects.append((skey, bx + 18, ry, bw - 36, 44))
            self._gl_rect(bx + 18, ry, bw - 36, 44, (30, 38, 54, 235))
            self.gl_text.draw_text(self.font_md, f"{title}: Ур. {val}", bx + 28, ry + 4, (150, 245, 180))
            self.gl_text.draw_text(self.font_sm, desc, bx + 28, ry + 24, (210, 222, 235))
            if p.skill_points > 0:
                self._gl_rect(bx + bw - 135, ry + 8, 105, 28, (42, 95, 62, 240))
                self._gl_border(bx + bw - 135, ry + 8, 105, 28, (125, 255, 165, 255), 1.4)
                self.gl_text.draw_text(self.font_sm, "+ Улучшить", bx + bw - 82, ry + 22, (240, 255, 245), center=True)

    def handle_mouse_down(self, mx: int, my: int, button: int) -> bool:
        """
        Обрабатывает клики по кнопкам Настроек, Подсказок, слотам Хотбара, Инвентаря (25 ячеек) и Сундука (15 ячеек)
        с точным совпадением точки захвата мыши при Drag & Drop!
        """
        self.sync_viewport_size()

        # 0. Клик по кнопкам "Телефон (Сенсор)", "Настройки", "Во весь экран [F11]" или "Подсказки клавиш" в верхней панели
        if self.ui_quests_btn_rect is not None:
            qbx, qby, qbw, qbh = self.ui_quests_btn_rect
            if qbx <= mx <= qbx + qbw and qby <= my <= qby + qbh:
                self.game.show_quests = not self.game.show_quests
                self.game.sound.play("build")
                return True

        if self.ui_mobile_toggle_btn_rect is not None:
            mbx, mby, mbw, mbh = self.ui_mobile_toggle_btn_rect
            if mbx <= mx <= mbx + mbw and mby <= my <= mby + mbh:
                self.game.mobile_controls_enabled = not self.game.mobile_controls_enabled
                if not self.game.mobile_controls_enabled:
                    self.handle_touch_or_pointer_up(-1)
                st_m = "ВКЛЮЧЕНО (Экранный джойстик и кнопки)" if self.game.mobile_controls_enabled else "ВЫКЛЮЧЕНО (Классический режим ПК)"
                self.game.add_notification(f"Управление для телефона: {st_m}", 3.0, (145, 255, 190))
                return True

        if (
            self.game.show_inventory or self.game.show_crafting or self.game.show_skills
        ) and self.ui_modal_close_btn_rect is not None:
            cx_m, cy_m, cw_m, ch_m = self.ui_modal_close_btn_rect
            if cx_m <= mx <= cx_m + cw_m and cy_m <= my <= cy_m + ch_m:
                self.game.show_inventory = False
                self.game.active_chest = None
                self.game.show_crafting = False
                self.game.show_skills = False
                self.game.dragged_item = None
                self.game.drag_source = None
                return True

        if self.ui_fullscreen_btn_rect is not None:
            fx, fy, fw, fh = self.ui_fullscreen_btn_rect
            if fx <= mx <= fx + fw and fy <= my <= fy + fh:
                self.toggle_fullscreen()
                return True

        if self.ui_settings_btn_rect is not None:
            sx, sy, sw, sh = self.ui_settings_btn_rect
            if sx <= mx <= sx + sw and sy <= my <= sy + sh:
                self.game.show_settings = not self.game.show_settings
                if self.game.show_settings:
                    self.game.show_controls_help = False
                return True

        if self.ui_help_btn_rect is not None:
            hx, hy, hw, hh = self.ui_help_btn_rect
            if hx <= mx <= hx + hw and hy <= my <= hy + hh:
                self.game.show_controls_help = not self.game.show_controls_help
                if self.game.show_controls_help:
                    self.game.show_settings = False
                return True

        # Обработка кликов внутри окна Настроек
        if self.game.show_settings:
            if self.ui_settings_close_rect is not None:
                cx, cy, cw, ch = self.ui_settings_close_rect
                if cx <= mx <= cx + cw and cy <= my <= cy + ch:
                    self.game.show_settings = False
                    return True
            for act, rx, ry, rw, rh in self.ui_settings_action_rects:
                if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                    if act == "fps_prev":
                        self.game.fps_cap_idx = (self.game.fps_cap_idx - 1) % len(FPS_CAPS)
                    elif act == "fps_next":
                        self.game.fps_cap_idx = (self.game.fps_cap_idx + 1) % len(FPS_CAPS)
                    elif act == "dist_minus":
                        self.game.adjust_render_distance(-15.0)
                    elif act == "dist_plus":
                        self.game.adjust_render_distance(15.0)
                    elif act == "grass_minus":
                        self.game.adjust_grass_density(-1)
                    elif act == "grass_plus":
                        self.game.adjust_grass_density(1)
                    elif act == "prof_prev":
                        self.game.apply_graphics_profile(self.game.graphics_profile_idx - 1)
                    elif act == "prof_next":
                        self.game.apply_graphics_profile(self.game.graphics_profile_idx + 1)
                    elif act == "detail_minus":
                        self.game.adjust_detail_quality(-1)
                    elif act == "detail_plus":
                        self.game.adjust_detail_quality(1)
                    elif act == "aa_minus":
                        self.game.adjust_antialiasing(-1)
                        self.apply_antialiasing_gl()
                    elif act == "aa_plus":
                        self.game.adjust_antialiasing(1)
                        self.apply_antialiasing_gl()
                    elif act == "chunk_minus":
                        self.game.adjust_chunk_gen_radius(-1)
                    elif act == "chunk_plus":
                        self.game.adjust_chunk_gen_radius(1)
                    elif act == "res_prev":
                        self.change_screen_resolution(-1)
                    elif act == "res_next":
                        self.change_screen_resolution(1)
                    elif act == "shadows_toggle":
                        self.game.toggle_shadows_and_reflections()
                    elif act == "fullscreen_toggle":
                        self.toggle_fullscreen()
                    elif act == "clouds_toggle":
                        self.game.clouds_enabled = not self.game.clouds_enabled
                    self.game.sound.play("build")
                    return True

        if self.game.show_controls_help and self.ui_help_close_rect is not None:
            cx, cy, cw, ch = self.ui_help_close_rect
            if cx <= mx <= cx + cw and cy <= my <= cy + ch:
                self.game.show_controls_help = False
                return True

        # 1. Клик или захват предмета из слотов Хотбара 1..9 (напрямую связанных с slots[0..8])
        for slot_i, rx, ry, rw, rh in self.ui_hotbar_rects:
            if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                if button == 1:
                    self.game.select_hotbar_slot(slot_i)
                    sl = self.game.player.slots[slot_i]
                    if sl is not None:
                        self.game.drag_source = ("hotbar", slot_i)
                        self.game.dragged_item = str(sl["item"])
                        self.game.dragged_count = int(sl.get("count", 1))
                        self.game.dragged_from_chest = False
                        self.game.drag_offset = (mx - rx, my - ry)
                        self.game.drag_card_size = (rw, rh)
                elif button == 3:
                    if self.game.show_inventory and self.game.active_chest is not None:
                        self.game.transfer_chest_item(to_chest=True, inv_slot_idx=slot_i)
                    elif self.game.player.slots[slot_i] is not None:
                        # Перемещаем из хотбара в свободную ячейку рюкзака (9..24)
                        free_bp = next((i for i in range(9, MAX_INVENTORY_SLOTS) if self.game.player.slots[i] is None), None)
                        if free_bp is not None:
                            self.game.move_or_swap_slots(("inv", slot_i), ("inv", free_bp))
                return True

        # 2. Если открыто окно РПГ-навыков — клик прокачивает навык
        if self.game.show_skills:
            for skey, rx, ry, rw, rh in self.ui_skill_upgrade_rects:
                if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                    msg = self.game.player.upgrade_skill(skey)
                    if msg:
                        self.game.add_notification(msg, 3.5, (255, 225, 100))
                    return True

        # 3. Если открыто ячеечное окно Крафта на Столе мастерской:
        #    Клик по ячейке рецепта ТОЛЬКО ВЫБИРАЕТ его, а крафт происходит только по кнопке 'СОЗДАТЬ'!
        if self.game.show_crafting:
            if self.ui_craft_confirm_btn_rect is not None:
                cx_b, cy_b, cw_b, ch_b = self.ui_craft_confirm_btn_rect
                if cx_b <= mx <= cx_b + cw_b and cy_b <= my <= cy_b + ch_b:
                    self.game.craft_recipe(self.game.selected_recipe_idx)
                    return True
            for rec_i, rx, ry, rw, rh in self.ui_recipe_row_rects:
                if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                    self.game.selected_recipe_idx = rec_i
                    self.game.sound.play("swing")
                    return True

        # 4. Если открыт Инвентарь (25 ячеек + 4 вертикальные ячейки брони + кнопка сброса) и/или Сундук (15 ячеек)
        if self.game.show_inventory:
            if self.ui_workbench_btn_rect is not None:
                bx, by, bw, bh = self.ui_workbench_btn_rect
                if bx <= mx <= bx + bw and by <= my <= by + bh:
                    self.game.craft_workbench_in_inventory()
                    return True

            if self.ui_inv_use_btn_rect is not None:
                ux_b, uy_b, uw_b, uh_b = self.ui_inv_use_btn_rect
                if ux_b <= mx <= ux_b + uw_b and uy_b <= my <= uy_b + uh_b:
                    sel_i = self.game.selected_inv_idx
                    if 0 <= sel_i < MAX_INVENTORY_SLOTS and self.game.player.slots[sel_i] is not None:
                        if self.game.active_chest is not None:
                            self.game.transfer_chest_item(to_chest=True, inv_slot_idx=sel_i)
                        else:
                            self.game.consume_specific_item(str(self.game.player.slots[sel_i]["item"]))
                    elif self.game.active_chest is not None:
                        self.game.transfer_chest_item(to_chest=False)
                    return True

            if self.ui_drop_btn_rect is not None:
                dx_b, dy_b, dw_b, dh_b = self.ui_drop_btn_rect
                if dx_b <= mx <= dx_b + dw_b and dy_b <= my <= dy_b + dh_b:
                    self.game.drop_item_from_slot("inv", self.game.selected_inv_idx, drop_all=(button == 1))
                    return True

            for a_idx, rx, ry, rw, rh in self.ui_armor_slot_rects:
                if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                    asl = self.game.player.armor_slots[a_idx]
                    if button == 1 and asl is not None:
                        self.game.drag_source = ("armor", a_idx)
                        self.game.dragged_item = str(asl["item"])
                        self.game.dragged_count = int(asl.get("count", 1))
                        self.game.dragged_from_chest = False
                        self.game.drag_offset = (mx - rx, my - ry)
                        self.game.drag_card_size = (rw, rh)
                    elif button == 3 and asl is not None:
                        if self.game.player.unequip_armor_slot(a_idx):
                            self.game.sound.play("build")
                    return True

            for inv_idx, rx, ry, rw, rh in self.ui_inv_card_rects:
                if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                    self.game.selected_inv_idx = inv_idx
                    if inv_idx < 9:
                        self.game.select_hotbar_slot(inv_idx)
                    sl = self.game.player.slots[inv_idx]
                    if button == 1 and sl is not None:
                        self.game.drag_source = ("inv", inv_idx)
                        self.game.dragged_item = str(sl["item"])
                        self.game.dragged_count = int(sl.get("count", 1))
                        self.game.dragged_from_chest = False
                        self.game.drag_offset = (mx - rx, my - ry)
                        self.game.drag_card_size = (rw, rh)
                    elif button == 3 and sl is not None:
                        if self.game.active_chest is not None:
                            self.game.transfer_chest_item(to_chest=True, inv_slot_idx=inv_idx)
                        else:
                            self.game.consume_specific_item(str(sl["item"]))
                    return True

            for chest_idx, rx, ry, rw, rh in self.ui_chest_card_rects:
                if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                    if self.game.active_chest is not None:
                        csl = self.game.active_chest.chest_slots[chest_idx]
                        if button == 1 and csl is not None:
                            self.game.drag_source = ("chest", chest_idx)
                            self.game.dragged_item = str(csl["item"])
                            self.game.dragged_count = int(csl.get("count", 1))
                            self.game.dragged_from_chest = True
                            self.game.drag_offset = (mx - rx, my - ry)
                            self.game.drag_card_size = (rw, rh)
                        elif button == 3 and csl is not None:
                            self.game.transfer_chest_item(to_chest=False, chest_slot_idx=chest_idx)
                    return True

        # 5. Обработка нажатий по экранным кнопкам телефона, виртуальному джойстику и зоне обзора 360°
        if self.game.mobile_controls_enabled and not (
            self.game.show_inventory
            or self.game.show_crafting
            or self.game.show_skills
            or self.game.show_settings
            or self.game.show_controls_help
        ):
            for act_id, bcx, bcy, br, _ in self.ui_mobile_buttons:
                if math.hypot(mx - bcx, my - bcy) <= br + 6.0:
                    self.game.touch_active_button = act_id
                    self._trigger_mobile_button_action(act_id, True)
                    return True

            for act_id, rx, ry, rw, rh, _ in self.ui_mobile_rect_buttons:
                if rx <= mx <= rx + rw and ry <= my <= ry + rh:
                    self.game.touch_active_button = act_id
                    self._trigger_mobile_button_action(act_id, True)
                    return True

            jcx, jcy, jr = self.ui_mobile_joy_circle
            if math.hypot(mx - jcx, my - jcy) <= jr * 1.35:
                self.game.touch_joy_active = True
                self.game.touch_joy_pointer_id = -1
                self._update_joystick_from_point(mx, my)
                return True

            # Касание в любой свободной области экрана — плавный свайп-поворот камеры 360°!
            self.game.touch_look_active = True
            self.game.touch_look_pointer_id = -1
            self.game.touch_look_last_pos = (float(mx), float(my))
            return True

        return False

    def handle_mouse_up(self, mx: int, my: int, button: int) -> None:
        """
        Завершает перетаскивание предмета мышью (Drop в любую ячейку Хотбара 1..9, Инвентаря 1..25 или Сундука 1..15).
        Проверяет как координаты курсора мыши (mx, my), так и центр перетаскиваемой карточки!
        """
        self.sync_viewport_size()
        if self.game.dragged_item is None or self.game.drag_source is None:
            self.game.dragged_item = None
            self.game.drag_source = None
            return

        src = self.game.drag_source
        off_x, off_y = self.game.drag_offset
        cw, ch = self.game.drag_card_size
        card_cx = mx - off_x + cw * 0.5
        card_cy = my - off_y + ch * 0.5

        self.game.dragged_item = None
        self.game.drag_source = None
        self.game.dragged_from_chest = False

        def hits_rect(rx: float, ry: float, rw: float, rh: float) -> bool:
            return (rx <= mx <= rx + rw and ry <= my <= ry + rh) or (rx <= card_cx <= rx + rw and ry <= card_cy <= ry + rh)

        # 1. Бросили предмет в ячейку Хотбара 1..9 (slots[0..8])
        for slot_i, rx, ry, rw, rh in self.ui_hotbar_rects:
            if hits_rect(rx, ry, rw, rh):
                self.game.move_or_swap_slots(src, ("hotbar", slot_i))
                self.game.select_hotbar_slot(slot_i)
                return

        # 2. Бросили предмет в любую из 25 ячеек Инвентаря (slots[0..24])
        if self.game.show_inventory:
            for inv_i, rx, ry, rw, rh in self.ui_inv_card_rects:
                if hits_rect(rx, ry, rw, rh):
                    self.game.move_or_swap_slots(src, ("inv", inv_i))
                    self.game.selected_inv_idx = inv_i
                    if inv_i < 9:
                        self.game.select_hotbar_slot(inv_i)
                    return

            # 3. Бросили предмет в конкретную ячейку Сундука (0..14)
            for chest_i, rx, ry, rw, rh in self.ui_chest_card_rects:
                if hits_rect(rx, ry, rw, rh):
                    self.game.move_or_swap_slots(src, ("chest", chest_i))
                    return

            # 4. Если бросили в общую область Сундука из Инвентаря/Хотбара — кладем в первую свободную ячейку сундука
            if self.game.active_chest is not None and self.ui_chest_box_rect is not None:
                cx, cy, box_w, box_h = self.ui_chest_box_rect
                if hits_rect(cx, cy, box_w, box_h) and src[0] in ("inv", "hotbar"):
                    self.game.transfer_chest_item(to_chest=True, inv_slot_idx=src[1])
                    return

            # 2b. Бросили предмет в одну из 4 вертикальных ячеек брони персонажа (0..3)
            for a_i, rx, ry, rw, rh in self.ui_armor_slot_rects:
                if hits_rect(rx, ry, rw, rh):
                    self.game.move_or_swap_slots(src, ("armor", a_i))
                    return

            # 2c. Бросили предмет на кнопку 'Выбросить предмет [Q]'
            if self.ui_drop_btn_rect is not None:
                dx_b, dy_b, dw_b, dh_b = self.ui_drop_btn_rect
                if hits_rect(dx_b, dy_b, dw_b, dh_b):
                    self.game.drop_item_from_slot(src[0], src[1], drop_all=True)
                    return

            # 5. Если бросили в общую область Инвентаря из Сундука — забираем в первую свободную ячейку инвентаря
            if self.game.active_chest is not None and self.ui_inv_box_rect is not None:
                ix, iy, box_w, box_h = self.ui_inv_box_rect
                if hits_rect(ix, iy, box_w, box_h) and src[0] == "chest":
                    self.game.transfer_chest_item(to_chest=False, chest_slot_idx=src[1])
                    return

            # 6. Если вытащили предмет мышью за пределы окна инвентаря — выбрасываем его на землю!
            w_cur, h_cur = self.game.width, self.game.height
            bw_m = 1190 if self.game.active_chest is not None else 860
            bh_m = 510
            bx_m = (w_cur - bw_m) * 0.5
            by_m = (h_cur - bh_m) * 0.5
            if not (bx_m <= mx <= bx_m + bw_m and by_m <= my <= by_m + bh_m):
                self.game.drop_item_from_slot(src[0], src[1], drop_all=True)
                return

    def _render_software_3d(self, surface: object) -> None:
        prof = GRAPHICS_PROFILES[self.game.graphics_profile_idx]
        sw_dist = prof["sw_render_dist"]
        sky_col, sun_dir, ambient = self.game.get_atmosphere_colors()
        sky_rgb = (int(sky_col[0] * 255), int(sky_col[1] * 255), int(sky_col[2] * 255))
        surface.fill(sky_rgb)

        w, h = self.game.width, self.game.height
        half_w, half_h = w * 0.5, h * 0.5
        fov_scale = half_h / math.tan(math.radians(35.0))

        cx, cy, cz = self.game.get_camera_pos()
        yaw_r = math.radians(self.game.player.yaw)
        pitch_r = math.radians(self.game.player.pitch)
        cos_y, sin_y = math.cos(yaw_r), math.sin(yaw_r)
        cos_p, sin_p = math.cos(pitch_r), math.sin(pitch_r)

        rot_mat = np.array(
            [
                [cos_y, 0.0, sin_y],
                [sin_y * sin_p, cos_p, -cos_y * sin_p],
                [-sin_y * cos_p, sin_p, cos_y * cos_p],
            ],
            dtype=np.float32,
        )

        v_list, c_list, n_list = [], [], []
        for ch in self.game.terrain.generated_chunks.values():
            if (ch.center_x - cx) ** 2 + (ch.center_z - cz) ** 2 <= (sw_dist + 40.0) ** 2:
                v_list.append(ch.sw_verts)
                c_list.append(ch.sw_cols)
                n_list.append(ch.sw_norms)

        if v_list:
            verts = np.concatenate(v_list, axis=0)
            cols = np.concatenate(c_list, axis=0)
            norms = np.concatenate(n_list, axis=0)
            rel = verts - np.array([cx, cy, cz], dtype=np.float32)
            cam_v = rel @ rot_mat.T
            depth = -cam_v[:, :, 2]
            valid = np.all(depth > 0.5, axis=1) & (depth.mean(axis=1) < sw_dist)
            cam_v = cam_v[valid]
            cols = cols[valid]
            norms = norms[valid]
            depth = depth[valid]

            if len(cam_v) > 0:
                mean_z = depth.mean(axis=1)
                order = np.argsort(mean_z)[::-1]
                cam_v = cam_v[order]
                cols = cols[order]
                norms = norms[order]
                mean_z = mean_z[order]

                sx = half_w + (cam_v[:, :, 0] / (-cam_v[:, :, 2])) * fov_scale
                sy = half_h - (cam_v[:, :, 1] / (-cam_v[:, :, 2])) * fov_scale
                pts = np.stack([sx, sy], axis=-1).astype(np.int32)

                sun_vec = np.array(sun_dir, dtype=np.float32)
                sun_vec /= np.linalg.norm(sun_vec) + 1e-6
                diff = np.clip(norms @ sun_vec, 0.0, 1.0)
                shade = np.clip(ambient * 0.55 + diff * ambient * 0.65, 0.15, 1.15)[:, None]
                fog_f = np.clip(mean_z / sw_dist, 0.0, 1.0)[:, None] ** 1.6
                sky_arr = np.array(sky_col, dtype=np.float32)[None, :]
                lit_rgb = np.clip((cols * shade * (1.0 - fog_f) + sky_arr * fog_f) * 255.0, 0, 255).astype(np.uint8)

                draw_poly = pygame.draw.polygon
                for i in range(len(pts)):
                    p = pts[i]
                    c = (int(lit_rgb[i, 0]), int(lit_rgb[i, 1]), int(lit_rgb[i, 2]))
                    draw_poly(surface, c, ((int(p[0, 0]), int(p[0, 1])), (int(p[1, 0]), int(p[1, 1])), (int(p[2, 0]), int(p[2, 1]))))

        # Отрисовка 3D-деревьев, камней, руд, построек и животных в режиме Android SDL2 (от дальних к ближним)
        billboards: List[Tuple[float, str, object]] = []
        for res in self.game.get_nearby_resources(cx, cz, cell_radius=3):
            if not res.alive or res.kind == "grass_tuft":
                continue
            d2 = (res.x - cx) ** 2 + (res.z - cz) ** 2
            if d2 <= sw_dist * sw_dist:
                billboards.append((d2, "res", res))
        for st in self.game.structures:
            d2 = (st.x - cx) ** 2 + (st.z - cz) ** 2
            if d2 <= sw_dist * sw_dist:
                billboards.append((d2, "st", st))
        for anim in self.game.animals:
            if not anim.alive:
                continue
            d2 = (anim.x - cx) ** 2 + (anim.z - cz) ** 2
            if d2 <= sw_dist * sw_dist:
                billboards.append((d2, "anim", anim))

        billboards.sort(key=lambda item: item[0], reverse=True)
        for _, b_kind, obj in billboards:
            ox, oy, oz = obj.x, obj.y, obj.z
            rel_p = np.array([ox - cx, oy - cy, oz - cz], dtype=np.float32) @ rot_mat.T
            rz = -float(rel_p[2])
            if rz <= 0.6:
                continue
            proj_x = int(half_w + (float(rel_p[0]) / rz) * fov_scale)
            proj_y = int(half_h - (float(rel_p[1]) / rz) * fov_scale)
            scale_px = max(2, int((fov_scale / rz) * getattr(obj, "scale", 1.0)))
            if proj_x < -200 or proj_x > w + 200 or proj_y < -200 or proj_y > h + 200:
                continue
            if b_kind == "res":
                rk = obj.kind
                if "pine" in rk or "oak" in rk or "birch" in rk or "tree" in rk:
                    tw_px = max(3, int(scale_px * 0.42))
                    th_px = max(8, int(scale_px * 3.8))
                    trunk_c = (215, 212, 202) if rk == "birch" else (105, 68, 38)
                    pygame.draw.rect(surface, trunk_c, (proj_x - tw_px // 2, proj_y - th_px, tw_px, th_px))
                    cr_r = max(6, int(scale_px * 1.65))
                    leaf_c = (215, 232, 248) if rk == "snow_pine" else ((218, 128, 36) if rk == "autumn_oak" else (42, 128, 48))
                    pygame.draw.circle(surface, leaf_c, (proj_x, proj_y - th_px - cr_r // 3), cr_r)
                else:
                    rr = max(4, int(scale_px * 0.85))
                    rc = (95, 215, 245) if "mythril" in rk else ((240, 195, 55) if "gold" in rk else (128, 132, 138))
                    pygame.draw.circle(surface, rc, (proj_x, proj_y - rr // 2), rr)
            elif b_kind == "st":
                sw_px = max(6, int((fov_scale / rz) * obj.size[0] * 0.5))
                sh_px = max(6, int((fov_scale / rz) * obj.size[1]))
                pygame.draw.rect(surface, (152, 104, 58), (proj_x - sw_px, proj_y - sh_px, sw_px * 2, sh_px))
            elif b_kind == "anim":
                ar = max(4, int(scale_px * 0.75))
                ac = (int(obj.body_color[0] * 255), int(obj.body_color[1] * 255), int(obj.body_color[2] * 255))
                pygame.draw.ellipse(surface, ac, (proj_x - ar, proj_y - int(ar * 1.3), ar * 2, int(ar * 1.3)))

    def _render_software_hud(self, surf: object) -> None:
        """Отрисовывает полный интерфейс, 6 полосок состояния, инвентарь и мобильный джойстик/кнопки поверх Pygame Surface."""
        DualRenderer3D._ACTIVE_SURF = surf
        try:
            self._render_opengl_hud()
        finally:
            DualRenderer3D._ACTIVE_SURF = None


# ==============================================================================
# 9. АВТОМАТИЧЕСКОЕ ТЕСТИРОВАНИЕ ВСЕХ НОВЫХ СИСТЕМ И ЗАПУСК
# ==============================================================================

def run_Automated_selftest() -> None:
    """
    Полная автоматическая проверка всех систем:
      1) 25 свободных ячеек инвентаря (без фиксированных предметов): на старте только Камень в 1-й ячейке,
         остальные 24 ячейки пустые; прямая связь Хотбара (1..9) с первыми 9 ячейками Инвентаря (slots[0..8]);
         переключение слотов хотбара колесиком мыши.
      2) Двусторонний перенос предметов Drag & Drop: Сундук <-> Инвентарь <-> Хотбар.
      3) Углы подъема: Горные козлы до 85°, остальные животные до 70°, Персонаж до 75°.
      4) Степи, Поля, Скалистые ущелья, Горы, Леса, больше кустов и травы + настройки FPS, прорисовки и травы.
      5) Независимое движение облаков в мировых координатах и средний сбалансированный спавн хищников.
    """
    print("=== Запуск самопроверки: 25 ячеек инвентаря, Сундук<->Инвентарь<->Хотбар, Углы 85°/70°/75°, Степи/Поля/Ущелья ===")
    game = SurvivalRPGGame(width=1280, height=720, headless=True)

    # 1. Проверка 25 свободных ячеек инвентаря и старта ТОЛЬКО с Камнем в 1-м слоте!
    assert len(game.player.slots) == 25, "В инвентаре должно быть ровно 25 ячеек!"
    assert game.player.slots[0] is not None and game.player.slots[0]["item"] == "rock" and game.player.slots[0]["count"] == 1, "В 1-й ячейке на старте должен быть только Камень!"
    assert get_slot_durability_ratio(game.player.slots[0]) == 1.0, "Камень выжившего на старте имеет 100% прочности!"
    assert all(s is None for s in game.player.slots[1:]), "Остальные 24 ячейки инвентаря на старте должны быть пустыми!"
    assert game.player.inventory.to_plain_dict() == {"rock": 1}, "Изначально в инвентаре не должно быть ничего, кроме Камня!"
    print("[OK] Инвентарь (25 свободных ячеек): на старте только Камень в 1-й ячейке, остальные 24 ячейки пусты!")

    # Проверка прямой связи Хотбара (1..9) и первых 9 ячеек Инвентаря (slots[0..8]) + колесика мыши
    game.player.inventory["wood"] += 4
    game.player.inventory["stone"] += 3
    game.player.inventory["berries"] += 5
    # Теперь заняты первые 4 ячейки хотбара (0..3) и первые 4 ячейки инвентаря (0..3)!
    filled_hotbar = [i for i in range(9) if game.player.hotbar[i] is not None]
    filled_inv_first9 = [i for i in range(9) if game.player.slots[i] is not None]
    assert filled_hotbar == [0, 1, 2, 3] and filled_inv_first9 == [0, 1, 2, 3], "Хотбар и первые 9 ячеек инвентаря напрямую связаны!"
    game.scroll_hotbar_wheel(1)
    assert game.player.active_hotbar_slot == 1, "Переключение хотбара колесиком мыши вперед!"
    game.scroll_hotbar_wheel(-1)
    assert game.player.active_hotbar_slot == 0, "Переключение хотбара колесиком мыши назад!"
    print("[OK] Прямая синхронизация Хотбара (1..9) и Инвентаря (ячейки 1..9) + прокрутка колесиком мыши работают!")

    # 2. Проверка переноса предметов: Инвентарь <-> Хотбар и Сундук <-> Инвентарь
    chest = next(st for st in game.structures if st.piece_id == "chest")
    game.active_chest = chest
    # Переносим предмет из 1-й ячейки сундука ('stone') в 12-ю ячейку инвентаря (индекс 11)
    assert chest.chest_slots[0] is not None, "В стартовом сундуке есть предметы"
    chest_item_name = chest.chest_slots[0]["item"]
    assert game.move_or_swap_slots(("chest", 0), ("inv", 11)), "Перенос из Сундука в 12-ю ячейку Инвентаря"
    assert game.player.slots[11] is not None and game.player.slots[11]["item"] == chest_item_name
    # Переносим из 12-й ячейки Инвентаря в 5-й слот Хотбара (индекс 4)
    assert game.move_or_swap_slots(("inv", 11), ("hotbar", 4)), "Перенос из Инвентаря в Хотбар"
    assert game.player.hotbar[4] == chest_item_name and game.player.slots[4]["item"] == chest_item_name and game.player.slots[11] is None
    # Переносим обратно из Хотбара в Сундук
    assert game.move_or_swap_slots(("hotbar", 4), ("chest", 0)), "Перенос обратно в Сундук"
    assert chest.chest_slots[0] is not None and chest.chest_slots[0]["item"] == chest_item_name and game.player.hotbar[4] is None
    game.active_chest = None
    print("[OK] Перенос предметов Drag & Drop (Сундук <-> Инвентарь <-> Хотбар) работает точно!")

    # 3. Прогрессия Стола мастерской и проверка коллизии стены над открытой дверью
    assert game.craft_workbench_in_inventory(), "Создание Стола мастерской в инвентаре за 2 дерева"
    assert game.place_workbench_from_hand(), "Установка Стола мастерской в мир"
    assert game.has_placed_workbench(), "Стол мастерской установлен!"
    door_1f = BuiltStructure(
        id=game._alloc_id(), piece_id="doorway", name="Входная стена с дверью",
        x=0.0, y=1.72, z=-4.0, rotation=0.0, size=(4.0, 3.0, 0.42), is_solid=True, is_roof=False, door_open=True,
    )
    wall_2f = BuiltStructure(
        id=game._alloc_id(), piece_id="wall", name="Бревенчатая стена 2-го этажа",
        x=0.0, y=4.72, z=-4.0, rotation=0.0, size=(4.0, 3.0, 0.42), is_solid=True, is_roof=False,
    )
    game.structures.extend([door_1f, wall_2f])
    game.player.y = 0.0
    assert not game._collides_with_world(0.0, -4.0, 0.55), "Стена 2-го этажа над открытой дверью не блокирует проход!"

    # 4. Проверка новых углов подъема: Козлы до 85°, Животные до 70°, Персонаж до 75°!
    assert game.can_animal_climb_angle(85.0, "mountain_goat") and not game.can_animal_climb_angle(85.5, "mountain_goat"), "Козлы: до 85°!"
    assert game.can_animal_climb_angle(70.0, "cow") and not game.can_animal_climb_angle(70.5, "cow"), "Животные: до 70°!"
    assert game.can_player_climb_angle(75.0) and not game.can_player_climb_angle(75.5), "Персонаж: до 75°!"
    print("[OK] Углы подъема проверены: Горные козлы <= 85°, Животные <= 70°, Персонаж <= 75°!")

    # 5. Проверка биомов: Степи, Поля, Скалистые ущелья, Леса, Горы + кусты и трава
    biomes = {
        game.terrain.get_biome(float(x), float(z))
        for x in np.linspace(-600, 600, 55)
        for z in np.linspace(-600, 600, 55)
    }
    print(f"[OK] Биомы мира: {sorted(biomes)}")
    for req_b in ("Бескрайняя степь", "Просторное поле и луга", "Скалистое ущелье", "Густой древний лес", "Вершина узкой горы (Обитель козлов)"):
        assert req_b in biomes, f"В мире должен быть биом '{req_b}'!"

    grass_cnt = sum(1 for r in game.resources if r.kind == "grass_tuft")
    bush_cnt = sum(1 for r in game.resources if r.kind in ("berry_bush", "wild_bush"))
    assert grass_cnt >= 400 and bush_cnt >= 120, f"Должно быть много травы ({grass_cnt}) и кустов ({bush_cnt})!"
    print(f"[OK] Флора мира: пучков 3D-травы = {grass_cnt}, кустов = {bush_cnt} (с настройкой плотности травы 0%..200%)!")

    # 6. Проверка независимого движения облаков и среднего спавна хищников
    cloud0_before = game.clouds[0][0]
    game.player.x += 30.0
    assert game.clouds[0][0] == cloud0_before, "Координаты облаков в мире НЕ зависят от ходьбы игрока!"
    game.update(0.5, 0.0, 0.0, False, False)
    assert game.clouds[0][0] != cloud0_before, "Облака самостоятельно плывут по небу со временем!"
    print("[OK] Облака двигаются по ветру в мировых координатах полностью независимо от игрока!")

    # 7. Проверка: переключение слотов НЕ спамит в чат уведомлений, а в руке отображается именно выбранный предмет (руда, а не копье!)
    game.notifications.clear()
    game.put_in_hotbar("wooden_spear", slot_idx=1)
    game.player.inventory["gold"] += 8
    gold_slot = next(i for i in range(9) if game.player.hotbar[i] == "gold")
    game.select_hotbar_slot(1)
    assert game.player.equipped_weapon == "wooden_spear", "В слоте 2 в руках копье"
    game.select_hotbar_slot(gold_slot)
    assert game.player.equipped_weapon == "gold", "При переключении на золотую руду в руках должна быть именно золотая руда, а не копье!"
    assert len(game.notifications) == 0, "Переключение слотов хотбара НЕ должно спамить уведомлениями в чат!"
    print("[OK] Переключение с копья на золотую руду меняет предмет в 3D-руке на золотую руду и не спамит в чат!")

    # 8. Проверка анимации животных: при ходьбе конечности двигаются (leg_swing != 0), а при остановке — строго прямые (leg_swing == 0.0)
    sheep = next(a for a in game.animals if not a.aquatic)
    sheep.state = "wander"
    sheep.state_timer = 2.0
    sheep.anim_phase = 0.2
    game._update_animals(0.15)
    assert abs(sheep.leg_swing) > 0.5, f"Идущее животное должно двигать конечностями, получено: {sheep.leg_swing}"
    sheep.state = "graze"
    sheep.state_timer = 3.0
    game._update_animals(0.15)
    assert sheep.leg_swing == 0.0, f"Остановившееся животное должно стоять с прямыми конечностями (leg_swing=0.0), получено: {sheep.leg_swing}"
    print("[OK] Анимация животных: при ходьбе обычная анимация шага, при остановке конечности строго прямые (0.0°)!")

    # 9. Проверка колесика мыши в режиме стройки: прокручиваются элементы стройки, а не хотбар!
    game.build_mode = True
    hb_before = game.player.active_hotbar_slot
    b_before = game.selected_build_idx
    game.handle_mouse_wheel(1)
    assert game.selected_build_idx == (b_before + 1) % len(BUILD_PIECES), "Колесико в режиме стройки должно менять элемент стройки!"
    assert game.player.active_hotbar_slot == hb_before, "В режиме стройки колесико НЕ должно переключать слот хотбара!"
    game.build_mode = False
    print("[OK] Колесико мыши в режиме стройки прокручивает строительные части, а не хотбар!")

    # 10. Проверка коллизий животных с постройками: сквозь стену и закрытую дверь пройти нельзя, а через открытую дверь — можно!
    door_1f.door_open = False
    assert not game._can_animal_move_segment(0.0, -2.5, 0.0, -5.5, 0.85, 0.0), "Животное НЕ должно проходить сквозь ЗАКРЫТУЮ дверь!"
    door_1f.door_open = True
    assert game._can_animal_move_segment(0.0, -2.5, 0.0, -5.5, 0.65, 0.0), "Животное ДОЛЖНО проходить сквозь ОТКРЫТУЮ дверь!"
    assert not game._can_animal_move_segment(-1.5, -2.5, -1.5, -5.5, 0.85, 0.0), "Животное НЕ должно проходить сквозь бревенчатый простенок рядом с дверью!"
    print("[OK] Коллизии животных с домом: животные не проходят сквозь стены и закрытые двери, но проходят через открытую дверь!")

    # 11. Проверка 4 отдельных вертикальных ячеек экипировки персонажа (Голова, Броня, Штаны, Носки)
    assert len(game.player.armor_slots) == 4 and all(s is None for s in game.player.armor_slots), "4 вертикальные ячейки брони!"
    game.player.inventory["fur_helmet"] += 1
    game.player.inventory["fur_armor"] += 1
    game.player.inventory["fur_pants"] += 1
    game.player.inventory["wool_socks"] += 1
    assert game.consume_specific_item("fur_helmet") and game.player.armor_slots[0]["item"] == "fur_helmet"
    assert game.consume_specific_item("fur_armor") and game.player.armor_slots[1]["item"] == "fur_armor"
    assert game.consume_specific_item("fur_pants") and game.player.armor_slots[2]["item"] == "fur_pants"
    assert game.consume_specific_item("wool_socks") and game.player.armor_slots[3]["item"] == "wool_socks"
    assert game.player.armor_reduction >= 0.55, f"Суммарная защита комплекта брони должна быть >= 55%, получено: {game.player.armor_reduction}"
    print("[OK] Персонаж в инвентаре и 4 отдельные вертикальные ячейки экипировки (Голова, Броня, Штаны, Носки) работают!")

    # 12. Проверка сброса предметов из инвентаря на землю [Q] и обратного подбора [F]
    game.player.inventory["copper"] += 5
    cop_slot = next(i for i in range(MAX_INVENTORY_SLOTS) if game.player.slots[i] is not None and game.player.slots[i]["item"] == "copper")
    dropped_before = len(game.dropped_items)
    assert game.drop_item_from_slot("inv", cop_slot, drop_all=True), "Сброс предмета из инвентаря на землю!"
    assert len(game.dropped_items) == dropped_before + 1 and game.player.inventory.get("copper", 0) == 0
    game.interact_world()
    assert len(game.dropped_items) == dropped_before and game.player.inventory.get("copper", 0) == 5, "Подбор сброшенного предмета с земли!"
    print("[OK] Сброс предметов из инвентаря на землю [Q] и подбор обратно [F] работают идеально!")

    # 13. Проверка плавного перехода дня и ночи (отсутствие резких скачков неба и освещения)
    max_sky_step = 0.0
    game.time_of_day = 0.0
    prev_sky, _, prev_amb = game.get_atmosphere_colors()
    for step_m in range(1, 240):
        game.time_of_day = (step_m * 0.1) % 24.0
        cur_sky, _, cur_amb = game.get_atmosphere_colors()
        diff = max(abs(cur_sky[0] - prev_sky[0]), abs(cur_sky[1] - prev_sky[1]), abs(cur_sky[2] - prev_sky[2]), abs(cur_amb - prev_amb))
        max_sky_step = max(max_sky_step, diff)
        prev_sky, prev_amb = cur_sky, cur_amb
    assert max_sky_step < 0.06, f"Переход дня и ночи должен быть плавным (шаг < 0.06), получено: {max_sky_step:.4f}"
    print(f"[OK] Плавный непрерывный переход дня и ночи проверен (макс. градиент за 6 мин = {max_sky_step:.4f})!")

    # 14. Проверка правил спавна: хищники >= 10 м от персонажа, никто не спавнится внутри построек или в 2 м от построек!
    assert not game._can_spawn_predator_at(game.player.x + 2.0, game.player.z + 2.0), "Хищник НЕ должен спавниться в 2 м от игрока (< 10 м)!"
    assert not game._can_spawn_predator_at(game.player.x + 9.0, game.player.z), "Хищник НЕ должен спавниться ближе 10 м от игрока!"
    st_sample = game.structures[0]
    assert not game._can_spawn_animal_at(st_sample.x, st_sample.z, hostile=False), "Никто НЕ должен спавниться внутри постройки!"
    assert not game._can_spawn_animal_at(st_sample.x + 1.5, st_sample.z, hostile=False), "Никто НЕ должен спавниться в 2 метрах от постройки!"
    print("[OK] Спавн хищников (>= 10 м от персонажа) и запрет спавна в доме или ближе 2 м от построек работают строго!")

    # 15. Проверка новых объектов постройки (каменная печь с трубой, забор, уличный факел на столбе, стол со скамьями)
    piece_ids = {bp.id for bp in BUILD_PIECES}
    for req_p in ("chimney_hearth", "fence", "torch_stand", "table_chair", "roof"):
        assert req_p in piece_ids, f"Объект постройки '{req_p}' должен быть доступен!"
    print(f"[OK] Новые объекты строительства ({len(BUILD_PIECES)} видов) и исправленная двускатная крыша проверены!")

    # 16. Проверка урона от падения с высоты (Fall Damage)
    hp_before_fall = game.player.hp
    dmg_taken = game.apply_fall_damage(8.5, impact_speed=15.0)
    assert dmg_taken > 10.0 and game.player.hp < hp_before_fall, "Прыжок/падение с большой высоты (8.5 м) должен наносить урон!"
    game.player.hp = game.player.max_hp
    print(f"[OK] Урон от падения с высоты (8.5 м -> -{dmg_taken} HP) работает корректно!")

    # 17. Проверка отсутствия застревания животных в деревьях и камнях при спавне
    stuck_in_trees = 0
    for anim in game.animals:
        if not anim.aquatic and game._is_near_any_tree_or_rock(anim.x, anim.z, min_clear_dist=0.5):
            stuck_in_trees += 1
    assert stuck_in_trees == 0, f"Ни одно животное не должно спавниться внутри дерева или валуна! Найдено: {stuck_in_trees}"
    print(f"[OK] Проверено {len(game.animals)} животных: ни одно не заспавнилось в деревьях или камнях!")

    # 18. Проверка точной привязки травы и сундуков к полигональной сетке чанков (0.000 м отклонения от треугольников!)
    for st in game.structures:
        if st.piece_id == "chest":
            th = game.terrain.get_height(st.x, st.z)
            sl_st = game.terrain.get_slope_degrees(st.x, st.z)
            assert abs((st.y - 0.32) - th) < 0.05 and sl_st < 20.0, f"Сундук '{st.name}' должен стоять ровно на земле (уклон={sl_st:.1f}°)!"
    print("[OK] Точная привязка травы и сундуков к треугольникам рельефа проверена (без зависания в воздухе)!")

    # 19. Проверка потери всех предметов из хотбара и инвентаря при смерти и 5-минутного (300 сек) таймера исчезновения
    game.dropped_items.clear()
    game.player.x, game.player.z = 22.0, -18.0
    game.player.y = game.terrain.get_height(22.0, -18.0)
    game.player.inventory["gold"] = 7
    game.player.inventory["wood"] = 12
    game.put_in_hotbar("wooden_spear", slot_idx=2)
    # Имитируем гибель персонажа на точке (22.0, -18.0)
    game._respawn_player()
    assert all(s is None for s in game.player.slots), "После смерти все ячейки хотбара и инвентаря должны стать пустыми!"
    assert all(a is None for a in game.player.armor_slots), "После смерти все ячейки брони также сбрасываются на месте смерти!"
    death_drops = [d for d in game.dropped_items if d.is_death_drop]
    assert len(death_drops) >= 3, "Все предметы из хотбара и инвентаря должны лежать на месте смерти!"
    assert all(abs(d.despawn_timer - 300.0) < 0.1 for d in death_drops), "Таймер исчезновения предметов должен быть ровно 300 сек (5 минут)!"
    # Проверяем, что спустя 4 минуты (240 сек) предметы все еще лежат на месте смерти
    for _ in range(240):
        game.update(1.0, 0.0, 0.0, False, False)
    assert len([d for d in game.dropped_items if d.is_death_drop]) == len(death_drops), "Через 4 минуты предметы еще должны лежать на месте смерти!"
    # Проверяем, что если игрок пришел на место смерти до истечения 5 минут и нажал [F], он подбирает свои вещи обратно
    game.player.x, game.player.z = 22.0, -18.0
    game.player.y = game.terrain.get_height(22.0, -18.0)
    game.interact_world()
    assert game.player.inventory.get("gold", 0) == 7 and game.player.inventory.get("wood", 0) == 12, "Игрок должен подобрать свои вещи на месте смерти!"
    # А теперь проверяем полное исчезновение предметов ровно через 5 минут (300 секунд), если их не подобрать:
    game._respawn_player()
    assert len([d for d in game.dropped_items if d.is_death_drop]) >= 3
    for _ in range(302):
        game.update(1.0, 0.0, 0.0, False, False)
    assert len([d for d in game.dropped_items if d.is_death_drop]) == 0, "Ровно через 5 минут (300 сек) неподобранные предметы должны исчезнуть!"
    print("[OK] Потеря всех предметов при смерти, возврат на место гибели и исчезновение ровно через 5 минут (300 сек) проверены!")

    # 20. Проверка стартовых настроек при первом заходе в игру (в точности как на скриншоте!), 4 разных уровней 3D-моделей, чанков, разрешения и сглаживания
    fresh_game = SurvivalRPGGame(width=1280, height=720, headless=True)
    assert fresh_game.graphics_profile_idx == 3, "Профиль при старте: УЛЬТРА HD (3)"
    assert fresh_game.detail_quality_idx == 3, "Детализация 3D-моделей при старте: Ультра HD (3)"
    assert fresh_game.shadows_enabled is False, "Тени и блики при старте: Выкл (False)"
    assert int(fresh_game.get_effective_render_dist()) == 60, "Дальность прорисовки при старте: 60 метров"
    assert fresh_game.grass_density_idx == 3, "Количество 3D-травы при старте: 150% (Высокая, индекс 3)"
    assert FPS_CAPS[fresh_game.fps_cap_idx] == 0, "Лимит FPS при старте: Без лимита (0)"
    assert fresh_game.clouds_enabled is True, "Объемные 3D-облака при старте: Включены (True)"

    # Проверка новых параметров: генерация чанков, сглаживание, выбор разрешения и 4 разных уровня детализации
    fresh_game.adjust_chunk_gen_radius(1)
    assert fresh_game.get_chunk_gen_radius() == 3, "Параметр генерации чанков должен переключаться (3 чанка = 7x7)!"
    fresh_game.adjust_antialiasing(-1)
    assert fresh_game.antialias_idx == 1, "Параметр сглаживания должен переключаться!"
    for d_lvl in (0, 1, 2, 3):
        fresh_game.detail_quality_idx = d_lvl
        assert DETAIL_QUALITY_PRESETS[d_lvl][1] == d_lvl
    print("[OK] Стартовые настройки по скриншоту, 4 разных уровня 3D-моделей, генерация чанков, разрешение экрана и сглаживание проверены!")

    # 21. Проверка прочности всех инструментов/оружия и одежды, полоски состояния брони, круглых частиц снега и частиц жаровни/костра
    for w_id in WEAPONS_DB:
        if w_id != "workbench_item":
            assert w_id in ITEM_MAX_DURABILITY, f"Инструмент/оружие '{w_id}' должен иметь прочность!"
    for a_id in ITEM_TO_ARMOR_SLOT_IDX:
        assert a_id in ITEM_MAX_DURABILITY, f"Одежда/броня '{a_id}' должна иметь прочность!"

    fresh_game.player.inventory["fur_helmet"] = 1
    fresh_game.player.equip_armor_item("fur_helmet")
    assert fresh_game.player.armor_status_value > 15.0, "Полоска состояния брони в HUD должна отражать надетую броню!"
    fresh_game.player.damage_equipped_armor(20.0)
    assert get_slot_durability_ratio(fresh_game.player.armor_slots[0]) < 1.0, "Прочность надетой брони должна уменьшаться от ударов!"
    fresh_game.player.damage_active_tool(10.0)
    assert get_slot_durability_ratio(fresh_game.player.slots[0]) < 1.0, "Прочность инструмента в хотбаре должна уменьшаться при использовании!"
    print("[OK] Прочность всех инструментов и одежды (полоска снизу ячейки), столбец состояния брони, 100+ FPS лук, предпросмотр лестницы и круглый снег проверены!")

    # 22. Проверка сенсорного управления для телефона (виртуальный джойстик, сенсорный обзор 360° и экранные кнопки действий)
    assert fresh_game.mobile_controls_enabled is True, "Управление для телефона должно быть включено по умолчанию!"
    test_renderer = DualRenderer3D(fresh_game, use_opengl=False)
    test_renderer.ui_mobile_joy_circle = (112.0, 444.0, 64.0)
    # Имитируем нажатие и сдвиг виртуального джойстика вперед-вправо
    test_renderer._update_joystick_from_point(112.0 + 32.0, 444.0 - 48.0)
    assert fresh_game.touch_joy_dx > 0.4 and fresh_game.touch_joy_dy < -0.6, "Виртуальный джойстик должен плавно менять вектор движения!"
    # Имитируем сенсорный поворот камеры пальцем
    fresh_game.touch_look_active = True
    fresh_game.touch_look_pointer_id = 7
    yaw_before = fresh_game.player.yaw
    test_renderer.handle_touch_or_Look_motion(500.0, 300.0, 45.0, -20.0, pointer_id=7)
    assert fresh_game.player.yaw != yaw_before, "Свайп по экрану должен плавно поворачивать 3D-камеру!"
    test_renderer.handle_touch_or_pointer_up(pointer_id=7)
    # Имитируем нажатие сенсорных кнопок (Прыжок, Бег, Рюкзак)
    test_renderer._trigger_mobile_button_action("sprint", True)
    assert fresh_game.touch_sprint_locked is True, "Кнопка [БЕГ] на телефоне должна фиксировать спринт!"
    test_renderer._trigger_mobile_button_action("inv_toggle", True)
    assert fresh_game.show_inventory is True, "Кнопка [РЮКЗАК] на телефоне должна открывать инвентарь!"
    test_renderer._trigger_mobile_button_action("inv_toggle", True)
    assert fresh_game.show_inventory is False
    # Проверка кнопки "Задания" (по умолчанию полный блок скрыт, при нажатии открывается и закрывается)
    assert fresh_game.show_quests is False, "По умолчанию полный блок заданий скрыт за кнопкой 'Задания'!"
    test_renderer.ui_quests_btn_rect = (1124.0, 10.0, 142.0, 44.0)
    assert test_renderer.handle_mouse_down(1150, 25, 1) is True
    assert fresh_game.show_quests is True, "Нажатие на кнопку 'Задания' должно открывать полный блок целей выживания и РПГ!"
    assert test_renderer.handle_mouse_down(1150, 25, 1) is True
    assert fresh_game.show_quests is False, "Повторное нажатие на кнопку 'Задания' должно сворачивать блок целей!"
    # Проверка мобильных кнопок СОХРАНИТЬ и ЗАГРУЗИТЬ
    fresh_game.player.x = 33.5
    test_renderer._trigger_mobile_button_action("save_game", True)
    fresh_game.player.x = 10.0
    test_renderer._trigger_mobile_button_action("load_game", True)
    assert abs(fresh_game.player.x - 33.5) < 1e-3, "Мобильные кнопки СОХРАНИТЬ и ЗАГРУЗИТЬ должны сохранять и загружать мир!"
    print("[OK] Кнопка 'Задания' (раскрытие по клику) и мобильные кнопки 'СОХРАНИТЬ' / 'ЗАГРУЗИТЬ' для телефона проверены!")

    cap0 = game.get_adaptive_predator_cap(0)
    cap1 = game.get_adaptive_predator_cap(1)
    cap5 = game.get_adaptive_predator_cap(5)
    cap10 = game.get_adaptive_predator_cap(10)
    cap99 = game.get_adaptive_predator_cap(99)
    assert cap0 < cap5 < cap10 == cap99, "Учащенный адаптивный спавн хищников с потолком на критическом уровне!"
    alive_preds = [a for a in game.animals if a.alive and a.hostile]
    print(f"[OK] Учащенный спавн хищников: Ур.0={cap0}, Ур.1={cap1}, Ур.5={cap5}, Потолок(Ур.10+)={cap10}, сейчас в мире: {len(alive_preds)}!")
    print("=== ВСЕ НОВЫЕ МЕХАНИКИ ПРОШЛИ ПРОВЕРКУ БЕЗ ОШИБОК! ===")


def main() -> None:
    if "--selftest" in sys.argv:
        run_Automated_selftest()
        return

    if not HAS_PYGAME:
        print("Для запуска графического 3D-окна установите Pygame и PyOpenGL:")
        print("  pip install pygame PyOpenGL numpy")
        run_Automated_selftest()
        return

    # Включаем поддержку реальных пикселей монитора (DPI Awareness) на Windows,
    # чтобы при развороте окна во весь экран или в Fullscreen мышь и glViewport совпадали 1:1!
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    pygame.init()
    width, height = 1280, 720
    if IS_ANDROID:
        try:
            info = pygame.display.Info()
            if info.current_w > 0 and info.current_h > 0:
                width, height = max(info.current_w, info.current_h), min(info.current_w, info.current_h)
        except Exception:
            pass
    flags = DOUBLEBUF | (pygame.FULLSCREEN if IS_ANDROID else RESIZABLE)
    use_gl = HAS_OPENGL and not IS_ANDROID
    if use_gl:
        flags |= OPENGL
        try:
            # Запрашиваем 4x MSAA аппаратное сглаживание полигонов и 24-битный буфер глубины
            pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 1)
            pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 4)
            pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
        except Exception:
            pass

    try:
        screen = pygame.display.set_mode((width, height), flags)
    except Exception:
        try:
            pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLEBUFFERS, 0)
            pygame.display.gl_set_attribute(pygame.GL_MULTISAMPLESAMPLES, 0)
        except Exception:
            pass
        screen = pygame.display.set_mode((width, height), flags)
    pygame.display.set_caption(
        "WILDERNESS: Эпоха Выживания — 3D Survival RPG (Стол мастерской, Drag & Drop мышью, Снежный барс)"
    )

    game = SurvivalRPGGame(width=width, height=height, headless=False)
    renderer = DualRenderer3D(game, use_opengl=use_gl)

    pygame.event.set_grab(False)
    pygame.mouse.set_visible(True)
    mouse_locked = False

    clock = pygame.time.Clock()
    running = True

    while running:
        t_frame_start = time.perf_counter()
        target_cap = FPS_CAPS[game.fps_cap_idx]
        dt = clock.tick(target_cap) / 1000.0 if target_cap > 0 else clock.tick() / 1000.0

        # В режиме управления для телефона или когда открыто любое окно — курсор/касание всегда свободны для нажатия кнопок!
        ui_modal_open = (
            game.show_inventory
            or game.show_crafting
            or game.show_skills
            or game.show_controls_help
            or game.show_settings
        )
        if ui_modal_open or game.mobile_controls_enabled:
            pygame.event.set_grab(False)
            pygame.mouse.set_visible(True)
        elif mouse_locked:
            pygame.event.set_grab(True)
            pygame.mouse.set_visible(False)

        for event in pygame.event.get():
            if event.type == QUIT:
                running = False
            elif hasattr(pygame, "VIDEORESIZE") and event.type == pygame.VIDEORESIZE:
                game.width, game.height = max(320, event.w), max(240, event.h)
                if use_gl:
                    glViewport(0, 0, game.width, game.height)
            elif hasattr(pygame, "MOUSEWHEEL") and event.type == pygame.MOUSEWHEEL:
                if event.y > 0:
                    game.handle_mouse_wheel(-1)
                elif event.y < 0:
                    game.handle_mouse_wheel(1)
            elif event.type == KEYDOWN:
                if event.key == pygame.K_ESCAPE or (hasattr(pygame, "K_AC_BACK") and event.key == pygame.K_AC_BACK):
                    if (
                        game.show_inventory
                        or game.show_crafting
                        or game.show_skills
                        or game.show_controls_help
                        or game.show_settings
                        or game.build_mode
                    ):
                        game.show_inventory = False
                        game.active_chest = None
                        game.show_crafting = False
                        game.show_skills = False
                        game.show_controls_help = False
                        game.show_settings = False
                        game.build_mode = False
                        game.dragged_item = None
                        game.drag_source = None
                    else:
                        mouse_locked = not mouse_locked
                        pygame.event.set_grab(mouse_locked)
                        pygame.mouse.set_visible(not mouse_locked)
                elif event.key == pygame.K_i or event.key == pygame.K_TAB:
                    game.show_inventory = not game.show_inventory
                    if not game.show_inventory:
                        game.active_chest = None
                        game.dragged_item = None
                    else:
                        game.show_crafting = False
                        game.show_skills = False
                elif event.key == pygame.K_m and game.show_inventory:
                    game.craft_workbench_in_inventory()
                elif event.key == pygame.K_c:
                    if game.show_crafting:
                        game.show_crafting = False
                    else:
                        # Крафт открывается только при нажатии [F] или ЛКМ на поставленный Стол мастерской!
                        if game.has_placed_workbench():
                            wb_near = any(
                                st.piece_id == "workbench" and math.hypot(st.x - game.player.x, st.z - game.player.z) <= 5.5
                                for st in game.structures
                            )
                            if wb_near:
                                game.show_crafting = True
                                game.show_inventory = False
                                game.show_skills = False
                            else:
                                game.add_notification("Подойдите к установленному Столу мастерской, чтобы открыть создание предметов!", 3.2, (255, 200, 120))
                        else:
                            game.add_notification(
                                "Крафт недоступен! Сначала добудьте 2 дерева камнем, создайте Стол мастерской в инвентаре и поставьте его!",
                                4.2,
                                (255, 140, 115),
                            )
                elif event.key == pygame.K_k:
                    game.show_skills = not game.show_skills
                    game.show_inventory = False
                    game.active_chest = None
                    game.show_crafting = False
                elif event.key == pygame.K_t:
                    if "torch" in game.player.unlocked_weapons:
                        game.player.equipped_weapon = "torch"
                    else:
                        game.add_notification("Скрафтите Горящий факел на Столе мастерской!", 2.5, (255, 175, 120))
                elif event.key == pygame.K_b:
                    if not game.has_placed_workbench():
                        game.add_notification(
                            "Строительство недоступно! Сначала добудьте 2 дерева камнем, создайте Стол мастерской в инвентаре и поставьте его!",
                            4.0,
                            (255, 135, 115),
                        )
                    else:
                        game.build_mode = not game.build_mode
                        if game.build_mode:
                            game.add_notification(
                                "Режим строительства активирован.",
                                3.8,
                                (150, 255, 195),
                            )
                elif event.key == pygame.K_BACKSPACE:
                    if game.show_inventory and game.active_chest is not None:
                        game.transfer_chest_item(to_chest=False)
                    else:
                        game.remove_last_or_hovered_structure()
                # Изменение графики и открытие настроек на клавиши G / O / 0 отключено по запросу игрока (настройки открываются кнопкой 'Настройки' сверху!)
                elif event.key == pygame.K_v:
                    game.cycle_fps_cap()
                elif event.key == pygame.K_n:
                    game.regenerate_with_new_seed()
                elif event.key == pygame.K_r:
                    game.build_rotation = (game.build_rotation + 90.0) % 360.0
                elif event.key == pygame.K_z:
                    game.selected_build_idx = (game.selected_build_idx - 1) % len(BUILD_PIECES)
                elif event.key == pygame.K_x:
                    game.selected_build_idx = (game.selected_build_idx + 1) % len(BUILD_PIECES)
                elif event.key == pygame.K_q:
                    target_slot = game.selected_inv_idx if game.show_inventory else game.player.active_hotbar_slot
                    game.drop_item_from_slot("inv", target_slot, drop_all=not bool(pygame.key.get_mods() & pygame.KMOD_CTRL))
                elif event.key == pygame.K_f:
                    game.interact_world()
                elif event.key == pygame.K_h:
                    game.consume_food_or_heal()
                elif event.key == pygame.K_e:
                    if game.player.equipped_weapon == "workbench_item":
                        game.place_workbench_from_hand()
                    elif game.build_mode or game.player.equipped_weapon == "hammer":
                        game.try_place_building()
                    else:
                        game.interact_world()
                elif event.key == pygame.K_UP:
                    if game.show_crafting:
                        game.selected_recipe_idx = (game.selected_recipe_idx - 1) % len(CRAFTING_RECIPES)
                    elif game.show_inventory:
                        game.selected_inv_idx = max(0, game.selected_inv_idx - 3)
                elif event.key == pygame.K_DOWN:
                    if game.show_crafting:
                        game.selected_recipe_idx = (game.selected_recipe_idx + 1) % len(CRAFTING_RECIPES)
                    elif game.show_inventory:
                        game.selected_inv_idx = game.selected_inv_idx + 3
                elif event.key == pygame.K_LEFT and game.show_inventory:
                    if game.active_chest is not None:
                        game.transfer_chest_item(to_chest=False)
                    else:
                        game.selected_inv_idx = max(0, game.selected_inv_idx - 1)
                elif event.key == pygame.K_RIGHT and game.show_inventory:
                    if game.active_chest is not None:
                        game.transfer_chest_item(to_chest=True)
                    else:
                        game.selected_inv_idx = game.selected_inv_idx + 1
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if game.show_crafting:
                        game.craft_recipe(game.selected_recipe_idx)
                    elif game.show_inventory:
                        if game.active_chest is not None:
                            game.transfer_chest_item(to_chest=True)
                        else:
                            game.consume_food_or_heal()
                elif event.key == pygame.K_F1 or event.key == pygame.K_SLASH:
                    if game.show_skills and event.key == pygame.K_F1:
                        msg = game.player.upgrade_skill("strength")
                        if msg:
                            game.add_notification(msg, 3.5, (255, 225, 100))
                    else:
                        game.show_controls_help = not game.show_controls_help
                elif event.key == pygame.K_F2:
                    msg = game.player.upgrade_skill("vitality")
                    if msg:
                        game.add_notification(msg, 3.5, (255, 225, 100))
                elif event.key == pygame.K_F3:
                    msg = game.player.upgrade_skill("endurance")
                    if msg:
                        game.add_notification(msg, 3.5, (255, 225, 100))
                elif event.key == pygame.K_F4:
                    msg = game.player.upgrade_skill("harvesting")
                    if msg:
                        game.add_notification(msg, 3.5, (255, 225, 100))
                elif event.key == pygame.K_F5:
                    if game.show_skills:
                        msg = game.player.upgrade_skill("hunter")
                        if msg:
                            game.add_notification(msg, 3.5, (255, 225, 100))
                    else:
                        game.save_game()
                elif event.key == pygame.K_F9:
                    game.load_game()
                elif event.key == pygame.K_F11 or (
                    event.key == pygame.K_RETURN and (pygame.key.get_mods() & pygame.KMOD_ALT)
                ):
                    renderer.toggle_fullscreen()
                elif pygame.K_1 <= event.key <= pygame.K_9:
                    slot_idx = event.key - pygame.K_1
                    if game.show_inventory and 0 <= game.selected_inv_idx < MAX_INVENTORY_SLOTS:
                        game.move_or_swap_slots(("inv", game.selected_inv_idx), ("hotbar", slot_idx))
                        game.select_hotbar_slot(slot_idx)
                    else:
                        game.select_hotbar_slot(slot_idx)
            elif hasattr(pygame, "FINGERDOWN") and event.type == pygame.FINGERDOWN:
                game.mobile_controls_enabled = True
                tx = int(event.x * game.width)
                ty = int(event.y * game.height)
                fid = int(getattr(event, "finger_id", 0))
                jcx, jcy, jr = renderer.ui_mobile_joy_circle
                if not ui_modal_open and math.hypot(tx - jcx, ty - jcy) <= jr * 1.35:
                    game.touch_joy_active = True
                    game.touch_joy_pointer_id = fid
                    renderer._update_joystick_from_point(tx, ty)
                elif not renderer.handle_mouse_down(tx, ty, 1):
                    game.touch_look_active = True
                    game.touch_look_pointer_id = fid
                    game.touch_look_last_pos = (float(tx), float(ty))
            elif hasattr(pygame, "FINGERMOTION") and event.type == pygame.FINGERMOTION:
                tx = float(event.x * game.width)
                ty = float(event.y * game.height)
                tdx = float(event.dx * game.width)
                tdy = float(event.dy * game.height)
                fid = int(getattr(event, "finger_id", 0))
                renderer.handle_touch_or_Look_motion(tx, ty, tdx, tdy, pointer_id=fid)
            elif hasattr(pygame, "FINGERUP") and event.type == pygame.FINGERUP:
                tx = int(event.x * game.width)
                ty = int(event.y * game.height)
                fid = int(getattr(event, "finger_id", 0))
                renderer.handle_touch_or_pointer_up(pointer_id=fid)
                renderer.handle_mouse_up(tx, ty, 1)
            elif event.type == pygame.MOUSEMOTION:
                mx_pos, my_pos = event.pos
                rel_x, rel_y = event.rel
                if game.mobile_controls_enabled and not ui_modal_open:
                    renderer.handle_touch_or_Look_motion(float(mx_pos), float(my_pos), float(rel_x), float(rel_y), pointer_id=-1)
            elif event.type == MOUSEBUTTONDOWN:
                mx_pos, my_pos = event.pos
                if event.button == 4:
                    if not hasattr(pygame, "MOUSEWHEEL"):
                        game.handle_mouse_wheel(-1)
                elif event.button == 5:
                    if not hasattr(pygame, "MOUSEWHEEL"):
                        game.handle_mouse_wheel(1)
                elif ui_modal_open:
                    renderer.handle_mouse_down(mx_pos, my_pos, event.button)
                elif event.button == 1:
                    if game.mobile_controls_enabled:
                        renderer.handle_mouse_down(mx_pos, my_pos, event.button)
                    elif not mouse_locked:
                        if not renderer.handle_mouse_down(mx_pos, my_pos, event.button):
                            mouse_locked = True
                    else:
                        game.perform_primary_action()
                elif event.button == 3:
                    if game.player.equipped_weapon == "workbench_item":
                        game.place_workbench_from_hand()
                    elif game.build_mode or game.player.equipped_weapon == "hammer":
                        game.try_place_building()
                    else:
                        game.interact_world()
            elif event.type == pygame.MOUSEBUTTONUP:
                mx_pos, my_pos = event.pos
                renderer.handle_touch_or_pointer_up(pointer_id=-1)
                renderer.handle_mouse_up(mx_pos, my_pos, event.button)

        if mouse_locked and not ui_modal_open and not game.mobile_controls_enabled:
            mx, my = pygame.mouse.get_rel()
            sens = 0.16
            game.player.yaw = (game.player.yaw + mx * sens) % 360.0
            game.player.pitch = max(-84.0, min(84.0, game.player.pitch - my * sens))
        else:
            pygame.mouse.get_rel()

        keys = pygame.key.get_pressed()
        kb_f = float(keys[pygame.K_w] or keys[pygame.K_UP]) - float(keys[pygame.K_s] or keys[pygame.K_DOWN])
        kb_r = float(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - float(keys[pygame.K_a] or keys[pygame.K_LEFT])
        # Суммируем клавиатуру (WASD) и виртуальный сенсорный джойстик телефона!
        joy_f = -game.touch_joy_dy if game.mobile_controls_enabled else 0.0
        joy_r = game.touch_joy_dx if game.mobile_controls_enabled else 0.0
        move_f = max(-1.0, min(1.0, kb_f + joy_f))
        move_r = max(-1.0, min(1.0, kb_r + joy_r))
        if ui_modal_open:
            move_f = 0.0
            move_r = 0.0
        jump = (bool(keys[pygame.K_SPACE]) or game.touch_jump_held) and not ui_modal_open
        dive = bool(keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL]) or game.touch_dive_held
        joy_outer_sprint = math.hypot(game.touch_joy_dx, game.touch_joy_dy) > 0.84
        sprint = bool(keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) or game.touch_sprint_locked or joy_outer_sprint

        if game.touch_attack_held and not ui_modal_open and not game.build_mode:
            game.perform_primary_action()

        game.update(dt, move_f, move_r, jump, sprint, dive=dive)
        renderer.render_frame(screen)
        pygame.display.flip()

        frame_elapsed = max(0.0005, time.perf_counter() - t_frame_start)
        game.fps_history.append(1.0 / frame_elapsed)
        game.current_fps = sum(game.fps_history) / len(game.fps_history)
        game.frame_ms = frame_elapsed * 1000.0

    pygame.quit()


if __name__ == "__main__":
    main()
