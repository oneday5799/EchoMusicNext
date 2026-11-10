@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
cd /d D:\Code\EchoMusicNext\build\release\app || exit /b 1
start "" echomusicnext.exe
