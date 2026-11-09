// Uses the real approval form in the Desk, in the container's headless Chromium: the request in words, who may answer, the draft order, the second answer.
//   .\dev\exec.ps1 bash -c "cd /workspace/ai_munimji/dev/browser && node round-trip.cjs"
// Needs the bench running (bench start) and the demo seeded with two pending purchase requests (dev\scripts\seed.py, then dev\scripts\reset_demo.py).
const puppeteer = require("puppeteer-core");

const BASE = process.env.BASE || "http://localhost:8000";
const PASSWORD = process.env.PASSWORD || "Munimji-dev-1!";
let failed = 0;
const check = (ok, what) => {
  console.log((ok ? "  PASS  " : "  FAIL  ") + what);
  if (!ok) failed++;
};
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

async function signIn(browser, user) {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
  await page.type("#login_email", user);
  await page.type("#login_password", PASSWORD);
  // Frappe v16's login button is `button.es-button` (v15's `.btn-login` is gone): pressing Enter in the password field works in both
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle0" }),
    page.keyboard.press("Enter"),
  ]);
  return page;
}

async function pendingRequests(page) {
  return page.evaluate(async () => {
    const filters = encodeURIComponent(
      JSON.stringify([
        ["status", "=", "pending"],
        ["kind", "=", "procurement.po"],
      ])
    );
    const r = await fetch(
      `/api/resource/Munimji Approval Request?filters=${filters}&order_by=creation asc&fields=["name","status","item_code","qty"]`
    );
    return (await r.json()).data;
  });
}

async function openRequest(page, name) {
  await page.goto(`${BASE}/app/munimji-approval-request/${name}`, {
    waitUntil: "networkidle0",
  });
  await page.waitForSelector('[data-fieldname="reasoning"]', {
    timeout: 20000,
  });
  await pause(800);
}

const reasoningText = (page) =>
  page.$eval('[data-fieldname="reasoning"]', (e) => e.innerText);

const visibleButtons = (page) =>
  page.evaluate(() =>
    [...document.querySelectorAll("button")]
      .filter((b) => b.offsetParent)
      .map((b) => b.textContent.trim())
  );

async function clickButton(page, label) {
  await page.waitForFunction(
    (text) =>
      [...document.querySelectorAll("button")].some(
        (b) => b.textContent.trim() === text && b.offsetParent
      ),
    { timeout: 20000 },
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

// what the form's buttons send: frappe.call({method: "ai_munimji.api.answer", args: {approval_id, action}})
const answerByApi = (page, name, action) =>
  page.evaluate(
    async (n, a) => {
      const r = await fetch("/api/method/ai_munimji.api.answer", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Frappe-CSRF-Token": frappe.csrf_token,
        },
        body: JSON.stringify({ approval_id: n, action: a }),
      });
      return { http: r.status, ...((await r.json()).message || {}) };
    },
    name,
    action
  );

const requestStatus = (page, name) =>
  page.evaluate(
    async (n) =>
      (
        await (
          await fetch(`/api/resource/Munimji Approval Request/${n}`)
        ).json()
      ).data.status,
    name
  );

