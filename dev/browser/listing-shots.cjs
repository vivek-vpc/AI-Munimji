// Takes the pictures for the Marketplace listing (docs/LISTING.md, section 4, pictures 1 to 9) in the real Desk of a development site, following one request through its whole flow as a person does:
// the reorder, Approve, the purchase request the vendor comparison makes, its "other vendors" block, the Change quantity dialog, Approve again, and the Draft Purchase Order that results.
// Nothing is faked, and the pages are photographed without a browser frame (the page only), in the light theme.
//
//   cd dev/browser && npm install && node listing-shots.cjs
//
// Needs: a site with the history loaded and the stock check run (a pending reorder for ITEM), a worker for the long queue, and Chrome.
// Each step looks at what is on the site and does what is left: a reorder still waiting is photographed and approved; a purchase request that waits is approved; one that was decided is only photographed.
// Environment: BASE (http://127.0.0.1:8002), DESK_USER (Administrator), DESK_PASSWORD, ITEM (ELC-CBL-25), VENDORS_ITEM (STL-PIPE-25: the item whose purchase request is used for the pictures of the
// other vendors and the Change quantity dialog, when it has one waiting: it compares four vendors), SHOTS (./shots), CHROME (the path of chrome.exe).
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const BASE = process.env.BASE || "http://127.0.0.1:8002";
const DESK_USER = process.env.DESK_USER || "Administrator";
const DESK_PASSWORD = process.env.DESK_PASSWORD || "admin";
const ITEM = process.env.ITEM || "ELC-CBL-25";
const VENDORS_ITEM = process.env.VENDORS_ITEM || "STL-PIPE-25";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
const CHROME =
  process.env.CHROME ||
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
fs.mkdirSync(SHOTS, { recursive: true });

const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = async (page, name) => {
  await pause(700);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  console.log("  picture:", name);
};

const api = (page, resource, filters, fields) =>
  page.evaluate(
    async (resource, filters, fields) => {
      const url =
        `/api/resource/${resource}?filters=${encodeURIComponent(
          JSON.stringify(filters)
        )}` +
        `&fields=${encodeURIComponent(
          JSON.stringify(fields)
        )}&order_by=creation desc&limit_page_length=50`;
      return (await (await fetch(url)).json()).data || [];
    },
    resource,
    filters,
    fields
  );

const requests = (page, item, kind, status) =>
  api(
    page,
    "Munimji Approval Request",
    [
      ["item_code", "=", item],
      ["kind", "=", kind],
      ["status", "=", status],
    ],
    ["name"]
  );

async function open(page, route, waitFor) {
  await page.goto(`${BASE}${route}`, { waitUntil: "networkidle0" });
  if (waitFor) await page.waitForSelector(waitFor, { timeout: 30000 });
  await pause(800);
}

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

// the Yes of the confirmation that is on the screen now (an earlier dialog stays in the page, hidden, so the first match is not the one)
async function confirmYes(page) {
  await page.waitForFunction(
    () =>
      [...document.querySelectorAll(".modal.show .btn-modal-primary")].some(
        (b) => b.offsetParent
      ),
    { timeout: 20000 }
  );
  await page.evaluate(() =>
    [...document.querySelectorAll(".modal.show .btn-modal-primary")]
      .filter((b) => b.offsetParent)
      .pop()
      .click()
  );
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll(".modal.show")].some(
        (m) => m.offsetParent
      ),
    { timeout: 30000 }
  );
}

// The Desk scrolls inside a container of its own, not the window: find the one that scrolls above the element.
// Scrolls instantly (smooth scrolling would carry on after the picture is taken) so that the element sits OFFSET pixels below the top, under the page's own header.
async function scrollToText(page, text, offset = 110) {
  const found = await page.evaluate(
    (needle, offset) => {
      const el = [...document.querySelectorAll("body *")].find(
        (e) =>
          e.children.length === 0 &&
          e.offsetParent &&
          e.textContent.trim() === needle
      );
      if (!el) return false;
      let p = el.parentElement;
      while (
        p &&
        !(
          p.scrollHeight > p.clientHeight + 4 &&
          /(auto|scroll)/.test(getComputedStyle(p).overflowY)
        )
      )
        p = p.parentElement;
      (p || document.scrollingElement).scrollBy({
        top: el.getBoundingClientRect().top - offset,
        behavior: "instant",
      });
      return true;
    },
    text,
    offset
  );
  await pause(1200);
  return found;
}

