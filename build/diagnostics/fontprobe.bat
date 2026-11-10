@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
set QTDIR=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64
cd /d D:\Code\EchoMusicNext\build\diagnostics || exit /b 1
cl /nologo /EHsc /MD /O2 /utf-8 /Zc:__cplusplus /permissive- /std:c++17 /I"%QTDIR%\include" /I"%QTDIR%\include\QtCore" /I"%QTDIR%\include\QtGui" fontprobe.cpp /link /LIBPATH:"%QTDIR%\lib" Qt6Core.lib Qt6Gui.lib /OUT:fontprobe.exe || exit /b 1
echo PROBE_BUILD_OK
