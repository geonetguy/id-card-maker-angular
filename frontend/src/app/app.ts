import { Component, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { NgIf } from '@angular/common';
import { firstValueFrom } from 'rxjs';

type Member = {
  name: string;
  id_number: string;
  date: string;
  email: string;
};

type GenerateBatchResult = { index: number; result: 'ok' | 'skip' | 'error' };
type GenerateBatchOut = {
  total: number;
  ok: number;
  skipped: number;
  errors: number;
  output_dir?: string;
  results: GenerateBatchResult[];
};

type GenerateOut = { filename: string; path: string; output_dir: string };
type ConfigOut = { output_dir?: string | null };
type ChooseOutputDirOut = { output_dir?: string | null };
type AssetDefaultsOut = {
  template_path?: string | null;
  signature_path?: string | null;
  template_base64?: string | null;
  signature_base64?: string | null;
};
type ChooseAssetOut = { kind: 'template' | 'signature'; path?: string | null; base64?: string | null };
type OpenPathOut = { ok: boolean };
type EmailResult = { index: number; result: 'sent' | 'skipped' | 'error'; message?: string | null };
type EmailOut = { total: number; sent: number; skipped: number; errors: number; results: EmailResult[] };
type EmailProvider = 'microsoft' | 'gmail';
type EmailAccountSettings = {
  email: string;
  password: string;
  save_password: boolean;
  from_name: string;
  subject_tpl: string;
  body_tpl: string;
};
type EmailProviderDefaults = {
  imap_server: string;
  imap_port: number;
  imap_encryption: string;
  smtp_server: string;
  smtp_port: number;
  smtp_encryption: string;
};
type EmailSettingsV2 = {
  active: EmailProvider;
  microsoft: EmailAccountSettings;
  gmail: EmailAccountSettings;
  defaults: Record<EmailProvider, EmailProviderDefaults>;
};

@Component({
  selector: 'app-root',
  imports: [NgIf],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App {
  private readonly apiBase = 'http://127.0.0.1:8000';

  protected readonly name = signal('');
  protected readonly idNumber = signal('');
  protected readonly date = signal('');
  protected readonly email = signal('');
  protected readonly outputDir = signal('');
  protected readonly isChoosingOutputDir = signal(false);

  protected readonly templateBase64 = signal<string | null>(null);
  protected readonly signatureBase64 = signal<string | null>(null);
  protected readonly templatePath = signal<string | null>(null);
  protected readonly signaturePath = signal<string | null>(null);
  protected readonly templateDefaultEnabled = signal(false);
  protected readonly signatureDefaultEnabled = signal(false);

  protected readonly previewPngBase64 = signal<string | null>(null);
  protected readonly warning = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly isLoading = signal(false);

  protected readonly members = signal<Member[]>([]);
  protected readonly selectedIndex = signal<number | null>(null);

  protected readonly batchStatus = signal<string | null>(null);
  protected readonly batchResult = signal<GenerateBatchOut | null>(null);

  protected readonly generateStatus = signal<string | null>(null);
  protected readonly lastGenerated = signal<GenerateOut | null>(null);

  protected readonly settingsOpen = signal(false);
  protected readonly emailActive = signal<EmailProvider>('microsoft');
  protected readonly emailDefaults = signal<Record<EmailProvider, EmailProviderDefaults> | null>(null);

  protected readonly msEmail = signal('');
  protected readonly msPassword = signal('');
  protected readonly msSavePassword = signal(false);
  protected readonly msFromName = signal('');
  protected readonly msSubjectTpl = signal('Your ID card, {name}');
  protected readonly msBodyTpl = signal('Hi {name},\n\nAttached is your ID card.\nID: {id_number}\nDate: {date}\n\nBest,\n{sender}');

  protected readonly gmailEmail = signal('');
  protected readonly gmailPassword = signal('');
  protected readonly gmailSavePassword = signal(false);
  protected readonly gmailFromName = signal('');
  protected readonly gmailSubjectTpl = signal('Your ID card, {name}');
  protected readonly gmailBodyTpl = signal('Hi {name},\n\nAttached is your ID card.\nID: {id_number}\nDate: {date}\n\nBest,\n{sender}');

  protected readonly emailStatus = signal<string | null>(null);
  protected readonly emailResult = signal<EmailOut | null>(null);
  protected readonly isEmailing = signal(false);
  protected readonly settingsStatus = signal<string | null>(null);
  protected readonly isSavingSettings = signal(false);

  private previewDebounceTimer: number | null = null;

  constructor(private readonly http: HttpClient) {}

  async ngOnInit(): Promise<void> {
    try {
      const cfg = await firstValueFrom(this.http.get<ConfigOut>(`${this.apiBase}/config`));
      const v = (cfg?.output_dir ?? '').toString().trim();
      if (v) this.outputDir.set(v);
    } catch {
      // ignore; API may not be up yet
    }

    await this.loadAssetDefaults();
    await this.loadEmailSettings();
  }

  protected async loadAssetDefaults(): Promise<void> {
    try {
      const d = await firstValueFrom(
        this.http.get<AssetDefaultsOut>(`${this.apiBase}/assets/defaults`)
      );
      const tplB64 = (d?.template_base64 ?? '').toString().trim();
      const sigB64 = (d?.signature_base64 ?? '').toString().trim();
      const tplPath = (d?.template_path ?? '').toString().trim();
      const sigPath = (d?.signature_path ?? '').toString().trim();

      this.templatePath.set(tplPath || null);
      this.signaturePath.set(sigPath || null);
      this.templateDefaultEnabled.set(!!tplPath);
      this.signatureDefaultEnabled.set(!!sigPath);
      if (tplB64) this.templateBase64.set(tplB64);
      if (sigB64) this.signatureBase64.set(sigB64);

      if (tplB64 || sigB64) this.schedulePreview();
    } catch {
      // ignore
    }
  }

  protected openSettings(): void {
    this.settingsStatus.set(null);
    this.settingsOpen.set(true);
  }

  protected closeSettings(): void {
    this.settingsOpen.set(false);
  }

  protected onTextChange(kind: 'name' | 'id' | 'date' | 'email', value: string): void {
    const v = value ?? '';
    if (kind === 'name') this.name.set(v);
    if (kind === 'id') this.idNumber.set(v);
    if (kind === 'date') this.date.set(v);
    if (kind === 'email') this.email.set(v);
    this.schedulePreview();
  }

  protected onOutputDirChange(value: string): void {
    this.outputDir.set(value ?? '');
  }

  protected async chooseOutputDir(): Promise<void> {
    this.error.set(null);
    this.isChoosingOutputDir.set(true);
    try {
      const payload = { initial_dir: this.outputDir().trim() || null };
      const resp = await firstValueFrom(
        this.http.post<ChooseOutputDirOut>(`${this.apiBase}/choose-output-dir`, payload)
      );
      const chosen = (resp?.output_dir ?? '').toString().trim();
      if (chosen) {
        this.outputDir.set(chosen);
      }
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to choose output folder.';
      this.error.set(String(msg));
    } finally {
      this.isChoosingOutputDir.set(false);
    }
  }

  protected async onPickImage(kind: 'template' | 'signature', file: File | null): Promise<void> {
    if (!file) {
      if (kind === 'template') this.templateBase64.set(null);
      if (kind === 'signature') this.signatureBase64.set(null);
      this.schedulePreview();
      return;
    }

    const b64 = await this.readFileAsBase64(file);
    if (kind === 'template') this.templateBase64.set(b64);
    if (kind === 'signature') this.signatureBase64.set(b64);
    this.schedulePreview();
  }

  protected async chooseDefaultAsset(kind: 'template' | 'signature'): Promise<void> {
    this.error.set(null);
    try {
      const initialDir =
        kind === 'template'
          ? (this.templatePath() || null)
          : (this.signaturePath() || null);

      const resp = await firstValueFrom(
        this.http.post<ChooseAssetOut>(`${this.apiBase}/choose-asset`, {
          kind,
          initial_dir: initialDir,
        })
      );

      const path = (resp?.path ?? '').toString().trim();
      const b64 = (resp?.base64 ?? '').toString().trim();
      if (!path || !b64) return;

      if (kind === 'template') {
        this.templatePath.set(path);
        this.templateBase64.set(b64);
        this.templateDefaultEnabled.set(true);
      } else {
        this.signaturePath.set(path);
        this.signatureBase64.set(b64);
        this.signatureDefaultEnabled.set(true);
      }

      await firstValueFrom(
        this.http.put(`${this.apiBase}/settings/assets`, {
          template_path: this.templatePath(),
          signature_path: this.signaturePath(),
        })
      );

      this.schedulePreview();
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to choose default asset.';
      this.error.set(String(msg));
    }
  }

  protected async setDefaultAsset(kind: 'template' | 'signature', enabled: boolean): Promise<void> {
    if (enabled) {
      const before =
        kind === 'template' ? this.templatePath() : this.signaturePath();
      await this.chooseDefaultAsset(kind);
      const after =
        kind === 'template' ? this.templatePath() : this.signaturePath();
      const ok = !!after && after !== before;
      if (!ok) {
        if (kind === 'template') this.templateDefaultEnabled.set(!!before);
        else this.signatureDefaultEnabled.set(!!before);
      }
      return;
    }

    // Disable default (but keep currently-loaded in-memory base64 if present)
    if (kind === 'template') {
      this.templatePath.set(null);
      this.templateDefaultEnabled.set(false);
    } else {
      this.signaturePath.set(null);
      this.signatureDefaultEnabled.set(false);
    }

    try {
      await firstValueFrom(
        this.http.put(`${this.apiBase}/settings/assets`, {
          template_path: this.templatePath(),
          signature_path: this.signaturePath(),
        })
      );
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to save default setting.';
      this.error.set(String(msg));
    }
  }

  protected async onUploadCsv(file: File | null): Promise<void> {
    if (!file) return;
    this.error.set(null);
    this.batchStatus.set(null);

    try {
      const form = new FormData();
      form.append('file', file, file.name);

      const resp = await firstValueFrom(
        this.http.post<{ members: Member[] }>(`${this.apiBase}/upload-csv`, form)
      );

      const incoming = Array.isArray(resp.members) ? resp.members : [];
      const merged = [...this.members(), ...incoming];
      this.members.set(merged);
      this.batchStatus.set(`Loaded ${incoming.length} member(s) from ${file.name}.`);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to upload CSV.';
      this.error.set(String(msg));
    }
  }

  protected selectRow(index: number): void {
    const rows = this.members();
    if (index < 0 || index >= rows.length) return;
    const row = rows[index];
    this.selectedIndex.set(index);
    this.name.set(row.name || '');
    this.idNumber.set(row.id_number || '');
    this.date.set(row.date || '');
    this.email.set(row.email || '');
    this.schedulePreview();
  }

  protected newMember(): void {
    this.selectedIndex.set(null);
    this.name.set('');
    this.idNumber.set('');
    this.date.set('');
    this.email.set('');
    this.schedulePreview();
  }

  protected saveMember(): void {
    const member: Member = {
      name: this.name().trim(),
      id_number: this.idNumber().trim(),
      date: this.date().trim(),
      email: this.email().trim(),
    };

    const idx = this.selectedIndex();
    const rows = this.members();
    if (idx === null) {
      this.members.set([...rows, member]);
      this.batchStatus.set('Added member to table.');
    } else {
      const next = rows.slice();
      next[idx] = member;
      this.members.set(next);
      this.batchStatus.set('Updated member in table.');
    }
  }

  protected async generateBatch(): Promise<void> {
    this.error.set(null);
    this.batchResult.set(null);
    this.batchStatus.set(null);

    const template = this.templateBase64();
    if (!template) {
      this.error.set('Choose a template image first.');
      return;
    }

    const rows = this.members();
    if (!rows.length) {
      this.error.set('No members loaded yet.');
      return;
    }

    this.isLoading.set(true);
    this.batchStatus.set(`Generating ${rows.length} card(s)...`);
    try {
      const payload = {
        members: rows,
        template_base64: template,
        signature_base64: this.signatureBase64(),
        output_dir: this.outputDir().trim() || null,
      };

      const resp = await firstValueFrom(
        this.http.post<GenerateBatchOut>(`${this.apiBase}/generate-batch`, payload)
      );
      this.batchResult.set(resp);
      const outDir = resp.output_dir ? ` Saved to: ${resp.output_dir}` : '';
      this.batchStatus.set(
        `Batch complete: ${resp.ok} saved, ${resp.skipped} skipped, ${resp.errors} errors.${outDir}`
      );
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to generate batch.';
      this.error.set(String(msg));
      this.batchStatus.set(String(msg));
    } finally {
      this.isLoading.set(false);
    }
  }

  protected async generateOne(): Promise<void> {
    this.error.set(null);
    this.generateStatus.set(null);
    this.lastGenerated.set(null);

    const template = this.templateBase64();
    if (!template) {
      this.error.set('Choose a template image first.');
      return;
    }

    const idNumber = this.idNumber().trim();
    if (!idNumber) {
      this.error.set('ID Number is required.');
      return;
    }

    this.isLoading.set(true);
    this.generateStatus.set('Generating card...');
    try {
      const payload = {
        member: {
          name: this.name().trim(),
          id_number: idNumber,
          date: this.date().trim(),
          email: this.email().trim(),
        },
        template_base64: template,
        signature_base64: this.signatureBase64(),
        output_dir: this.outputDir().trim() || null,
      };

      const resp = await firstValueFrom(
        this.http.post<GenerateOut>(`${this.apiBase}/generate`, payload)
      );
      this.lastGenerated.set(resp);
      this.generateStatus.set(`Saved: ${resp.filename}`);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to generate card.';
      this.error.set(String(msg));
      this.generateStatus.set(String(msg));
    } finally {
      this.isLoading.set(false);
    }
  }

  protected async downloadLast(): Promise<void> {
    const last = this.lastGenerated();
    if (!last) return;

    try {
      const payload = { output_dir: last.output_dir, filename: last.filename };
      const resp = await firstValueFrom(
        this.http.post(`${this.apiBase}/download`, payload, { responseType: 'blob' })
      );
      const url = URL.createObjectURL(resp);
      const a = document.createElement('a');
      a.href = url;
      a.download = last.filename || 'idcard.png';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to download file.';
      this.error.set(String(msg));
    }
  }

  protected async openGenerated(kind: 'file' | 'folder'): Promise<void> {
    const last = this.lastGenerated();
    if (!last) return;

    const path = kind === 'folder' ? last.output_dir : last.path;
    try {
      await firstValueFrom(this.http.post<OpenPathOut>(`${this.apiBase}/open-path`, { path }));
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to open path.';
      this.error.set(String(msg));
    }
  }

  protected onSmtpChange(): void {}
  protected onEmailTplChange(): void {}

  protected currentEmail(): string {
    return this.emailActive() === 'microsoft' ? this.msEmail() : this.gmailEmail();
  }

  protected currentPassword(): string {
    return this.emailActive() === 'microsoft' ? this.msPassword() : this.gmailPassword();
  }

  protected currentFromName(): string {
    return this.emailActive() === 'microsoft' ? this.msFromName() : this.gmailFromName();
  }

  protected currentSubjectTpl(): string {
    return this.emailActive() === 'microsoft' ? this.msSubjectTpl() : this.gmailSubjectTpl();
  }

  protected currentBodyTpl(): string {
    return this.emailActive() === 'microsoft' ? this.msBodyTpl() : this.gmailBodyTpl();
  }

  protected async loadEmailSettings(): Promise<void> {
    try {
      const s = await firstValueFrom(
        this.http.get<EmailSettingsV2>(`${this.apiBase}/settings/email`)
      );
      if (!s) return;

      this.emailActive.set(s.active ?? 'microsoft');
      this.emailDefaults.set(s.defaults ?? null);

      this.msEmail.set((s.microsoft?.email ?? '').toString());
      this.msPassword.set((s.microsoft?.password ?? '').toString());
      this.msSavePassword.set(!!s.microsoft?.save_password);
      this.msFromName.set((s.microsoft?.from_name ?? '').toString());
      this.msSubjectTpl.set((s.microsoft?.subject_tpl ?? this.msSubjectTpl()).toString());
      this.msBodyTpl.set((s.microsoft?.body_tpl ?? this.msBodyTpl()).toString());

      this.gmailEmail.set((s.gmail?.email ?? '').toString());
      this.gmailPassword.set((s.gmail?.password ?? '').toString());
      this.gmailSavePassword.set(!!s.gmail?.save_password);
      this.gmailFromName.set((s.gmail?.from_name ?? '').toString());
      this.gmailSubjectTpl.set((s.gmail?.subject_tpl ?? this.gmailSubjectTpl()).toString());
      this.gmailBodyTpl.set((s.gmail?.body_tpl ?? this.gmailBodyTpl()).toString());
    } catch {
      // ignore; API may not be up yet
    }
  }

  protected async saveEmailSettings(): Promise<void> {
    this.settingsStatus.set(null);
    this.isSavingSettings.set(true);
    try {
      const payload: EmailSettingsV2 = {
        active: this.emailActive(),
        microsoft: {
          email: this.msEmail().trim(),
          password: this.msPassword(),
          save_password: this.msSavePassword(),
          from_name: this.msFromName(),
          subject_tpl: this.msSubjectTpl(),
          body_tpl: this.msBodyTpl(),
        },
        gmail: {
          email: this.gmailEmail().trim(),
          password: this.gmailPassword(),
          save_password: this.gmailSavePassword(),
          from_name: this.gmailFromName(),
          subject_tpl: this.gmailSubjectTpl(),
          body_tpl: this.gmailBodyTpl(),
        },
        defaults: this.emailDefaults() ?? ({} as any),
      };

      const resp = await firstValueFrom(this.http.put<EmailSettingsV2>(`${this.apiBase}/settings/email`, payload));
      if (resp?.defaults) this.emailDefaults.set(resp.defaults);
      this.settingsStatus.set('Saved.');

      // If the user didn't opt in to save the password, clear it locally too.
      if (!this.msSavePassword()) this.msPassword.set('');
      if (!this.gmailSavePassword()) this.gmailPassword.set('');
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to save settings.';
      this.settingsStatus.set(String(msg));
      this.error.set(String(msg));
    } finally {
      this.isSavingSettings.set(false);
    }
  }

  protected async sendEmailBatch(): Promise<void> {
    this.error.set(null);
    this.emailStatus.set(null);
    this.emailResult.set(null);

    const rows = this.members();
    if (!rows.length) {
      this.error.set('No members loaded yet.');
      return;
    }

    const emailAddr = this.currentEmail().trim();
    const password = this.currentPassword();
    const defaults = this.emailDefaults();
    const provider = this.emailActive();
    const d = defaults?.[provider];

    if (!emailAddr || !password) {
      this.error.set('Enter email + password for the active account in Email settings.');
      this.openSettings();
      return;
    }
    if (!d) {
      this.error.set('Email defaults not loaded yet. Try again.');
      return;
    }

    this.isEmailing.set(true);
    this.isLoading.set(true);
    this.emailStatus.set(`Sending ${rows.length} email(s)...`);

    try {
      const payload = {
        members: rows,
        smtp: {
          host: d.smtp_server,
          port: d.smtp_port,
          use_tls: (d.smtp_encryption ?? '').toUpperCase().startsWith('STARTTLS'),
          use_ssl: (d.smtp_encryption ?? '').toUpperCase().startsWith('SSL'),
          username: emailAddr,
          password,
          from_name: this.currentFromName(),
          from_email: emailAddr,
        },
        subject_tpl: this.currentSubjectTpl(),
        body_tpl: this.currentBodyTpl(),
        template_base64: this.templateBase64(),
        signature_base64: this.signatureBase64(),
        output_dir: this.outputDir().trim() || null,
      };

      const resp = await firstValueFrom(this.http.post<EmailOut>(`${this.apiBase}/email`, payload));
      this.emailResult.set(resp);
      this.emailStatus.set(`Email complete: ${resp.sent} sent, ${resp.skipped} skipped, ${resp.errors} errors.`);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to send email.';
      this.error.set(String(msg));
      this.emailStatus.set(String(msg));
    } finally {
      this.isEmailing.set(false);
      this.isLoading.set(false);
    }
  }

  protected async sendEmailOne(): Promise<void> {
    this.error.set(null);
    this.emailStatus.set(null);
    this.emailResult.set(null);

    const idnum = this.idNumber().trim();
    const toEmail = this.email().trim();
    if (!idnum) {
      this.error.set('ID Number is required.');
      return;
    }
    if (!toEmail) {
      this.error.set('Member email is required.');
      return;
    }

    const emailAddr = this.currentEmail().trim();
    const password = this.currentPassword();
    const defaults = this.emailDefaults();
    const provider = this.emailActive();
    const d = defaults?.[provider];

    if (!emailAddr || !password) {
      this.error.set('Enter email + password for the active account in Email settings.');
      this.openSettings();
      return;
    }
    if (!d) {
      this.error.set('Email defaults not loaded yet. Try again.');
      return;
    }

    this.isEmailing.set(true);
    this.isLoading.set(true);
    this.emailStatus.set('Sending email...');

    try {
      const payload = {
        members: [
          {
            name: this.name().trim(),
            id_number: idnum,
            date: this.date().trim(),
            email: toEmail,
          },
        ],
        smtp: {
          host: d.smtp_server,
          port: d.smtp_port,
          use_tls: (d.smtp_encryption ?? '').toUpperCase().startsWith('STARTTLS'),
          use_ssl: (d.smtp_encryption ?? '').toUpperCase().startsWith('SSL'),
          username: emailAddr,
          password,
          from_name: this.currentFromName(),
          from_email: emailAddr,
        },
        subject_tpl: this.currentSubjectTpl(),
        body_tpl: this.currentBodyTpl(),
        template_base64: this.templateBase64(),
        signature_base64: this.signatureBase64(),
        output_dir: this.outputDir().trim() || null,
      };

      const resp = await firstValueFrom(this.http.post<EmailOut>(`${this.apiBase}/email`, payload));
      this.emailResult.set(resp);
      this.emailStatus.set(`Email complete: ${resp.sent} sent, ${resp.skipped} skipped, ${resp.errors} errors.`);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to send email.';
      this.error.set(String(msg));
      this.emailStatus.set(String(msg));
    } finally {
      this.isEmailing.set(false);
      this.isLoading.set(false);
    }
  }

  protected async refreshPreview(): Promise<void> {
    this.error.set(null);
    this.warning.set(null);

    const template = this.templateBase64();
    if (!template) {
      this.previewPngBase64.set(null);
      return;
    }

    this.isLoading.set(true);
    try {
      const payload = {
        member: {
          name: this.name(),
          id_number: this.idNumber(),
          date: this.date(),
          email: this.email(),
        },
        template_base64: template,
        signature_base64: this.signatureBase64(),
        output_dir: this.outputDir().trim() || null,
      };

      const resp = await firstValueFrom(
        this.http.post<{ png_base64: string; warning?: string | null }>(
          `${this.apiBase}/preview`,
          payload
        )
      );

      this.previewPngBase64.set(resp.png_base64);
      this.warning.set(resp.warning ?? null);
    } catch (e: any) {
      const msg =
        e?.error?.detail ||
        e?.message ||
        'Failed to generate preview. Ensure the Python API is running.';
      this.error.set(String(msg));
      this.previewPngBase64.set(null);
    } finally {
      this.isLoading.set(false);
    }
  }

  protected previewSrc(): string | null {
    const b64 = this.previewPngBase64();
    return b64 ? `data:image/png;base64,${b64}` : null;
  }

  protected trackIndex(index: number): number {
    return index;
  }

  private schedulePreview(): void {
    if (this.previewDebounceTimer !== null) {
      window.clearTimeout(this.previewDebounceTimer);
    }
    this.previewDebounceTimer = window.setTimeout(() => {
      this.refreshPreview();
    }, 250);
  }

  private readFileAsBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Failed to read file'));
      reader.onload = () => {
        const result = String(reader.result || '');
        // result is a data URL; API accepts either raw base64 or data URL, but we send raw base64.
        const comma = result.indexOf(',');
        resolve(comma >= 0 ? result.slice(comma + 1) : result);
      };
      reader.readAsDataURL(file);
    });
  }
}
