// The two Telegram pictures for the Marketplace listing (docs/LISTING.md, section 4, pictures 10 and 11): the Telegram section of the Settings page after "Connect the bot", and the
// Connect Telegram dialog with its link. Telegram is the pretend one (dev/scripts/fake_telegram.py, the bot "AI Munimji demo"), so no real bot, token or chat is on the pictures; the token typed
// here is a pretend one and the field shows only dots after the page is saved. The one-time code in the dialog is blurred before the picture is taken.
//
//   1. start the pretend Telegram:  python3 dev/scripts/fake_telegram.py --port 8999   (in the container that serves the site)
//   2. point the site at it:        bench --site <site> set-config ai_munimji_telegram_api_base http://127.0.0.1:8999
//                                   bench --site <site> set-config host_name https://munimji-demo.example.com     (a webhook address must be https; the pretend Telegram does not call it)
//   3. cd dev/browser && node listing-shots-telegram.cjs
//   4. put the site back: bench --site <site> set-config ai_munimji_telegram_api_base null  (and host_name), and switch Telegram off on the Settings page.
//
// Environment: BASE (http://127.0.0.1:8002), DESK_USER (Administrator), DESK_PASSWORD, APPROVER_USER (munimji.approver@example.com: a person with the Munimji Approver role, for the dialog),
// APPROVER_PASSWORD, SHOTS (./shots), CHROME (the path of chrome.exe).
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const BASE = process.env.BASE || "http://127.0.0.1:8002";
const DESK_USER = process.env.DESK_USER || "Administrator";
const DESK_PASSWORD = process.env.DESK_PASSWORD || "admin";
const SHOTS = process.env.SHOTS || path.join(__dirname, "shots");
const CHROME =
  process.env.CHROME ||
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const APPROVER_USER =
  process.env.APPROVER_USER || "munimji.approver@example.com";
const APPROVER_PASSWORD = process.env.APPROVER_PASSWORD || "Munimji-dev-1!";
const TOKEN = "424242:pretend-token-for-the-listing-pictures";
fs.mkdirSync(SHOTS, { recursive: true });

const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const shot = async (page, name) => {
  await pause(700);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
  console.log("  picture:", name);
};

// scrolls the Desk's own scrolling container so that the element sits OFFSET pixels below the top
async function scrollToSelector(page, selector, offset = 100) {
  await page.evaluate(
    (selector, offset) => {
      const el = document.querySelector(selector);
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
    },
    selector,
    offset
  );
  await pause(1200);
}

(async () => {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
  });
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 1 });
    await page.emulateMediaFeatures([
      { name: "prefers-color-scheme", value: "light" },
    ]);
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
    await page.type("#login_email", DESK_USER);
    await page.type("#login_password", DESK_PASSWORD);
    await Promise.all([
      page.waitForNavigation({ waitUntil: "networkidle0" }),
      page.keyboard.press("Enter"),
    ]);

    // 10. the Settings page: Telegram on, webhook mode, the pretend token saved (the field shows dots), then "Connect the bot"
    await page.goto(`${BASE}/app/ai-munimji-settings/AI%20Munimji%20Settings`, {
      waitUntil: "networkidle0",
    });
    await page.waitForSelector('[data-fieldname="telegram_enabled"]', {
      timeout: 30000,
    });
    await pause(800);
    await page.evaluate(async (token) => {
      cur_frm.set_value("telegram_enabled", 1);
      cur_frm.set_value("telegram_mode", "Webhook");
      cur_frm.set_value("telegram_bot_token", token);
      await cur_frm.save();
    }, TOKEN);
    await pause(1500);
    await page.click('[data-fieldname="telegram_connect_bot"] button');
    await page.waitForFunction(
      () => /Connected to @/.test(document.body.innerText),
      { timeout: 20000 }
    );
    await pause(2500);
    const tokenOnPage = await page.$eval(
      '[data-fieldname="telegram_bot_token"] input',
      (e) => e.value
    );
    if (tokenOnPage.includes("pretend-token"))
      throw new Error("the token is on the page: not taking the picture");
    console.log(
      `  the token field shows: ${JSON.stringify(tokenOnPage.slice(0, 4))}...`
    );
    await page.evaluate(() =>
      document
        .querySelectorAll(".es-toast, .desk-alert, #alert-container .alert")
        .forEach((e) => e.remove())
    ); // the toasts say "Saved" and name the pretend address
    await scrollToSelector(page, '[data-fieldname="telegram_enabled"]', 120);
    await shot(page, "10-telegram-settings");

    // 11. the Connect Telegram dialog with its link, as a person who may answer requests (the Administrator is refused: "Use your own user"); the one-time code is blurred
    const context = await browser.createBrowserContext();
    const approver = await context.newPage();
    await approver.setViewport({
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
    });
    await approver.emulateMediaFeatures([
      { name: "prefers-color-scheme", value: "light" },
    ]);
    await approver.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
    await approver.type("#login_email", APPROVER_USER);
    await approver.type("#login_password", APPROVER_PASSWORD);
    await Promise.all([
      approver.waitForNavigation({ waitUntil: "networkidle0" }),
      approver.keyboard.press("Enter"),
    ]);
    await approver.goto(`${BASE}/app/munimji-telegram-link`, {
      waitUntil: "networkidle0",
    });
    await approver.waitForSelector(".primary-action:not(.hide)", {
      timeout: 30000,
    });
    await approver.click(".primary-action");
    await finishDialog(approver);
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error("FAILED:", e.message);
  process.exit(1);
});

async function finishDialog(page) {
  {
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll("a[href*='start=']")].some(
          (a) => a.offsetParent
        ),
      { timeout: 20000 }
    );
    await pause(1000);
    const blurred = await page.evaluate(() => {
      const link = [...document.querySelectorAll("a[href*='start=']")].find(
        (a) => a.offsetParent
      );
      const code = new URL(link.href).searchParams.get("start");
      const dialog =
        link.closest(".modal-dialog") ||
        link.closest(".modal") ||
        document.body;
      let n = 0;
      dialog.querySelectorAll("*").forEach((el) => {
        if (el.children.length === 0 && el.textContent.includes(code)) {
          el.innerHTML = el.innerHTML
            .split(code)
            .join(`<span style="filter: blur(7px)">${code}</span>`);
          n++;
        }
      });
      return { n, shown: dialog.innerText };
    });
    console.log(
      "  the dialog says:",
      JSON.stringify(blurred.shown.replace(/\s+/g, " ").slice(0, 300))
    );
    console.log(`  the code is blurred in ${blurred.n} place(s)`);
    await shot(page, "11-connect-telegram");
    console.log("done; pictures in", SHOTS);
  }
}
