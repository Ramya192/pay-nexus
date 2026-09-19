import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PayslipHistoryList } from "./PayslipHistoryList";
import { usePayslipHistoryStore, type SnapshotEntry } from "../../store/payslipHistoryStore";
import * as payslipApi from "../../api/payslip";

const jan: SnapshotEntry = { id: "1", createdAt: "2026-01-01T00:00:00Z", data: { month: "2026-01" } };
const feb: SnapshotEntry = { id: "2", createdAt: "2026-02-01T00:00:00Z", data: { month: "2026-02" } };
const janDupeOlder: SnapshotEntry = { id: "3", createdAt: "2025-12-01T00:00:00Z", data: { month: "2026-01" } };
const janDupeNewer: SnapshotEntry = { id: "4", createdAt: "2026-03-01T00:00:00Z", data: { month: "2026-01" } };

beforeEach(() => {
  usePayslipHistoryStore.getState().clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PayslipHistoryList", () => {
  it("shows an empty state with nothing saved", () => {
    render(<PayslipHistoryList />);
    expect(screen.getByText("No payslips saved to history yet.")).toBeInTheDocument();
  });

  it("lists saved months sorted, with no duplicate banner when every month is unique", () => {
    usePayslipHistoryStore.getState().setEntries([feb, jan]);
    render(<PayslipHistoryList />);
    expect(screen.queryByText(/duplicate/)).not.toBeInTheDocument();
    const months = screen.getAllByText(/^2026-0/).map((el) => el.textContent);
    expect(months).toEqual(["2026-01", "2026-02"]); // sorted, Jan before Feb
  });

  it("falls back to 'unknown month' when a saved entry has no month field", () => {
    usePayslipHistoryStore.getState().setEntries([{ id: "5", createdAt: "2026-01-01", data: {} }]);
    render(<PayslipHistoryList />);
    expect(screen.getByText("unknown month")).toBeInTheDocument();
  });

  describe("duplicate detection", () => {
    it("shows the duplicate count banner (singular wording for exactly one duplicate)", () => {
      usePayslipHistoryStore.getState().setEntries([jan, janDupeOlder]);
      render(<PayslipHistoryList />);
      expect(screen.getByText("1 duplicate entry found.")).toBeInTheDocument();
    });

    it("uses plural wording for more than one duplicate", () => {
      usePayslipHistoryStore.getState().setEntries([jan, janDupeOlder, janDupeNewer]);
      render(<PayslipHistoryList />);
      expect(screen.getByText("2 duplicate entries found.")).toBeInTheDocument();
    });

    it("Remove duplicates keeps the most recently saved entry per month and deletes the rest, after confirming", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const del = vi.spyOn(payslipApi, "deleteSnapshot").mockResolvedValue();
      usePayslipHistoryStore.getState().setEntries([jan, janDupeOlder, janDupeNewer, feb]);
      render(<PayslipHistoryList />);

      await user.click(screen.getByRole("button", { name: "Remove duplicates" }));

      await waitFor(() => expect(usePayslipHistoryStore.getState().entries).toHaveLength(2));
      const remainingIds = usePayslipHistoryStore.getState().entries.map((e) => e.id).sort();
      // janDupeNewer (id 4) is the most recently created for 2026-01 -- kept; jan/janDupeOlder deleted.
      expect(remainingIds).toEqual(["2", "4"]);
      expect(del).toHaveBeenCalledWith("1");
      expect(del).toHaveBeenCalledWith("3");
      expect(del).not.toHaveBeenCalledWith("4");
    });

    it("does nothing when the confirm dialog is cancelled", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(false);
      const del = vi.spyOn(payslipApi, "deleteSnapshot");
      usePayslipHistoryStore.getState().setEntries([jan, janDupeOlder]);
      render(<PayslipHistoryList />);

      await user.click(screen.getByRole("button", { name: "Remove duplicates" }));

      expect(del).not.toHaveBeenCalled();
      expect(usePayslipHistoryStore.getState().entries).toHaveLength(2);
    });
  });

  describe("delete one entry", () => {
    it("does nothing when cancelled", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(false);
      const del = vi.spyOn(payslipApi, "deleteSnapshot");
      usePayslipHistoryStore.getState().setEntries([jan]);
      render(<PayslipHistoryList />);

      await user.click(screen.getByTitle("Delete this saved payslip"));

      expect(del).not.toHaveBeenCalled();
    });

    it("removes the entry once confirmed and the API call succeeds", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      vi.spyOn(payslipApi, "deleteSnapshot").mockResolvedValue();
      usePayslipHistoryStore.getState().setEntries([jan]);
      render(<PayslipHistoryList />);

      await user.click(screen.getByTitle("Delete this saved payslip"));

      await waitFor(() => expect(usePayslipHistoryStore.getState().entries).toHaveLength(0));
    });

    it("shows an error and keeps the entry when the API call fails", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      vi.spyOn(payslipApi, "deleteSnapshot").mockRejectedValue(new Error("network"));
      usePayslipHistoryStore.getState().setEntries([jan]);
      render(<PayslipHistoryList />);

      await user.click(screen.getByTitle("Delete this saved payslip"));

      await waitFor(() => expect(screen.getByText("Couldn't delete that entry — try again.")).toBeInTheDocument());
      expect(usePayslipHistoryStore.getState().entries).toHaveLength(1);
    });
  });
});
