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

  private previewDebounceTimer: number | null = null;

  constructor(private readonly http: HttpClient) {}

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
