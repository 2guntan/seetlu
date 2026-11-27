import { expect, test } from "@playwright/test";

import { DAY, KIT, mockApi, SHOP } from "./mock-api";

test("journey 1 — login by phone + WhatsApp code (AC-F7-2, AC-F7-4)", async ({ page }) => {
  const api = await mockApi(page, "owner", { signedIn: false });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
  await page.getByLabel("Numéro de téléphone").fill("77 123 45 67");
  await page.getByRole("button", { name: "Recevoir le code" }).click();
  await page.getByLabel("Code reçu").fill("000000");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("alert")).toHaveText("Code incorrect ou expiré.");
  await page.getByLabel("Code reçu").fill("123456");
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { name: "Aujourd'hui" })).toBeVisible();
  expect(api.calls.find((c) => c.path === "/v1/auth/otp/request")?.body).toEqual({ phone_e164: "+221771234567" });
});

test("journey 2 — today: per-shop card with counter status (AC-F7-1)", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  const card = page.getByTestId(`today-${SHOP}`);
  await expect(card.getByText("Boutique Awa")).toBeVisible();
  await expect(card.getByText("84")).toBeVisible();
  await expect(card.getByText("262 500 F")).toBeVisible();
  await expect(card.getByTestId("counter-state")).toContainText("Vide depuis");
  await expect(card.getByText(/Dernier signal du kit/)).toBeVisible();
  // English is selectable
  await page.getByLabel("Langue").selectOption("en");
  await expect(page.getByRole("heading", { name: "Today" })).toBeVisible();
});

test("journey 3 — history → day detail → play a moment (AC-F7-1, AC-F5-2)", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/history");
  await page.getByRole("button", { name: "Mois précédent" }).waitFor();
  // go to November 2026 whatever today's month is
  for (let i = 0; i < 24 && !(await page.getByTestId(`cal-${DAY}`).isVisible()); i++) {
    const title = (await page.locator("main b.grow").textContent()) ?? "";
    await page.getByRole("button", { name: /2027|2028/.test(title) ? "Mois précédent" : "Mois suivant" }).click();
  }
  await expect(page.getByTestId(`cal-${DAY}`)).toHaveAttribute("data-verdict", "normal");
  await page.getByTestId(`cal-${DAY}`).click();
  await expect(page.getByTestId("verdict")).toHaveText("Journée normale.");
  await expect(page.getByTestId("missing-hours")).toContainText("14h–16h"); // never zeros (rule 3)
  await expect(page.locator('[data-testid="hour-14"][data-missing="true"]')).toBeVisible();
  await page.getByTestId("moment-1").getByRole("button", { name: "Voir la vidéo" }).click();
  await expect(page.getByText("Vidéo en préparation…")).toBeVisible();
  await expect(page.getByTestId("clip-video")).toBeVisible({ timeout: 10_000 });
  expect(api.calls.some((c) => c.path.startsWith("/v1/clips/"))).toBe(true); // playback goes through the audited API
});

