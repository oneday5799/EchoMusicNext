@echo off
setlocal EnableExtensions
set "REPO=D:\Code\EchoMusicNext"
set "QT_PREFIX=%REPO%\build\qt-official\6.12.0\msvc2022_64"
set "NODE_OPTIONS=--use-system-ca"
rem FETCHCONTENT_FULLY_DISCONNECTED=ON: crashpad/curl sources are pre-seeded in
rem build\release\_deps (see build\fetchcontent-tarballs). If build\release is
rem ever deleted, re-run the seed step before building offline, or remove this
rem flag to let cmake download from codeload.github.com (may hang on IPv6).

call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 exit /b 1

cd /d "%REPO%"

cmake --preset release -DCMAKE_PREFIX_PATH="%QT_PREFIX%" -DECHO_DISTRIBUTION_BUILD=ON -DECHO_APPLICATION_OUTPUT_DIRECTORY="%REPO%\build\release\app" -DFETCHCONTENT_FULLY_DISCONNECTED=ON
if errorlevel 1 exit /b 1

cmake --build --preset release
if errorlevel 1 exit /b 1

for /l %%i in (1,1,3) do (
  echo === prepare attempt %%i ===
  node tools\release\prepare.mjs && goto prepare_ok
  echo prepare attempt %%i failed
)
echo prepare.mjs failed after 3 attempts; continuing with existing materials

:prepare_ok
node tools\release\package.mjs --qt="%QT_PREFIX%"
if errorlevel 1 exit /b 1
