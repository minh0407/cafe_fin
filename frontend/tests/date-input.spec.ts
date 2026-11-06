import { test, expect, type Page } from "@playwright/test";

async function mountDateInput(
  page: Page,
  options: {
    value?: string;
    disabled?: boolean;
    form?: boolean;
    required?: boolean;
    formDisabled?: boolean;
    controlDisabled?: boolean;
  } = {},
) {
  await page.route("**/date-input-save", (route) =>
    route.fulfill({ json: { saved: true } }),
  );
  await page.route("**/date-input-harness", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<!doctype html><html><body><div id="root"></div></body></html>',
    }),
  );
  await page.goto("/date-input-harness");
  await page.evaluate(async (settings) => {
    // Mount only the component: no app health polling or ConfigProvider locale.
    const refreshPath = "/@react-refresh";
    const refresh = (await import(refreshPath)).default;
    refresh.injectIntoGlobalHook(window);
    Reflect.set(window, "$RefreshReg$", () => {});
    Reflect.set(window, "$RefreshSig$", () => (type: unknown) => type);
    Reflect.set(window, "__vite_plugin_react_preamble_installed__", true);
    const reactPath = "/node_modules/.vite/deps/react.js";
    const rootPath = "/node_modules/.vite/deps/react-dom_client.js";
    const componentPath = "/src/shared/DateInput.tsx";
    // Use the component's exact optimized-module URL (including Vite's version
    // query). A second URL would instantiate a different AntD DisabledContext,
    // making this harness unlike a real app even though Form values still work.
    const componentSource = await (await fetch(componentPath)).text();
    const antdPath = componentSource.match(
      /["'](\/node_modules\/\.vite\/deps\/antd\.js(?:\?[^"']*)?)["']/,
    )?.[1];
    if (!antdPath) throw new Error("Vite AntD module URL unavailable");
    const React = (await import(reactPath)).default;
    const { createRoot } = (await import(rootPath)).default;
    const { DateInput, dateInputRule } = await import(componentPath);
    const { Form } = await import(antdPath);
    const h = React.createElement;
    function Harness() {
      const [value, setValue] = React.useState(settings.value ?? "2026-11-06");
      const [emitted, setEmitted] = React.useState([]);
      return h(
        "main",
        null,
        h("label", { htmlFor: "business-date" }, "Ngày nghiệp vụ"),
        h(DateInput, {
          id: "business-date",
          "aria-label": "Ngày nghiệp vụ",
          disabled: settings.disabled,
          value,
          onChange: (next: string) => {
            setValue(next);
            setEmitted((previous: string[]) => [...previous, next]);
          },
        }),
        h("button", { type: "button" }, "Tiếp theo"),
        h("output", { "data-testid": "iso" }, value),
        h("output", { "data-testid": "emitted" }, JSON.stringify(emitted)),
        h(
          "button",
          { type: "button", onClick: () => setValue("2026-02-31") },
          "Nạp ngày không hợp lệ",
        ),
      );
    }
    function FormHarness() {
      const [form] = Form.useForm();
      const [submitted, setSubmitted] = React.useState("");
      const [draft, setDraft] = React.useState(settings.value ?? "2026-11-06");
      const [formDisabled, setFormDisabled] = React.useState(settings.formDisabled ?? false);
      const [changeCount, setChangeCount] = React.useState(0);
      return h(
        Form,
        {
          form,
          disabled: formDisabled,
          initialValues: { date: settings.value ?? "2026-11-06" },
          onValuesChange: (_changed: unknown, values: { date: string }) => {
            setDraft(values.date);
            setChangeCount((previous: number) => previous + 1);
          },
          onFinish: async (values: { date: string }) => {
            await fetch("/date-input-save", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(values),
            });
            setSubmitted(JSON.stringify(values));
          },
        },
        h(
          Form.Item,
          {
            name: "date",
            label: "Ngày biểu mẫu",
            rules: [
              ...(settings.required ? [{ required: true, message: "Nhập ngày." }] : []),
              dateInputRule,
            ],
          },
          h(DateInput, {
            "aria-label": "Ngày biểu mẫu",
            disabled: settings.controlDisabled,
          }),
        ),
        h("button", { type: "submit" }, "Lưu biểu mẫu"),
        h("output", { "data-testid": "submitted" }, submitted),
        h("output", { "data-testid": "form-draft" }, draft),
        h("output", { "data-testid": "change-count" }, String(changeCount)),
        h(
          "button",
          { type: "button", onClick: () => setFormDisabled((previous: boolean) => !previous) },
          formDisabled ? "Mở biểu mẫu" : "Khóa biểu mẫu",
        ),
      );
    }
    createRoot(document.getElementById("root")!).render(
      h(settings.form ? FormHarness : Harness),
    );
  }, options);
}

