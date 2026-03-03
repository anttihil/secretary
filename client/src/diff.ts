export interface DiffToken {
  id: number;
  kind: "equal" | "delete" | "insert";
  text: string;
  /** Trailing whitespace after this token */
  space: string;
  /** ID of paired token (delete↔insert) */
  pairId?: number;
}

interface WordToken {
  text: string;
  space: string;
}

function tokenize(str: string): WordToken[] {
  const tokens: WordToken[] = [];
  const re = /(\S+)(\s*)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(str)) !== null) {
    tokens.push({ text: m[1], space: m[2] });
  }
  return tokens;
}

export function computeDiff(original: string, cleaned: string): DiffToken[] {
  const a = tokenize(original);
  const b = tokenize(cleaned);
  const m = a.length;
  const n = b.length;

  // LCS DP
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    new Array(n + 1).fill(0),
  );
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      if (a[i].text === b[j].text) {
        dp[i][j] = dp[i + 1][j + 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }

  // Build diff tokens from LCS
  const result: DiffToken[] = [];
  let id = 0;
  let i = 0;
  let j = 0;

  while (i < m || j < n) {
    if (i < m && j < n && a[i].text === b[j].text) {
      result.push({ id: id++, kind: "equal", text: a[i].text, space: b[j].space || a[i].space });
      i++;
      j++;
    } else if (j < n && (i >= m || dp[i][j + 1] > dp[i + 1][j])) {
      result.push({ id: id++, kind: "insert", text: b[j].text, space: b[j].space });
      j++;
    } else {
      result.push({ id: id++, kind: "delete", text: a[i].text, space: a[i].space });
      i++;
    }
  }

  // Link adjacent delete+insert pairs
  for (let k = 0; k < result.length - 1; k++) {
    if (result[k].kind === "delete" && result[k + 1].kind === "insert") {
      result[k].pairId = result[k + 1].id;
      result[k + 1].pairId = result[k].id;
      k++; // skip the insert
    }
  }

  return result;
}

/**
 * Build final text from diff tokens and user choices.
 * `choices` maps token id → "old" | "new".
 * For paired tokens, keyed by the delete token's id.
 * Undecided tokens default to accepting the change (new).
 */
export function buildResult(
  tokens: DiffToken[],
  choices: Map<number, "old" | "new">,
): string {
  let out = "";
  for (const t of tokens) {
    if (t.kind === "equal") {
      out += t.text + t.space;
    } else if (t.kind === "delete") {
      if (t.pairId !== undefined) {
        // Paired: include old text only if user chose "old"
        const choice = choices.get(t.id);
        if (choice === "old") {
          out += t.text + t.space;
        }
        // "new" or undecided → skip delete (insert will emit)
      } else {
        // Unpaired delete: keep if user chose "old", otherwise remove
        const choice = choices.get(t.id);
        if (choice === "old") {
          out += t.text + t.space;
        }
        // undecided defaults to accepting deletion
      }
    } else if (t.kind === "insert") {
      if (t.pairId !== undefined) {
        // Paired: include new text unless user chose "old"
        const choice = choices.get(t.pairId);
        if (choice !== "old") {
          out += t.text + t.space;
        }
      } else {
        // Unpaired insert: include unless user explicitly rejected
        const choice = choices.get(t.id);
        if (choice !== "old") {
          out += t.text + t.space;
        }
      }
    }
  }
  return out;
}
