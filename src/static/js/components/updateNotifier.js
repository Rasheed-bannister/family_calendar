/**
 * Update Notifier Component
 * Settings gear button with notification badge and update panel.
 * Periodically checks for new releases and allows in-app upgrades.
 */
const UpdateNotifier = (function () {
  const CHECK_INTERVAL = 6 * 60 * 60 * 1000; // Check every 6 hours
  let checkTimer = null;
  let gearButton = null;
  let panel = null;
  let updateData = null; // Cached update check result
  let upgradePollingTimer = null;

  // --- DOM Creation ---

  function createGearButton() {
    gearButton = document.createElement("button");
    gearButton.className = "settings-gear-button";
    gearButton.setAttribute("aria-label", "Settings");
    gearButton.innerHTML = '<i class="fas fa-cog"></i><span class="settings-badge" style="display:none"></span>';
    gearButton.addEventListener("click", handleGearClick);
    document.body.appendChild(gearButton);
  }

  function createPanel() {
    panel = document.createElement("div");
    panel.className = "settings-panel";
    panel.style.display = "none";
    panel.innerHTML = `
      <div class="settings-panel-header">
        <span>Settings</span>
        <button class="settings-panel-close" aria-label="Close">&times;</button>
      </div>
      <div class="settings-panel-body">
        <div class="settings-version-row">
          <span class="settings-label">Version</span>
          <span class="settings-value" id="settings-current-version">...</span>
        </div>
        <div class="settings-update-section" id="settings-update-section">
          <span class="settings-update-status" id="settings-update-status">Checking...</span>
        </div>
        <div class="settings-actions">
          <button class="settings-btn" id="settings-check-btn">Check for updates</button>
          <button class="settings-btn settings-btn-primary" id="settings-apply-btn" style="display:none">Apply update</button>
        </div>
        <div class="settings-upgrade-progress" id="settings-upgrade-progress" style="display:none">
          <span id="settings-upgrade-message"></span>
        </div>
      </div>
    `;
    document.body.appendChild(panel);

    // Wire up panel events
    panel.querySelector(".settings-panel-close").addEventListener("click", closePanel);
    panel.querySelector("#settings-check-btn").addEventListener("click", handleCheckClick);
    panel.querySelector("#settings-apply-btn").addEventListener("click", handleApplyClick);
  }

  // --- Event Handlers ---

  function handleGearClick(e) {
    e.stopPropagation();
    if (panel.style.display === "none") {
      openPanel();
    } else {
      closePanel();
    }
  }

  function openPanel() {
    panel.style.display = "block";
    refreshPanelContent();
  }

  function closePanel() {
    panel.style.display = "none";
  }

  function handleDocumentClick(e) {
    if (panel && panel.style.display !== "none" && !panel.contains(e.target) && !gearButton.contains(e.target)) {
      closePanel();
    }
  }

  async function handleCheckClick() {
    const statusEl = panel.querySelector("#settings-update-status");
    statusEl.textContent = "Checking...";
    await checkForUpdate();
    refreshPanelContent();
  }

  async function handleApplyClick() {
    if (!updateData || !updateData.latest_version) return;

    const applyBtn = panel.querySelector("#settings-apply-btn");
    applyBtn.disabled = true;
    applyBtn.textContent = "Upgrading...";

    const progressEl = panel.querySelector("#settings-upgrade-progress");
    const messageEl = panel.querySelector("#settings-upgrade-message");
    progressEl.style.display = "block";
    messageEl.textContent = "Starting upgrade...";

    try {
      const tag = "v" + updateData.latest_version;
      const resp = await fetch("/api/upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tag }),
      });
      const result = await resp.json();

      if (result.success) {
        messageEl.textContent = result.message;
        startUpgradePolling();
      } else {
        messageEl.textContent = result.message;
        applyBtn.disabled = false;
        applyBtn.textContent = "Apply update";
      }
    } catch (error) {
      messageEl.textContent = "Failed to start upgrade.";
      applyBtn.disabled = false;
      applyBtn.textContent = "Apply update";
    }
  }

  // --- Upgrade Polling ---

  function startUpgradePolling() {
    if (upgradePollingTimer) clearInterval(upgradePollingTimer);

    upgradePollingTimer = setInterval(async () => {
      try {
        const resp = await fetch("/api/upgrade/status");
        const status = await resp.json();
        const messageEl = panel.querySelector("#settings-upgrade-message");

        if (messageEl) {
          messageEl.textContent = status.message;
        }

        if (status.state === "restarting") {
          clearInterval(upgradePollingTimer);
          upgradePollingTimer = null;
          if (messageEl) {
            messageEl.textContent = "Restarting... page will reload shortly.";
          }
          // Poll until server comes back, then reload
          waitForRestart();
        } else if (status.state === "error" || status.state === "done") {
          clearInterval(upgradePollingTimer);
          upgradePollingTimer = null;
          const applyBtn = panel.querySelector("#settings-apply-btn");
          if (applyBtn) {
            applyBtn.disabled = false;
            applyBtn.textContent = "Apply update";
          }
        }
      } catch (error) {
        // Server might be restarting
        clearInterval(upgradePollingTimer);
        upgradePollingTimer = null;
        waitForRestart();
      }
    }, 2000);
  }

  function waitForRestart() {
    let attempts = 0;
    const maxAttempts = 30;

    const poller = setInterval(async () => {
      attempts++;
      try {
        const resp = await fetch("/api/version", { cache: "no-store" });
        if (resp.ok) {
          clearInterval(poller);
          window.location.reload();
        }
      } catch (e) {
        // Server still down, keep polling
      }
      if (attempts >= maxAttempts) {
        clearInterval(poller);
        const messageEl = panel ? panel.querySelector("#settings-upgrade-message") : null;
        if (messageEl) {
          messageEl.textContent = "Server did not restart in time. Please reload manually.";
        }
      }
    }, 3000);
  }

  // --- Update Check ---

  async function checkForUpdate() {
    try {
      const response = await fetch("/api/version?check_update=true");
      if (!response.ok) return;
      updateData = await response.json();
      updateBadge();
    } catch (error) {
      // Silently ignore
    }
  }

  function updateBadge() {
    if (!gearButton) return;
    const badge = gearButton.querySelector(".settings-badge");
    if (updateData && updateData.update_available) {
      badge.style.display = "block";
    } else {
      badge.style.display = "none";
    }
  }

  function refreshPanelContent() {
    if (!panel) return;

    const versionEl = panel.querySelector("#settings-current-version");
    const statusEl = panel.querySelector("#settings-update-status");
    const applyBtn = panel.querySelector("#settings-apply-btn");

    if (updateData) {
      versionEl.textContent = updateData.current_version || "unknown";

      if (updateData.update_available) {
        statusEl.textContent = `v${updateData.latest_version} available`;
        statusEl.className = "settings-update-status has-update";
        applyBtn.style.display = "inline-block";
        applyBtn.textContent = `Update to v${updateData.latest_version}`;
      } else {
        statusEl.textContent = "Up to date";
        statusEl.className = "settings-update-status up-to-date";
        applyBtn.style.display = "none";
      }
    } else {
      versionEl.textContent = "...";
      statusEl.textContent = "Not checked yet";
      statusEl.className = "settings-update-status";
      applyBtn.style.display = "none";
    }
  }

  // --- Public API ---

  return {
    init: function () {
      createGearButton();
      createPanel();
      document.addEventListener("click", handleDocumentClick);

      // Initial check after a short delay to not slow down page load
      setTimeout(checkForUpdate, 30000);
      checkTimer = setInterval(checkForUpdate, CHECK_INTERVAL);
      return true;
    },

    cleanup: function () {
      if (checkTimer) {
        clearInterval(checkTimer);
        checkTimer = null;
      }
      if (upgradePollingTimer) {
        clearInterval(upgradePollingTimer);
        upgradePollingTimer = null;
      }
      document.removeEventListener("click", handleDocumentClick);
      if (gearButton && gearButton.parentNode) {
        gearButton.parentNode.removeChild(gearButton);
        gearButton = null;
      }
      if (panel && panel.parentNode) {
        panel.parentNode.removeChild(panel);
        panel = null;
      }
      updateData = null;
    },
  };
})();

export default UpdateNotifier;
