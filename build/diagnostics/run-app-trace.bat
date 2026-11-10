@echo off
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
set ECHO_PIXEL_SNAP_TRACE=e
cd /d D:\Code\EchoMusicNext\build\release\app
echomusicnext.exe 2>pixel-trace.log
