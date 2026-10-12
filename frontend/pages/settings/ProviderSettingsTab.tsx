/**
 * This file loads the full language-model provider manager only when its settings tab is open.
 *
 * ProviderSettingsTab displays the existing ProviderManagementPage.
 */

import { ProviderManagementPage } from "../../components/provider-management/ProviderManagementPage";

export default function ProviderSettingsTab() {
  return <ProviderManagementPage />;
}
