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
type OpenPathOut = { ok: boolean };
type EmailResult = { index: number; result: 'sent' | 'skipped' | 'error'; message?: string | null };
type EmailOut = { total: number; sent: number; skipped: number; errors: number; results: EmailResult[] };

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

  protected readonly smtpHost = signal('');
  protected readonly smtpPort = signal('587');
  protected readonly smtpUseTls = signal(true);
  protected readonly smtpUseSsl = signal(false);
  protected readonly smtpUsername = signal('');
  protected readonly smtpPassword = signal('');
  protected readonly smtpFromName = signal('');
  protected readonly smtpFromEmail = signal('');

  protected readonly emailSubjectTpl = signal('Your ID card, {name}');
  protected readonly emailBodyTpl = signal('Hi {name},\n\nAttached is your ID card.\nID: {id_number}\nDate: {date}\n\nBest,\n{sender}');

  protected readonly emailStatus = signal<string | null>(null);
  protected readonly emailResult = signal<EmailOut | null>(null);
  protected readonly isEmailing = signal(false);

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

    try {
      const raw = localStorage.getItem('idcard.smtp');
      if (raw) {
        const s = JSON.parse(raw);
        if (typeof s.host === 'string') this.smtpHost.set(s.host);
        if (typeof s.port === 'string') this.smtpPort.set(s.port);
        if (typeof s.useTls === 'boolean') this.smtpUseTls.set(s.useTls);
        if (typeof s.useSsl === 'boolean') this.smtpUseSsl.set(s.useSsl);
        if (typeof s.username === 'string') this.smtpUsername.set(s.username);
        if (typeof s.password === 'string') this.smtpPassword.set(s.password);
        if (typeof s.fromName === 'string') this.smtpFromName.set(s.fromName);
        if (typeof s.fromEmail === 'string') this.smtpFromEmail.set(s.fromEmail);
      }
      const subj = localStorage.getItem('idcard.emailSubjectTpl');
      const body = localStorage.getItem('idcard.emailBodyTpl');
      if (subj) this.emailSubjectTpl.set(subj);
      if (body) this.emailBodyTpl.set(body);
    } catch {
      // ignore
    }
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

  protected onSmtpChange(): void {
    try {
      localStorage.setItem(
        'idcard.smtp',
        JSON.stringify({
          host: this.smtpHost(),
          port: this.smtpPort(),
          useTls: this.smtpUseTls(),
          useSsl: this.smtpUseSsl(),
          username: this.smtpUsername(),
          password: this.smtpPassword(),
          fromName: this.smtpFromName(),
          fromEmail: this.smtpFromEmail(),
        })
      );
    } catch {
      // ignore
    }
  }

  protected onEmailTplChange(): void {
    try {
      localStorage.setItem('idcard.emailSubjectTpl', this.emailSubjectTpl());
      localStorage.setItem('idcard.emailBodyTpl', this.emailBodyTpl());
    } catch {
      // ignore
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

    const host = this.smtpHost().trim();
    const fromEmail = this.smtpFromEmail().trim();
    if (!host || !fromEmail) {
      this.error.set('SMTP host and From email are required.');
      return;
    }

    const portNum = Number.parseInt(this.smtpPort().trim() || '587', 10);
    if (!Number.isFinite(portNum) || portNum <= 0) {
      this.error.set('SMTP port must be a number.');
      return;
    }

    this.isEmailing.set(true);
    this.isLoading.set(true);
    this.emailStatus.set(`Sending ${rows.length} email(s)...`);

    try {
      const payload = {
        members: rows,
        smtp: {
          host,
          port: portNum,
          use_tls: this.smtpUseTls(),
          use_ssl: this.smtpUseSsl(),
          username: this.smtpUsername(),
          password: this.smtpPassword(),
          from_name: this.smtpFromName(),
          from_email: fromEmail,
        },
        subject_tpl: this.emailSubjectTpl(),
        body_tpl: this.emailBodyTpl(),
        template_base64: this.templateBase64(),
        signature_base64: this.signatureBase64(),
        output_dir: this.outputDir().trim() || null,
      };

      const resp = await firstValueFrom(this.http.post<EmailOut>(`${this.apiBase}/email`, payload));
      this.emailResult.set(resp);
      this.emailStatus.set(`Email complete: ${resp.sent} sent, ${resp.skipped} skipped, ${resp.errors} errors.`);

      this.onSmtpChange();
      this.onEmailTplChange();
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
