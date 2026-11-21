import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { App } from "./app";
import { HourlyBars } from "./components/hourly-bars";
import i18n, { setLanguage } from "./i18n";
import en from "./i18n/en.json";
import fr from "./i18n/fr.json";
import wo from "./i18n/wo.json";
import { AuthProvider } from "./lib/auth";

function keys(obj: object, prefix = ""): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    typeof v === "object" && v !== null ? keys(v as object, `${prefix}${k}.`) : [`${prefix}${k}`],
  );
}

function renderApp() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("web app", () => {
  beforeEach(() => {
    localStorage.clear();
    void i18n.changeLanguage("fr");
  });

  it("AC-F7-4: renders the login in French by default", () => {
    renderApp();
    expect(screen.getByText(fr.login.title)).toBeInTheDocument();
    expect(screen.getByText(fr.login.send)).toBeInTheDocument();
  });

  it("AC-F7-4: fr, wo and en have the same keys; English is selectable", () => {
    expect(keys(wo).sort()).toEqual(keys(fr).sort());
    expect(keys(en).sort()).toEqual(keys(fr).sort());
    renderApp();
    act(() => setLanguage("en"));
    expect(screen.getByText(en.login.send)).toBeInTheDocument();
  });

  it("verdict wording matches docs/06 (rule 4)", () => {
    expect(fr.verdict.normal).toBe("Journée normale.");
    expect(fr.verdict.large_gap).toBe("Écart important : beaucoup de clients servis, peu d'argent enregistré.");
    const all = JSON.stringify(fr).toLowerCase();
    for (const word of ["vol", "voleur", "fraude"]) expect(all).not.toMatch(new RegExp(`\\b${word}\\b`));
  });

  it("rule 3: missing hours are hatched, not drawn as zero bars", () => {
    const hours = Array.from({ length: 24 }, (_, h) => ({
      hour: h,
      entries: h === 9 ? 4 : 0,
      served: 0,
      waits: 0,
      sales_xof: 0,
      missing: h === 14,
    }));
    render(<HourlyBars hours={hours} />);
    expect(screen.getByTestId("hour-14").dataset.missing).toBe("true");
    expect(screen.getByTestId("hour-9").dataset.missing).toBeUndefined();
  });
});
