# WORK LOG – ID CARD MAKER

---

## STEP D1 – SYSTEM ANALYSIS

### Objective
Understand architecture and define migration plan.

### Files Reviewed
- idcard_maker/app.py
- idcard_maker/ui/layout.py
- idcard_maker/controllers/actions.py
- idcard_maker/services/generation.py
- idcard_maker/core/render.py

### Findings
- UI tightly coupled to Toga
- Business logic already modular
- Backend extraction feasible without major rewrite

### Result
READY FOR API EXTRACTION

---

## NEXT STEP
D2 – Backend API Layer

---

## STEP D2 – BACKEND API LAYER

### Objective
Expose existing Python functionality as HTTP APIs for the Angular UI without changing business logic.

### Files Changed/Added
- idcard_maker/api_preview.py
- idcard_maker/api_app.py
- tests/test_api_d2.py
- pyproject.toml
- .gitignore
- LICENSE

### Implemented Endpoints
- GET /health
- POST /preview
- POST /generate
- POST /generate-batch
- POST /upload-csv
- POST /email

### Verification
- py -3.13 -m briefcase dev -r (dependencies installed, app started)
- py -3.13 -m pytest -q (5 passed)

### Result
D2 COMPLETE – API surface available for Angular integration (D3).

---

## STEP D3 – ANGULAR FRONTEND (IN PROGRESS)

### Objective
Continue rebuilding the UI in Angular, maintaining workflow parity and improving UX.

### Updates
- Added comprehensive Help page describing the current Angular workflow (assets, members table editing, selection-based generate/email, output folder, CSV import/export, and troubleshooting).
- Implemented Email settings “Quick sender” buttons (President/Vice President/Membership Officer) to autofill sender email/name for the active account.

### Files Changed
- idcard_maker/resources/help.html
- frontend/src/app/app.html
- frontend/src/app/app.scss
- frontend/src/app/app.ts

### Verification
- TypeScript compile: `node frontend\\node_modules\\typescript\\bin\\tsc -p frontend\\tsconfig.app.json --noEmit` (pass)

### Additional Updates
- Implemented Clear cards (2-click confirm) to delete generated PNGs and reset table state.
- Fixed Set as default checkboxes to persist the currently loaded template/signature without opening a file picker (defaults can now be stored as base64).
- CSV upload now selects all imported rows by default so Generate card(s) is immediately available; clicking into any table cell now selects the row for preview.
- Settings persistence is now stable across run modes by using a single per-user `settings.json` path (instead of switching between Briefcase app-data vs repo-root fallback).
- Date normalization now tolerates non-ASCII “dash-like” characters (prevents blank dates when CSV/clipboard uses en dash/non-breaking hyphen).
- CSV upload input is reset after processing so you can re-upload the same CSV after Clear cards.
- Member rows now require Name, ID Number, Date, and Email before Generate/Email actions are enabled; backend endpoints enforce the same validation.
- UI now marks required columns with “*”, highlights missing required cells in selected rows, and shows a hint when Generate/Email are disabled due to missing required fields.
- Increased label and hint text sizes for better readability in the Assets/CSV panels and settings dialogs.
- Increased the Batch/Email status notification text size above the members table.
- Output folder is now required (Generate/Email disabled until set), and removed developer-only header/API start hint text from the UI.
- Styled the Batch/Email notification area above the members table and increased its text size.
- Required-field and required-output-folder messages now render inside the styled notification area (larger text, consistent styling).

### Files Changed
- idcard_maker/api_app.py
- tests/test_api_d2.py
- frontend/src/app/app.html
- frontend/src/app/app.scss
- frontend/src/app/app.ts

### Verification
- `py -3.13 -m pytest -q` (10 passed)
