import { Component, computed, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { NgIf } from '@angular/common';
import { firstValueFrom } from 'rxjs';

type Member = {
  name: string;
  id_number: string;
  employer_id: string;
  date: string;
  email: string;
};

type MemberRow = Member & { selected: boolean };

type PageSize = 10 | 25 | 50 | 100 | 'all';
type SortColumn = keyof Member;
type SortDir = 'asc' | 'desc';

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
type OutputSettingsOut = { output_dir?: string | null };
type ChooseOutputDirOut = { output_dir?: string | null };
type AssetDefaultsOut = {
  template_path?: string | null;
  signature_path?: string | null;
  template_base64?: string | null;
  signature_base64?: string | null;
};
type AssetSettingsOut = {
  template_path?: string | null;
  signature_path?: string | null;
  template_base64?: string | null;
  signature_base64?: string | null;
};
type ChooseAssetOut = { kind: 'template' | 'signature'; path?: string | null; base64?: string | null };
type OpenPathOut = { ok: boolean };
type OpenHelpOut = { ok: boolean };
type EmailResult = { index: number; result: 'sent' | 'skipped' | 'error'; message?: string | null };
type EmailOut = { total: number; sent: number; skipped: number; errors: number; results: EmailResult[] };
type EmailProvider = 'microsoft' | 'gmail';
type OfficerRole = 'President' | 'Vice President' | 'Membership Officer';
type EmailAccountSettings = {
  email: string;
  password: string;
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
type UnionManagementSettings = {
  enabled: boolean;
  email: string;
};
type EmailSettingsV2 = {
  active: EmailProvider;
  active_sender: OfficerRole;
  microsoft: EmailAccountSettings;
  gmail: EmailAccountSettings;
  microsoft_senders: Partial<Record<OfficerRole, EmailAccountSettings>>;
  gmail_senders: Partial<Record<OfficerRole, EmailAccountSettings>>;
  union_management: UnionManagementSettings;
  defaults: Record<EmailProvider, EmailProviderDefaults>;
};
type ClearCardsOut = { output_dir: string; deleted: number };
type CardsCountOut = { output_dir: string; count: number };

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
  protected readonly outputDefaultEnabled = signal(false);

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

  protected readonly members = signal<MemberRow[]>([]);
  protected readonly selectedIndex = signal<number | null>(null);

  protected readonly searchQuery = signal('');
  protected readonly sortColumn = signal<SortColumn | null>(null);
  protected readonly sortDir = signal<SortDir>('asc');

  protected readonly pageSize = signal<PageSize>(25);
  protected readonly pageIndex = signal(0); // 0-based

  protected readonly batchStatus = signal<string | null>(null);
  protected readonly batchResult = signal<GenerateBatchOut | null>(null);
  protected readonly generatedCardCount = signal(0);

  protected readonly generateStatus = signal<string | null>(null);
  protected readonly lastGenerated = signal<GenerateOut | null>(null);

  protected readonly settingsOpen = signal(false);
  protected readonly pendingSend = signal<'one' | 'batch' | null>(null);
  protected readonly emailActive = signal<EmailProvider>('microsoft');
  protected readonly emailSender = signal<OfficerRole>('Membership Officer');
  protected readonly emailDefaults = signal<Record<EmailProvider, EmailProviderDefaults> | null>(null);
  protected readonly msSenderProfiles = signal<Partial<Record<OfficerRole, EmailAccountSettings>>>({});
  protected readonly gmailSenderProfiles = signal<Partial<Record<OfficerRole, EmailAccountSettings>>>({});
  protected readonly unionMgmtEnabled = signal(false);
  protected readonly unionMgmtEmail = signal('');

  protected readonly msEmail = signal('');
  protected readonly msPassword = signal('');
  protected readonly msFromName = signal('');
  protected readonly msSubjectTpl = signal('Your ID card, {name}');
  protected readonly msBodyTpl = signal('Hi {name},\n\nAttached is your ID card.\nID: {id_number}\nDate: {date}\n\nBest,\n{sender}');

  protected readonly gmailEmail = signal('');
  protected readonly gmailPassword = signal('');
  protected readonly gmailFromName = signal('');
  protected readonly gmailSubjectTpl = signal('Your ID card, {name}');
  protected readonly gmailBodyTpl = signal('Hi {name},\n\nAttached is your ID card.\nID: {id_number}\nDate: {date}\n\nBest,\n{sender}');

  protected readonly emailStatus = signal<string | null>(null);
  protected readonly emailResult = signal<EmailOut | null>(null);
  protected readonly isEmailing = signal(false);
  protected readonly settingsStatus = signal<string | null>(null);
  protected readonly isSavingSettings = signal(false);

  protected readonly clearConfirm = signal(false);
  private clearConfirmTimer: number | null = null;

  protected readonly hasTemplate = computed(() => !!this.templateBase64());
  protected readonly hasSignature = computed(() => !!this.signatureBase64());
  protected readonly assetsReady = computed(() => this.hasTemplate() && this.hasSignature());

  protected readonly memberComplete = computed(() => {
    return (
      this.name().trim().length > 0 &&
      this.idNumber().trim().length > 0 &&
      this.date().trim().length > 0 &&
      this.email().trim().length > 0
    );
  });

  protected readonly selectedCount = computed(() => {
    const rows = this.members();
    return rows.reduce((acc, r) => acc + (r.selected ? 1 : 0), 0);
  });

  protected readonly viewMembers = computed(() => {
    const rows = this.members();
    const q = this.searchQuery().trim().toLowerCase();
    let out: Array<{ index: number; row: MemberRow }> = rows.map((row, index) => ({ index, row }));

    if (q) {
      out = out.filter(({ row }) => {
        const name = (row.name ?? '').toString().toLowerCase();
        const idNum = (row.id_number ?? '').toString().toLowerCase();
        const empId = (row.employer_id ?? '').toString().toLowerCase();
        const date = (row.date ?? '').toString().toLowerCase();
        const email = (row.email ?? '').toString().toLowerCase();
        return name.includes(q) || idNum.includes(q) || empId.includes(q) || date.includes(q) || email.includes(q);
      });
    }

    const col = this.sortColumn();
    if (col) {
      const dir = this.sortDir();
      const mul = dir === 'asc' ? 1 : -1;
      out = out
        .slice()
        .sort((a, b) => {
          const av = (a.row[col] ?? '').toString();
          const bv = (b.row[col] ?? '').toString();
          const cmp = av.localeCompare(bv, undefined, { numeric: true, sensitivity: 'base' });
          return cmp !== 0 ? cmp * mul : a.index - b.index;
        });
    }

    return out;
  });

  protected readonly viewAnySelected = computed(() => {
    const v = this.viewMembers();
    return v.some((x) => !!x.row.selected);
  });

  protected readonly viewAllSelected = computed(() => {
    const v = this.viewMembers();
    return v.length > 0 && v.every((x) => !!x.row.selected);
  });

  protected readonly viewIndeterminate = computed(() => this.viewAnySelected() && !this.viewAllSelected());

  protected readonly totalPages = computed(() => {
    const total = this.viewMembers().length;
    const size = this.pageSize();
    if (size === 'all') return total > 0 ? 1 : 0;
    return total > 0 ? Math.max(1, Math.ceil(total / size)) : 0;
  });

  protected readonly pagedMembers = computed(() => {
    const rows = this.viewMembers();
    const total = rows.length;
    const size = this.pageSize();
    if (!total) return [] as Array<{ index: number; row: MemberRow }>;
    if (size === 'all') return rows;
    const page = Math.max(0, this.pageIndex());
    const start = Math.min(total, page * size);
    const end = Math.min(total, start + size);
    const out: Array<{ index: number; row: MemberRow }> = [];
    for (let i = start; i < end; i++) out.push(rows[i]);
    return out;
  });

  protected readonly selectedMembers = computed<Member[]>(() => {
    const rows = this.members();
    const chosen = rows.filter((r) => r.selected);
    return chosen.map(({ name, id_number, employer_id, date, email }) => ({ name, id_number, employer_id, date, email }));
  });

  protected readonly selectedRowsComplete = computed(() => {
    const rows = this.members();
    const chosen = rows.filter((r) => r.selected);
    if (!chosen.length) return false;
    return chosen.every((m) => {
      return this.isRowValid(m);
    });
  });

  protected isWorkSelected(row: MemberRow): boolean {
    return !!row.selected;
  }

  protected isMissing(row: MemberRow, field: keyof Member): boolean {
    const v = (row[field] ?? '').toString().trim();
    return v.length === 0;
  }

  private isValidDate(value: string): boolean {
    const v = (value ?? '').trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(v)) return false;
    const [y, m, d] = v.split('-').map((x) => Number(x));
    if (!y || !m || !d) return false;
    const dt = new Date(Date.UTC(y, m - 1, d));
    return dt.getUTCFullYear() === y && dt.getUTCMonth() === (m - 1) && dt.getUTCDate() === d;
  }

  private isValidEmail(value: string): boolean {
    const v = (value ?? '').trim();
    return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v);
  }

  private friendlyEmailFailureMessage(raw: string): string {
    const msg = (raw ?? '').toString().trim();
    const lower = msg.toLowerCase();

    if (!msg) return 'Email failed.';

    if (lower.includes('active_email_account_requires_email_and_password')) {
      return 'Enter the email + password for the active account in Email settings, then try again.';
    }
    if (lower.includes('union_management_email_is_invalid')) {
      return 'Union Management System email is invalid. Fix it in Email settings or disable it.';
    }

    // Common SMTP auth failures (Office365/Gmail).
    if (lower.startsWith('smtp_auth_failed') || lower.includes('authentication unsuccessful') || lower.includes('535')) {
      if (lower.includes('5.7.139')) {
        return 'Microsoft 365 rejected the login (5.7.139). Check email/password; if you use MFA, use an app password. Your tenant may also need SMTP AUTH enabled.';
      }
      return 'Email login failed. Check email/password; if you use MFA, use an app password. Your provider may also require SMTP AUTH to be enabled.';
    }

    // Network/connectivity.
    if (lower.includes('socket.gaierror') || lower.includes('name or service not known') || lower.includes('nodename nor servname')) {
      return 'Could not resolve the SMTP server address (DNS). Check your internet/VPN and the SMTP server name.';
    }
    if (lower.includes('timeouterror') || lower.includes('timed out')) {
      return 'Timed out connecting to the SMTP server. Check your internet connection and firewall rules for port 587.';
    }
    if (lower.includes('smtpconnecterror') || lower.includes('connection refused') || lower.includes('serverdisconnected')) {
      return 'Could not connect to the SMTP server. Check network/firewall access and that the SMTP host/port are correct.';
    }

    // Address issues.
    if (lower.includes('smtprecipientsrefused')) {
      return 'The SMTP server refused the recipient address. Check the member email (and Union Management System email if enabled).';
    }
    if (lower.includes('smtpsenderrefused')) {
      return 'The SMTP server refused the sender address. Check the account email and From name/email settings.';
    }

    // Backend-provided wrapped errors.
    if (lower.startsWith('email_failed:')) {
      return 'Email failed to send. Check your SMTP settings, network connection, and credentials.';
    }

    return msg;
  }

  private normalizeIdNumber(value: unknown): string {
    const v = (value ?? '').toString().trim();
    return v.replace(/[^\d]/g, '');
  }

  private isValidIdNumber(value: string): boolean {
    const v = this.normalizeIdNumber(value);
    return /^\d{7}$/.test(v);
  }

  protected isInvalid(row: MemberRow, field: keyof Member): boolean {
    if (field === 'employer_id') return false;
    const raw = (row[field] ?? '').toString();
    const v = raw.trim();
    if (!v) return true;
    if (field === 'date') return !this.isValidDate(v);
    if (field === 'email') return !this.isValidEmail(v);
    if (field === 'id_number') return !this.isValidIdNumber(raw);
    return false;
  }

  private isRowValid(row: MemberRow): boolean {
    return (
      !this.isInvalid(row, 'name') &&
      !this.isInvalid(row, 'id_number') &&
      !this.isInvalid(row, 'date') &&
      !this.isInvalid(row, 'email')
    );
  }

  protected readonly outputFolder = computed(() => {
    const direct = this.outputDir().trim();
    if (direct) return direct;
    const batch = this.batchResult();
    if (batch?.output_dir) return batch.output_dir;
    return '';
  });

  protected readonly hasOutputFolder = computed(() => this.outputFolder().trim().length > 0);
  protected readonly hasGeneratedCards = computed(() => this.generatedCardCount() > 0);

  protected readonly hasActiveEmailCreds = computed(() => {
    const emailAddr = this.currentEmail().trim();
    const password = this.currentPassword();
    return !!emailAddr && !!password;
  });

  private previewDebounceTimer: number | null = null;

  constructor(private readonly http: HttpClient) {}

  async ngOnInit(): Promise<void> {
    try {
      const cfg = await firstValueFrom(this.http.get<ConfigOut>(`${this.apiBase}/config`));
      const v = (cfg?.output_dir ?? '').toString().trim();
      if (v) {
        this.outputDir.set(v);
        this.outputDefaultEnabled.set(true);
      }
    } catch {
      // ignore; API may not be up yet
    }

    await this.loadAssetDefaults();
    await this.loadEmailSettings();
    await this.refreshCardCount();
  }

  private clampPagination(): void {
    const pages = this.totalPages();
    if (!pages) {
      this.pageIndex.set(0);
      return;
    }
    const idx = this.pageIndex();
    if (idx < 0) this.pageIndex.set(0);
    else if (idx > pages - 1) this.pageIndex.set(pages - 1);
  }

  protected onPageSizeChange(value: string): void {
    const v = (value ?? '').toString().trim().toLowerCase();
    const next: PageSize =
      v === 'all' ? 'all' : (Number(v) === 10 ? 10 : Number(v) === 25 ? 25 : Number(v) === 50 ? 50 : Number(v) === 100 ? 100 : 25);
    this.pageSize.set(next);
    this.pageIndex.set(0);
    this.clampPagination();
  }

  protected onSearchChange(value: string): void {
    this.searchQuery.set((value ?? '').toString());
    this.pageIndex.set(0);
    this.clampPagination();
  }

  protected toggleSort(col: SortColumn): void {
    const current = this.sortColumn();
    if (current !== col) {
      this.sortColumn.set(col);
      this.sortDir.set('asc');
    } else if (this.sortDir() === 'asc') {
      this.sortDir.set('desc');
    } else {
      this.sortColumn.set(null);
      this.sortDir.set('asc');
    }
    this.pageIndex.set(0);
    this.clampPagination();
  }

  protected sortIndicator(col: SortColumn): string {
    if (this.sortColumn() !== col) return '↕';
    return this.sortDir() === 'asc' ? '▲' : '▼';
  }

  protected ariaSort(col: SortColumn): string | null {
    if (this.sortColumn() !== col) return 'none';
    return this.sortDir() === 'asc' ? 'ascending' : 'descending';
  }

  protected toggleSelectAllVisible(enabled: boolean): void {
    const view = this.viewMembers();
    if (!view.length) return;
    const rows = this.members();
    const next = rows.slice();
    for (const { index } of view) {
      if (index >= 0 && index < next.length) next[index] = { ...next[index], selected: !!enabled };
    }
    this.members.set(next);
  }

  protected prevPage(): void {
    if (this.totalPages() <= 1) return;
    this.pageIndex.set(Math.max(0, this.pageIndex() - 1));
  }

  protected nextPage(): void {
    const pages = this.totalPages();
    if (pages <= 1) return;
    this.pageIndex.set(Math.min(pages - 1, this.pageIndex() + 1));
  }

  private async refreshCardCount(): Promise<void> {
    try {
      const outDir = this.outputDir().trim();
      if (!outDir) {
        this.generatedCardCount.set(0);
        return;
      }
      const resp = await firstValueFrom(
        this.http.get<CardsCountOut>(`${this.apiBase}/cards/count`, { params: { output_dir: outDir } as any })
      );
      this.generatedCardCount.set(Number(resp?.count ?? 0) || 0);
    } catch {
      // ignore
    }
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
      this.templateDefaultEnabled.set(!!(tplPath || tplB64));
      this.signatureDefaultEnabled.set(!!(sigPath || sigB64));
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
    this.pendingSend.set(null);
    this.settingsOpen.set(false);
  }

  protected onTextChange(kind: 'name' | 'id' | 'date' | 'email', value: string): void {
    const v = value ?? '';
    if (kind === 'name') this.name.set(v);
    if (kind === 'id') this.idNumber.set(v);
    if (kind === 'date') this.date.set(v);
    if (kind === 'email') this.email.set(v);

    // If a table row is selected, edits in the form update that row live.
    const idx = this.selectedIndex();
    if (idx !== null) {
      const field: keyof Member =
        kind === 'name' ? 'name' : kind === 'id' ? 'id_number' : kind === 'date' ? 'date' : 'email';
      const rows = this.members();
      if (idx >= 0 && idx < rows.length) {
        const nextRows = rows.slice();
        const row = { ...nextRows[idx], [field]: v };
        nextRows[idx] = row;
        this.members.set(nextRows);
      }
    }
    this.schedulePreview();
  }

  protected onOutputDirChange(value: string): void {
    this.outputDir.set(value ?? '');
    this.generatedCardCount.set(0);
  }

  protected async setDefaultOutputDir(enabled: boolean): Promise<void> {
    const current = this.outputDir().trim();
    if (enabled) {
      if (!current) {
        this.error.set('Choose a save folder first.');
        this.outputDefaultEnabled.set(false);
        return;
      }
      try {
        await firstValueFrom(
          this.http.put<OutputSettingsOut>(`${this.apiBase}/settings/output`, { output_dir: current })
        );
        this.outputDefaultEnabled.set(true);
      } catch (e: any) {
        const msg = e?.error?.detail || e?.message || 'Failed to save default save folder.';
        this.error.set(String(msg));
        this.outputDefaultEnabled.set(false);
      }
      return;
    }

    try {
      await firstValueFrom(
        this.http.put<OutputSettingsOut>(`${this.apiBase}/settings/output`, { output_dir: null })
      );
      this.outputDefaultEnabled.set(false);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to clear default save folder.';
      this.error.set(String(msg));
    }
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
        await this.refreshCardCount();
      }
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to choose save folder.';
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
        this.http.put<AssetSettingsOut>(`${this.apiBase}/settings/assets`, {
          template_path: this.templatePath(),
          signature_path: this.signaturePath(),
          // When persisting by path, do not bloat settings with base64.
          template_base64: null,
          signature_base64: null,
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
      // Prefer persisting the currently-loaded in-memory base64 (from Choose file…).
      const b64 = kind === 'template' ? this.templateBase64() : this.signatureBase64();
      if (b64 && b64.trim()) {
        // Preserve the other asset default (path-based or base64-based) as-is.
        const currentTemplatePath = this.templatePath();
        const currentSignaturePath = this.signaturePath();
        const currentTemplateB64 =
          this.templateDefaultEnabled() && !currentTemplatePath ? (this.templateBase64() || '').trim() : '';
        const currentSignatureB64 =
          this.signatureDefaultEnabled() && !currentSignaturePath ? (this.signatureBase64() || '').trim() : '';

        if (kind === 'template') {
          this.templatePath.set(null);
          this.templateDefaultEnabled.set(true);
        } else {
          this.signaturePath.set(null);
          this.signatureDefaultEnabled.set(true);
        }

        try {
          const payload: AssetSettingsOut = {
            template_path: kind === 'template' ? null : currentTemplatePath,
            signature_path: kind === 'signature' ? null : currentSignaturePath,
            template_base64: kind === 'template' ? b64 : (currentTemplatePath ? null : (currentTemplateB64 || null)),
            signature_base64: kind === 'signature' ? b64 : (currentSignaturePath ? null : (currentSignatureB64 || null)),
          };
          await firstValueFrom(this.http.put<AssetSettingsOut>(`${this.apiBase}/settings/assets`, payload));
          this.schedulePreview();
          return;
        } catch (e: any) {
          const msg = e?.error?.detail || e?.message || 'Failed to save default setting.';
          this.error.set(String(msg));
          if (kind === 'template') this.templateDefaultEnabled.set(false);
          else this.signatureDefaultEnabled.set(false);
          return;
        }
      }

      // Fallback: if nothing is loaded yet, ask the backend to pick an on-disk file.
      const before = kind === 'template' ? this.templatePath() : this.signaturePath();
      await this.chooseDefaultAsset(kind);
      const after = kind === 'template' ? this.templatePath() : this.signaturePath();
      const ok = !!after && after !== before;
      if (!ok) {
        if (kind === 'template') this.templateDefaultEnabled.set(!!before);
        else this.signatureDefaultEnabled.set(!!before);
      }
      return;
    }

    // Disable default (but keep currently-loaded in-memory base64 if present)
    const currentTemplatePath = this.templatePath();
    const currentSignaturePath = this.signaturePath();
    const currentTemplateB64 =
      this.templateDefaultEnabled() && !currentTemplatePath ? (this.templateBase64() || '').trim() : '';
    const currentSignatureB64 =
      this.signatureDefaultEnabled() && !currentSignaturePath ? (this.signatureBase64() || '').trim() : '';

    if (kind === 'template') {
      this.templatePath.set(null);
      this.templateDefaultEnabled.set(false);
    } else {
      this.signaturePath.set(null);
      this.signatureDefaultEnabled.set(false);
    }

    try {
      await firstValueFrom(
        this.http.put<AssetSettingsOut>(`${this.apiBase}/settings/assets`, {
          template_path: kind === 'template' ? null : currentTemplatePath,
          signature_path: kind === 'signature' ? null : currentSignaturePath,
          template_base64: kind === 'template' ? null : (currentTemplatePath ? null : (currentTemplateB64 || null)),
          signature_base64: kind === 'signature' ? null : (currentSignaturePath ? null : (currentSignatureB64 || null)),
        })
      );
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to save default setting.';
      this.error.set(String(msg));
    }
  }

  protected async onUploadCsv(inputEl: HTMLInputElement, file: File | null): Promise<void> {
    if (!file) return;
    this.error.set(null);
    this.batchStatus.set(null);

    try {
      const form = new FormData();
      form.append('file', file, file.name);

      const resp = await firstValueFrom(this.http.post<{ members: Member[] }>(`${this.apiBase}/upload-csv`, form));

      const incoming = Array.isArray(resp.members) ? resp.members : [];
      const incomingRows: MemberRow[] = incoming.map((m) => ({
        name: m.name ?? '',
        id_number: this.normalizeIdNumber(m.id_number ?? ''),
        employer_id: ((m as any).employer_id ?? '').toString(),
        date: m.date ?? '',
        email: m.email ?? '',
        selected: true,
      }));
      const merged = [...this.members(), ...incomingRows].map((r) => ({ ...r, selected: true }));
      this.members.set(merged);
      this.pageIndex.set(0);
      this.clampPagination();
      this.batchStatus.set(`Loaded ${incoming.length} member(s) from ${file.name}.`);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to load CSV.';
      this.error.set(String(msg));
    } finally {
      // Allow selecting the same file again (some browsers won't fire change otherwise).
      try {
        inputEl.value = '';
      } catch {}
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

  protected addMemberRow(): void {
    const rows = this.members();
    const next: MemberRow = { name: '', id_number: '', employer_id: '', date: '', email: '', selected: true };
    const updated = [...rows, next];
    this.members.set(updated);
    this.selectRow(updated.length - 1);
    this.clampPagination();
  }

  protected removeMember(index: number): void {
    const rows = this.members();
    if (index < 0 || index >= rows.length) return;

    const next = rows.slice();
    next.splice(index, 1);
    this.members.set(next);
    this.clampPagination();

    const sel = this.selectedIndex();
    if (sel === null) return;

    if (sel === index) {
      this.selectedIndex.set(null);
      this.name.set('');
      this.idNumber.set('');
      this.date.set('');
      this.email.set('');
      this.schedulePreview();
      return;
    }

    if (sel > index) {
      this.selectedIndex.set(sel - 1);
    }
  }

  protected toggleSelectAll(enabled: boolean): void {
    this.toggleSelectAllVisible(!!enabled);
  }

  protected toggleRowSelected(index: number, enabled: boolean): void {
    const rows = this.members();
    if (index < 0 || index >= rows.length) return;
    const next = rows.slice();
    next[index] = { ...next[index], selected: !!enabled };
    this.members.set(next);
  }

  protected updateRowField(index: number, field: keyof Member, value: string): void {
    const rows = this.members();
    if (index < 0 || index >= rows.length) return;

    const nextRows = rows.slice();
    const row = { ...nextRows[index] };
    if (field === 'id_number') row[field] = this.normalizeIdNumber(value ?? '');
    else row[field] = value ?? '';
    nextRows[index] = row;
    this.members.set(nextRows);
    this.clampPagination();

    if (this.selectedIndex() === index) {
      this.name.set(row.name || '');
      this.idNumber.set(row.id_number || '');
      this.date.set(row.date || '');
      this.email.set(row.email || '');
      this.schedulePreview();
    }
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
    const member: MemberRow = {
      name: this.name().trim(),
      id_number: this.idNumber().trim(),
      employer_id: '',
      date: this.date().trim(),
      email: this.email().trim(),
      selected: true,
    };

    const idx = this.selectedIndex();
    const rows = this.members();
    if (idx === null) {
      this.members.set([...rows, member]);
      this.batchStatus.set('Added member to table.');
    } else {
      const next = rows.slice();
      next[idx] = { ...member, selected: rows[idx]?.selected ?? true };
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

    const outDir = this.outputDir().trim();
    if (!outDir) {
      this.error.set('Choose a save folder first.');
      return;
    }

    const chosen = this.selectedMembers();
    if (!chosen.length) {
      this.error.set('No members selected.');
      return;
    }

    this.isLoading.set(true);
    this.batchStatus.set(`Creating ${chosen.length} card(s)...`);
    try {
      const payload = {
        members: chosen,
        template_base64: template,
        signature_base64: this.signatureBase64(),
        output_dir: outDir,
      };

      const resp = await firstValueFrom(
        this.http.post<GenerateBatchOut>(`${this.apiBase}/generate-batch`, payload)
      );
      this.batchResult.set(resp);
      // Optimistic: ensure Clear cards can enable even if /cards/count isn't available yet.
      if ((resp?.ok ?? 0) > 0) this.generatedCardCount.set(Math.max(this.generatedCardCount(), Number(resp.ok) || 0));
      await this.refreshCardCount();
      const outDirMsg = resp.output_dir ? ` Saved to: ${resp.output_dir}` : '';
      this.batchStatus.set(
        `Batch complete: ${resp.ok} saved, ${resp.skipped} skipped, ${resp.errors} errors.${outDirMsg}`
      );
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to create cards.';
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
    this.generateStatus.set('Creating card...');
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
      this.generatedCardCount.set(Math.max(this.generatedCardCount(), 1));
      await this.refreshCardCount();
      this.generateStatus.set(`Saved: ${resp.filename}`);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to create card.';
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

  protected async openOutputFolder(): Promise<void> {
    this.error.set(null);
    const folder = this.outputFolder().trim();
    if (!folder) {
      this.error.set('Set a save folder first (or create cards to establish one).');
      return;
    }
    try {
      await firstValueFrom(this.http.post<OpenPathOut>(`${this.apiBase}/open-path`, { path: folder }));
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to open folder.';
      this.error.set(String(msg));
    }
  }

  protected exportCsv(): void {
    const rows = this.members();
    const headers = ['name', 'id_number', 'employer_id', 'date', 'email'];

    const esc = (v: string) => {
      const s = (v ?? '').toString();
      if (/[\",\n\r]/.test(s)) return `"${s.replace(/\"/g, '""')}"`;
      return s;
    };

    const lines: string[] = [];
    lines.push(headers.join(','));
    for (const r of rows) {
      lines.push([r.name, r.id_number, r.employer_id, r.date, r.email].map(esc).join(','));
    }

    const blob = new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'members.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
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
      this.unionMgmtEnabled.set(!!s.union_management?.enabled);
      this.unionMgmtEmail.set((s.union_management?.email ?? '').toString());
      this.emailSender.set((s.active_sender ?? 'Membership Officer') as OfficerRole);
      this.msSenderProfiles.set((s.microsoft_senders ?? {}) as any);
      this.gmailSenderProfiles.set((s.gmail_senders ?? {}) as any);

      // Load the active sender profile for each provider (fallback to provider defaults).
      const role = (s.active_sender ?? 'Membership Officer') as OfficerRole;
      const msProfile = (s.microsoft_senders?.[role] ?? s.microsoft) as any;
      const gmailProfile = (s.gmail_senders?.[role] ?? s.gmail) as any;

      this.msEmail.set((msProfile?.email ?? '').toString());
      this.msPassword.set((msProfile?.password ?? '').toString());
      this.msFromName.set((msProfile?.from_name ?? '').toString());
      this.msSubjectTpl.set((msProfile?.subject_tpl ?? this.msSubjectTpl()).toString());
      this.msBodyTpl.set((msProfile?.body_tpl ?? this.msBodyTpl()).toString());

      this.gmailEmail.set((gmailProfile?.email ?? '').toString());
      this.gmailPassword.set((gmailProfile?.password ?? '').toString());
      this.gmailFromName.set((gmailProfile?.from_name ?? '').toString());
      this.gmailSubjectTpl.set((gmailProfile?.subject_tpl ?? this.gmailSubjectTpl()).toString());
      this.gmailBodyTpl.set((gmailProfile?.body_tpl ?? this.gmailBodyTpl()).toString());
    } catch {
      // ignore; API may not be up yet
    }
  }

  protected async saveEmailSettings(): Promise<void> {
    this.settingsStatus.set(null);
    this.isSavingSettings.set(true);
    try {
      const role = this.emailSender();
      const nextMsProfiles: any = { ...(this.msSenderProfiles() ?? {}) };
      const nextGmailProfiles: any = { ...(this.gmailSenderProfiles() ?? {}) };

      // Save the current form values into the active sender profile.
      const msProfile: EmailAccountSettings = {
        email: this.msEmail().trim(),
        password: this.msPassword(),
        from_name: this.msFromName(),
        subject_tpl: this.msSubjectTpl(),
        body_tpl: this.msBodyTpl(),
      };
      const gmailProfile: EmailAccountSettings = {
        email: this.gmailEmail().trim(),
        password: this.gmailPassword(),
        from_name: this.gmailFromName(),
        subject_tpl: this.gmailSubjectTpl(),
        body_tpl: this.gmailBodyTpl(),
      };

      nextMsProfiles[role] = msProfile;
      nextGmailProfiles[role] = gmailProfile;

      const payload: EmailSettingsV2 = {
        active: this.emailActive(),
        active_sender: role,
        microsoft: {
          email: this.msEmail().trim(),
          password: this.msPassword(),
          from_name: this.msFromName(),
          subject_tpl: this.msSubjectTpl(),
          body_tpl: this.msBodyTpl(),
        },
        gmail: {
          email: this.gmailEmail().trim(),
          password: this.gmailPassword(),
          from_name: this.gmailFromName(),
          subject_tpl: this.gmailSubjectTpl(),
          body_tpl: this.gmailBodyTpl(),
        },
        microsoft_senders: nextMsProfiles,
        gmail_senders: nextGmailProfiles,
        union_management: {
          enabled: !!this.unionMgmtEnabled(),
          email: this.unionMgmtEmail().trim(),
        },
        defaults: this.emailDefaults() ?? ({} as any),
      };

      const resp = await firstValueFrom(this.http.put<EmailSettingsV2>(`${this.apiBase}/settings/email`, payload));
      if (resp?.defaults) this.emailDefaults.set(resp.defaults);
      if (resp?.active_sender) this.emailSender.set(resp.active_sender as OfficerRole);
      this.msSenderProfiles.set((resp?.microsoft_senders ?? nextMsProfiles) as any);
      this.gmailSenderProfiles.set((resp?.gmail_senders ?? nextGmailProfiles) as any);
      this.settingsStatus.set('Saved.');
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to save settings.';
      this.settingsStatus.set(String(msg));
      this.error.set(String(msg));
    } finally {
      this.isSavingSettings.set(false);
    }
  }

  protected applyQuickSender(role: OfficerRole): void {
    const OFFICER_EMAILS: Record<OfficerRole, string> = {
      President: 'president@cupe3523.ca',
      'Vice President': 'vice.president@cupe3523.ca',
      'Membership Officer': 'membership.officer@cupe3523.ca',
    };

    this.emailSender.set(role);
    this.settingsStatus.set(`Selected ${role}.`);

    const addr = (OFFICER_EMAILS[role] || '').trim();

    if (this.emailActive() === 'microsoft') {
      const profiles = this.msSenderProfiles() ?? {};
      const p = (profiles as any)[role] as EmailAccountSettings | undefined;
      if (p) {
        this.msEmail.set((p.email ?? '').toString());
        this.msPassword.set((p.password ?? '').toString());
        this.msFromName.set((p.from_name ?? '').toString());
        this.msSubjectTpl.set((p.subject_tpl ?? this.msSubjectTpl()).toString());
        this.msBodyTpl.set((p.body_tpl ?? this.msBodyTpl()).toString());
      } else {
        if (addr) this.msEmail.set(addr);
        this.msFromName.set(role);
      }
    } else {
      const profiles = this.gmailSenderProfiles() ?? {};
      const p = (profiles as any)[role] as EmailAccountSettings | undefined;
      if (p) {
        this.gmailEmail.set((p.email ?? '').toString());
        this.gmailPassword.set((p.password ?? '').toString());
        this.gmailFromName.set((p.from_name ?? '').toString());
        this.gmailSubjectTpl.set((p.subject_tpl ?? this.gmailSubjectTpl()).toString());
        this.gmailBodyTpl.set((p.body_tpl ?? this.gmailBodyTpl()).toString());
      } else {
        if (addr) this.gmailEmail.set(addr);
        this.gmailFromName.set(role);
      }
    }
  }

  protected canSendWithActiveSettings(): boolean {
    const emailAddr = this.currentEmail().trim();
    const password = this.currentPassword();
    if (!emailAddr || !password) return false;
    if (this.unionMgmtEnabled()) {
      const cc = this.unionMgmtEmail().trim();
      if (!cc || !this.isValidEmail(cc)) return false;
    }
    return true;
  }

  protected async sendPendingFromModal(): Promise<void> {
    const pending = this.pendingSend();
    if (!pending) return;

    if (pending === 'one') {
      await this.sendEmailOne({ fromSettingsModal: true });
    } else {
      await this.sendEmailBatch({ fromSettingsModal: true });
    }
  }

  protected async sendEmailBatch(opts?: { fromSettingsModal?: boolean }): Promise<void> {
    this.error.set(null);
    this.emailStatus.set(null);
    this.emailResult.set(null);

    const outDir = this.outputDir().trim();
    if (!outDir) {
      this.error.set('Choose a save folder first.');
      return;
    }

    const chosen = this.selectedMembers();
    if (!chosen.length) {
      this.error.set('No members selected.');
      return;
    }

    const emailAddr = this.currentEmail().trim();
    const password = this.currentPassword();
    const defaults = this.emailDefaults();
    const provider = this.emailActive();
    const d = defaults?.[provider];

    if (!emailAddr || !password) {
      this.error.set('Enter email + password for the active account in Email settings.');
      if (!opts?.fromSettingsModal) {
        this.pendingSend.set('batch');
        this.openSettings();
      }
      return;
    }
    if (!d) {
      this.error.set('Email defaults not loaded yet. Try again.');
      return;
    }

    this.isEmailing.set(true);
    this.isLoading.set(true);
    this.emailStatus.set(`Sending ${chosen.length} email(s)...`);

    try {
      const payload = {
        members: chosen,
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
        output_dir: outDir,
      };

      const resp = await firstValueFrom(this.http.post<EmailOut>(`${this.apiBase}/email`, payload));
      this.emailResult.set(resp);
      this.emailStatus.set(`Email complete: ${resp.sent} sent, ${resp.skipped} skipped, ${resp.errors} errors.`);
      this.pendingSend.set(null);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to send email.';
      this.error.set(null);
      this.emailStatus.set(this.friendlyEmailFailureMessage(String(msg)));
    } finally {
      this.isEmailing.set(false);
      this.isLoading.set(false);
    }
  }

  protected async sendEmailOne(opts?: { fromSettingsModal?: boolean }): Promise<void> {
    this.error.set(null);
    this.emailStatus.set(null);
    this.emailResult.set(null);

    const outDir = this.outputDir().trim();
    if (!outDir) {
      this.error.set('Choose a save folder first.');
      return;
    }

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
      if (!opts?.fromSettingsModal) {
        this.pendingSend.set('one');
        this.openSettings();
      }
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
        output_dir: outDir,
      };

      const resp = await firstValueFrom(this.http.post<EmailOut>(`${this.apiBase}/email`, payload));
      this.emailResult.set(resp);
      this.emailStatus.set(`Email complete: ${resp.sent} sent, ${resp.skipped} skipped, ${resp.errors} errors.`);
      this.pendingSend.set(null);
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to send email.';
      this.error.set(null);
      this.emailStatus.set(this.friendlyEmailFailureMessage(String(msg)));
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
        'Failed to create preview. Ensure the Python API is running.';
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

  protected async clearCards(): Promise<void> {
    this.error.set(null);
    this.batchStatus.set(null);

    if (!this.clearConfirm()) {
      this.clearConfirm.set(true);
      this.batchStatus.set('Ready to delete all generated cards. Click Clear cards again to confirm (6s).');
      if (this.clearConfirmTimer !== null) window.clearTimeout(this.clearConfirmTimer);
      this.clearConfirmTimer = window.setTimeout(() => {
        this.clearConfirm.set(false);
        this.batchStatus.set('Clear cancelled.');
      }, 6000);
      return;
    }

    if (this.clearConfirmTimer !== null) {
      window.clearTimeout(this.clearConfirmTimer);
      this.clearConfirmTimer = null;
    }
    this.clearConfirm.set(false);

    this.isLoading.set(true);
    try {
      const outputDir = this.outputDir().trim();
      if (!outputDir) {
        this.error.set('Choose a save folder first.');
        this.batchStatus.set('Choose a save folder first.');
        return;
      }
      const resp = await firstValueFrom(
        this.http.post<ClearCardsOut>(`${this.apiBase}/clear-cards`, { output_dir: outputDir })
      );

      // Reset UI state (keep template/signature + output dir settings).
      this.members.set([]);
      this.selectedIndex.set(null);
      this.name.set('');
      this.idNumber.set('');
      this.date.set('');
      this.email.set('');
      this.batchResult.set(null);
      this.emailResult.set(null);
      this.emailStatus.set(null);
      this.warning.set(null);
      this.previewPngBase64.set(null);

      this.batchStatus.set(`Cleared ${resp.deleted} card(s).`);
      this.generatedCardCount.set(0);
      await this.refreshCardCount();
      this.schedulePreview();
    } catch (e: any) {
      const msg = e?.error?.detail || e?.message || 'Failed to clear cards.';
      this.error.set(String(msg));
      this.batchStatus.set(String(msg));
    } finally {
      this.isLoading.set(false);
    }
  }

  protected onWindowKeydown(ev: KeyboardEvent): void {
    // F1 should open help, even when focus is inside an input (WebView often eats app-level shortcuts).
    const key = (ev.key || '').toLowerCase();
    const isF1 = key === 'f1' || (ev as any).keyCode === 112;
    if (!isF1) return;
    try {
      ev.preventDefault();
      (ev as any).stopPropagation?.();
    } catch {}
    this.openHelp();
  }

  protected async openHelp(): Promise<void> {
    try {
      await firstValueFrom(this.http.post<OpenHelpOut>(`${this.apiBase}/open-help`, {}));
    } catch {
      this.error.set('Failed to open Help. Ensure the Python API is running.');
    }
  }
}
