@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
cd /d D:\Code\EchoMusicNext || exit /b 1
cmake --build --preset release --target echo-shell-test echo-desktop-pages-test --parallel 6 || exit /b 1
echo BUILD_OK
