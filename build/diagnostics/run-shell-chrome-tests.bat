@echo off
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
set QT_QPA_PLATFORM=offscreen
cd /d D:\Code\EchoMusicNext\build\release || exit /b 1
echo-shell-test.exe 2>&1
