---
name: screenshot
description: Use when the user wants to take a screenshot of a specific part of the UI or the entire screen. This skill instructs the agent to identify the UI elements or tabs to capture and provides the standard procedure for capturing screenshots in a browser environment.
---

# Screenshot Skill

Use this skill to help the user capture screenshots of the opencode interface. 

Since the opencode harness is a web UI, screenshots should be taken using a browser extension or a headless browser command. 

### Instructions for the User:
1. **Identify the Target**: Determine which tab (Search, Models, Benchmarks, Chat, Traces, Status, or Logs) needs a screenshot.
2. **Capture Method**:
   - If using **GoFullPage**, click the extension icon to capture the entire scrollable area.
   - If using **Awesome Screenshot**, select the specific card or data row to highlight.
   - If using **Lightshot**, use the hotkey to drag a box over the specific UI element.

### Screenshot Checklist:
- Ensure the correct tab is active.
- Make sure all relevant data (e.g., benchmark results, log lines) are visible on the screen.
- If capturing the **Status** tab, ensure the sparklines are active and showing the required data.
- Capture the full width of the browser to ensure no UI elements are cut off.

### Verification:
Confirm that the screenshot clearly shows the requested information and that all labels/buttons are legible.
