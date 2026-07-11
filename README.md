# Nexus Download Collection (NDC) — Python CLI

An automated downloader for NexusMods collections. This tool provides a workaround for **non-Premium users** to download entire collections directly within Vortex without clicking "slow download" for every single mod.

---

## 🚀 How to Run

Simply double-click **`Run NDC.bat`** (or run `python ndc.py` in your terminal).

---

## ⚙️ Download Modes

On first run (or if `ndc_config.json` is deleted), the tool will guide you through a quick setup to set your **API Key**, **Cookie String**, and **Mode**:

### 1. Cookie Mode (Recommended for Non-Premium)
* **How it works:** Uses your browser session cookies to scrape keyed NXM download links, bypassing the "Premium Required" prompt.
* **Flow:** Triggers Windows to send these keyed NXM links directly to **Vortex**. Vortex then downloads the files internally in the background without prompting you.
* **Note:** No Chrome/browser download settings need to be modified. Everything is handled directly by Vortex.

### 2. API Mode
* **How it works:** Generates standard `nxm://` collection download links using your Nexus API key.
* **Flow:** Sends links straight to your Vortex mod manager.
* **Note:** Non-Premium users will see the "Premium Required" slow download webpage inside Vortex for every mod in this mode.

---

## 🛠️ Step-by-Step Guide for Cookie Mode

To download mods automatically directly inside Vortex:

### Step 1: Cancel Ongoing Vortex Installs
If Vortex is currently prompting you with download dialogs, click **Cancel** on the install process inside Vortex.

### Step 2: Run the Script
1. Run **`Run NDC.bat`**.
2. Select **Option 1 (Download a collection)**.
3. Paste the NexusMods Collection URL.
4. Select which mods to download (All, Mandatory, or Optional).
5. The script will automatically trigger Vortex to download the files one-by-one.

### Step 3: Install in Vortex
1. Once Vortex finishes downloading the files, go to the **Downloads** tab on the left sidebar.
2. Click **Install All**!

---

## ⚙️ Modifying Settings
Run the script, select **Option 2 (Settings)** to:
* Switch between **Cookie** and **API** modes.
* Re-paste or update your API key / Cookie string.
* Adjust the pause time between downloads (default: 5 seconds).
* Adjust download speed limits.
