@echo off
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1 || exit /b 1
set "PATH=D:\Code\EchoMusicNext\build\qt-official\6.12.0\msvc2022_64\bin;%PATH%"
set QT_QPA_PLATFORM=offscreen
cd /d D:\Code\EchoMusicNext\build\release || exit /b 1
echo === controls-ui ===
echo-controls-ui-test.exe pixelSnapTracksScenePositionAcrossReparentAndWindows pixelSnapDisabledUsesLogicalGeometry imageDensityTracksScaleWithoutTrackingScroll || exit /b 1
echo === plugin-runtime ===
echo-plugin-runtime-test.exe uiStyleLayersRestoreLiveBindings uiPartsIdentityObservationAndPublicActions uiPartsProductionPlaybackAndMini uiPartInstanceStylesAndLeasesStayBounded temporaryAppearancePriorityLiveBaseAndRevocation appearanceErrorsAndActivationRollback || exit /b 1
echo ALL_GREEN
