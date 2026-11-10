@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
set PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%
cd /d D:\Code\EchoMusicNext\build\release
set OUT=D:\Code\EchoMusicNext\build\diagnostics\test-out.txt
%* > "%OUT%" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "%OUT%"
