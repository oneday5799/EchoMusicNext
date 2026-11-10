@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
cd /d D:\Code\EchoMusicNext || exit /b 1
python scripts/patch-qt-qml.py --qt-prefix "D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64" --jobs 6 --archive "D:\Code\EchoMusicNext\build\qt-qv4-gc\qtdeclarative-4332fbbb.tar.gz"
