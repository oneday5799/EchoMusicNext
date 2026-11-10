@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
cd /D D:\Code\EchoMusicNext\build\release
link.exe /nologo @CMakeFiles\echomusicnext-map.rsp /out:app\echomusicnext-map.exe /implib:app\echomusicnext-map.lib /pdb:app\echomusicnext-map.pdb /version:0.0 /machine:x64 /INCREMENTAL:NO /subsystem:windows /MAP /MAPINFO:EXPORTS
echo LINKEXIT=%ERRORLEVEL%
