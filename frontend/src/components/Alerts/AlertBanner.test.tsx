import { beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AlertBanner } from "./AlertBanner";
import type { Alert } from "../../utils/alerts";

const warningAlert: Alert = {
  id: "budget-overspending",
  title: "Over budget on Rent",
  message: "₹36,000 spent vs ₹27,201 budgeted",
  severity: "warning",
};

const infoAlert: Alert = {
  id: "stale-payslip",
  title: "Your payslip history hasn't been updated in a while",
  message: "Your most recent saved payslip is from 2026-03",
  severity: "info",
};

beforeEach(() => {
  localStorage.clear();
});

describe("AlertBanner", () => {
  it("renders nothing when there are no alerts", () => {
    const { container } = render(<AlertBanner alerts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders each alert's title and message", () => {
    render(<AlertBanner alerts={[warningAlert, infoAlert]} />);
    expect(screen.getByText(warningAlert.title)).toBeInTheDocument();
    expect(screen.getByText(warningAlert.message)).toBeInTheDocument();
    expect(screen.getByText(infoAlert.title)).toBeInTheDocument();
  });

  it("hides an alert already dismissed today (localStorage), without re-rendering it at all", () => {
    localStorage.setItem(`paynexus_alert_dismissed_${warningAlert.id}`, new Date().toISOString().slice(0, 10));
    render(<AlertBanner alerts={[warningAlert, infoAlert]} />);
    expect(screen.queryByText(warningAlert.title)).not.toBeInTheDocument();
    expect(screen.getByText(infoAlert.title)).toBeInTheDocument();
  });

  it("dismissing one alert hides only that one and persists the dismissal to localStorage", async () => {
    const user = userEvent.setup();
    render(<AlertBanner alerts={[warningAlert, infoAlert]} />);

    // Two alerts render, so two Dismiss buttons -- click the first one (warningAlert's).
    await user.click(screen.getAllByRole("button", { name: "Dismiss" })[0]);

    expect(screen.queryByText(warningAlert.title)).not.toBeInTheDocument();
    expect(screen.getByText(infoAlert.title)).toBeInTheDocument();
    expect(localStorage.getItem(`paynexus_alert_dismissed_${warningAlert.id}`)).toBe(
      new Date().toISOString().slice(0, 10)
    );
  });

  it("renders nothing once every alert is dismissed", async () => {
    const user = userEvent.setup();
    const { container } = render(<AlertBanner alerts={[warningAlert]} />);
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(container).toBeEmptyDOMElement();
  });
});
