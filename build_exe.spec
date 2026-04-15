# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for packaging the FastAPI backend as a standalone exe.
# Build: pyinstaller build_exe.spec
# Output: dist/backend.exe

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['run_server.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('migrations', 'migrations'),
        ('alembic.ini', '.'),
    ],
    hiddenimports=[
        # FastAPI / Starlette
        'fastapi',
        'fastapi.middleware.cors',
        'fastapi.staticfiles',
        'starlette',
        'starlette.middleware',
        'starlette.staticfiles',
        'starlette.responses',
        # Uvicorn
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # SQLAlchemy + aiosqlite
        'sqlalchemy',
        'sqlalchemy.ext.asyncio',
        'sqlalchemy.dialects.sqlite',
        'aiosqlite',
        # Alembic
        'alembic',
        'alembic.runtime.migration',
        'alembic.operations',
        # Pydantic
        'pydantic',
        'pydantic_settings',
        'pydantic.v1',
        # Auth
        'jose',
        'jose.jwt',
        'passlib',
        'passlib.handlers.bcrypt',
        # HTTP
        'httpx',
        'httpcore',
        # Playwright
        'playwright',
        'playwright.sync_api',
        'playwright.async_api',
        # Others
        'python_multipart',
        'gmssl',
        'imageio_ffmpeg',
        'dotenv',
        'multipart',
        # App modules
        'machine',
        'machine.server',
        'machine.api',
        'machine.api.v1',
        'machine.api.v1.auth',
        'machine.api.v1.fanpage',
        'machine.api.v1.test_user',
        'machine.api.v1.content',
        'machine.controllers',
        'machine.external',
        'machine.models',
        'machine.schemas',
        'core',
        'core.settings',
        'core.db',
        'core.db.base',
        'core.db.session',
        'core.fastapi',
        'core.fastapi.middleware',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'PIL'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # keep True so logs are visible during dev; set False for silent mode
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
