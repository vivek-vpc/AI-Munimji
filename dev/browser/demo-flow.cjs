// Follows the whole flow of a request in the real Desk, in the container's headless Chromium, as the people the walkthrough names (dev/demo.ps1 prints it), and says how long each step took.
// Nothing is faked: the stock check is the Run the check now button, the vendor comparison is the job the approval queues, the draft Purchase Order is made by the Approve button.
//   .\dev\exec.ps1 bash -c "cd /workspace/ai_munimji/dev/browser && node demo-flow.cjs"
// Needs the bench running (bench start, with a worker) and the demo data (dev\scripts\seed_demo_flow.py): MD-SCREW-M6 (three suppliers, one late) and MD-GASKET-G1 (no supplier);
// SCREW and GASKET name another pair (seed_demo_flow.py -B makes MD-SCREW-M6-B and MD-GASKET-G1-B).
// Pictures of each step go to $SHOTS (default /tmp/demo-shots).
const fs = require("fs");
const puppeteer = require("puppeteer-core");

const BASE = process.env.BASE || "http://localhost:8000";
const PASSWORD = process.env.PASSWORD || "Munimji-dev-1!";
const SHOTS = process.env.SHOTS || "/tmp/demo-shots";
const SCREW = process.env.SCREW || "MD-SCREW-M6";
const GASKET = process.env.GASKET || "MD-GASKET-G1";
fs.mkdirSync(SHOTS, { recursive: true });

let failed = 0;
const timings = [];
const check = (ok, what) => {
  console.log((ok ? "  PASS  " : "  FAIL  ") + what);
  if (!ok) failed++;
};
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const seconds = (since) => Math.round((Date.now() - since) / 100) / 10;
const note = (step, took, what) => {
  timings.push({ step, seconds: took, what });
  console.log(
    `  TIME  ${took.toFixed(1)} s  ${step}${what ? ": " + what : ""}`
  );
};

async function signIn(browser, user) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
  await page.type("#login_email", user);
  await page.type("#login_password", PASSWORD);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle0" }),
    page.keyboard.press("Enter"),
  ]);
  return page;
}

const shot = (page, name) =>
  page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

const api = (page, path) =>
  page.evaluate(async (p) => (await (await fetch(p)).json()).data, path);

const requestsOf = (page, item, kind, status) =>
  api(
    page,
    `/api/resource/Munimji Approval Request?filters=${encodeURIComponent(
      JSON.stringify([
        ["item_code", "=", item],
        ["kind", "=", kind],
        ["status", "=", status],
      ])
    )}&fields=${encodeURIComponent(
      JSON.stringify(["name", "created_at", "decided_at", "title"])
    )}&order_by=creation desc`
  );

async function openForm(page, slug, name, field) {
  await page.goto(`${BASE}/app/${slug}/${encodeURIComponent(name)}`, {
    waitUntil: "networkidle0",
  });
  await page.waitForSelector(`[data-fieldname="${field}"]`, { timeout: 30000 });
  await pause(600);
}

const textOf = (page, field) =>
  page.$eval(`[data-fieldname="${field}"]`, (e) => e.innerText).catch(() => "");

async function press(page, label) {
  await page.waitForFunction(
    (text) =>
      [...document.querySelectorAll("button")].some(
        (b) => b.textContent.trim() === text && b.offsetParent
      ),
    { timeout: 30000 },
    label
  );
  await page.evaluate(
    (text) =>
      [...document.querySelectorAll("button")]
        .find((b) => b.textContent.trim() === text && b.offsetParent)
        .click(),
    label
  );
}

async function confirmYes(page) {
  await page.waitForSelector(".modal-dialog .btn-modal-primary", {
    visible: true,
    timeout: 20000,
  });
  await page.click(".modal-dialog .btn-modal-primary"); // Yes
}