async function scrollToTop(page) {
  await page.evaluate(() => {
    document.querySelectorAll("*").forEach((e) => {
      if (e.scrollTop) e.scrollTop = 0;
    });
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  await pause(800);
}

async function closeDialog(page) {
  await page.click(".modal.show .btn-modal-close");
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll(".modal.show")].some(
        (m) => m.offsetParent
      ),
    { timeout: 10000 }
  );
  await pause(500);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([
      { name: "prefers-color-scheme", value: "light" },
    ]);

    console.log(`signing in to ${BASE} as ${DESK_USER}`);
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
    await page.type("#login_email", DESK_USER);
    await page.type("#login_password", DESK_PASSWORD);
    await Promise.all([
      page.waitForNavigation({ waitUntil: "networkidle0" }),
      page.keyboard.press("Enter"),
    ]);

    // 9. the home page, with the shortcuts and the counts
    await open(page, "/app/ai-munimji");
    await shot(page, "01-home");

    // 1. the Settings page, the stock monitor on
    await open(
      page,
      "/app/ai-munimji-settings/AI%20Munimji%20Settings",
      ".form-layout"
    );
    await shot(page, "02-settings");

    // 2. the requests that wait for an answer
    await open(
      page,
      "/app/munimji-approval-request?status=pending",
      ".list-row"
    );
    await shot(page, "03-requests-waiting");

    // 3. the reorder suggestion; Approve it: the vendors are compared in the background and a purchase request appears
    let reorder = await requests(page, ITEM, "inventory.reorder", "pending");
    if (reorder.length) {
      await open(
        page,
        `/app/munimji-approval-request/${reorder[0].name}`,
        '[data-fieldname="flow"]'
      );
      await scrollToTop(page);
      await shot(page, "04-reorder-request");
      await press(page, "Approve");
      await confirmYes(page);
      console.log("  approved the reorder; waiting for the purchase request");
      for (
        let i = 0;
        i < 90 &&
        !(await requests(page, ITEM, "procurement.po", "pending")).length;
        i++
      )
        await pause(2000);
    } else {
      console.log(
        `  no reorder of ${ITEM} is waiting: the picture of the reorder is not retaken`
      );
    }

    // 4. the purchase request: what is proposed, the stock and how long it lasts, the chosen vendor
    let main = await requests(page, ITEM, "procurement.po", "pending");
    const mainWaits = main.length > 0;
    if (mainWaits) {
      await open(
        page,
        `/app/munimji-approval-request/${main[0].name}`,
        '[data-fieldname="flow"]'
      );
      await scrollToTop(page);
      await shot(page, "05-purchase-request");
    } else {
      main = await requests(page, ITEM, "procurement.po", "decided");
      if (!main.length)
        throw new Error(
          `no purchase request of ${ITEM} found: run the stock check and approve its reorder first`
        );
      console.log(
        "  the purchase request was answered already: the picture of it waiting is not retaken"
      );
    }

    // 5 and 6. the other vendors and why they were not chosen, and the Change quantity dialog (cancelled: nothing is changed): on the purchase request of VENDORS_ITEM when one waits
    let vendors = await requests(
      page,
      VENDORS_ITEM,
      "procurement.po",
      "pending"
    );
    if (!vendors.length && mainWaits) vendors = main;
    if (vendors.length) {
      await open(
        page,
        `/app/munimji-approval-request/${vendors[0].name}`,
        '[data-fieldname="flow"]'
      );
      if (
        !(await scrollToText(
          page,
          "The other vendors, and why they were not chosen"
        ))
      )
        console.log("  (heading not found)");
      await shot(page, "06-other-vendors-not-chosen");
      await press(page, "Change quantity");
      await page.waitForSelector(".modal.show", {
        visible: true,
        timeout: 20000,
      });
      await pause(600);
      await shot(page, "07-change-quantity");
      await closeDialog(page);
    } else {
      console.log(
        "  no purchase request is waiting for the pictures of the other vendors and of the dialog"
      );
    }

    // 7. the purchase request after Approve: a Draft Purchase Order is made, and its number is on the request (in the Flow block)
    await open(
      page,
      `/app/munimji-approval-request/${main[0].name}`,
      '[data-fieldname="flow"]'
    );
    if (mainWaits) {
      await press(page, "Approve");
      await confirmYes(page);
      await page.waitForFunction(
        () =>
          /PUR-ORD-/.test(
            document.querySelector('[data-fieldname="flow"]')?.innerText || ""
          ),
        { timeout: 60000, polling: 500 }
      );
      await pause(1500);
    }
    await scrollToTop(page);
    await shot(page, "08-request-after-approval");

    // 8. the Draft Purchase Order, with the request reference and the approver
    const orders = await api(
      page,
      "Purchase Order",
      [
        ["custom_agent_ref", "is", "set"],
        ["Purchase Order Item", "item_code", "=", ITEM],
      ],
      ["name"]
    );
    if (!orders.length)
      throw new Error(
        `no purchase order made by the app for ${ITEM} was found`
      );
    await open(page, `/app/purchase-order/${orders[0].name}`, ".form-layout");
    await scrollToTop(page);
    await shot(page, "09-draft-purchase-order");
    console.log("done; pictures in", SHOTS);
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error("FAILED:", e.message);
  process.exit(1);
});
