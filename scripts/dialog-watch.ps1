# dialog-watch.ps1 — record which process owns a native dialog window (#32770).
# Keeps running; every new dialog window is appended to logs\dialog-watch.log.

$ErrorActionPreference = "SilentlyContinue"
$log = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\logs\dialog-watch.log"))
$null = New-Item -ItemType Directory -Force -Path (Split-Path $log)

Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class WinEnum2 {
    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr parent, EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr hWnd, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetClassNameW(IntPtr hWnd, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);

    public static List<string[]> List() {
        var rows = new List<string[]>();
        EnumWindows(delegate(IntPtr h, IntPtr l) {
            if (!IsWindowVisible(h)) return true;
            var title = new StringBuilder(512);
            var cls = new StringBuilder(256);
            GetWindowTextW(h, title, 512);
            GetClassNameW(h, cls, 256);
            uint pid;
            GetWindowThreadProcessId(h, out pid);

            var childText = new StringBuilder();
            if (cls.ToString() == "#32770") {
                EnumChildWindows(h, delegate(IntPtr c, IntPtr l2) {
                    var t = new StringBuilder(1024);
                    GetWindowTextW(c, t, 1024);
                    if (t.Length > 0) childText.Append(t.ToString()).Append(" | ");
                    return true;
                }, IntPtr.Zero);
            }
            rows.Add(new string[] { pid.ToString(), cls.ToString(), title.ToString(), childText.ToString() });
            return true;
        }, IntPtr.Zero);
        return rows;
    }
}
"@

$self = $PID
$seen = @{}
Write-Host "watching native dialogs (skip self pid=$self); log: $log"

while ($true) {
    foreach ($row in [WinEnum2]::List()) {
        $procId = [int]$row[0]
        $cls = $row[1]
        $title = $row[2]
        $body = $row[3]
        if ($procId -eq $self) { continue }
        if ($cls -ne "#32770") { continue }
        if ($title -notmatch "警告|Warning|加密|合约|提示|Notice|Alert") { continue }

        $key = "$procId|$title|$body"
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = 1

        $proc = Get-Process -Id $procId
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$procId"
        $parentId = $cim.ParentProcessId
        $parent = Get-Process -Id $parentId
        $line = "{0} | pid={1} proc={2} title='{3}' body='{4}' exe={5} parent={6}({7}) start={8} | cmd={9}" -f `
            (Get-Date -Format o), $procId, $proc.ProcessName, $title, $body.Trim(), $cim.ExecutablePath, `
            $parent.ProcessName, $parentId, $proc.StartTime, $cim.CommandLine
        $line | Tee-Object -FilePath $log -Append | Write-Host
    }
    Start-Sleep -Milliseconds 300
}
