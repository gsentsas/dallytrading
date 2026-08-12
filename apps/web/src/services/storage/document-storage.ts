/**
 * Document storage — interface only, deliberately.
 *
 * ## Why there is no implementation
 *
 * Public file upload is not implemented, and this file exists so that when it is,
 * it lands behind an abstraction rather than in an ad-hoc `fs.writeFile` next to
 * the Next.js build.
 *
 * The blocking questions are not technical, they are decisions nobody has taken:
 *
 * * **Where.** An S3-compatible bucket is the intended answer, but the provider,
 *   the region and the retention period are unknown. Customs documents and
 *   commercial invoices are involved, so the jurisdiction is a real question.
 * * **How long.** Retention interacts with the privacy policy (§74). Keeping a
 *   customer's passport scan indefinitely because nobody chose a period is the
 *   kind of default that becomes a liability.
 * * **What is accepted.** A MIME allowlist, a size cap and a virus-scanning
 *   decision. "Accept anything and sort it out later" is how a file upload becomes
 *   a malware distribution endpoint.
 *
 * ## The one rule that already applies
 *
 * **No user file is ever written to the front-end filesystem.** A Next.js instance
 * is disposable — it is rebuilt on every deploy and, on a VPS, runs in a container
 * whose filesystem does not survive a restart. A document written there is lost,
 * and worse, is lost silently. Every implementation of this interface must target
 * external storage.
 *
 * Until then, the quote form does not offer an upload, and asks customers to send
 * documents by e-mail or WhatsApp with their reference. That is a worse experience
 * and a deliberate one: it loses nothing.
 */

/** A stored document, as referenced from elsewhere in the system. */
export interface StoredDocument {
  /**
   * Opaque storage key. Never a path the client chose, and never a sequential id:
   * both let a caller reach documents that are not theirs.
   */
  readonly key: string;
  readonly filename: string;
  readonly contentType: string;
  readonly sizeBytes: number;
  readonly uploadedAt: string;
  /** Business reference this document belongs to, e.g. DT-2026-000124. */
  readonly reference: string;
}

export interface UploadRequest {
  readonly filename: string;
  readonly contentType: string;
  readonly sizeBytes: number;
  readonly reference: string;
  readonly content: Uint8Array;
}

/** Why an upload was refused. Stable codes, so the UI can branch on them. */
export type StorageRejection =
  | 'type_not_allowed'
  | 'too_large'
  | 'empty'
  | 'quota_exceeded'
  | 'unavailable';

export class DocumentStorageError extends Error {
  readonly reason: StorageRejection;

  constructor(reason: StorageRejection, message: string) {
    super(message);
    this.name = 'DocumentStorageError';
    this.reason = reason;
  }
}

/**
 * Contract every storage backend must satisfy.
 *
 * Note what is absent: no method returns a filesystem path, and none accepts one.
 * Documents are addressed by opaque key and read through time-limited URLs, so a
 * backend swap cannot leak a local path into a template or an e-mail.
 */
export interface DocumentStorage {
  /**
   * Store a document.
   *
   * Implementations must validate type and size themselves and throw
   * `DocumentStorageError` — validation cannot be left to callers, because the
   * one caller that forgets is the vulnerability.
   */
  put(request: UploadRequest): Promise<StoredDocument>;

  /**
   * Issue a short-lived URL to read a document.
   *
   * Time-limited on purpose: a permanent public URL to a customs document is a
   * leak waiting for someone to forward an e-mail.
   */
  getSignedUrl(key: string, expiresInSeconds: number): Promise<string>;

  /** Remove a document. Needed for the deletion right (§74). */
  delete(key: string): Promise<void>;

  /** Documents attached to a business reference. */
  list(reference: string): Promise<ReadonlyArray<StoredDocument>>;
}

/**
 * Placeholder backend.
 *
 * Every method fails with a clear message. Deliberately not a no-op that pretends
 * to succeed: silently discarding a customer's customs document is far worse than
 * an explicit refusal, and a no-op would let an upload feature ship looking as
 * though it worked.
 */
export class UnconfiguredDocumentStorage implements DocumentStorage {
  private static readonly MESSAGE =
    'Document storage is not configured. Uploads are disabled until a backend ' +
    '(bucket, retention period and accepted types) has been decided.';

  async put(_request: UploadRequest): Promise<StoredDocument> {
    throw new DocumentStorageError(
      'unavailable',
      UnconfiguredDocumentStorage.MESSAGE,
    );
  }

  async getSignedUrl(_key: string, _expiresInSeconds: number): Promise<string> {
    throw new DocumentStorageError(
      'unavailable',
      UnconfiguredDocumentStorage.MESSAGE,
    );
  }

  async delete(_key: string): Promise<void> {
    throw new DocumentStorageError(
      'unavailable',
      UnconfiguredDocumentStorage.MESSAGE,
    );
  }

  async list(_reference: string): Promise<ReadonlyArray<StoredDocument>> {
    // An empty list rather than a throw: "this reference has no documents" is a
    // truthful answer when storage is disabled, and it lets a page render.
    return [];
  }
}

let instance: DocumentStorage | null = null;

/** The configured storage backend. */
export function getDocumentStorage(): DocumentStorage {
  instance ??= new UnconfiguredDocumentStorage();
  return instance;
}

/** Replace the backend. For tests, and for wiring a real one in later. */
export function setDocumentStorage(storage: DocumentStorage | null): void {
  instance = storage;
}

/** Whether uploads can be offered at all. The UI must check before showing one. */
export function isDocumentStorageConfigured(): boolean {
  return !(getDocumentStorage() instanceof UnconfiguredDocumentStorage);
}
