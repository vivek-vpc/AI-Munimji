# The approval round trip over HTTP, as the browser's "Create Purchase Order" button does it (a session login, the CSRF token, run_doc_method).
# The bench must be running (.\dev\exec.ps1 bench start) and the dev site seeded (dev\scripts\seed.py).
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

# what the button sends: frm.call({doc, method}) -> POST /api/method/run_doc_method
function Press-Button($who, $request) {
    $body = @{ docs = ($request | ConvertTo-Json -Depth 10 -Compress); method = "create_draft_purchase_order" }
    try {
        $r = Invoke-RestMethod -Method Post -Uri "$Base/api/method/run_doc_method" -Body $body -WebSession $who.Session -Headers @{ "X-Frappe-CSRF-Token" = $who.Token }
        return @{ Ok = $true; Message = $r.message; Status = 200 }
    } catch {
        $status = [int]$_.Exception.Response.StatusCode
        $detail = ""
        try { $detail = ($_.ErrorDetails.Message | ConvertFrom-Json).exc_type } catch { }
        return @{ Ok = $false; Message = $detail; Status = $status }
    }
}

Write-Host "1. The approver signs in and looks at the requests the job made"
$approver = Login "munimji.approver@example.com"
$pending = (Invoke-RestMethod -Uri "$Base/api/resource/Munimji%20Approval%20Request?filters=%5B%5B%22status%22,%22=%22,%22Pending%22%5D%5D&fields=%5B%22name%22,%22item_code%22,%22qty%22%5D&order_by=name%20asc" -WebSession $approver.Session).data
Check ($pending.Count -ge 2) "at least two requests are Pending ($($pending.Count) found: $(($pending | ForEach-Object { $_.name + ' ' + $_.item_code + ' x ' + $_.qty }) -join '; '))"
$first, $second = $pending[0].name, $pending[1].name

Write-Host "2. The viewer presses the button on ${first}: refused"
$viewer = Login "munimji.viewer@example.com"
$r = Press-Button $viewer (Get-Doc $viewer "Munimji Approval Request" $first)
Check ((-not $r.Ok) -and $r.Status -eq 403) "HTTP $($r.Status) $($r.Message)"
Check ((Get-Doc $approver "Munimji Approval Request" $first).status -eq "Pending") "the request is still Pending"

Write-Host "3. The approver presses the button on ${first}"
$r = Press-Button $approver (Get-Doc $approver "Munimji Approval Request" $first)
Check $r.Ok "a draft order was made: $($r.Message)"
if ($r.Ok) {
    $order = Get-Doc $approver "Purchase Order" $r.Message
    Check ($order.docstatus -eq 0) "it is a draft (docstatus $($order.docstatus))"
    Check ($order.custom_agent_ref -eq $first) "it carries the request: custom_agent_ref = $($order.custom_agent_ref)"
    Check ($order.supplier -eq "Munimji Demo Supplier" -and $order.items[0].qty -eq $pending[0].qty) "supplier and quantity are the request's ($($order.supplier), $($order.items[0].qty))"
    Check ($order.custom_agent_approved_by -eq "$($approver.User) via desk") "it carries the approver, in the standalone service's form of words: $($order.custom_agent_approved_by)"
    Check ($order.owner -eq $approver.User) "it was created by the signed-in user: owner = $($order.owner)"
    $request = Get-Doc $approver "Munimji Approval Request" $first
    Check ($request.status -eq "Ordered" -and $request.purchase_order -eq $order.name) "the request is Ordered and points at $($request.purchase_order)"
}

Write-Host "4. The approver presses it again: refused, no second order"
$r2 = Press-Button $approver (Get-Doc $approver "Munimji Approval Request" $first)
Check ((-not $r2.Ok) -and $r2.Status -ge 400) "HTTP $($r2.Status) $($r2.Message)"
$orders = (Invoke-RestMethod -Uri "$Base/api/resource/Purchase%20Order?filters=%5B%5B%22custom_agent_ref%22,%22=%22,%22$first%22%5D%5D" -WebSession $approver.Session).data
Check ($orders.Count -eq 1) "exactly one order carries $first ($($orders.Count))"

Write-Host ""
if ($failed -eq 0) { Write-Host "Round trip: all checks passed. $second is still Pending for you to try in the browser." -ForegroundColor Green } else { Write-Host "Round trip: $failed check(s) failed." -ForegroundColor Red }
exit $failed