for (const settings of [
  { locale: "en-US", timezoneId: "America/Los_Angeles" },
  { locale: "vi-VN", timezoneId: "Asia/Ho_Chi_Minh" },
  { locale: "en-US", timezoneId: "Pacific/Kiritimati" },
]) {
  test.describe(`${settings.locale}, ${settings.timezoneId}`, () => {
    test.use(settings);
    test("displays day/month/year and emits the same ISO date across locales and timezones", async ({
      page,
    }) => {
      await mountDateInput(page);
      const input = page.getByLabel("Ngày nghiệp vụ", { exact: true });
      await expect(input).toHaveAttribute("id", "business-date");
      await expect(input).toHaveJSProperty("type", "text");
      await expect(input).toHaveValue("06/11/2026");
      await page.getByRole("button", { name: "Mở lịch chọn ngày" }).click();
      await expect(page.getByText("T2", { exact: true })).toBeVisible();
      await page.getByRole("button", { name: "Mở lịch chọn ngày" }).click();
      await input.fill("01/02/2026");
      await input.press("Tab");
      await expect(page.getByTestId("iso")).toHaveText("2026-02-01");
      await expect(input).toHaveValue("01/02/2026");
      await input.fill("02/01/2026");
      await input.press("Tab");
      await expect(page.getByTestId("iso")).toHaveText("2026-01-02");
      await expect(input).toHaveValue("02/01/2026");
      await expect(page.getByTestId("emitted")).toHaveText(
        '["2026-02-01","2026-01-02"]',
      );
    });
  });
}

test("accepts leap day and propagates impossible date drafts without rollover or stale ISO", async ({
  page,
}) => {
  await mountDateInput(page);
  const input = page.getByLabel("Ngày nghiệp vụ", { exact: true });
  await input.fill("29/02/2024");
  await input.press("Tab");
  await expect(page.getByTestId("iso")).toHaveText("2024-02-29");
  for (const invalid of ["31/02/2026", "29/02/2025"]) {
    await input.fill(invalid);
    await input.press("Tab");
    await expect(input).toHaveValue(invalid);
    await expect(page.getByTestId("iso")).toHaveText(invalid);
    await expect(input).toHaveAttribute("aria-invalid", "true");
  }
  await expect(page.getByTestId("emitted")).toHaveText(
    '["2024-02-29","31/02/2026","29/02/2025"]',
  );
  await input.fill("07/11/2026");
  await input.press("Tab");
  await expect(page.getByTestId("iso")).toHaveText("2026-11-07");
});

test("clear emits an empty string and invalid incoming ISO is not normalized", async ({
  page,
}) => {
  await mountDateInput(page);
  const input = page.getByLabel("Ngày nghiệp vụ", { exact: true });
  await input.hover();
  await page.getByRole("button", { name: "Xóa", exact: true }).click();
  await expect(input).toHaveValue("");
  await expect(page.getByTestId("iso")).toHaveText("");
  await expect(page.getByTestId("emitted")).toHaveText('[""]');
  await input.fill("06/11/2026");
  await input.press("Tab");
  await expect(page.getByTestId("iso")).toHaveText("2026-11-06");
  await input.fill("");
  await input.press("Tab");
  await expect(page.getByTestId("iso")).toHaveText("");
  await expect(page.getByTestId("emitted")).toHaveText(
    '["","2026-11-06",""]',
  );
  await page.getByRole("button", { name: "Nạp ngày không hợp lệ" }).click();
  await expect(input).toHaveValue("2026-02-31");
  await expect(input).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByTestId("iso")).toHaveText("2026-02-31");
  await expect(page.getByTestId("emitted")).toHaveText(
    '["","2026-11-06",""]',
  );
});

