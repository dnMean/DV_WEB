/** Append-only JSONL audit log of every tool invocation. */
import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { dirname } from 'node:path';

import { log } from './common/logging';

export class AuditLog {
  private queue: Promise<void> = Promise.resolve();

  constructor(private readonly path: string) {}

  write(entry: Record<string, unknown>): void {
    const line = JSON.stringify({ ts: new Date().toISOString(), ...entry }) + '\n';
    // serialized appends keep lines whole and in order
    this.queue = this.queue
      .then(async () => {
        await mkdir(dirname(this.path), { recursive: true });
        await appendFile(this.path, line, 'utf-8');
      })
      .catch((exc) => log.error(`cannot write audit log to ${this.path}`, exc));
  }

  async tail(limit: number): Promise<unknown[]> {
    let text: string;
    try {
      text = await readFile(this.path, 'utf-8');
    } catch {
      return [];
    }
    return text.split('\n').filter(Boolean).slice(-limit).reverse().map((line) => JSON.parse(line));
  }
}
