# The approval round trip over HTTP, as the browser's "Create Purchase Order" button does it (a session login, the CSRF token, POST ai_munimji.api.answer).
# The bench must be running (.\dev\exec.ps1 bench start) and the dev site seeded (dev\scripts\seed.py, dev\scripts\reset_demo.py).
#   .\dev\roundtrip.ps1
param([string]$Base = "http://localhost:8000", [string]$Password = "Munimji-dev-1!")
$ErrorActionPreference = "Stop"
$failed = 0

function Check($ok, $what) { if ($ok) { Write-Host "  PASS  $what" } else { Write-Host "  FAIL  $what" -ForegroundColor Red; $script:failed++ } }

function Login($user) {
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    Invoke-RestMethod -Method Post -Uri "$Base/api/method/login" -Body @{ usr = $user; pwd = $Password } -WebSession $session | Out-Null
    $page = Invoke-WebRequest -UseBasicParsing -Uri "$Base/app" -WebSession $session
    $token = [regex]::Match($page.Content, 'csrf_token\s*=\s*"([^"]+)"').Groups[1].Value
    return @{ Session = $session; Token = $token; User = $user }
}

function Get-Doc($who, $doctype, $name) {
    (Invoke-RestMethod -Uri "$Base/api/resource/$([uri]::EscapeDataString($doctype))/$([uri]::EscapeDataString($name))" -WebSession $who.Session).data
}

# what the button sends: frappe.call({method: "ai_munimji.api.answer", args: {approval_id, action: "approve"}}). The engine answers 200 with ok true or false and a status word.
function Press-Button($who, $name) {
    try {
        $r = Invoke-RestMethod -Method Post -Uri "$Base/api/method/ai_munimji.api.answer" -Body @{ approval_id = $name; action = "approve" } -WebSession $who.Session -Headers @{ "X-Frappe-CSRF-Token" = $who.Token }
        return @{ Ok = [bool]$r.message.ok; Message = $r.message.message; Answer = $r.message.status; Status = 200 }
    } catch {
        $status = [int]$_.Exception.Response.StatusCode
        $detail = ""
        try { $detail = ($_.ErrorDetails.Message | ConvertFrom-Json).exc_type } catch { }
        return @{ Ok = $false; Message = $detail; Answer = "http $status"; Status = $status }
    }
}

# the proposal behind a request, which knows the order made from it
function Get-Proposal($who, $request) {
    $filters = [uri]::EscapeDataString(('[["approval_id","=","{0}"]]' -f $request))
    $fields = [uri]::EscapeDataString('["name","po_name","qty","supplier"]')
    (Invoke-RestMethod -Uri "$Base/api/resource/Munimji%20Purchase%20Proposal?filters=$filters&fields=$fields" -WebSession $who.Session).data[0]
}

Write-Host "1. The approver signs in and looks at the purchase requests the job made"
$approver = Login "munimji.approver@example.com"
$filters = [uri]::EscapeDataString('[["status","=","pending"],["kind","=","procurement.po"]]')
$fields = [uri]::EscapeDataString('["name","item_code","qty"]')
$pending = (Invoke-RestMethod -Uri "$Base/api/resource/Munimji%20Approval%20Request?filters=$filters&fields=$fields&order_by=creation%20asc" -WebSession $approver.Session).data
Check ($pending.Count -ge 2) "at least two purchase requests are pending ($($pending.Count) found: $(($pending | ForEach-Object { $_.name + ' ' + $_.item_code + ' x ' + $_.qty }) -join '; '))"
$first, $second = $pending[0].name, $pending[1].name

Write-Host "2. The viewer presses the button on ${first}: refused"
$viewer = Login "munimji.viewer@example.com"
$r = Press-Button $viewer $first
Check ((-not $r.Ok) -and $r.Answer -eq "forbidden") "answer '$($r.Answer)': $($r.Message)"
Check ((Get-Doc $approver "Munimji Approval Request" $first).status -eq "pending") "the request is still pending"

Write-Host "3. The approver presses the button on ${first}"
$r = Press-Button $approver $first
Check $r.Ok "the engine answered: $($r.Message)"
if ($r.Ok) {
    $proposal = Get-Proposal $approver $first
    Check ([bool]$proposal.po_name) "the proposal behind the request says which order was made: $($proposal.po_name)"
    $order = Get-Doc $approver "Purchase Order" $proposal.po_name
    Check ($order.docstatus -eq 0) "it is a draft (docstatus $($order.docstatus))"
    Check ($order.custom_agent_ref -eq $proposal.name) "it carries the proposal: custom_agent_ref = $($order.custom_agent_ref)"
    Check ($order.supplier -eq "Munimji Demo Supplier" -and $order.items[0].qty -eq $proposal.qty) "supplier and quantity are the proposal's ($($order.supplier), $($order.items[0].qty))"
    Check ($order.custom_agent_approved_by -like "$($approver.User) via*") "it carries the approver, in the standalone service's form of words: $($order.custom_agent_approved_by)"
    Check ($order.owner -eq $approver.User) "it was created by the signed-in user: owner = $($order.owner)"
    $request = Get-Doc $approver "Munimji Approval Request" $first
    Check ($request.status -eq "decided" -and $request.answer -eq "approve") "the request is decided: $($request.status), answer $($request.answer), by $($request.approver)"
}

Write-Host "4. The approver presses it again: refused, no second order"
$r2 = Press-Button $approver $first
Check ((-not $r2.Ok) -and $r2.Answer -eq "already_decided") "answer '$($r2.Answer)': $($r2.Message)"
if ($proposal) {
    $orders = (Invoke-RestMethod -Uri "$Base/api/resource/Purchase%20Order?filters=$([uri]::EscapeDataString(('[["custom_agent_ref","=","{0}"]]' -f $proposal.name)))" -WebSession $approver.Session).data
    Check ($orders.Count -eq 1) "exactly one order carries $($proposal.name) ($($orders.Count))"
}

Write-Host ""
if ($failed -eq 0) { Write-Host "Round trip: all checks passed. $second is still pending for you to try in the browser." -ForegroundColor Green } else { Write-Host "Round trip: $failed check(s) failed." -ForegroundColor Red }
exit $failed
