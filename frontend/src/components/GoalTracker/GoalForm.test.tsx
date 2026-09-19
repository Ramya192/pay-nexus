import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GoalForm } from "./GoalForm";
import { useAuthStore } from "../../store/authStore";
import { useGoalStore } from "../../store/goalStore";
import * as goalsApi from "../../api/goals";
import * as encryption from "../../crypto/clientEncryption";

vi.mock("../../crypto/clientEncryption", () => ({
  encryptJSON: vi.fn(),
}));

beforeEach(() => {
  useGoalStore.getState().clear();
  useAuthStore.getState().setAuth("tok", "salt==", "user@example.com", {} as CryptoKey);
  vi.mocked(encryption.encryptJSON).mockResolvedValue({ ciphertextB64: "ct==", ivB64: "iv==" });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("GoalForm", () => {
  it("only shows FD/mutual-fund fields once that tracking type is selected", async () => {
    const user = userEvent.setup();
    render(<GoalForm />);
    expect(screen.queryByLabelText("Principal (₹)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("AMFI scheme code")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Track this goal's value"), "fd");
    expect(screen.getByLabelText("Principal (₹)")).toBeInTheDocument();
    expect(screen.queryByLabelText("AMFI scheme code")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Track this goal's value"), "mutual_fund");
    expect(screen.queryByLabelText("Principal (₹)")).not.toBeInTheDocument();
    expect(screen.getByLabelText("AMFI scheme code")).toBeInTheDocument();
  });

  describe("validation", () => {
    it("requires a name and target amount, without calling the API", async () => {
      const user = userEvent.setup();
      const create = vi.spyOn(goalsApi, "createGoal");
      render(<GoalForm />);

      await user.click(screen.getByRole("button", { name: "Add goal" }));

      expect(screen.getByText("Name and target amount are required.")).toBeInTheDocument();
      expect(create).not.toHaveBeenCalled();
    });

    it("requires FD principal/rate/start-date when Fixed deposit tracking is selected", async () => {
      const user = userEvent.setup();
      const create = vi.spyOn(goalsApi, "createGoal");
      render(<GoalForm />);

      await user.type(screen.getByLabelText("Goal name"), "Emergency fund");
      await user.type(screen.getByLabelText("Target amount (₹)"), "200000");
      await user.selectOptions(screen.getByLabelText("Track this goal's value"), "fd");
      await user.click(screen.getByRole("button", { name: "Add goal" }));

      expect(
        screen.getByText("Principal, annual rate, and start date are required for a fixed deposit.")
      ).toBeInTheDocument();
      expect(create).not.toHaveBeenCalled();
    });

    it("requires MF scheme code/units when Mutual fund tracking is selected", async () => {
      const user = userEvent.setup();
      const create = vi.spyOn(goalsApi, "createGoal");
      render(<GoalForm />);

      await user.type(screen.getByLabelText("Goal name"), "Retirement");
      await user.type(screen.getByLabelText("Target amount (₹)"), "500000");
      await user.selectOptions(screen.getByLabelText("Track this goal's value"), "mutual_fund");
      await user.click(screen.getByRole("button", { name: "Add goal" }));

      expect(
        screen.getByText("Scheme code and units held are required for a mutual fund.")
      ).toBeInTheDocument();
      expect(create).not.toHaveBeenCalled();
    });
  });

  describe("submit", () => {
    it("saves a manual goal and resets the form", async () => {
      const user = userEvent.setup();
      vi.spyOn(goalsApi, "createGoal").mockResolvedValue({ id: "g1", created_at: "2026-01-01" });
      render(<GoalForm />);

      await user.type(screen.getByLabelText("Goal name"), "Goa Trip");
      await user.type(screen.getByLabelText("Target amount (₹)"), "100000");
      await user.type(screen.getByLabelText(/Already saved/), "20000");
      await user.click(screen.getByRole("button", { name: "Add goal" }));

      await waitFor(() => expect(useGoalStore.getState().entries).toHaveLength(1));
      const saved = useGoalStore.getState().entries[0];
      expect(saved.data).toEqual({
        name: "Goa Trip",
        category: "Trip",
        targetAmount: 100_000,
        targetDate: undefined,
        savedAmount: 20_000,
      });
      expect(screen.getByLabelText("Goal name")).toHaveValue("");
    });

    it("saves an FD-linked goal with its instrument fields, defaulting savedAmount to 0 when left blank", async () => {
      const user = userEvent.setup();
      vi.spyOn(goalsApi, "createGoal").mockResolvedValue({ id: "g2", created_at: "2026-01-01" });
      render(<GoalForm />);

      await user.type(screen.getByLabelText("Goal name"), "Emergency fund");
      await user.type(screen.getByLabelText("Target amount (₹)"), "200000");
      await user.selectOptions(screen.getByLabelText("Track this goal's value"), "fd");
      await user.type(screen.getByLabelText("Principal (₹)"), "45000");
      await user.type(screen.getByLabelText("Annual rate (%)"), "7");
      await user.type(screen.getByLabelText("Opened on"), "2025-01-01");
      await user.click(screen.getByRole("button", { name: "Add goal" }));

      await waitFor(() => expect(useGoalStore.getState().entries).toHaveLength(1));
      expect(useGoalStore.getState().entries[0].data).toEqual({
        name: "Emergency fund",
        category: "Trip",
        targetAmount: 200_000,
        targetDate: undefined,
        savedAmount: 0,
        instrumentType: "fd",
        fdPrincipal: 45_000,
        fdAnnualRate: 7,
        fdStartDate: "2025-01-01",
      });
    });

    it("shows an error and keeps the form filled in (not reset) when the save fails", async () => {
      const user = userEvent.setup();
      vi.spyOn(goalsApi, "createGoal").mockRejectedValue(new Error("network"));
      render(<GoalForm />);

      await user.type(screen.getByLabelText("Goal name"), "Goa Trip");
      await user.type(screen.getByLabelText("Target amount (₹)"), "100000");
      await user.click(screen.getByRole("button", { name: "Add goal" }));

      await waitFor(() =>
        expect(screen.getByText("Couldn't save that goal — try again.")).toBeInTheDocument()
      );
      expect(useGoalStore.getState().entries).toEqual([]);
      expect(screen.getByLabelText("Goal name")).toHaveValue("Goa Trip");
    });
  });
});
