@echo off
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
set QT_QPA_PLATFORM=offscreen
set ECHO_SIDEBAR_REFLOW_CAPTURE_DIR=D:\Code\EchoMusicNext\build\diagnostics\sidebar-captures
cd /d D:\Code\EchoMusicNext\build\release || exit /b 1
echo-desktop-pages-test.exe sidebarShortcutCollapseFrames 2>&1
