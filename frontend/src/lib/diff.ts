// =============================================================================
// Simple line-level diff for comparing email content.
// Uses a basic LCS (Longest Common Subsequence) approach to produce
// an array of diff operations that can be rendered with add/remove styling.
// =============================================================================

type DiffOp = "equal" | "add" | "remove";

interface DiffLine {
  op: DiffOp;
  text: string;
}

/**
 * Compute a line-level diff between two strings.
 * Returns an array of DiffLine entries with operations.
 */
function diffLines(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");

  const m = oldLines.length;
  const n = newLines.length;

  // Build LCS table
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    Array.from({ length: n + 1 }, () => 0)
  );

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldLines[i - 1] === newLines[j - 1]) {
        dp[i]![j] = (dp[i - 1]?.[j - 1] ?? 0) + 1;
      } else {
        dp[i]![j] = Math.max(dp[i - 1]?.[j] ?? 0, dp[i]?.[j - 1] ?? 0);
      }
    }
  }

  // Backtrack to produce diff
  const result: DiffLine[] = [];
  let i = m;
  let j = n;

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      result.push({ op: "equal", text: oldLines[i - 1] ?? "" });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || (dp[i]?.[j - 1] ?? 0) >= (dp[i - 1]?.[j] ?? 0))) {
      result.push({ op: "add", text: newLines[j - 1] ?? "" });
      j--;
    } else {
      result.push({ op: "remove", text: oldLines[i - 1] ?? "" });
      i--;
    }
  }

  return result.reverse();
}

/**
 * Compute a word-level diff between two strings for inline highlighting.
 */
function diffWords(oldText: string, newText: string): DiffLine[] {
  const oldWords = oldText.split(/(\s+)/);
  const newWords = newText.split(/(\s+)/);

  const m = oldWords.length;
  const n = newWords.length;

  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    Array.from({ length: n + 1 }, () => 0)
  );

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (oldWords[i - 1] === newWords[j - 1]) {
        dp[i]![j] = (dp[i - 1]?.[j - 1] ?? 0) + 1;
      } else {
        dp[i]![j] = Math.max(dp[i - 1]?.[j] ?? 0, dp[i]?.[j - 1] ?? 0);
      }
    }
  }

  const result: DiffLine[] = [];
  let i = m;
  let j = n;

  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldWords[i - 1] === newWords[j - 1]) {
      result.push({ op: "equal", text: oldWords[i - 1] ?? "" });
      i--;
      j--;
    } else if (j > 0 && (i === 0 || (dp[i]?.[j - 1] ?? 0) >= (dp[i - 1]?.[j] ?? 0))) {
      result.push({ op: "add", text: newWords[j - 1] ?? "" });
      j--;
    } else {
      result.push({ op: "remove", text: oldWords[i - 1] ?? "" });
      i--;
    }
  }

  return result.reverse();
}

export { diffLines, diffWords };
export type { DiffLine, DiffOp };
