@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
cd /d D:\Code\EchoMusicNext || exit /b 1
cmake --build --preset release --target echo-playback-page-test --parallel 6 || exit /b 1
echo BUILD_OK
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
set QT_QPA_PLATFORM=offscreen
cd /d D:\Code\EchoMusicNext\build\release || exit /b 1
echo-playback-page-test.exe secondaryColorsResolveAcrossPageSkins 2>&1
