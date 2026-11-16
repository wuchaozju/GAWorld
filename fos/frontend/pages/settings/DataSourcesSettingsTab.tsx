/**
 * This file loads data-source controls only when their settings tab is open.
 *
 * DataSourcesSettingsTab displays the existing DataSourceSettings panel.
 */

import { DataSourceSettings } from "../../components/DataSourceSettings";

export default function DataSourcesSettingsTab() {
  return <DataSourceSettings />;
}
