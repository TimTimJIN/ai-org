$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
    Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
    $req = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($req.action -ne 'read') { throw 'Native sending is disabled pending live validation.' }
    $scope = [System.Windows.Automation.TreeScope]::Descendants
    $all = [System.Windows.Automation.Condition]::TrueCondition
    function Elements($root) { return $root.FindAll($scope, $all) }
    function Pattern($element, $id) {
        $value = $null
        if ($element.TryGetCurrentPattern($id, [ref]$value)) { return $value }
        return $null
    }
    function Text($element) {
        $p = Pattern $element ([System.Windows.Automation.TextPattern]::Pattern)
        if ($null -eq $p) { throw 'TextPattern unavailable; stopped without guessing.' }
        return $p.DocumentRange.GetText(-1)
    }
    $processName = if ($req.kind -eq 'claude') { 'Claude' } elseif ($req.kind -eq 'chatgpt') { 'ChatGPT' } else { throw 'Unknown provider' }
    $windows = @(Get-Process -Name $processName -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 })
    if ($windows.Count -ne 1) { throw 'Open exactly one window of the selected app.' }
    $window = [System.Windows.Automation.AutomationElement]::FromHandle($windows[0].MainWindowHandle)
    $nodes = @(Elements $window)
    $docs = @($nodes | Where-Object { $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Document })
    $docs = @($docs | Where-Object {
        if ($req.kind -eq 'claude') {
            $v = Pattern $_ ([System.Windows.Automation.ValuePattern]::Pattern)
            $null -ne $v -and $v.Current.Value -ceq $req.target
        } else { $_.Current.Name -ceq $req.target }
    })
    if ($docs.Count -ne 1) { throw 'Conversation identity does not match. Open the selected chat.' }
    $doc = $docs[0]
    $nodes = @(Elements $doc)
    $edits = @($nodes | Where-Object {
        $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Edit -and
        $_.Current.Name -match 'Claude へのプロンプト|Write|Message|メッセージ|Work モードで作成|何でも聞いて'
    })
    if ($edits.Count -ne 1) { throw 'Cannot uniquely identify the message editor.' }
    $editor = $edits[0]
    $value = Pattern $editor ([System.Windows.Automation.ValuePattern]::Pattern)
    if ($null -eq $value) { throw 'Editor does not expose ValuePattern. No unsafe fallback is used.' }
    $draft = $value.Current.Value
    # Some Chromium providers expose placeholder as value. Do NOT silently treat it as empty.
    $busy = @($nodes | Where-Object {
        $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
        $_.Current.Name -match '^(応答を停止|停止|Stop|Stop generating|Stop response)$'
    }).Count -gt 0
    $turns = [System.Collections.Generic.List[object]]::new()
    if ($req.kind -eq 'claude') {
        # Article boundaries are supplied by Claude's accessibility provider.
        $articles = @($nodes | Where-Object { $_.Current.LocalizedControlType -match '記事|article' -and $_.Current.Name -match 'メッセージ|message' })
        foreach ($article in $articles) {
            $children = @(Elements $article)
            $heading = @($children | Where-Object { $_.Current.Name -match '^(あなたの入力:|Claude の応答：|You said:|Claude said:)' }) | Select-Object -First 1
            if ($null -eq $heading) { continue }
            $role = if ($heading.Current.Name -match '^(あなたの入力:|You said:)') { 'user' } else { 'assistant' }
            # Prefer accessible text elements, excluding headings, buttons, and reasoning panels.
            $parts = @($children | Where-Object {
                $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Text -and
                $_.Current.Name -notmatch '^(あなたの入力:|Claude の応答：|You said:|Claude said:)' -and
                $_.Current.LocalizedControlType -notmatch '見出し|heading|日時|date'
            } | ForEach-Object { $_.Current.Name })
            $turns.Add(@($role, ($parts -join "`n").Trim()))
        }
    } else {
        $main = @($nodes | Where-Object { $_.Current.LocalizedControlType -match '^メイン$|^main$' })
        if ($main.Count -ne 1) { throw 'Cannot identify ChatGPT main conversation.' }
        $role = $null; $parts = [System.Collections.Generic.List[string]]::new()
        foreach ($node in @(Elements $main[0])) {
            $name = $node.Current.Name
            if ($name -match '^(あなたの発言:|ChatGPT の発言:|You said:|ChatGPT said:)$') {
                if ($null -ne $role) { $turns.Add(@($role, ($parts -join "`n").Trim())) }
                $role = if ($name -match '^(あなた|You)') { 'user' } else { 'assistant' }
                $parts.Clear()
            } elseif ($null -ne $role -and $node.Current.ControlType -eq [System.Windows.Automation.ControlType]::Text -and
                      $node.Current.LocalizedControlType -notmatch '見出し|heading') { $parts.Add($name) }
        }
        if ($null -ne $role) { $turns.Add(@($role, ($parts -join "`n").Trim())) }
    }
    if ($turns.Count -eq 0) { throw 'No complete conversation turns recognized. Use an existing text-only chat.' }
    if ($req.action -eq 'send') {
        if (Test-Path -LiteralPath $req.stop_file) { throw 'Stopped before send.' }
        if ($busy -or -not [string]::IsNullOrWhiteSpace($draft)) { throw 'Busy or non-empty editor; stopped.' }
        $expected = ConvertTo-Json -InputObject @($req.expected_turns) -Depth 8 -Compress
        $actual = ConvertTo-Json -InputObject @($turns.ToArray()) -Depth 8 -Compress
        if ($expected -cne $actual) { throw 'Conversation changed since preflight; stopped.' }
        if ($value.Current.IsReadOnly) { throw 'Editor is read-only.' }
        $sendButtons = @($nodes | Where-Object {
            $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
            $_.Current.Name -match '^(メッセージを送信|送信|Send|Send message|Send prompt)$'
        })
        # Button may be absent until text is entered. Fill only through the selected control.
        if (Test-Path -LiteralPath $req.stop_file) { throw 'Stopped before draft.' }
        $value.SetValue([string]$req.text)
        if ($value.Current.Value -cne $req.text) { throw 'Draft verification failed; inspect draft manually.' }
        $sendButtons = @(@(Elements $doc) | Where-Object {
            $_.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and
            $_.Current.Name -match '^(メッセージを送信|送信|Send|Send message|Send prompt)$' -and $_.Current.IsEnabled
        })
        if ($sendButtons.Count -ne 1) { throw 'Send button not unique; draft left unsent.' }
        $invoke = Pattern $sendButtons[0] ([System.Windows.Automation.InvokePattern]::Pattern)
        if ($null -eq $invoke) { throw 'Send button not invokable; draft left unsent.' }
        if (Test-Path -LiteralPath $req.stop_file) { throw 'Stopped; draft left unsent.' }
        $invoke.Invoke()
    } elseif ($req.action -ne 'read') { throw 'Unknown action' }
    @{ok=$true; target=$req.target; draft=$draft; busy=$busy; ready=$true; turns=@($turns.ToArray())} | ConvertTo-Json -Depth 10 -Compress
} catch {
    @{ok=$false; error=$_.Exception.Message} | ConvertTo-Json -Compress
    exit 1
}
