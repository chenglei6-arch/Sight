/** Saves run in order across graph views; pending changes coalesce to the latest snapshot. */
export class SerializedGraphSaver {
  private pending = new Map<string, () => Promise<number | null>>();
  private running = false;
  private waiters = new Map<string, Array<(id: number | null) => void>>();
  enqueue(
    save: () => Promise<number | null>,
    key = "default",
  ): Promise<number | null> {
    this.pending.set(key, save);
    const result = new Promise<number | null>((resolve) =>
      this.waiters.set(key, [...(this.waiters.get(key) || []), resolve]),
    );
    if (!this.running) void this.drain();
    return result;
  }
  private async drain() {
    this.running = true;
    let id: number | null = null;
    try {
      while (this.pending.size) {
        const [key, save] = this.pending.entries().next().value!;
        this.pending.delete(key);
        try {
          id = await save();
        } catch {
          id = null;
        }
        if (!this.pending.has(key)) {
          const waiters = this.waiters.get(key) || [];
          this.waiters.delete(key);
          waiters.forEach((resolve) => resolve(id));
        }
      }
    } finally {
      this.running = false;
    }
  }
}
export const graphSaves = new SerializedGraphSaver();
