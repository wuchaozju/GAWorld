import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowRight, Sparkles } from "lucide-react";

import { Card } from "../components/ui/card";
import "../styles/routes/experiment-setup.css";

export function CreateExperimentPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const entries = [
    {
      key: "preset",
      title: t("createExperiment.entry.preset.title"),
      description: t("createExperiment.entry.preset.description"),
      onClick: () => navigate("/simulations/create/preset"),
      tone: "cool",
    },
    {
      key: "custom",
      title: t("createExperiment.entry.custom.title"),
      description: t("createExperiment.entry.custom.description"),
      onClick: () => navigate("/simulations/create/custom"),
      tone: "warm",
    },
  ];

  return (
    <div className="studio-page px-6 py-8">
      <div className="mx-auto max-w-6xl space-y-5">
        <section
          className="lab-surface overflow-hidden p-0"
          style={{
            background: `
              radial-gradient(circle at top left, color-mix(in srgb, var(--ss-brand-soft) 68%, transparent), transparent 34%),
              radial-gradient(circle at top right, color-mix(in srgb, var(--ss-info-soft, #dfeefe) 72%, transparent), transparent 28%),
              linear-gradient(180deg, color-mix(in srgb, var(--ss-page-surface) 96%, white 4%), color-mix(in srgb, var(--ss-page-surface-muted) 94%, transparent))
            `,
          }}
        >
          <div className="px-6 py-7 lg:px-8 lg:py-8">
            <div className="max-w-4xl space-y-5">
              <div className="lab-label">
                <Sparkles size={14} />
                {t("createExperiment.entry.badge")}
              </div>

              <div className="space-y-3">
                <h1
                  className="display-title m-0"
                  style={{ color: "#a57a2a" }}
                >
                  {t("createExperiment.entry.title")}
                </h1>
                <p className="lab-meta max-w-3xl text-[1.04rem]">
                  {t("createExperiment.entry.subtitle")}
                </p>
              </div>
            </div>
          </div>
        </section>

        <div className="grid gap-5 lg:grid-cols-2">
          {entries.map((entry) => {
            const isWarm = entry.tone === "warm";
            return (
              <Card
                key={entry.key}
                className="group p-0 transition-transform duration-200 hover:-translate-y-1"
                style={{
                  borderColor: isWarm
                    ? "color-mix(in srgb, var(--ss-accent-warm) 18%, var(--ss-border))"
                    : "color-mix(in srgb, #86b8f5 20%, var(--ss-border))",
                  background: isWarm
                    ? "linear-gradient(180deg, color-mix(in srgb, var(--ss-page-surface) 94%, white 6%), color-mix(in srgb, var(--ss-brand-soft) 30%, var(--ss-page-surface) 70%))"
                    : "linear-gradient(180deg, color-mix(in srgb, var(--ss-page-surface) 96%, white 4%), color-mix(in srgb, #e8f3ff 36%, var(--ss-page-surface) 64%))",
                  boxShadow: "var(--ss-shadow-card)",
                }}
              >
                <button
                  type="button"
                  onClick={entry.onClick}
                  className="flex h-full min-h-[18.5rem] w-full flex-col rounded-[1.45rem] p-7 text-left"
                >
                  <div className="flex items-start justify-end">
                    <span
                      className="rounded-full px-3 py-1 text-xs font-semibold"
                      style={{
                        border: "1px solid color-mix(in srgb, var(--ss-brand-primary) 14%, var(--ss-border))",
                        background: "color-mix(in srgb, var(--ss-page-surface) 78%, transparent)",
                        color: "var(--ss-text-muted)",
                      }}
                    >
                      {entry.key === "preset"
                        ? t("createExperiment.entry.standardFlow")
                        : t("createExperiment.entry.aiAssisted")}
                    </span>
                  </div>

                  <div className="mt-10 flex-1 space-y-4">
                    <h2
                      className="m-0 text-[3rem] font-semibold leading-[0.98] tracking-[-0.06em]"
                      style={{ color: "#a57a2a" }}
                    >
                      {entry.title}
                    </h2>
                    <p className="m-0 max-w-[34rem] text-[1.02rem] leading-7" style={{ color: "var(--ss-text-muted)" }}>
                      {entry.description}
                    </p>
                  </div>

                  <div className="mt-8 flex items-center justify-between gap-3 border-t pt-5" style={{ borderColor: "color-mix(in srgb, var(--ss-brand-primary) 10%, var(--ss-border))" }}>
                    <div className="flex items-start justify-between gap-4">
                      <div
                        className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium"
                        style={{
                          background: "color-mix(in srgb, var(--ss-page-surface) 72%, transparent)",
                          color: "var(--ss-brand-primary)",
                          border: "1px solid color-mix(in srgb, var(--ss-brand-primary) 16%, var(--ss-border))",
                        }}
                      >
                        <span>{t("createExperiment.entry.enter")}</span>
                      </div>
                    </div>
                    <div
                      className="flex h-10 w-10 items-center justify-center rounded-full transition-transform duration-200 group-hover:translate-x-1"
                      style={{
                        background: "color-mix(in srgb, var(--ss-brand-soft) 68%, var(--ss-page-surface) 32%)",
                        color: "var(--ss-brand-hover)",
                      }}
                    >
                      <ArrowRight size={18} />
                    </div>
                  </div>
                </button>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default CreateExperimentPage;
