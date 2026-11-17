/* Trình khởi động "Công cụ văn bản NĐ30": chạy runtime\pythonw.exe app\nd30fmt\desktop.py (không bật cửa sổ dòng lệnh). */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE h, HINSTANCE p, PWSTR cmd, int show) {
    wchar_t dir[MAX_PATH], exe[MAX_PATH], line[4 * MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, dir, MAX_PATH);
    if (!n || n >= MAX_PATH) return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    swprintf(exe, MAX_PATH, L"%ls\\runtime\\pythonw.exe", dir);
    swprintf(line, 4 * MAX_PATH, L"\"%ls\" -I -X utf8 \"%ls\\app\\nd30fmt\\desktop.py\"", exe, dir);
    if (GetFileAttributesW(exe) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"Thiếu thư mục runtime. Hãy cài lại ứng dụng.", L"Công cụ văn bản NĐ30", MB_ICONERROR);
        return 1;
    }
    STARTUPINFOW si = {0};
    PROCESS_INFORMATION pi = {0};
    si.cb = sizeof(si);
    if (!CreateProcessW(exe, line, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"Không chạy được ứng dụng.", L"Công cụ văn bản NĐ30", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
