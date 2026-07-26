@echo off
rem launch_yeet.bat — start YEET with a clean Python environment.
rem
rem Resolve exports PYTHONHOME (and friends) for its own scripting host. A
rem PyInstaller exe that inherits PYTHONHOME crashes instantly on startup, which
rem looks like "clicking the menu item does nothing". Clearing these first is the
rem whole reason this shim exists — do not launch YEET.exe directly from Resolve.
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONSTARTUP="
set "PYTHONEXECUTABLE="
set "PYTHONNOUSERSITE="
set "PYTHONDONTWRITEBYTECODE="
start "" "%~dp0YEET.exe" %*
