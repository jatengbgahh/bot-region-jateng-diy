Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$desktop = [System.Windows.Automation.AutomationElement]::RootElement

# PENTING: cek dulu apakah tombolnya lagi nunjukin "Disconnect" (berarti
# SUDAH connected). AutomationId "1160" dipakai ULANG oleh tombol yang sama
# di kedua state (Connect/Disconnect) — cuma Name-nya yang beda. Kalau
# langsung cari by AutomationId tanpa cek Name dulu, script ini bisa nge-klik
# tombol Disconnect dan MEMUTUS koneksi yang sebenarnya sudah nyambung.
$conditionDisconnect = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, "Disconnect"
)
$disconnectButton = $desktop.FindFirst([System.Windows.Automation.TreeScope]::Subtree, $conditionDisconnect)
if ($disconnectButton -ne $null) {
    Write-Host "SKIP: sudah ada tombol Disconnect (VPN sudah connected), tidak jadi klik apa pun"
    exit
}

$conditionName = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty, "Connect"
)
$button = $desktop.FindFirst([System.Windows.Automation.TreeScope]::Subtree, $conditionName)

if ($button -eq $null) {
    $conditionId = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty, "1160"
    )
    $candidate = $desktop.FindFirst([System.Windows.Automation.TreeScope]::Subtree, $conditionId)
    # Guard tambahan: cuma dipakai kalau Name-nya BUKAN "Disconnect".
    if ($candidate -ne $null -and $candidate.Current.Name -ne "Disconnect") {
        $button = $candidate
    }
}

if ($button -ne $null) {
    # Cara 1 (utama): InvokePattern — panggil handler klik langsung lewat
    # UI Automation API, tanpa gerakin kursor sama sekali. Ini yang tetap
    # jalan walau sesi RDP disconnect / tidak ada desktop interaktif aktif,
    # beda dengan simulasi mouse_event yang butuh kursor fisik nyampe ke
    # window-nya.
    $invokePattern = $null
    $got = $button.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invokePattern)
    if ($got -and $invokePattern -ne $null) {
        try {
            $invokePattern.Invoke()
            Write-Host "SUCCESS: INVOKED"
            return
        } catch {
            Write-Host "WARN: Invoke() gagal, coba fallback mouse_event. $_"
        }
    }

    # Cara 2 (fallback): simulasi klik mouse fisik di posisi tombol.
    # Cuma jalan kalau ada sesi desktop interaktif aktif (RDP tersambung/
    # console login, bukan minimized/disconnected).
    $rect = $button.Current.BoundingRectangle
    if ($rect.Width -gt 0 -and $rect.Height -gt 0) {
        $centerX = [int]($rect.X + ($rect.Width / 2))
        $centerY = [int]($rect.Y + ($rect.Height / 2))

        [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point($centerX, $centerY)
        Start-Sleep -Milliseconds 100

        $signature = '[DllImport("user32.dll")] public static extern void mouse_event(int dwFlags, int dx, int dy, int cButtons, int dwExtraInfo);'
        $type = Add-Type -MemberDefinition $signature -Name "Win32MouseHelper" -Namespace "Win32Util" -PassThru
        $type::mouse_event(0x0002, 0, 0, 0, 0)
        Start-Sleep -Milliseconds 50
        $type::mouse_event(0x0004, 0, 0, 0, 0)
        Write-Host "SUCCESS: CLICKED (mouse fallback)"
    } else {
        Write-Host "FAIL: tombol Connect ketemu tapi tidak punya InvokePattern maupun BoundingRectangle valid"
    }
} else {
    Write-Host "FAIL: tombol Connect tidak ditemukan (window GlobalProtect mungkin belum terbuka)"
}
