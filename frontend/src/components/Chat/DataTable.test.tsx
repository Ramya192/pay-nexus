import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataTable } from "./DataTable";

describe("DataTable", () => {
  it("renders the title as a caption and each header", () => {
    render(
      <DataTable
        table={{
          title: "Section 80C breakdown",
          headers: ["Component", "Amount"],
          rows: [["ELSS", "₹50,000"]],
        }}
      />
    );
    expect(screen.getByText("Section 80C breakdown")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Component" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Amount" })).toBeInTheDocument();
  });

  it("right-aligns a column where every cell is a currency/count/percentage figure", () => {
    render(
      <DataTable
        table={{
          title: "t",
          headers: ["Category", "Spent", "Count", "Share"],
          rows: [
            ["Rent", "₹36,000", "2", "62%"],
            ["Groceries", "↑3,500", "1", "15%"],
          ],
        }}
      />
    );
    expect(screen.getByRole("columnheader", { name: "Spent" })).toHaveClass("text-right");
    expect(screen.getByRole("columnheader", { name: "Count" })).toHaveClass("text-right");
    expect(screen.getByRole("columnheader", { name: "Share" })).toHaveClass("text-right");
    expect(screen.getByRole("columnheader", { name: "Category" })).toHaveClass("text-left");
  });

  it("keeps a column left-aligned when even one cell in it isn't numeric", () => {
    render(
      <DataTable
        table={{
          title: "t",
          headers: ["Mixed"],
          rows: [["₹50,000"], ["Not filed yet"]],
        }}
      />
    );
    expect(screen.getByRole("columnheader", { name: "Mixed" })).toHaveClass("text-left");
  });

  it("treats a column of only empty cells as non-numeric (left-aligned), not a false positive", () => {
    render(
      <DataTable
        table={{
          title: "t",
          headers: ["Notes"],
          rows: [[""], [""]],
        }}
      />
    );
    expect(screen.getByRole("columnheader", { name: "Notes" })).toHaveClass("text-left");
  });

  it("does not treat a text value that merely starts with a digit as numeric", () => {
    render(
      <DataTable
        table={{
          title: "t",
          headers: ["Section"],
          rows: [["80C"], ["80D"]],
        }}
      />
    );
    expect(screen.getByRole("columnheader", { name: "Section" })).toHaveClass("text-left");
  });
});
