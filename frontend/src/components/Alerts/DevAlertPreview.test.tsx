import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DevAlertPreview, resolvePreviewDate } from "./DevAlertPreview";

describe("DevAlertPreview", () => {
  it("calls onChange with the newly selected preview key", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<DevAlertPreview value="real" onChange={onChange} />);
    await user.selectOptions(screen.getByRole("combobox"), "itr");
    expect(onChange).toHaveBeenCalledWith("itr");
  });

  it("shows the extra 'Investments & loans' hint only for the headroom preview", () => {
    const { rerender } = render(<DevAlertPreview value="itr" onChange={vi.fn()} />);
    expect(screen.queryByText(/also needs the "Investments/)).not.toBeInTheDocument();

    rerender(<DevAlertPreview value="headroom" onChange={vi.fn()} />);
    expect(screen.getByText(/also needs the "Investments/)).toBeInTheDocument();
  });
});

describe("resolvePreviewDate", () => {
  it("returns null-mapped 'real' as today's actual date (not a fixed preview date)", () => {
    const before = Date.now();
    const resolved = resolvePreviewDate("real").getTime();
    const after = Date.now();
    expect(resolved).toBeGreaterThanOrEqual(before);
    expect(resolved).toBeLessThanOrEqual(after);
  });

  it("resolves 'itr' to a date inside the June-July ITR reminder window (July 26)", () => {
    const d = resolvePreviewDate("itr");
    expect(d.getMonth()).toBe(6); // July, 0-indexed
    expect(d.getDate()).toBe(26);
  });

  it("resolves 'regime' to March 15 (inside the Feb-April regime window)", () => {
    const d = resolvePreviewDate("regime");
    expect(d.getMonth()).toBe(2);
    expect(d.getDate()).toBe(15);
  });

  it("resolves 'headroom' to February 10 (inside the Jan-March headroom window)", () => {
    const d = resolvePreviewDate("headroom");
    expect(d.getMonth()).toBe(1);
    expect(d.getDate()).toBe(10);
  });

  it("falls back to the real current date for an unrecognized key", () => {
    const before = Date.now();
    const resolved = resolvePreviewDate("nonsense-key").getTime();
    const after = Date.now();
    expect(resolved).toBeGreaterThanOrEqual(before);
    expect(resolved).toBeLessThanOrEqual(after);
  });
});
