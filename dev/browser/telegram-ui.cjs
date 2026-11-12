// The Telegram screens in the real Desk, in the container's headless Chromium, as the people who use them: a Munimji Manager sets Telegram up on the Settings page, a Munimji Approver connects her
// chat with the Connect Telegram button, and a Viewer is kept out. Telegram itself is the pretend one (dev/scripts/fake_telegram.py): when the dialog shows its link, this script does what
// Telegram does when the person presses Start (the pretend Telegram posts the update to the site's webhook with the secret it was given). Pictures go to $SHOTS (default /tmp/telegram-shots).
//   .\dev\telegram-e2e.ps1 -Browser            (starts everything, makes the people, runs this, puts the site back)
// Needs the site's own server (BASE, default http://127.0.0.1:8010), the pretend Telegram (FAKE, default http://127.0.0.1:8999) and the people of dev/scripts/telegram_ui_setup.py.
const fs = require("fs");
const puppeteer = require("puppeteer-core");

const BASE = process.env.BASE || "http://127.0.0.1:8010";
const FAKE = process.env.FAKE || "http://127.0.0.1:8999";
const PASSWORD = process.env.PASSWORD || "Munimji-dev-1!";
const SHOTS = process.env.SHOTS || "/tmp/telegram-shots";
const MANAGER = "ui.manager@example.com";
const ALICE = "ui.alice@example.com";
const VIEWER = "ui.viewer@example.com";
const TOKEN_PART = "AAE2E-pretend-token-not-a-secret";
const CHAT = 8101;
fs.mkdirSync(SHOTS, { recursive: true });

let failed = 0;
const check = (ok, what) => {
  console.log((ok ? "  PASS  " : "  FAIL  ") + what);
  if (!ok) failed++;
};
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = (page, name) =>
  page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

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

