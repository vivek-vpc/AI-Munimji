# The whole flow of a request on demo data, to follow in the browser: puts the demo items on the development site (dev/scripts/seed_demo_flow.py: one item bought from three suppliers with
# different prices and delivery times, one of them late, with 90 days of usage; and one item with no supplier) and prints the walkthrough. Nothing is faked: the stock check is the button on the
# Settings page, the vendor comparison is the job that approving a reorder queues, the draft Purchase Order is made by the Approve button. Safe to run again.
#   .\dev\demo.ps1                  # seed (if needed) and print the walkthrough
#   .\dev\demo.ps1 -NoSeed          # only print it
#   .\dev\demo.ps1 -Run             # also walk through it in the container's headless browser as the three people and say how long each step took (pictures in /tmp/demo-shots)
#   .\dev\demo.ps1 -Suffix -B       # a second pair of items, MD-SCREW-M6-B and MD-GASKET-G1-B: an item that went through the flow is "ordered recently" and is not asked about again
# The development containers must be up (.\dev\up.ps1) and the bench running (.\dev\exec.ps1 bench start), with its worker: the comparison is a background job.
param([string]$Suffix = "", [switch]$NoSeed, [switch]$Run)
$ErrorActionPreference = "Continue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$exec = Join-Path $here "exec.ps1"
$screw = "MD-SCREW-M6$Suffix"
$gasket = "MD-GASKET-G1$Suffix"

try { $up = (Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8000/api/method/ping" -TimeoutSec 3).StatusCode -eq 200 } catch { $up = $false }
if (-not $up) { Write-Host "The bench does not answer on http://localhost:8000. Start it:  .\dev\exec.ps1 bench start   (it needs its worker: the vendor comparison is a background job)" -ForegroundColor Yellow }

if (-not $NoSeed) {
    Write-Host "Putting the demo items on the development site (a few minutes the first time, seconds after) ..." -ForegroundColor Cyan
    $seedArgs = @()
    if ($Suffix) { $seedArgs += $Suffix }
    & $exec bash /workspace/ai_munimji/dev/run-script.sh /workspace/ai_munimji/dev/scripts/seed_demo_flow.py @seedArgs
    if ($LASTEXITCODE -ne 0) { Write-Host "The demo data could not be made." -ForegroundColor Red; exit $LASTEXITCODE }
}

Write-Host @"

WALKTHROUGH (about five minutes; every step is the real flow)
Sign in at http://localhost:8000. The password of all three people is  Munimji-dev-1!
    munimji.manager@example.com    Manager: the settings and the stock check
    munimji.approver@example.com   Approver: answers requests; the draft Purchase Order is made in this person's name
    munimji.viewer@example.com     Viewer: reads the requests, cannot answer them

What the data is
    $screw   Screw M6 x 20: 40 on hand, about 5 days of stock, 90 days of usage; bought from three suppliers
                   Quick Fasteners Ltd      4.50 each, delivers in about 4 days, on time
                   Munimji Demo Supplier    5.30 each (the dearest), delivers in 2 to 3 days, on time
                   Bharat Bolt Traders      4.10 each (the cheapest), promises 5 days and delivers in 9 to 12: late every time
    $gasket  Gasket G1: 90 days of usage, 8 on hand, no supplier and no purchase history

1. As the MANAGER: open AI Munimji Settings. Under "The stock check" press "Run the check now".
       You see: "The stock check is queued and starts in a moment ..." and, a few seconds later, when the check ran, how far it got ("Finished") and how many requests it made.
       A second press while it is queued or running is refused, in a sentence. The check raises a Reorder request for the screw and one for the gasket.

2. As the APPROVER: open Munimji Approval Request and then "Reorder suggested: Screw M6 x 20 ($screw)".
       At the top is the Flow block:  Reorder request (you are here)  ->  Purchase request  ->  Draft Purchase Order. Each step is a link.

3. Press Approve, then Yes.
       You see: "Approved. The vendors are being compared; the purchase request will appear in Munimji Approval Request in about a minute."
       The Flow block says "Being made" and fills in by itself, without a reload: the request appears within seconds (the job takes about two; the block asks again every five).

4. Follow the link to the purchase request.
       Munimji Demo Supplier is recommended: the dearest, but it delivers in about two days and has always been on time. Quick Fasteners Ltd comes second (cheaper, four days). Bharat Bolt Traders,
       the cheapest, is explained as not chosen: it arrives too late, after the stock runs out, and its on-time record is 0%.

5. Press Approve ("Create order"), then Yes.
       You see: "Draft Purchase Order PUR-ORD-... made. Review and submit it in ERPNext." The number is a link. Reload the request: the number is still there, in the Flow block (step 3).

6. Open the Purchase Order: it is a Draft, with the supplier, the price and the approver's name on it. Review it and submit it in ERPNext as you would. Nothing has been sent to the vendor.

7. The gasket: open its Reorder request and Approve it.
       The request that appears says that no vendor could be compared (no supplier, no purchase history) and what to do: order it in ERPNext by hand, then press "Got it". Press "Got it":
       "Marked as handled. Nothing was ordered from here ..."

8. Dismiss: on any request, "Dismiss" answers "Closed. Nothing was ordered."

If the approval does not lead to a purchase request within a minute, the Flow block says so and when the next scheduled check makes it (usually: no worker is running for the long queue).
"@

if ($Run) {
    Write-Host "Walking through it in the headless browser (the manager, then the approver) ..." -ForegroundColor Cyan
    & $exec bash -c "cd /workspace/ai_munimji/dev/browser && SCREW=$screw GASKET=$gasket node demo-flow.cjs"
    exit $LASTEXITCODE
}
