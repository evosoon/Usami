import { test, expect } from "@playwright/test";

test.describe("Smoke tests", () => {
  test("landing page loads", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Usami/i);
  });

  test("login page is accessible", async ({ page }) => {
    await page.goto("/login");
    // Should see login form
    await expect(page.locator("form, [data-testid='login-form'], input")).toBeVisible();
  });

  test("unauthenticated user is redirected from /chat", async ({ page }) => {
    await page.goto("/chat");
    // Should redirect to login
    await page.waitForURL(/\/login/);
    expect(page.url()).toContain("/login");
  });

  test("about page loads", async ({ page }) => {
    await page.goto("/about");
    await expect(page.locator("main, [role='main'], body")).toBeVisible();
  });
});