// the sentence the Desk shows after an answer (a toast: Frappe 16's .es-toast), with its links
async function toast(page, pattern) {
  await page.waitForFunction(
    (source) =>
      [...document.querySelectorAll(".es-toast")].some((e) =>
        new RegExp(source).test(e.innerText)
      ),
    { timeout: 30000 },
    pattern.source
  );
  return page.evaluate((source) => {
    const found = [...document.querySelectorAll(".es-toast")].find((e) =>
      new RegExp(source).test(e.innerText)
    );
    return {
      text: found.querySelector(".es-toast__message").innerText.trim(),
      links: [...found.querySelectorAll("a")].map((a) =>
        a.getAttribute("href")
      ),
    };
  }, pattern.source);
}

const flowHasPurchaseRequest = (page) =>
  page.waitForFunction(
    () => {
      const flow = document.querySelector('[data-fieldname="flow"]');
      return (
        flow &&
        flow.querySelectorAll('a[href*="/app/munimji-approval-request/"]')
          .length >= 2
      );
    },
    { timeout: 180000, polling: 250 }
  );

(async () => {
  const browser = await puppeteer.launch({
    executablePath: "/usr/bin/chromium-headless-shell",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
  });
  try {
    // ---------------------------------------------------------------- 0. the manager runs the stock check
    console.log(
      "0. munimji.manager@example.com presses Run the check now on AI Munimji Settings"
    );
    const manager = await signIn(browser, "munimji.manager@example.com");
    await openForm(
      manager,
      "ai-munimji-settings",
      "AI Munimji Settings",
      "check_status"
    );
    const before = await textOf(manager, "check_status");
    check(
      await manager.$('button[data-fieldname="run_check_now"]'),
      "the button is on the page for a Munimji Manager"
    );
    let t0 = Date.now();
    await press(manager, "Run the check now");
    const queued = await toast(manager, /stock check/i);
    check(/queued/i.test(queued.text), `the page says: ${queued.text}`);
    await manager.waitForFunction(
      (was) => {
        const now =
          document.querySelector('[data-fieldname="check_status"]')
            ?.innerText || "";
        return (
          now !== was &&
          /Requests it made/.test(now) &&
          !/A stock check is/.test(now)
        );
      },
      { timeout: 300000, polling: 500 },
      before
    );
    const status = await textOf(manager, "check_status");
    note(
      "0. the stock check, from the button to Finished",
      seconds(t0),
      status.replace(/\s+/g, " ")
    );
    check(
      /Finished/.test(status) && /Requests it made/.test(status),
      "the page shows when it ran, how far it got and how many requests it made"
    );
    await shot(manager, "0-settings-after-the-check");
    const second = await manager.evaluate(
      async () =>
        (
          await (
            await fetch("/api/method/ai_munimji.api.run_check_now", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "X-Frappe-CSRF-Token": frappe.csrf_token,
              },
            })
          ).json()
        ).message
    );
    check(
      second && /^(queued|queued_already|running)$/.test(second.status),
      `a press straight after is answered in words: ${second && second.message}`
    );

    // ---------------------------------------------------------------- 1. the approver opens the reorder request
    console.log(
      "1. munimji.approver@example.com opens the reorder request for the screw"
    );
    const approver = await signIn(browser, "munimji.approver@example.com");
    const [reorder] = await requestsOf(
      approver,
      SCREW,
      "inventory.reorder",
      "pending"
    );
    check(reorder, `a reorder request is waiting: ${reorder && reorder.title}`);
    await openForm(approver, "munimji-approval-request", reorder.name, "flow");
    let flow = await textOf(approver, "flow");
    check(
      /Reorder request/.test(flow) &&
        /You are here/.test(flow) &&
        /Waiting for an answer/.test(flow),
      "the Flow block shows the three steps and marks the reorder request"
    );
    check(
      /Made after the reorder is approved/.test(flow),
      "and says the purchase request comes after the approval"
    );
    await shot(approver, "1-reorder-request");

    // ---------------------------------------------------------------- 2. approve the reorder: the purchase request appears
    console.log("2. the approver presses Approve on the reorder request");
    await press(approver, "Approve");
    await confirmYes(approver);
    t0 = Date.now();
    const said = await toast(approver, /Approved/);
    note("2a. the sentence after the answer", seconds(t0), said.text);
    check(
      said.text ===
        "Approved. The vendors are being compared; the purchase request will appear in Munimji Approval Request in about a minute.",
      "the sentence says what happens next and where to look"
    );
    await pause(1500);
    // (a dialog titled Confirm may still be fading out in the headless browser; a "Message" dialog is Frappe showing the server's messages, which the answer must not leave)
    const messages = await approver.evaluate(() =>
      [...document.querySelectorAll(".modal.show")]
        .filter((m) =>
          /Message/.test(m.querySelector(".modal-title")?.innerText || "")
        )
        .map((m) => m.innerText.trim().slice(0, 200))
    );
    check(
      messages.length === 0,
      "no pop-up of messages stands over the sentence" +
        (messages.length ? `: ${messages[0]}` : "")
    );
    flow = await textOf(approver, "flow");
    check(
      /Being made/.test(flow) || /Waiting for an answer/.test(flow),
      "the Flow block says the purchase request is being made (or is already there)"
    );
    await shot(approver, "2-being-made");
    await flowHasPurchaseRequest(approver);
    const seen = seconds(t0);
    const [purchase] = await requestsOf(
      approver,
      SCREW,
      "procurement.po",
      "pending"
    );
    const [decided] = await api(
      approver,
      `/api/resource/Munimji Approval Request?filters=${encodeURIComponent(
        JSON.stringify([["name", "=", reorder.name]])
      )}&fields=${encodeURIComponent(JSON.stringify(["decided_at"]))}`
    );
    const server =
      (Date.parse(purchase.created_at.replace(" ", "T")) -
        Date.parse(decided.decided_at.replace(" ", "T"))) /
      1000;
    note(
      "2b. from the approval until the purchase request is on the screen",
      seen,
      "no reload: the Flow block asked again by itself"
    );
    note(
      "2c. from the approval until the purchase request was made (the records' own times)",
      server,
      purchase.title
    );
    check(purchase, "the purchase request exists");
    await shot(approver, "2-purchase-request-appeared");

    // ---------------------------------------------------------------- 3. the purchase request
    console.log("3. the approver follows the link to the purchase request");
    t0 = Date.now();
    await openForm(
      approver,
      "munimji-approval-request",
      purchase.name,
      "reasoning"
    );
    note("3. the purchase request opens", seconds(t0));
    const why = await textOf(approver, "reasoning");
    flow = await textOf(approver, "flow");
    check(
      /Why this vendor/.test(why) &&
        /The other vendors, and why they were not chosen/.test(why),
      "it says why this vendor and why the others were not chosen"
    );
    check(
      /Bharat Bolt Traders/.test(why) &&
        /Quick Fasteners Ltd/.test(why) &&
        /Munimji Demo Supplier/.test(why),
      "all three suppliers are compared"
    );
    check(
      /late|too late|on time/i.test(why),
      "the late supplier is called late"
    );
    check(
      /You are here/.test(flow) && /Step 2 of 3/.test(flow),
      "the Flow block marks the purchase request, with a link back to the reorder request"
    );
    console.log(
      "  VENDOR  " +
        why
          .split("\n")
          .filter((l) => /Bharat|Quick|Munimji Demo|recommend|score/i.test(l))
          .slice(0, 8)
          .join(" | ")
    );
    await shot(approver, "3-purchase-request");

    // ---------------------------------------------------------------- 4. approve the purchase request
    console.log("4. the approver presses Approve on the purchase request");
    await press(approver, "Approve");
    await confirmYes(approver);
    t0 = Date.now();
    const made = await toast(approver, /Draft Purchase Order/);
    note(
      "4a. from the approval until the draft Purchase Order is named",
      seconds(t0),
      made.text
    );
    const orderLink = made.links.find((href) =>
      /\/app\/purchase-order\//.test(href)
    );
    check(
      /^Draft Purchase Order \S+ made\. Review and submit it in ERPNext\.$/.test(
        made.text
      ),
      "the sentence names the draft order and says what to do"
    );
    check(orderLink, `the number is a link: ${orderLink}`);
    await shot(approver, "4-draft-order-made");
    await approver.goto(
      `${BASE}/app/munimji-approval-request/${purchase.name}`,
      { waitUntil: "networkidle0" }
    );
    await approver.waitForSelector(
      '[data-fieldname="flow"] a[href*="/app/purchase-order/"]',
      { timeout: 20000 }
    );
    flow = await textOf(approver, "flow");
    check(
      orderLink &&
        flow.includes(decodeURIComponent(orderLink.split("/").pop())),
      "after a reload the approved request still shows the draft order's number"
    );
    await shot(approver, "4-after-reload");
    t0 = Date.now();
    await approver.goto(`${BASE}${orderLink}`, { waitUntil: "networkidle0" });
    await approver.waitForSelector(".page-indicator-pill", { timeout: 30000 });
    const pill = await approver.$eval(".page-indicator-pill", (e) =>
      e.innerText.trim()
    );
    note(
      "4b. the draft Purchase Order opens in ERPNext",
      seconds(t0),
      `${orderLink.split("/").pop()} is ${pill}`
    );
    check(
      /Draft/i.test(pill),
      `ERPNext shows it as a draft (${pill}), not submitted`
    );
    await shot(approver, "4-purchase-order");

    // ---------------------------------------------------------------- 5. an item with no vendor history
    console.log(
      "5. the approver approves the reorder for the gasket, which has no supplier and no purchase history"
    );
    const [gasket] = await requestsOf(
      approver,
      GASKET,
      "inventory.reorder",
      "pending"
    );
    check(gasket, `a reorder request is waiting: ${gasket && gasket.title}`);
    await openForm(approver, "munimji-approval-request", gasket.name, "flow");
    await press(approver, "Approve");
    await confirmYes(approver);
    t0 = Date.now();
    await toast(approver, /Approved/);
    await flowHasPurchaseRequest(approver);
    flow = await textOf(approver, "flow");
    note(
      "5a. from the approval until the request for the gasket is on the screen",
      seconds(t0)
    );
    check(
      /No vendor could be compared for this item, so no purchase request was made\./.test(
        flow
      ),
      "the Flow block says no comparison was possible"
    );
    await shot(approver, "5-no-history-flow");
    const [manual] = await requestsOf(
      approver,
      GASKET,
      "procurement.manual",
      "pending"
    );
    await openForm(approver, "munimji-approval-request", manual.name, "flow");
    flow = await textOf(approver, "flow");
    check(
      /What to do: order it in ERPNext by hand, then press “Got it” on that request\./.test(
        flow
      ),
      "and what to do: order it in ERPNext by hand, then press Got it"
    );
    await shot(approver, "5-manual-request");
    await press(approver, "Got it");
    await confirmYes(approver);
    const handled = await toast(approver, /Marked as handled/);
    check(
      /order it in ERPNext by hand/.test(handled.text),
      `Got it is answered in words: ${handled.text}`
    );

    console.log("\nTimes:");
    for (const t of timings)
      console.log(`  ${t.seconds.toFixed(1).padStart(6)} s  ${t.step}`);
  } catch (error) {
    failed++;
    console.log("  FAIL  " + error.message);
  } finally {
    await browser.close();
  }
  console.log(failed ? `\n${failed} FAILED` : "\nALL PASSED");
  process.exit(failed ? 1 : 0);
})();