test("disabled input stays unchanged and AntD Form receives a plain ISO string", async ({
  page,
}) => {
  await mountDateInput(page, { disabled: true });
  const disabled = page.getByLabel("Ngày nghiệp vụ", { exact: true });
  await expect(disabled).toBeDisabled();
  await expect(disabled).toHaveValue("06/11/2026");
  await page.getByRole("button", { name: "Tiếp theo" }).click();
  await expect(page.getByTestId("emitted")).toHaveText("[]");
  await mountDateInput(page, { form: true });
  const field = page.getByLabel("Ngày biểu mẫu", { exact: true });
  await field.fill("01/02/2026");
  await field.press("Tab");
  await page.getByRole("button", { name: "Lưu biểu mẫu" }).click();
  await expect(page.getByTestId("submitted")).toHaveText('{"date":"2026-02-01"}');
});

for (const required of [true, false]) {
  test(`${required ? "required" : "optional"} Form date rejects invalid drafts instead of submitting stale ISO or empty`, async ({
    page,
  }) => {
    const payloads: unknown[] = [];
    page.on("request", (request) => {
      if (request.url().endsWith("/date-input-save")) {
        payloads.push(request.postDataJSON());
      }
    });
    await mountDateInput(page, { form: true, required });
    const field = page.getByLabel("Ngày biểu mẫu", { exact: true });
    await expect(field).toHaveValue("06/11/2026");
    await field.fill("31/02/2026");
    await field.press("Tab");
    await page.getByRole("button", { name: "Lưu biểu mẫu" }).click();
    await expect(
      page.getByText("Ngày không hợp lệ. Nhập DD/MM/YYYY.", { exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("form-draft")).toHaveText("31/02/2026");
    await expect(page.getByTestId("submitted")).toHaveText("");
    expect(payloads).toEqual([]);
    await field.fill("07/11/2026");
    await field.press("Tab");
    await page.getByRole("button", { name: "Lưu biểu mẫu" }).click();
    await expect(page.getByTestId("submitted")).toHaveText('{"date":"2026-11-07"}');
    expect(payloads).toEqual([{ date: "2026-11-07" }]);
  });
}

test("optional Form date can really be cleared, but invalid text cannot submit as that empty value", async ({
  page,
}) => {
  const payloads: unknown[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/date-input-save")) {
      payloads.push(request.postDataJSON());
    }
  });
  await mountDateInput(page, { form: true });
  const field = page.getByLabel("Ngày biểu mẫu", { exact: true });
  await field.fill("");
  await page.getByRole("button", { name: "Lưu biểu mẫu" }).click();
  await expect(page.getByTestId("submitted")).toHaveText('{"date":""}');
  expect(payloads).toEqual([{ date: "" }]);
  await field.fill("31/02/2026");
  await page.getByRole("button", { name: "Lưu biểu mẫu" }).click();
  await expect(
    page.getByText("Ngày không hợp lệ. Nhập DD/MM/YYYY.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("form-draft")).toHaveText("31/02/2026");
  expect(payloads).toEqual([{ date: "" }]);
});

test("calendar selection emits an ISO date without submitting the surrounding Form", async ({
  page,
}) => {
  await mountDateInput(page, { form: true });
  await page.getByRole("button", { name: "Mở lịch chọn ngày" }).click();
  await page.locator('[title="2026-11-07"]').click();
  await expect(page.getByTestId("form-draft")).toHaveText("2026-11-07");
  await expect(page.getByTestId("submitted")).toHaveText("");
  await expect(page.getByLabel("Ngày biểu mẫu", { exact: true })).toHaveValue("07/11/2026");
});

test("calendar can navigate month/year without changing the draft until a day is chosen", async ({
  page,
}) => {
  await mountDateInput(page, { form: true });
  await page.getByRole("button", { name: "Mở lịch chọn ngày" }).click();
  const year = page.locator(".ant-picker-calendar-year-select").getByRole("combobox");
  await year.click();
  await year.press("ArrowDown");
  await year.press("Enter");
  const month = page.locator(".ant-picker-calendar-month-select").getByRole("combobox");
  await month.click();
  for (let index = 0; index < 10; index += 1) await month.press("ArrowUp");
  await month.press("Enter");
  await expect(page.getByTestId("form-draft")).toHaveText("2026-11-06");
  await page.locator('[title="2027-01-02"]').click();
  await expect(page.getByTestId("form-draft")).toHaveText("2027-01-02");
  await expect(page.getByTestId("submitted")).toHaveText("");
});

test("Form disabled context locks text, clear and an already open calendar without emitting changes", async ({
  page,
}) => {
  await mountDateInput(page, { form: true });
  const field = page.getByLabel("Ngày biểu mẫu", { exact: true });
  const calendar = page.getByRole("button", { name: "Mở lịch chọn ngày" });
  await calendar.click();
  const nextDay = page.locator('[title="2026-11-07"]');
  await expect(nextDay).toBeVisible();
  const previouslyOpenDay = await nextDay.elementHandle();
  await page.getByRole("button", { name: "Khóa biểu mẫu", exact: true }).click();
  await expect(field).toBeDisabled();
  await expect(calendar).toBeDisabled();
  await expect(calendar).toHaveAttribute("aria-expanded", "false");
  await expect(nextDay).toBeHidden();
  await expect(page.getByRole("button", { name: "Xóa", exact: true })).toBeHidden();
  // A queued click targeting the former popup must not alter Form state either.
  await previouslyOpenDay?.dispatchEvent("click");
  await calendar.click({ force: true });
  await expect(nextDay).toBeHidden();
  await expect(field).toHaveValue("06/11/2026");
  await expect(page.getByTestId("form-draft")).toHaveText("2026-11-06");
  await expect(page.getByTestId("change-count")).toHaveText("0");
  await expect(page.getByTestId("submitted")).toHaveText("");

  await page.getByRole("button", { name: "Mở biểu mẫu", exact: true }).click();
  await expect(field).toBeEnabled();
  await expect(calendar).toBeEnabled();
  await expect(calendar).toHaveAttribute("aria-expanded", "false");
  await field.fill("");
  await expect(page.getByTestId("form-draft")).toHaveText("");
  await field.fill("07/11/2026");
  await expect(page.getByTestId("form-draft")).toHaveText("2026-11-07");
  await calendar.click();
  await page.locator('[title="2026-11-08"]').click();
  await expect(page.getByTestId("form-draft")).toHaveText("2026-11-08");
  await expect(page.getByTestId("change-count")).toHaveText("3");
});

test("explicit disabled false overrides Form context consistently for input and calendar", async ({
  page,
}) => {
  await mountDateInput(page, { form: true, formDisabled: true, controlDisabled: false });
  const field = page.getByLabel("Ngày biểu mẫu", { exact: true });
  const calendar = page.getByRole("button", { name: "Mở lịch chọn ngày" });
  await expect(field).toBeEnabled();
  await expect(calendar).toBeEnabled();
  await field.fill("07/11/2026");
  await expect(page.getByTestId("form-draft")).toHaveText("2026-11-07");
  await calendar.click();
  const year = page.locator(".ant-picker-calendar-year-select").getByRole("combobox");
  await expect(year).toBeEnabled();
  await year.click();
  await year.press("ArrowDown");
  await year.press("Enter");
  const month = page.locator(".ant-picker-calendar-month-select").getByRole("combobox");
  await expect(month).toBeEnabled();
  await month.click();
  for (let index = 0; index < 10; index += 1) await month.press("ArrowUp");
  await month.press("Enter");
  await page.locator('[title="2027-01-08"]').click();
  await expect(page.getByTestId("form-draft")).toHaveText("2027-01-08");
});
