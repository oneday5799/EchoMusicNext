@echo off
REM Build the application (and optional targets) with the MSVC environment.
REM Usage: build-app.bat [target ...]   (default: echomusicnext)
set QTBASE=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" || exit /b 1
set PATH=%QTBASE%\bin;%PATH%
if "%~1"=="" (
  cmake --build D:\Code\EchoMusicNext\build\release --target echomusicnext || exit /b 1
) else (
  :loop
  if not "%~1"=="" (
    cmake --build D:\Code\EchoMusicNext\build\release --target %1 || exit /b 1
    shift
    goto loop
  )
)
echo BUILD_DONE
