import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import { App } from "./App";
import en from "./i18n/en.json";
import fr from "./i18n/fr.json";
import wo from "./i18n/wo.json";

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

describe("M0 scaffold", () => {
  it("renders in French by default (AC-F7-4)", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(
      <QueryClientProvider client={new QueryClient()}>
        <App />
      </QueryClientProvider>,
    );
    expect(screen.getByText(fr.app.tagline)).toBeInTheDocument();
  });

  it("has the same i18n keys in fr, wo and en (AC-F7-4)", () => {
    expect(keys(wo).sort()).toEqual(keys(fr).sort());
    expect(keys(en).sort()).toEqual(keys(fr).sort());
  });
});
