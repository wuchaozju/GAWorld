/**
 * This file manages uploaded files only when the files settings tab is open.
 *
 * FileSettingsTab lists files, deletes selected files, and checks for unused uploads.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { TrashIcon } from "@radix-ui/react-icons";
import { Database, FileStack } from "lucide-react";
import { useTranslation } from "react-i18next";

import { deleteUpload, findOrphans, listUploads } from "../../services/uploads";

function formatSize(bytes: number, byteLabel: string, kbLabel: string, mbLabel: string): string {
  if (bytes < 1024) return `${bytes}${byteLabel}`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}${kbLabel}`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}${mbLabel}`;
}

export default function FileSettingsTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [orphanResult, setOrphanResult] = useState<{ orphaned: string[]; total: number } | null>(null);
  const [findingOrphans, setFindingOrphans] = useState(false);
  const filesQuery = useQuery({ queryKey: ["uploads"], queryFn: listUploads });
  const uploads = filesQuery.data ?? [];
  const deleteFile = useMutation({
    mutationFn: deleteUpload,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["uploads"] }),
  });

  const scanForOrphans = async (): Promise<void> => {
    setFindingOrphans(true);
    try {
      setOrphanResult(await findOrphans());
    } finally {
      setFindingOrphans(false);
    }
  };

  return (
    <div className="ss-settings-section">
      <div className="ss-settings-grid">
        <div className="ss-settings-metric ss-inset"><FileStack size={16} /><div><span>{t("settings.files.metrics.files")}</span><strong>{uploads.length}</strong></div></div>
        <div className="ss-settings-metric ss-inset"><Database size={16} /><div><span>{t("settings.files.metrics.orphanScan")}</span><strong>{orphanResult?.orphaned.length ?? "-"}</strong></div></div>
      </div>
      <section className="card">
        <div className="panel-title">{t("settings.files.title")}</div>
        <div className="panel-subtitle">{t("settings.files.description")}</div>
        {filesQuery.isLoading ? <div>{t("settings.files.loading")}</div> : null}
        {filesQuery.isError ? <div className="ss-settings-error">{t("settings.files.error")}</div> : null}
        {uploads.length > 0 ? (
          <div className="ss-data-table-wrap">
            <table className="ss-data-table">
              <thead><tr><th>{t("settings.files.table.filename")}</th><th>{t("settings.files.table.type")}</th><th>{t("settings.files.table.size")}</th><th>{t("settings.files.table.created")}</th><th>{t("settings.files.table.actions")}</th></tr></thead>
              <tbody>
                {uploads.map((file) => (
                  <tr key={file.id}>
                    <td title={file.filename}>{file.filename}</td><td>{file.type || "-"}</td>
                    <td>{formatSize(file.size, t("settings.files.byte"), t("settings.files.kb"), t("settings.files.mb"))}</td>
                    <td>{new Date(file.created * 1000).toLocaleString()}</td>
                    <td><button type="button" className="icon-button square" aria-label={t("settings.files.delete")} onClick={() => window.confirm(t("settings.files.deleteConfirm")) && deleteFile.mutate(file.id)}><TrashIcon /></button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {!uploads.length && !filesQuery.isLoading ? <div className="ss-empty-state ss-inset">{t("settings.files.empty")}</div> : null}
      </section>
      <section className="card">
        <div className="panel-title">{t("settings.files.maintenanceTitle")}</div>
        <div className="panel-subtitle">{t("settings.files.maintenanceHint")}</div>
        <div className="ss-settings-action-row">
          <button type="button" className="ss-button-secondary" onClick={() => void scanForOrphans()} disabled={findingOrphans}>
            {findingOrphans ? "..." : t("settings.files.findOrphans")}
          </button>
          <span className="panel-subtitle">{orphanResult?.orphaned.length ? t("settings.files.orphansFound", { count: orphanResult.orphaned.length }) : t("settings.files.noOrphans")}</span>
        </div>
      </section>
    </div>
  );
}
