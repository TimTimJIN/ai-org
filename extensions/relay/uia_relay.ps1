# ai-org relay：Claude・Codex アプリの画面を UI Automation で読み書きする。
# 標準入力に JSON {"action": "probe|read|send", "app": "claude|codex", "title": "<会話名>", "text": "...", "nonce": "..."}
# 標準出力に JSON {"ok": true, ...} または {"ok": false, "error": "..."}
# 決めた会話が表示されていない・入力欄が1つに決まらない・書きかけの文がある・貼り付けを確かめられない、のどれでも送らずに止まる。
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Out-Result($value) { [Console]::Out.Write(($value | ConvertTo-Json -Compress -Depth 4)) }

try {
    Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
    Add-Type -Namespace AiOrg -Name Win -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
[DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
[DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
[DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
[DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
[DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
[DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
'@
    # Windows は、裏で動くプログラムが窓を前面に出すことを止める（直前に利用者の入力がないとき）。
    # 1) そのまま 2) ALT キーを一度押して離す（前面の切り替えの制限が外れる） 3) 前面の窓の入力に一時的に相乗りする、の順に試す。
    # 2) と 3) は、利用者が使っている窓にも ALT が届く・入力に相乗りするので、送るときだけ使う（$force）。
    function Set-Front([IntPtr]$h, [bool]$force = $false) {
        if ([AiOrg.Win]::GetForegroundWindow() -eq $h) { return $true }
        [AiOrg.Win]::SetForegroundWindow($h) | Out-Null
        Start-Sleep -Milliseconds 150
        if ([AiOrg.Win]::GetForegroundWindow() -eq $h) { return $true }
        if (-not $force) { return $false }
        [AiOrg.Win]::keybd_event(0x12, 0, 0, [UIntPtr]::Zero)
        [AiOrg.Win]::keybd_event(0x12, 0, 2, [UIntPtr]::Zero)
        [AiOrg.Win]::SetForegroundWindow($h) | Out-Null
        Start-Sleep -Milliseconds 150
        if ([AiOrg.Win]::GetForegroundWindow() -eq $h) { return $true }
        $fgThread = [AiOrg.Win]::GetWindowThreadProcessId([AiOrg.Win]::GetForegroundWindow(), [IntPtr]::Zero)
        $me = [AiOrg.Win]::GetCurrentThreadId()
        if ($fgThread -and $fgThread -ne $me) { [AiOrg.Win]::AttachThreadInput($me, $fgThread, $true) | Out-Null }
        try {
            [AiOrg.Win]::BringWindowToTop($h) | Out-Null
            [AiOrg.Win]::SetForegroundWindow($h) | Out-Null
        } finally {
            if ($fgThread -and $fgThread -ne $me) { [AiOrg.Win]::AttachThreadInput($me, $fgThread, $false) | Out-Null }
        }
        Start-Sleep -Milliseconds 200
        return ([AiOrg.Win]::GetForegroundWindow() -eq $h)
    }
    $req = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $AE = [System.Windows.Automation.AutomationElement]
    $CT = [System.Windows.Automation.ControlType]
    $desc = [System.Windows.Automation.TreeScope]::Descendants

    # アプリの窓（Claude：Claude デスクトップ、Codex：OpenAI.Codex パッケージの ChatGPT.exe）
    if ($req.app -eq 'claude') { $procName = 'claude'; $pathMark = '\Claude_' }
    elseif ($req.app -eq 'codex') { $procName = 'ChatGPT'; $pathMark = '\OpenAI.Codex_' }
    else { throw "未対応のアプリです：$($req.app)" }
    $ids = @(Get-Process -Name $procName -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and $_.Path.Contains($pathMark) } | ForEach-Object { $_.Id })
    if ($ids.Count -eq 0) { throw 'アプリが起動していません。' }
    # 本体の窓と、別の窓に出した会話（ポップアウト）の両方を探す。
    $windows = @($AE::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition) | Where-Object { $ids -contains $_.Current.ProcessId })
    if ($windows.Count -eq 0) { throw 'アプリの窓が見つかりません。' }

    function Find-All($root, $type) {
        $cond = New-Object System.Windows.Automation.PropertyCondition($AE::ControlTypeProperty, $type)
        return @($root.FindAll($desc, $cond))
    }
    function Get-Pattern($element, $pattern) {
        $value = $null
        if ($element.TryGetCurrentPattern($pattern, [ref]$value)) { return $value }
        return $null
    }
    function Get-Docs($window) {
        return @(Find-All $window $CT::Document | Where-Object { $_.Current.AutomationId -eq 'RootWebArea' })
    }
    function Get-Inputs($root) {
        return @(Find-All $root $CT::Edit | Where-Object { $_.Current.IsKeyboardFocusable -and (Get-Pattern $_ ([System.Windows.Automation.ValuePattern]::Pattern)) })
    }
    # 会話（RootWebArea）ごとに、それを表示している窓を覚える。
    # 画面の読み上げ用の木が育っていないと要素が少ない。2回目の問い合わせで育つことが多い。
    $found = @()
    foreach ($attempt in 1..2) {
        foreach ($w in $windows) { foreach ($d in (Get-Docs $w)) { $found += , @($d, $w) } }
        if ($found.Count -gt 0) { break }
        Start-Sleep -Seconds 2
    }
    $names = @($found | ForEach-Object { $_[0].Current.Name })
    if ($req.action -eq 'probe') {
        Out-Result @{ ok = $true; conversations = $names; inputs = @($found | ForEach-Object { @(Get-Inputs $_[0]).Count }) }
        exit 0
    }

    $title = [string]$req.title
    $matched = @($found | Where-Object { $_[0].Current.Name -ceq $title -or $_[0].Current.Name -ceq "$title - Claude Code" })
    # 同じ会話を本体の窓と別の窓（ポップアウト）の両方に出しているときは、題名がそのままの別の窓を使う。
    # それでも1つに決まらなければ送らない。
    if ($matched.Count -gt 1) { $matched = @($matched | Where-Object { $_[0].Current.Name -ceq $title }) }
    if ($matched.Count -ne 1) {
        throw "決めた会話「$title」が表示されていません（表示中：$($names -join ' / ')）。その会話を開いてから再開してください。"
    }
    $doc = $matched[0][0]
    $docName = $doc.Current.Name
    $window = $matched[0][1]
    $hwnd = [IntPtr]$window.Current.NativeWindowHandle
    if ([AiOrg.Win]::IsIconic($hwnd)) { [AiOrg.Win]::ShowWindow($hwnd, 9) | Out-Null; Start-Sleep -Milliseconds 800 }
    $textPattern = Get-Pattern $doc ([System.Windows.Automation.TextPattern]::Pattern)
    if ($null -eq $textPattern) { throw '会話の文字を読めません（TextPattern がありません）。' }
    $single = @($found | Where-Object { $_[1] -eq $window }).Count -eq 1
    function Find-Input {
        $list = @(Get-Inputs $doc)
        # 入力欄が会話の外にある作りでも、その窓に会話が1つだけなら、窓の入力欄を使う（分割表示では使わない）。
        if ($list.Count -eq 0 -and $single) { $list = @(Get-Inputs $window) }
        return , $list
    }
    $inputs = Find-Input
    if ($inputs.Count -eq 0) {
        # 前面に出したことのない窓（フォーカスなしで開いたポップアウトなど）は、読み上げ用の木が作られていない。
        # 一度だけ前面に出して木を作らせ、元の窓に戻す。
        $before = [AiOrg.Win]::GetForegroundWindow()
        Set-Front $hwnd $true | Out-Null
        foreach ($attempt in 1..4) { Start-Sleep -Seconds 2; $inputs = Find-Input; if ($inputs.Count -gt 0) { break } }
        if ($before -ne [IntPtr]::Zero -and $before -ne $hwnd) { Set-Front $before | Out-Null }
    }
    if ($inputs.Count -ne 1) { throw "入力欄が1つに決まりません（$($inputs.Count) 個）。" }
    $box = $inputs[0]
    $boxValue = Get-Pattern $box ([System.Windows.Automation.ValuePattern]::Pattern)

    if ($req.action -eq 'read' -and $req.refresh) {
        # 他の窓に隠れた窓は、画面の読み上げ用の木が更新されない（返答が終わっても「実行中」のまま見える）。
        # 一瞬だけ前面に出して更新させ、元の窓に戻す。
        $before = [AiOrg.Win]::GetForegroundWindow()
        if ($before -ne $hwnd) {
            # 裏で動くプログラムの普通の切り替えは、Windows にほぼ必ず止められるので、強い手を使う（回数は中継側で倍々に減らす）。
            Set-Front $hwnd $true | Out-Null
            Start-Sleep -Seconds 2
            if ($before -ne [IntPtr]::Zero) { Set-Front $before $true | Out-Null }
        }
    }
    if ($req.action -eq 'read') {
        Out-Result @{ ok = $true; conversation = $doc.Current.Name; text = $textPattern.DocumentRange.GetText(-1); draft = $boxValue.Current.Value }
        exit 0
    }
    if ($req.action -ne 'send') { throw "未対応の操作です：$($req.action)" }

    # 書きかけの文は消さない（空か、入力欄の案内文だけのときに送る）。
    $draft = ([string]$boxValue.Current.Value).Trim()
    if ($draft -and $draft -ne $box.Current.Name.Trim()) { throw '入力欄に書きかけの文があります。消してから再開してください（中継は消しません）。' }
    $nonce = [string]$req.nonce
    if (-not $nonce -or -not ([string]$req.text).Contains($nonce)) { throw '送る文に relay-id がありません。' }

    $previous = [AiOrg.Win]::GetForegroundWindow()
    $saved = $null
    # クリップボードは、文字だけでなく画像・ファイル・書式などすべての形式を写して、送った後に戻す。
    try {
        $current = [System.Windows.Forms.Clipboard]::GetDataObject()
        if ($null -ne $current) {
            $saved = New-Object System.Windows.Forms.DataObject
            foreach ($format in $current.GetFormats($false)) {
                try { $value = $current.GetData($format, $false); if ($null -ne $value) { $saved.SetData($format, $false, $value) } } catch { }
            }
            if ($saved.GetFormats().Count -eq 0) { $saved = $null }
        }
    } catch { $saved = $null }
    try {
        if (-not (Set-Front $hwnd $true)) { throw 'アプリの窓を前面にできませんでした（Windows が切り替えを止めました）。' }
        Start-Sleep -Milliseconds 200
        $box.SetFocus()
        Start-Sleep -Milliseconds 200
        [System.Windows.Forms.Clipboard]::SetText([string]$req.text)
        [System.Windows.Forms.SendKeys]::SendWait('^v')
        # 長い文は、入力欄に反映されるまで時間がかかる（数千字で1秒を超える）。最大6秒待つ。
        $pasted = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 300
            if (([string]$boxValue.Current.Value).Contains($nonce)) { $pasted = $true; break }
        }
        if (-not $pasted) { throw '貼り付けた文を入力欄で確かめられません。送っていません（入力欄に文が残っていれば消してください）。' }
        if ([AiOrg.Win]::GetForegroundWindow() -ne $hwnd) { throw '貼り付けの間に別の窓が前面になりました。送っていません（入力欄の文を確かめてください）。' }
        # Enter の直前に、表示中の会話がまだ決めた会話かを確かめ直す（その間に別の会話へ切り替わっていないか）。
        if ($doc.Current.Name -cne $docName) { throw "貼り付けの間に表示中の会話が変わりました（$($doc.Current.Name)）。送っていません（入力欄の文を確かめてください）。" }
        [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
        $sent = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 300
            if (-not ([string]$boxValue.Current.Value).Contains($nonce)) { $sent = $true; break }
        }
        if (-not $sent) { throw 'Enter を押しても入力欄から文が消えません。送れたか、画面を確かめてください。' }
    } finally {
        try { if ($null -ne $saved) { [System.Windows.Forms.Clipboard]::SetDataObject($saved, $true) } else { [System.Windows.Forms.Clipboard]::Clear() } } catch { }
        if ($previous -ne [IntPtr]::Zero -and $previous -ne $hwnd) { Set-Front $previous $true | Out-Null }
    }
    Out-Result @{ ok = $true; conversation = $doc.Current.Name }
} catch {
    Out-Result @{ ok = $false; error = $_.Exception.Message }
}
