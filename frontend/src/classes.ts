type ClassValue =
  string | false | null | undefined | Record<string, unknown> | ClassValue[];

/** Resolve local CSS module names while retaining the shared design-system classes. */
export function classNames(styles: Record<string, string>) {
  return (...values: ClassValue[]): string => {
    const tokens: string[] = [];
    function append(value: ClassValue) {
      if (!value) return;
      if (typeof value === "string")
        tokens.push(...value.split(/\s+/).filter(Boolean));
      else if (Array.isArray(value)) value.forEach(append);
      else
        Object.entries(value).forEach(([name, enabled]) => {
          if (enabled) append(name);
        });
    }
    values.forEach(append);
    // A component may refine a shared class (e.g. `.head-actions .btn`).
    // Keep its original name so the global base rules still apply alongside the module.
    return tokens
      .map((name) => (styles[name] ? `${name} ${styles[name]}` : name))
      .join(" ");
  };
}
