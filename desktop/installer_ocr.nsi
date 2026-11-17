; Gói nhận dạng chữ tiếng Việt (Tesseract OCR) cho "Công cụ văn bản NĐ30" – cài vào thư mục của ứng dụng.
; makensis -DSTAGE=<thư mục có tesseract\> -DOUT=<file exe> installer_ocr.nsi
Unicode true
!include "MUI2.nsh"
!define APPNAME "Công cụ văn bản NĐ30"
!define APPID "CongCuVanBanND30"
!define VERSION "1.0.45"
Name "${APPNAME} – Gói nhận dạng chữ"
OutFile "${OUT}"
InstallDir "$LOCALAPPDATA\Programs\${APPID}"
InstallDirRegKey HKCU "Software\${APPID}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${APPNAME} ${VERSION}"
VIProductVersion "1.0.45.0"
VIAddVersionKey /LANG=1066 "ProductName" "${APPNAME}"
VIAddVersionKey /LANG=1066 "FileDescription" "Gói nhận dạng chữ tiếng Việt cho ${APPNAME}"
VIAddVersionKey /LANG=1066 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1066 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1066 "LegalCopyright" " "
!define MUI_ICON "app.ico"
!define MUI_WELCOMEPAGE_TEXT "Cài gói nhận dạng chữ tiếng Việt (Tesseract OCR) để ${APPNAME} đọc được PDF quét và ảnh.$\r$\n$\r$\nHãy cài ${APPNAME} trước, rồi cài gói này vào cùng thư mục."
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "Vietnamese"

Function .onVerifyInstDir
  IfFileExists "$INSTDIR\${APPID}.exe" +2
    Abort
FunctionEnd

Section "Install"
  SetOutPath "$INSTDIR"
  RMDir /r "$INSTDIR\tesseract"
  File /r "${STAGE}\tesseract"
SectionEnd
