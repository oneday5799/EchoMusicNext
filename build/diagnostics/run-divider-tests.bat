@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
set QT_QPA_PLATFORM=offscreen
cd /d D:\Code\EchoMusicNext\build\release || exit /b 1
echo === discovery underline pixel test (zoom 1.0 + 1.25) ===
echo-discovery-test.exe freeListenAndDiscoverFlowPages 2>&1
echo === playlist detail regression ===
echo-playlist-detail-test.exe 2>&1 | findstr /C:"PASS" /C:"FAIL" /C:"Totals"
