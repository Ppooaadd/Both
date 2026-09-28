import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { defaultParams } from "@/lib/api/schemas";
import { ParameterPanel, describeTranspose, paramsEqual } from "./ParameterPanel";

describe("ParameterPanel", () => {
  it("enables submit only after a change and submits validated params", async () => {
    const onSubmit = vi.fn();
    render(<ParameterPanel initial={defaultParams("intermediate")} keyTonic={0} pending={false} onSubmit={onSubmit} />);
    const submit = screen.getByRole("button", { name: /다시 편곡/ });
    expect(submit).toBeDisabled();

    await userEvent.click(screen.getByRole("tab", { name: "고급" }));
    await userEvent.click(screen.getByRole("switch", { name: /쉬운 조/ }));
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ difficulty: "advanced", simplify_key: true, transpose: 0 }));

    await userEvent.click(screen.getByRole("button", { name: /되돌리기/ }));
    expect(submit).toBeDisabled();
  });

  it("describes transposition with the target key", () => {
    expect(describeTranspose(0, 0)).toBe("원래 조");
    expect(describeTranspose(2, 0)).toBe("+2반음 → D");
    expect(describeTranspose(-3, 0)).toBe("−3반음 → A");
    expect(paramsEqual(defaultParams(), { ...defaultParams() })).toBe(true);
  });
});
