# PROJECT PLAN – ID CARD MAKER ANGULAR MIGRATION

## CURRENT PHASE: FRONTEND DECOUPLING

---

## STEP D1 – SYSTEM ANALYSIS

### Objective
Understand current architecture and define migration boundaries.

### Tasks
- Identify frontend responsibilities in Toga
- Identify backend/domain logic
- Define API surface for Angular

### Status
1.	Current architecture summary
•	Single-process Python desktop app built on BeeWare/Toga: E:\id-card-maker-angular\idcard_maker\app.py
•	UI layer (Toga widgets/layout): E:\id-card-maker-angular\idcard_maker\ui\layout.py, E:\id-card-maker-angular\idcard_maker\ui\mail_settings.py
•	Controller/orchestration layer (ties UI events to services, owns “live preview”, CSV import, batch generation, email flows): E:\id-card-maker-angular\idcard_maker\controllers\actions.py
•	Business-capability services (already fairly UI-agnostic):
•	Rendering: E:\id-card-maker-angular\idcard_maker\core\render.py (generate_id_card)
•	Card generation/file naming/output folder: E:\id-card-maker-angular\idcard_maker\services\generation.py
•	Email composition/sending: E:\id-card-maker-angular\idcard_maker\services\mailer.py
•	No web server/API framework present (no FastAPI/Flask/etc found).
2.	Frontend/backend boundary
•	Frontend responsibility (to be Angular): all widget concerns + UX state (form fields, table selection/edit mode, progress bar, status messages, file-picker UI for template/signature/CSV, “open output folder” behavior).
•	Backend responsibility (remain Python): authoritative rendering + generation + email:
•	Render PNG bytes for preview (generate_id_card / generate_single_card)
•	Persist generated PNGs under generated_cards (today: project_output_dir() in services/generation.py)
•	Batch generation semantics (skip if missing id_number, yield ok/skip/error)
•	Email send and message templating, attachments resolution
3.	Angular migration boundary
•	Replace everything under the Toga UI + event wiring with Angular:
•	Replace: E:\id-card-maker-angular\idcard_maker\ui\* and the UI-facing parts of E:\id-card-maker-angular\idcard_maker\controllers\actions.py
•	Preserve core/service modules as-is and wrap them behind an HTTP API:
•	Preserve: E:\id-card-maker-angular\idcard_maker\core\render.py, ...\services\generation.py, ...\services\mailer.py
•	Treat controller logic as the “spec” for behavior parity (e.g., preview warning when date is unrecognized; batch skip rules; email skip rules), but move that orchestration into API handlers.
4.	Required backend API surface (minimum to support the same features)
•	POST /preview
•	Inputs: member (name, id_number, date, email), template image, signature image (optional), possibly use_default_font/font selection.
•	Output: PNG bytes (or base64) + a small status field mirroring current UX (“unrecognized date → left blank”, “pick a template to preview” becomes a 4xx error).
•	Behavior parity note: current code does not default a missing date to today; it leaves date blank (_normalize_date returns ""). (E:\id-card-maker-angular\idcard_maker\controllers\actions.py)
•	POST /generate
•	Inputs: member + template + signature (or previously uploaded asset IDs).
•	Output: saved filename/path (contract wants {id_number}.png under /generated_cards; current implementation uses safe_filename(idnum) and collision-suffixing via next_available).
•	POST /generate-batch
•	Inputs: list of members + template + signature.
•	Output: results per row (ok/skip/error), and optionally progress streaming (SSE/websocket) if you want UI parity with the progress bar.
•	POST /upload-csv
•	Inputs: CSV file upload.
•	Output: parsed members normalized to {name,id_number,date,email} (this matches the existing load_csv logic in actions.py).
•	POST /email
•	Inputs: member(s) + SMTP config + subject/body templates.
•	Output: success/failure per recipient; skips if missing attachment/email/id rules match current behavior.

###Decission
Proceeed to backend API extraction (D2)

---

## STEP D2 – BACKEND API LAYER

### Objective
Expose existing functionality as APIs.

### Planned Endpoints
- /preview
- /generate
- /generate-batch
- /upload-csv
- /email

---

## STEP D3 – ANGULAR FRONTEND

### Objective
Rebuild UI using Angular.

---

## RULE
Codex must NOT proceed to next step until current step is complete and verified.