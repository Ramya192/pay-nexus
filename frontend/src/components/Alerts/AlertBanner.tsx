import { AlertTriangle, Info, X } from "lucide-react";
import { useState } from "react";
import { dismissForToday, isDismissedToday, type Alert } from "../../utils/alerts";

const SEVERITY_STYLES: Record<Alert["severity"], string> = {
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  info: "border-brand-200 bg-brand-50 text-brand-800",
};

const SEVERITY_ICON: Record<Alert["severity"], typeof AlertTriangle> = {
  warning: AlertTriangle,
  info: Info,
};

/**
 * Renders whichever of computeAlerts()'s date/data-driven alerts aren't
 * dismissed for today (§ utils/alerts.ts) as dismissible banners under the
 * header — not a blocking modal, since none of these need to interrupt the
 * user mid-task, and a modal that reappears for a whole two-month window
 * (the regime-declaration or ITR-deadline windows) would get old fast.
 */
export function AlertBanner({ alerts }: { alerts: Alert[] }) {
  const now = new Date();
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(new Set());

  const visible = alerts.filter((a) => !dismissedIds.has(a.id) && !isDismissedToday(a.id, now));
  if (visible.length === 0) return null;

  function handleDismiss(id: string) {
    dismissForToday(id, now);
    setDismissedIds((prev) => new Set(prev).add(id));
  }

  return (
    <div className="flex flex-col gap-2 border-b border-slate-200 bg-slate-50 px-4 py-2">
      {visible.map((alert) => {
        const Icon = SEVERITY_ICON[alert.severity];
        return (
          <div
            key={alert.id}
            className={`flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-sm ${SEVERITY_STYLES[alert.severity]}`}
          >
            <div className="flex items-start gap-2">
              <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div>
                <p className="font-medium">{alert.title}</p>
                <p className="mt-0.5 text-xs opacity-90">{alert.message}</p>
              </div>
            </div>
            <button
              onClick={() => handleDismiss(alert.id)}
              aria-label="Dismiss"
              className="shrink-0 opacity-70 hover:opacity-100"
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
