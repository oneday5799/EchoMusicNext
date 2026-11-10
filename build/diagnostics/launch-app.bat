@echo off
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
cd /d D:\Code\EchoMusicNext\build\release\app || exit /b 1
start "" echomusicnext.exe
echo LAUNCHED
