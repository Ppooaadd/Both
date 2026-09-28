import path from "node:path";

import { expect, test } from "@playwright/test";

const FIXTURE = path.join(__dirname, "fixtures", "demo-song.mp3");
const SHOTS = process.env.E2E_SCREENSHOT_DIR;

test("sign up, upload, watch progress, explore and re-arrange", async ({ page, request }) => {
  const email = `e2e-${Date.now()}@example.com`;

  // Sign up
  await page.goto("/signup");
  await page.getByLabel("이름").fill("E2E 피아니스트");
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill("Correct-Horse-9");
  await page.getByRole("button", { name: "가입하기" }).click();
  await expect(page.getByRole("button", { name: "편곡 시작" })).toBeVisible();

  // Upload with "beginner" as the first difficulty
  await page.locator('input[type="file"]').setInputFiles(FIXTURE);
  await expect(page.getByText("demo-song.mp3")).toBeVisible();
  await page.getByText("초급", { exact: true }).click();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/1-upload.png` });
  await page.getByRole("button", { name: "편곡 시작" }).click();

  // Live progress over WebSocket, then the workspace
  await page.waitForURL(/\/projects\/[0-9a-f-]+$/);
  const progress = page.getByText("분석과 편곡 진행 중");
  await expect(progress).toBeVisible();
  await expect(page.getByText("실시간")).toBeVisible();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/2-progress.png` });
  await expect(page.getByRole("heading", { name: "분석 결과" })).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("C major").first()).toBeVisible();

  // Arrangement: piano roll renders, audio becomes playable
  const roll = page.getByRole("application", { name: /피아노 롤/ });
  await expect(roll).toBeVisible();
  await expect(page.getByRole("radio", { name: /초급/ })).toHaveAttribute("aria-checked", "true");
  await expect(page.getByRole("button", { name: "재생" })).toBeEnabled({ timeout: 30_000 });
  await roll.click({ position: { x: 400, y: 200 } }); // seek + play
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/3-workspace.png`, fullPage: true });

  // Score tab: OSMD renders SVG from the MusicXML export
  await page.getByRole("tab", { name: "악보" }).click();
  await expect(page.locator('[aria-label="악보 미리보기"] svg').first()).toBeVisible({ timeout: 30_000 });
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/4-score.png`, fullPage: true });

  // Re-arrange as advanced; the new version is selected when the job finishes
  await page.getByRole("tab", { name: "고급" }).click();
  await page.getByRole("button", { name: /다시 편곡/ }).click();
  await expect(page.getByText("다시 편곡하는 중")).toBeVisible();
  await expect(page.getByRole("radio", { name: /고급/ })).toHaveAttribute("aria-checked", "true", { timeout: 60_000 });
  await page.getByRole("tab", { name: "피아노 롤" }).click();
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/5-advanced.png`, fullPage: true });

  // Same settings again: answered from the existing arrangement, no new job
  await page.getByRole("radio", { name: /초급/ }).click();
  await page.getByRole("tab", { name: "고급" }).click();
  await page.getByRole("button", { name: /다시 편곡/ }).click();
  await expect(page.getByText(/바로 불러왔습니다/)).toBeVisible();

  // Download: the same-origin link redirects to storage and serves a real PDF
  await page.getByRole("button", { name: "다운로드" }).click();
  const pdfHref = await page.getByRole("menuitem", { name: /PDF 악보/ }).getAttribute("href");
  expect(pdfHref).toMatch(/\/exports\/pdf$/);
  const pdf = await page.request.get(pdfHref!);
  expect(pdf.ok()).toBeTruthy();
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
  await page.keyboard.press("Escape");

  // Project list shows the finished project
  await page.getByRole("link", { name: "내 프로젝트" }).click();
  await expect(page.getByRole("link", { name: "demo-song" })).toBeVisible();
  await expect(page.getByText("완료").first()).toBeVisible();
  void request;
});