test("journey 4 — installer: claim, shop, zones, count check, activate (AC-F8-1..4, AC-F8-7, AC-F8-8)", async ({ page }) => {
  const api = await mockApi(page, "installer");
  await page.goto("/install");
  await page.getByLabel("Numéro de série").fill("SN-0001");
  await page.getByLabel("Code du kit").fill("good-token");
  await page.getByRole("button", { name: "Continuer" }).click();
  await page.getByLabel("Choisir une boutique").selectOption(SHOP);
  await page.getByRole("button", { name: "Continuer" }).click();
  await expect(page.getByRole("heading", { name: "Caméras et zones" })).toBeVisible();

  const door = page.getByTestId("camera-door");
  // AC-F8-7: stream verdict from the box, low fps only warns
  await expect(page.getByTestId("checks-door")).toContainText("Flux correct");
  await expect(page.getByTestId("checks-counter")).toContainText("moins de 5 images/s");
  // AC-F8-8: angle checklist; a failed item means an add-on camera
  await page.getByTestId("checks-door").getByRole("checkbox").first().check();
  await page.getByTestId("checks-door").getByRole("checkbox").nth(1).check();
  await page.getByTestId("checks-door").getByRole("button", { name: "Valider l'angle" }).click();
  await expect(page.getByTestId("checks-door")).toContainText("Angle validé");
  await page.getByTestId("checks-counter").getByRole("checkbox").first().check();
  await page.getByTestId("checks-counter").getByRole("button", { name: "Valider l'angle" }).click();
  await expect(page.getByTestId("addon-counter")).toContainText("il faut une caméra en plus");
  await door.getByRole("button", { name: "Prendre une photo" }).click();
  await door.getByRole("button", { name: /ligne de porte/ }).click();
  const dc = door.getByTestId("zone-canvas");
  await dc.click({ position: { x: 40, y: 60 } });
  await dc.click({ position: { x: 200, y: 60 } });
  await door.getByLabel("Côté intérieur").selectOption("right");

  const counter = page.getByTestId("camera-counter");
  const cc = counter.getByTestId("zone-canvas");
  await counter.getByRole("button", { name: /Zone client/ }).click();
  for (const [x, y] of [[20, 20], [120, 20], [120, 100]]) await cc.click({ position: { x, y } });
  await counter.getByRole("button", { name: /Zone vendeur/ }).click();
  for (const [x, y] of [[150, 20], [250, 20], [250, 100]]) await cc.click({ position: { x, y } });
  await page.getByRole("button", { name: "Enregistrer les zones" }).click();

  const cams = api.calls.find((c) => c.path === `/v1/kits/${KIT}/cameras`)?.body as { name: string; zones: { type: string; geometry: number[][]; inward_side: string | null }[] }[];
  expect(cams[0].zones[0]).toMatchObject({ type: "door_line", inward_side: "right" });
  expect(cams[0].zones[0].geometry).toHaveLength(2);
  expect(cams[1].zones.map((z) => z.type)).toEqual(["customer_side", "staff_side"]);
  for (const p of cams.flatMap((c) => c.zones.flatMap((z) => z.geometry)).flat()) expect(p).toBeGreaterThanOrEqual(0);

  await page.getByRole("button", { name: "Démarrer" }).click();
  for (let i = 0; i < 20; i++) await page.getByTestId("plus-one").click();
  await expect(page.getByTestId("manual-count")).toHaveText("Votre compte : 20");
  await page.getByRole("button", { name: "Terminer" }).click();
  await expect(page.getByTestId("count-result")).toContainText("Réussi");
  await page.getByRole("button", { name: "Continuer" }).click();
  await page.getByRole("button", { name: "Activer le kit" }).click();
  await expect(page.getByText("Il manque la référence CDP de la boutique.")).toBeVisible(); // AC-F8-4
});

test("journey 5 — settings: hours, thresholds, alerts, invite (AC-F7-1)", async ({ page }) => {
  const api = await mockApi(page);
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: /Réglages · Boutique Awa/ })).toBeVisible();
  await page.getByLabel("sun-open").waitFor({ state: "detached" });
  await page.locator('input[name="service_min_s"]').fill("25");
  await page.locator('input[name="cdp"]').fill("CDP-2026-0042");
  await page.getByRole("button", { name: "Enregistrer" }).first().click();
  await expect(page.getByRole("status").first()).toHaveText("Enregistré");
  const p = api.calls.find((c) => c.method === "PATCH")?.body as Record<string, unknown>;
  expect(p).toMatchObject({ service_min_s: 25, cdp_declaration_ref: "CDP-2026-0042" });
  expect((p.opening_hours as Record<string, unknown>).sun).toEqual([]);

  await page.locator('input[name="alert-not_opened"]').uncheck();
  await page.locator("section", { hasText: "Alertes" }).getByRole("button", { name: "Enregistrer" }).click();
  const rules = (api.calls.find((c) => c.method === "PUT")?.body as { rules: { type: string; enabled: boolean }[] }).rules;
  expect(rules.find((r) => r.type === "not_opened")?.enabled).toBe(false);

  await page.getByPlaceholder("Nom").fill("Fatou");
  await page.getByPlaceholder("+221…").fill("78 000 00 01");
  await page.getByRole("button", { name: "Inviter" }).click();
  await expect.poll(() => api.calls.some((c) => c.method === "POST" && c.path.endsWith("/users"))).toBe(true);
  await page.getByRole("button", { name: "Afficher un code" }).click();
  await expect(page.getByTestId("pair-code")).toHaveText("482913");
  const inv = api.calls.find((c) => c.method === "POST" && c.path.endsWith("/users"))?.body;
  expect(inv).toMatchObject({ name: "Fatou", phone_e164: "+221780000001", role: "staff" });
});
