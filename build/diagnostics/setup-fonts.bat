@echo off
rem The offscreen QPA platform resolves fonts through Qt's BasicFontDatabase,
rem which scans <Qt>\lib\fonts. Without deployed fonts QFontDatabase::families()
rem is empty and text renders with degenerate box metrics. Copy the Windows set
rem once after (re)installing the Qt build.
rem The scanner filters files by extension and never registers ".ttc", so the
rem YaHei collections deploy under ".ttf" names; FreeType reads the container
rem regardless of the extension and both UI faces register.
set "FONTS=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\lib\fonts"
if not exist "%FONTS%" mkdir "%FONTS%" || exit /b 1
for %%F in (arial.ttf arialbd.ttf segoeui.ttf segoeuib.ttf consola.ttf) do (
    if not exist "%FONTS%\%%F" copy /y "C:\Windows\Fonts\%%F" "%FONTS%\%%F" >nul || exit /b 1
)
if not exist "%FONTS%\msyh.ttf" copy /y "C:\Windows\Fonts\msyh.ttc" "%FONTS%\msyh.ttf" >nul || exit /b 1
if not exist "%FONTS%\msyhbd.ttf" copy /y "C:\Windows\Fonts\msyhbd.ttc" "%FONTS%\msyhbd.ttf" >nul || exit /b 1
if exist "%FONTS%\msyh.ttc" del "%FONTS%\msyh.ttc"
if exist "%FONTS%\msyhbd.ttc" del "%FONTS%\msyhbd.ttc"
echo FONTS_OK