(async () => {
  const browser = await puppeteer.launch({
    executablePath: "/usr/bin/chromium-headless-shell",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
  });
  try {
    console.log(
      "1. The approver opens a pending purchase request: the reasoning is on the form"
    );
    const approver = await signIn(browser, "munimji.approver@example.com");
    const [first, second] = await pendingRequests(approver);
    check(
      first && second,
      `two purchase requests are pending (${first && first.name}, ${
        second && second.name
      })`
    );
    await openRequest(approver, first.name);
    const why = await reasoningText(approver);
    check(
      /Waiting for your answer/.test(why),
      "the form says it is waiting for an answer"
    );
    check(
      new RegExp(first.item_code).test(why) && /Why this vendor/.test(why),
      `it names the item (${first.item_code}) and says why this vendor`
    );
    check(
      /The stock, and how long it lasts/.test(why) && /On hand/.test(why),
      "it shows the stock and how long it lasts"
    );
    check(
      /What is proposed, and what it costs/.test(why) &&
        /Expected delivery/.test(why),
      "the cost and the time to delivery"
    );
    check(
      /Duties and taxes|Taxes are not included in these totals/.test(why),
      "the tax figures, or the plain statement that taxes are not included"
    );
    check(
      /The other vendors, and why they were not chosen/.test(why) ||
        /Score .* the only vendor/.test(why),
      "the other vendors and why they lost (or that there are none to compare)"
    );
    check(
      /What each button does/.test(why) && /draft purchase order/i.test(why),
      "and what each button does, including the draft order that approving makes"
    );
    const approverButtons = await visibleButtons(approver);
    check(
      ["Approve", "Change quantity", "Change vendor", "Dismiss"].every((b) =>
        approverButtons.includes(b)
      ),
      `the approver has Approve, Change quantity, Change vendor and Dismiss (${approverButtons.join(
        ", "
      )})`
    );

    console.log(
      "2. The viewer opens the same request: reads it, cannot answer it"
    );
    const viewer = await signIn(browser, "munimji.viewer@example.com");
    await openRequest(viewer, first.name);
    check(
      /Why this vendor/.test(await reasoningText(viewer)),
      "the viewer can read the reasoning"
    );
    const viewerButtons = await visibleButtons(viewer);
    check(
      !["Approve", "Change quantity", "Change vendor", "Dismiss"].some((b) =>
        viewerButtons.includes(b)
      ),
      "and sees no button to answer with"
    );
    const refused = await answerByApi(viewer, first.name, "approve");
    check(
      refused.ok === false && refused.status === "forbidden",
      `asked by hand, the server refuses: ${refused.status} (${refused.message})`
    );
    check(
      (await requestStatus(viewer, first.name)) === "pending",
      "the request is still pending"
    );

    console.log(
      "3. The approver approves: a draft Purchase Order exists, and a second press is refused"
    );
    await clickButton(approver, "Approve");
    await approver.waitForSelector(".modal-dialog .btn-modal-primary", {
      visible: true,
      timeout: 20000,
    });
    const question = await approver.$eval(".modal-dialog .modal-body", (e) =>
      e.textContent.trim()
    );
    check(
      /draft purchase order/i.test(question),
      `the dialog asks first: "${question}"`
    );
    await approver.click(".modal-dialog .btn-modal-primary"); // Yes
    await approver
      .waitForFunction(() => document.body.innerText.includes("PUR-ORD"), {
        timeout: 30000,
      })
      .catch(() => {});
    await pause(1500);
    const proposal = await approver.evaluate(async (name) => {
      const filters = encodeURIComponent(
        JSON.stringify([["approval_id", "=", name]])
      );
      const r = await fetch(
        `/api/resource/Munimji Purchase Proposal?filters=${filters}&fields=["name","po_name"]`
      );
      return (await r.json()).data[0];
    }, first.name);
    check(
      (await requestStatus(approver, first.name)) === "decided" &&
        !!proposal &&
        !!proposal.po_name,
      `the request is decided, order ${proposal && proposal.po_name}`
    );
    const order = await approver.evaluate(
      async (name) =>
        (
          await (await fetch(`/api/resource/Purchase Order/${name}`)).json()
        ).data,
      proposal.po_name
    );
    check(
      order.docstatus === 0 && order.custom_agent_ref === proposal.name,
      `a draft order with custom_agent_ref = ${order.custom_agent_ref}`
    );
    await openRequest(approver, first.name);
    check(
      !(await visibleButtons(approver)).includes("Approve") &&
        /Answered/.test(await reasoningText(approver)),
      "the decided request has no Approve button and says it was answered"
    );
    const again = await answerByApi(approver, first.name, "approve");
    check(
      again.ok === false &&
        again.status === "already_decided" &&
        /Already answered/.test(again.message),
      `a second press is refused: ${again.status} (${again.message})`
    );

    console.log(
      "4. Two people open the other request; the first answer wins and the second is told"
    );
    await openRequest(approver, second.name);
    const other = await signIn(browser, "munimji.approver@example.com");
    await openRequest(other, second.name);
    const first_answer = await answerByApi(other, second.name, "dismiss");
    check(
      first_answer.ok === true,
      `the first answer (dismiss) is taken: ${first_answer.message}`
    );
    await clickButton(approver, "Approve"); // this form was opened before, and still shows the buttons
    await approver.waitForSelector(".modal-dialog .btn-modal-primary", {
      visible: true,
      timeout: 20000,
    });
    await approver.click(".modal-dialog .btn-modal-primary");
    await approver
      .waitForFunction(() => /Not done/.test(document.body.innerText), {
        timeout: 20000,
      })
      .catch(() => {});
    const told = await approver.evaluate(() => document.body.innerText);
    check(
      /Not done/.test(told) && /Already answered|dismissed/i.test(told),
      "the second person is told: Not done, and who answered first"
    );
    check(
      (await requestStatus(approver, second.name)) === "dismissed" ||
        (await requestStatus(approver, second.name)) === "decided",
      "and the request keeps the first answer"
    );

    console.log(
      "5. A Munimji Manager opens AI Munimji Settings, and the viewer is refused"
    );
    const manager = await signIn(browser, "munimji.manager@example.com");
    await manager.goto(`${BASE}/app/ai-munimji-settings`, {
      waitUntil: "networkidle0",
    });
    await manager
      .waitForSelector(".form-layout", { timeout: 20000 })
      .catch(() => {});
    const settingsText = await manager.evaluate(() => document.body.innerText);
    check(
      /Watch stock/.test(settingsText) &&
        /When to ask for a purchase/.test(settingsText),
      "the manager sees the settings page: Watch stock, When to ask for a purchase"
    );
    check(
      /Demand calendar/.test(settingsText) &&
        /Requests waiting for an answer/.test(settingsText),
      "with its demand calendar and the time requests wait"
    );
    const stored = await manager.evaluate(
      async () =>
        (
          await (
            await fetch("/api/resource/AI Munimji Settings/AI Munimji Settings")
          ).json()
        ).data
    );
    check(
      stored && stored.name === "AI Munimji Settings",
      "and can read the page's values over the API"
    );
    // the stock monitor starts off, and the page says so while it is off (the demo has it on, as a person would after reviewing the thresholds)
    const setSwitch = (value) =>
      manager.evaluate(
        async (v) =>
          (
            await fetch(
              "/api/resource/AI Munimji Settings/AI Munimji Settings",
              {
                method: "PUT",
                headers: {
                  "Content-Type": "application/json",
                  "X-Frappe-CSRF-Token": frappe.csrf_token,
                },
                body: JSON.stringify({ enabled: v }),
              }
            )
          ).status,
        value
      );
    const intro =
      /Stock monitoring is off\. Review the thresholds below, then switch on Watch stock\./;
    check(
      !intro.test(settingsText),
      "while Watch stock is ticked the page carries no 'monitoring is off' note"
    );
    check(
      /Before you do, review/.test(settingsText),
      "and the switch says what to review before it is turned on"
    );
    check(
      (await setSwitch(0)) === 200,
      "the manager switches Watch stock off (this also stops the scheduled job)"
    );
    await manager.reload({ waitUntil: "networkidle0" });
    await manager
      .waitForSelector(".form-layout", { timeout: 20000 })
      .catch(() => {});
    check(
      intro.test(await manager.evaluate(() => document.body.innerText)),
      "and the page now says: Stock monitoring is off. Review the thresholds below, then switch on Watch stock."
    );
    check(
      (await setSwitch(1)) === 200,
      "the manager switches it on again (the demo needs it on)"
    );
    await manager.reload({ waitUntil: "networkidle0" });
    await manager
      .waitForSelector(".form-layout", { timeout: 20000 })
      .catch(() => {});
    check(
      !intro.test(await manager.evaluate(() => document.body.innerText)),
      "and the note is gone"
    );
    await viewer.goto(`${BASE}/app/ai-munimji-settings`, {
      waitUntil: "networkidle0",
    });
    await pause(2000);
    const refusedText = await viewer.evaluate(() => document.body.innerText);
    check(
      !/Watch stock/.test(refusedText) &&
        /not permitted|permission|Insufficient/i.test(refusedText),
      "the viewer is told they are not permitted, and sees none of the values"
    );
    const viewerApi = await viewer.evaluate(
      async () =>
        (
          await fetch("/api/resource/AI Munimji Settings/AI Munimji Settings")
        ).status
    );
    check(
      viewerApi === 403,
      `and the API says 403 to the viewer (${viewerApi})`
    );
  } catch (error) {
    console.log("  FAIL  " + error.message);
    failed++;
  } finally {
    await browser.close();
  }
  console.log(
    failed === 0
      ? "\nBrowser round trip: all checks passed."
      : `\nBrowser round trip: ${failed} check(s) failed.`
  );
  process.exit(failed ? 1 : 0);
})();
