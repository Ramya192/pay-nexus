import { expect, test } from "@playwright/test";
import { mockChat, register } from "./helpers";

const ASK = "Where is most of my money going?";

// Regression: minimizing the chat unmounted it, wiping the in-flight state, so a question typed
// after reopening mid-answer was dropped (no bubble, no request).
test("a question typed after minimizing and reopening mid-answer is queued, not lost", async ({ page }) => {
  await mockChat(page, 2500);
  await register(page);

  const input = page.getByPlaceholder("Am I on the best tax regime for me?");
  await input.fill(ASK);
  await input.press("Enter");
  await expect(page.getByText(ASK)).toBeVisible();

  await page.getByRole("button", { name: "Minimize chat" }).click();
  await page.getByRole("button", { name: "Open chat" }).click();

  await input.fill("Second question");
  await input.press("Enter");
  await expect(page.getByRole("button", { name: /Remove queued question: Second question/ })).toBeVisible();

  // The first answer finishes (it was not lost), then the queued one runs and answers too.
  await expect(page.getByText(`Mock answer to: ${ASK}`)).toBeVisible();
  await expect(page.getByText("Mock answer to: Second question")).toBeVisible();
});
