; NSIS script generated from this template by the installer probe when Inno Setup is not
; available. It must stay at user level: no admin rights are requested.
Unicode true
RequestExecutionLevel user
Name "@DISPLAY_NAME@"
OutFile "@OUTPUT_FILE@"
InstallDir "$LOCALAPPDATA\Programs\@APP_ID@\@VERSION@"
InstallDirRegKey HKCU "Software\@APP_ID@" "InstallDir"
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "Install"
  SetOutPath "$INSTDIR"
  File /r "@BUNDLE_DIR@\*.*"
  CreateDirectory "$SMPROGRAMS\@DISPLAY_NAME@"
  CreateShortCut "$SMPROGRAMS\@DISPLAY_NAME@\@DISPLAY_NAME@.lnk" "$INSTDIR\python\pythonw.exe" '"$INSTDIR\launcher.py"' "$INSTDIR\python\pythonw.exe" 0
  WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
  RMDir /r "$INSTDIR"
  Delete "$SMPROGRAMS\@DISPLAY_NAME@\@DISPLAY_NAME@.lnk"
  RMDir "$SMPROGRAMS\@DISPLAY_NAME@"
SectionEnd
