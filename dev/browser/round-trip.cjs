// Clicks the real "Create Purchase Order" button in the Desk, in the container's headless Chromium.
//   .\dev\exec.ps1 bash -c "cd /workspace/ai_munimji/dev/browser && node round-trip.cjs"
// Needs the bench running (bench start) and the demo seeded with two Pending requests (dev\scripts\reset_demo.py).
const puppeteer = require("puppeteer-core");

const BASE = process.env.BASE || "http://localhost:8000";
const PASSWORD = process.env.PASSWORD || "Munimji-dev-1!";
let failed = 0;
const check = (ok, what) => {
	console.log((ok ? "  PASS  " : "  FAIL  ") + what);
	if (!ok) failed++;
};

async function signIn(browser, user) {
	const context = await browser.createBrowserContext();
	const page = await context.newPage();
	await page.setViewport({ width: 1280, height: 900 });
	await page.goto(`${BASE}/login`, { waitUntil: "networkidle0" });
	await page.type("#login_email", user);
	await page.type("#login_password", PASSWORD);
	// Frappe v16's login button is `button.es-button` (v15's `.btn-login` is gone): pressing Enter in the password field works in both
	await Promise.all([page.waitForNavigation({ waitUntil: "networkidle0" }), page.keyboard.press("Enter")]);
	return page;
}

async function pendingRequests(page) {
	return page.evaluate(async () => {
		const filters = encodeURIComponent(JSON.stringify([["status", "=", "Pending"]]));
		const r = await fetch(`/api/resource/Munimji Approval Request?filters=${filters}&order_by=name asc&fields=["name","status","purchase_order"]`);
		return (await r.json()).data;
	});
}

async function clickButton(page, label) {
	await page.waitForFunction((text) => [...document.querySelectorAll("button")].some((b) => b.textContent.trim() === text && b.offsetParent), { timeout: 20000 }, label);
	await page.evaluate((text) => [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === text && b.offsetParent).click(), label);
}

(async () => {
	const browser = await puppeteer.launch({
		executablePath: "/usr/bin/chromium-headless-shell",
		args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
	});
	try {
		console.log("1. The approver opens a Pending request and presses the button");
		const approver = await signIn(browser, "munimji.approver@example.com");
		const [first, second] = await pendingRequests(approver);
		check(first && second, `two requests are Pending (${first && first.name}, ${second && second.name})`);
		await approver.goto(`${BASE}/app/munimji-approval-request/${first.name}`, { waitUntil: "networkidle0" });
		await clickButton(approver, "Create Purchase Order");
		await approver.waitForSelector(".modal-dialog .btn-modal-primary", { visible: true, timeout: 20000 });
		const question = await approver.$eval(".modal-dialog .modal-body", (e) => e.textContent.trim());
		check(/draft Purchase Order/i.test(question) && /Nothing is submitted/.test(question), `the dialog asks first: "${question}"`);
		await approver.click(".modal-dialog .btn-modal-primary"); // Yes
		await approver.waitForFunction(() => document.body.innerText.includes("Draft PUR-ORD") , { timeout: 30000 }).catch(() => {});
		await new Promise((r) => setTimeout(r, 1500));
		const after = await approver.evaluate(async (name) => (await (await fetch(`/api/resource/Munimji Approval Request/${name}`)).json()).data, first.name);
		check(after.status === "Ordered" && !!after.purchase_order, `the request is now ${after.status}, order ${after.purchase_order}`);
		const order = await approver.evaluate(async (name) => (await (await fetch(`/api/resource/Purchase Order/${name}`)).json()).data, after.purchase_order);
		check(order.docstatus === 0 && order.custom_agent_ref === first.name, `a draft order with custom_agent_ref = ${order.custom_agent_ref}`);
		const buttons = await approver.evaluate(() => [...document.querySelectorAll("button")].filter((b) => b.offsetParent).map((b) => b.textContent.trim()));
		check(!buttons.includes("Create Purchase Order"), "the button is gone from the Ordered request");

		console.log("2. The viewer opens the other request and presses the button");
		const viewer = await signIn(browser, "munimji.viewer@example.com");
		await viewer.goto(`${BASE}/app/munimji-approval-request/${second.name}`, { waitUntil: "networkidle0" });
		await clickButton(viewer, "Create Purchase Order");
		await viewer.waitForSelector(".modal-dialog .btn-modal-primary", { visible: true, timeout: 20000 });
		await viewer.click(".modal-dialog .btn-modal-primary");
		await new Promise((r) => setTimeout(r, 3000));
		const text = await viewer.evaluate(() => document.body.innerText);
		check(/not permitted|permission/i.test(text), "the viewer is told they are not permitted");
		const still = await viewer.evaluate(async (name) => (await (await fetch(`/api/resource/Munimji Approval Request/${name}`)).json()).data.status, second.name);
		check(still === "Pending", `the request is still ${still}`);
	} catch (error) {
		console.log("  FAIL  " + error.message);
		failed++;
	} finally {
		await browser.close();
	}
	console.log(failed === 0 ? "\nBrowser round trip: all checks passed." : `\nBrowser round trip: ${failed} check(s) failed.`);
	process.exit(failed ? 1 : 0);
})();
