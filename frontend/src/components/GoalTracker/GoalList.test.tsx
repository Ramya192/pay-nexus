import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GoalList } from "./GoalList";
import { useGoalStore, type Goal, type GoalEntry } from "../../store/goalStore";
import { useAuthStore } from "../../store/authStore";
import * as goalsApi from "../../api/goals";
import * as encryption from "../../crypto/clientEncryption";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));

const manualGoal: Goal = {
  name: "Vacation",
  category: "Trip",
  targetAmount: 100_000,
  savedAmount: 40_000,
};
const manualEntry: GoalEntry = { id: "g1", createdAt: "2026-01-01", data: manualGoal };

const fdGoal: Goal = {
  name: "Emergency fund",
  category: "Emergency Fund",
  targetAmount: 200_000,
  savedAmount: 50_000,
  instrumentType: "fd",
  fdPrincipal: 45_000,
  fdAnnualRate: 7,
  fdStartDate: "2025-01-01",
};
const fdEntry: GoalEntry = { id: "g2", createdAt: "2026-01-01", data: fdGoal };

beforeEach(() => {
  useGoalStore.getState().clear();
  useAuthStore.getState().logout();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GoalList", () => {
  it("shows an empty state with no goals", () => {
    render(<GoalList />);
    expect(screen.getByText("No financial goals added yet.")).toBeInTheDocument();
  });

  it("renders a manual goal's progress as whole rupees, capped at 100%", () => {
    useGoalStore.getState().setEntries([manualEntry]);
    render(<GoalList />);
    expect(screen.getByText("Vacation")).toBeInTheDocument();
    expect(screen.getByText(/₹40,000 of ₹1,00,000 \(40%\)/)).toBeInTheDocument();
  });

  it("caps displayed progress at 100% even if savedAmount exceeds targetAmount", () => {
    useGoalStore.getState().setEntries([
      { id: "g3", createdAt: "2026-01-01", data: { ...manualGoal, savedAmount: 150_000 } },
    ]);
    render(<GoalList />);
    expect(screen.getByText(/\(100%\)/)).toBeInTheDocument();
  });

  it("fetches live valuations only for instrument-linked goals, not manual ones, and shows the result rounded to whole rupees (regression: this is the same decimal-formatting bug fixed elsewhere today)", async () => {
    const fetchValuations = vi
      .spyOn(goalsApi, "fetchGoalValuations")
      .mockResolvedValue([{ goal_id: "g2", current_value: 47_832.156, error: null }]);
    useGoalStore.getState().setEntries([manualEntry, fdEntry]);
    render(<GoalList />);

    await waitFor(() => expect(fetchValuations).toHaveBeenCalled());
    // Only the FD-linked goal is requested -- the manual goal is never sent.
    expect(fetchValuations.mock.calls[0][0]).toEqual([
      { goal_id: "g2", instrument_type: "fd", fd_principal: 45_000, fd_annual_rate: 7, fd_start_date: "2025-01-01" },
    ]);

    await waitFor(() => expect(screen.getByText(/₹47,832 of/)).toBeInTheDocument());
    expect(screen.queryByText(/₹47,832\.156/)).not.toBeInTheDocument();
    expect(screen.getByText(/live FD value/)).toBeInTheDocument();
  });

  it("shows a per-goal valuation error and falls back to the last-known figure, without blocking other goals", async () => {
    vi.spyOn(goalsApi, "fetchGoalValuations").mockResolvedValue([
      { goal_id: "g2", current_value: null, error: "Setu sandbox timeout" },
    ]);
    useGoalStore.getState().setEntries([fdEntry]);
    render(<GoalList />);

    await waitFor(() =>
      expect(screen.getByText(/Couldn't fetch a live value: Setu sandbox timeout/)).toBeInTheDocument()
    );
    // Last-known saved figure still shown, not blanked out.
    expect(screen.getByText(/₹50,000 of/)).toBeInTheDocument();
  });

  it("an instrument-linked goal cannot be manually edited (no 'Update progress' control)", () => {
    useGoalStore.getState().setEntries([fdEntry]);
    render(<GoalList />);
    expect(screen.queryByText("Update progress")).not.toBeInTheDocument();
    expect(screen.getByText(/Value tracked automatically/)).toBeInTheDocument();
  });

  describe("manual progress update", () => {
    beforeEach(() => {
      useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
    });

    it("saves a valid amount and exits edit mode", async () => {
      const user = userEvent.setup();
      vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
      const update = vi
        .spyOn(goalsApi, "updateGoal")
        .mockResolvedValue({ id: "g1", created_at: "2026-01-01" });
      useGoalStore.getState().setEntries([manualEntry]);
      render(<GoalList />);

      await user.click(screen.getByText("Update progress"));
      const input = screen.getByRole("spinbutton");
      await user.clear(input);
      await user.type(input, "60000");
      await user.click(screen.getByRole("button", { name: "Save" }));

      await waitFor(() => expect(update).toHaveBeenCalled());
      expect(useGoalStore.getState().entries[0].data.savedAmount).toBe(60_000);
      expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    });

    it("rejects a negative or non-numeric amount without calling the API", async () => {
      const user = userEvent.setup();
      const update = vi.spyOn(goalsApi, "updateGoal");
      useGoalStore.getState().setEntries([manualEntry]);
      render(<GoalList />);

      await user.click(screen.getByText("Update progress"));
      const input = screen.getByRole("spinbutton");
      await user.clear(input);
      await user.type(input, "-5");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(screen.getByText("Enter a valid amount.")).toBeInTheDocument();
      expect(update).not.toHaveBeenCalled();
    });

    it("Cancel restores the original amount and exits edit mode without saving", async () => {
      const user = userEvent.setup();
      const update = vi.spyOn(goalsApi, "updateGoal");
      useGoalStore.getState().setEntries([manualEntry]);
      render(<GoalList />);

      await user.click(screen.getByText("Update progress"));
      await user.clear(screen.getByRole("spinbutton"));
      await user.type(screen.getByRole("spinbutton"), "99999");
      await user.click(screen.getByRole("button", { name: "Cancel" }));

      expect(update).not.toHaveBeenCalled();
      expect(screen.getByText("Update progress")).toBeInTheDocument();
      expect(useGoalStore.getState().entries[0].data.savedAmount).toBe(40_000);
    });
  });

  describe("delete", () => {
    it("does nothing when the confirm dialog is cancelled", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(false);
      const del = vi.spyOn(goalsApi, "deleteGoal");
      useGoalStore.getState().setEntries([manualEntry]);
      render(<GoalList />);

      await user.click(screen.getByRole("button", { name: "Delete" }));

      expect(del).not.toHaveBeenCalled();
      expect(useGoalStore.getState().entries).toHaveLength(1);
    });

    it("removes the goal once confirmed and the API call succeeds", async () => {
      const user = userEvent.setup();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      vi.spyOn(goalsApi, "deleteGoal").mockResolvedValue();
      useGoalStore.getState().setEntries([manualEntry]);
      render(<GoalList />);

      await user.click(screen.getByRole("button", { name: "Delete" }));

      await waitFor(() => expect(useGoalStore.getState().entries).toHaveLength(0));
    });
  });
});
