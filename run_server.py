"""
Entry point for PyInstaller bundle.
Runs the FastAPI backend with uvicorn on port 8000.
Environment variables can be passed via a .env file placed next to the exe,
or via OS environment (e.g., set by Electron main process before spawning).
"""
import multiprocessing
import os
import sys

# When running as a PyInstaller bundle, __file__ is inside a temp dir.
# Set the working directory to the folder that contains the exe so that
# app.db and downloads/ are created next to the executable.
if getattr(sys, 'frozen', False):
    # APP_DATA_DIR is set by Electron to app.getPath('userData') — a writable directory.
    # Fall back to exe directory only if not set (e.g. running standalone).
    data_dir = os.environ.get('APP_DATA_DIR') or os.path.dirname(sys.executable)
    os.chdir(data_dir)

import uvicorn

if __name__ == '__main__':
    # Required for PyInstaller + multiprocessing on Windows
    multiprocessing.freeze_support()

    port = int(os.environ.get('APP_PORT', 8000))
    host = os.environ.get('APP_HOST', '127.0.0.1')

    uvicorn.run(
        'machine.server:app',
        host=host,
        port=port,
        log_level='info',
    )
