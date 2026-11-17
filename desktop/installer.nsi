; Bộ cài "Công cụ văn bản NĐ30" (cài cho người dùng hiện tại, không cần quyền quản trị)
; makensis -DSTAGE=<thư mục đã ghép: CongCuVanBanND30.exe, app\, runtime\> -DOUT=<file exe> installer.nsi
; Gói nhận dạng chữ (Tesseract) cài riêng bằng installer_ocr.nsi để mỗi file dưới 30 MB.
Unicode true
!include "MUI2.nsh"
!define APPNAME "Công cụ văn bản NĐ30"
!define APPID "CongCuVanBanND30"
!define VERSION "1.0.45"
Name "${APPNAME}"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Programs\${APPID}"
InstallDirRegKey HKCU "Software\${APPID}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${APPNAME} ${VERSION}"
VIProductVersion "1.0.45.0"
VIAddVersionKey /LANG=1066 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=1066 "FileDescription" "Cài đặt ${APPNAME}"
VIAddVersionKey /LANG=1066 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1066 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1066 "LegalCopyright" " "

!define MUI_ICON "app.ico"
!define MUI_UNICON "app.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${APPID}.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Mở ${APPNAME}"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Vietnamese"

Section "Install"
  SetOutPath "$INSTDIR"
  ; bản cũ: xoá mã nguồn và môi trường chạy (dữ liệu người dùng ở %LOCALAPPDATA%\${APPID} được giữ)
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\runtime"
  File "${STAGE}\${APPID}.exe"
  File "app.ico"
  File /r "${STAGE}\app"
  File /r "${STAGE}\runtime"
  File "${STAGE}\DOC_TRUOC.txt"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${APPID}.exe" "" "$INSTDIR\app.ico"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${APPID}.exe" "" "$INSTDIR\app.ico"
  CreateShortCut "$SMPROGRAMS\${APPNAME}\Gỡ cài đặt.lnk" "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\${APPID}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" "DisplayIcon" "$INSTDIR\app.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" "InstallLocation" "$INSTDIR"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir /r "$INSTDIR\app"
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\tesseract"
  Delete "$INSTDIR\${APPID}.exe"
  Delete "$INSTDIR\app.ico"
  Delete "$INSTDIR\DOC_TRUOC.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}"
  DeleteRegKey HKCU "Software\${APPID}"
SectionEnd