async function toast(page, containing, timeout = 15000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    const texts = await page.$$eval(
      ".es-toast, .desk-alert, #alert-container .alert",
      (els) => els.map((e) => e.innerText)
    );
    const hit = texts.find((t) => t.includes(containing));
    if (hit) return hit;
    await pause(300);
  }
  return null;
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: "/usr/bin/chromium-headless-shell",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
  });
  try {
    console.log("1. a Munimji Manager sets Telegram up on the Settings page");
    const manager = await signIn(browser, MANAGER);
    await manager.goto(`${BASE}/app/ai-munimji-settings`, {
      waitUntil: "networkidle0",
    });
    await manager.waitForSelector('[data-fieldname="telegram_enabled"]', {
      timeout: 30000,
    });
    await shot(manager, "01-settings");
    check(
      await manager.$eval(
        '[data-fieldname="telegram_enabled"] input',
        (e) => e.checked
      ),
      "the Telegram switch is on (the people-setup switched it on)"
    );
    const tokenShown = await manager.$eval(
      '[data-fieldname="telegram_bot_token"] input',
      (e) => e.value
    );
    check(
      !tokenShown.includes(TOKEN_PART),
      `the token is not on the page (the field shows ${JSON.stringify(
        tokenShown.slice(0, 3)
      )}...)`
    );
    check(
      !(await manager.content()).includes(TOKEN_PART),
      "nor anywhere else in the page"
    );
    const buttons = await manager.$$eval(
      '[data-fieldname="telegram_connect_bot"] button, [data-fieldname="telegram_send_test"] button',
      (els) => els.map((e) => e.innerText.trim())
    );
    check(
      buttons.includes("Connect the bot") &&
        buttons.includes("Send me a test message"),
      `the two buttons are there: ${JSON.stringify(buttons)}`
    );
    const status = await manager.$eval(
      '[data-fieldname="telegram_status"]',
      (e) => e.innerText
    );
    check(
      status.includes("Telegram") && status.includes("not connected yet"),
      `the status block says the bot is not connected yet: ${JSON.stringify(
        status.replace(/\s+/g, " ").trim()
      )}`
    );
    await manager.click('[data-fieldname="telegram_connect_bot"] button');
    const connected = await toast(manager, "Connected to @");
    check(
      !!connected,
      `Connect the bot: ${JSON.stringify(
        connected && connected.replace(/\s+/g, " ").slice(0, 120)
      )}`
    );
    await pause(1500);
    await shot(manager, "02-settings-connected");
    const botField = await manager.$eval(
      '[data-fieldname="telegram_bot_username"]',
      (e) => e.innerText
    );
    check(
      botField.includes("munimji_demo_bot"),
      "the bot's name is on the page now"
    );

    console.log("2. a Munimji Approver connects her chat");
    const alice = await signIn(browser, ALICE);
    await alice.goto(`${BASE}/app/munimji-telegram-link`, {
      waitUntil: "networkidle0",
    });
    await alice.waitForSelector(".primary-action:not(.hide)", {
      timeout: 30000,
    });
    await shot(alice, "03-links-empty");
    const empty = await alice
      .$eval(".no-result", (e) => e.innerText.replace(/\s+/g, " ").trim())
      .catch(() => "");
    check(
      empty.includes("Press Connect Telegram"),
      `the empty list says what to do, in the app's words: ${JSON.stringify(
        empty
      )}`
    );
    const primary = await alice
      .$eval(".primary-action:not(.hide)", (e) => e.innerText.trim())
      .catch(() => "");
    check(
      primary.includes("Connect Telegram"),
      `the list's button says Connect Telegram: ${JSON.stringify(primary)}`
    );
    await alice.click(".primary-action");
    await alice.waitForSelector(".modal-dialog a[href*='start=']", {
      timeout: 15000,
    });
    const link = await alice.$eval(
      ".modal-dialog a[href*='start=']",
      (e) => e.href
    );
    await shot(alice, "04-connect-dialog");
    const url = new URL(link);
    check(
      url.hostname === "t.me" &&
        url.pathname === "/munimji_demo_bot" &&
        /^[A-Za-z0-9_-]{8,64}$/.test(url.searchParams.get("start") || ""),
      `the dialog's link goes to the bot with a code: ${url.origin}${url.pathname}?start=...`
    );
    const waiting = await alice.$eval(".modal-dialog", (e) => e.innerText);
    check(
      waiting.includes("Waiting for you to press Start"),
      "and says it is waiting for her to press Start"
    );
    const sent = await fetch(`${FAKE}/control/forward`, {
      method: "POST",
      body: JSON.stringify({
        to: BASE,
        update: {
          update_id: Date.now() % 1000000000,
          message: {
            message_id: 1,
            text: `/start ${url.searchParams.get("start")}`,
            from: { id: CHAT, is_bot: false, first_name: "Alice" },
            chat: { id: CHAT, type: "private" },
          },
        },
      }),
    }).then((r) => r.json());
    check(
      sent.status === 200,
      `Telegram (pretend) pressed Start: the site answered ${sent.status}`
    );
    const done = await toast(alice, "Telegram is connected", 20000);
    check(
      !!done,
      `the dialog noticed and said so: ${JSON.stringify(
        done && done.replace(/\s+/g, " ").slice(0, 80)
      )}`
    );
    await pause(1500);
    check(
      (await alice.$$(".modal-dialog:not([style*='display: none'])")).length ===
        0 || !(await alice.$eval(".modal.show", () => true).catch(() => false)),
      "the dialog closed itself"
    );
    await shot(alice, "05-links-connected");
    const rows = await alice.$$eval(".list-row-container .list-row", (els) =>
      els.map((e) => e.innerText.replace(/\s+/g, " ").trim())
    );
    check(
      rows.length === 1 && rows[0].includes(ALICE),
      `her list has one row, hers: ${JSON.stringify(rows)}`
    );
    const state = await fetch(`${FAKE}/control/state`).then((r) => r.json());
    check(
      state.messages.some(
        (m) => m.chat_id === String(CHAT) && m.text.startsWith("Connected.")
      ),
      "and the bot told her chat that it is connected"
    );

    console.log("3. she can look at her link and disconnect");
    await alice.goto(
      `${BASE}/app/munimji-telegram-link/${encodeURIComponent(ALICE)}`,
      { waitUntil: "networkidle0" }
    );
    await alice.waitForSelector('[data-fieldname="chat_id"]', {
      timeout: 30000,
    });
    await shot(alice, "06-link-form");
    const chatField = await alice.$eval(
      '[data-fieldname="chat_id"]',
      (e) => e.innerText
    );
    check(
      chatField.includes(String(CHAT)),
      "the form shows her chat number (read only)"
    );
    const buttonsOnForm = await alice.$$eval(
      ".custom-actions button, .page-actions button",
      (els) => els.map((e) => e.innerText.trim())
    );
    check(
      buttonsOnForm.includes("Disconnect"),
      `the form has a Disconnect button: ${JSON.stringify(buttonsOnForm)}`
    );
    const other = await alice.evaluate(
      async (base) =>
        (await fetch(`${base}/api/resource/Munimji Telegram Link`)).json(),
      BASE
    );
    check(
      (other.data || []).length === 1,
      "the REST list shows her one link and nobody else's"
    );
    await alice.evaluate(() =>
      [
        ...document.querySelectorAll(
          ".custom-actions button, .page-actions button"
        ),
      ]
        .find((b) => b.innerText.trim() === "Disconnect")
        .click()
    );
    await alice.waitForSelector(".modal-dialog .btn-modal-primary", {
      timeout: 10000,
    });
    await alice.click(".modal-dialog .btn-modal-primary");
    const gone = await toast(alice, "Telegram is disconnected", 15000);
    check(
      !!gone,
      `Disconnect: ${JSON.stringify(
        gone && gone.replace(/\s+/g, " ").slice(0, 100)
      )}`
    );
    await pause(1000);
    const after = await alice.evaluate(
      async (base) =>
        (
          await (
            await fetch(`${base}/api/resource/Munimji Telegram Link`)
          ).json()
        ).data,
      BASE
    );
    check(after.length === 0, "the link is gone");

    console.log("4. a Viewer is kept out");
    const viewer = await signIn(browser, VIEWER);
    const refused = await viewer.evaluate(
      async (base) =>
        (
          await fetch(`${base}/api/resource/Munimji Telegram Link`)
        ).status,
      BASE
    );
    check(refused === 403, `a Viewer's list of links is refused (${refused})`);
    const noButton = await viewer.evaluate(
      async (base) =>
        (
          await fetch(`${base}/api/method/ai_munimji.telegram.api.connect`, {
            method: "POST",
            headers: { "X-Frappe-CSRF-Token": window.frappe.csrf_token },
          })
        ).status,
      BASE
    );
    check(noButton === 403, `and so is Connect Telegram (${noButton})`);
  } finally {
    await browser.close();
  }
  console.log(failed ? `\n${failed} check(s) failed` : "\nall checks passed");
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  console.error(error);
  process.exit(2);
});
