@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
set QT_QPA_PLATFORM=offscreen
set QT_SCALE_FACTOR=1.25
cd /d D:\Code\EchoMusicNext\build\release || exit /b 1
echo === probe with snap enabled ===
echo-playlist-detail-test.exe probeDividerPhaseDuringResize 2>&1
echo === probe with snap disabled ===
set ECHO_PIXEL_SNAP=0
echo-playlist-detail-test.exe probeDividerPhaseDuringResize 2>&1
