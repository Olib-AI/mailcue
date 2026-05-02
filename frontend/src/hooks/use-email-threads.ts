import { useMemo } from "react";
import { useEmails } from "./use-emails";
import type { EmailSummary } from "@/types/api";

/**
 * A single conversation thread — a sequence of emails sharing the same
 * `thread_id`, sorted ascending by date so the latest message is at the tail.
 */
export interface ThreadSummary {
  thread_id: string;
  emails: EmailSummary[];
  latest: EmailSummary;
  count: number;
  has_unread: boolean;
}

export interface ThreadListData {
  threads: ThreadSummary[];
  total: number;
  loadedEmailCount: number;
}

/**
 * Group a flat list of emails into thread summaries.
 *
 * - Emails missing a `thread_id` (older backends, non-thread queries) are
 *   treated as singleton threads keyed by `mailbox:uid` so the UI still
 *   renders correctly.
 * - Emails inside each thread are sorted ascending by date.
 * - Threads themselves are sorted by their latest email's date, descending.
 */
function groupIntoThreads(emails: readonly EmailSummary[]): ThreadSummary[] {
  const buckets = new Map<string, EmailSummary[]>();

  for (const email of emails) {
    const key =
      email.thread_id && email.thread_id.length > 0
        ? email.thread_id
        : `__single__:${email.mailbox}:${email.uid}`;
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.push(email);
    } else {
      buckets.set(key, [email]);
    }
  }

  const threads: ThreadSummary[] = [];
  for (const [thread_id, group] of buckets) {
    const sorted = [...group].sort(
      (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
    );
    const latest = sorted[sorted.length - 1];
    if (!latest) continue;
    threads.push({
      thread_id,
      emails: sorted,
      latest,
      count: sorted.length,
      has_unread: sorted.some((e) => !e.is_read),
    });
  }

  threads.sort(
    (a, b) =>
      new Date(b.latest.date).getTime() - new Date(a.latest.date).getTime()
  );

  return threads;
}

/**
 * Wraps {@link useEmails} with `thread_view=true` and groups the resulting
 * pages into {@link ThreadSummary} objects.
 */
export function useEmailThreads(
  mailbox: string | null,
  folder: string,
  search?: string
) {
  const query = useEmails(mailbox, folder, search, true);

  const data = useMemo<ThreadListData | undefined>(() => {
    if (!query.data) return undefined;
    const flat = query.data.pages.flatMap((page) => page.emails);
    const threads = groupIntoThreads(flat);
    const total = query.data.pages[0]?.total ?? flat.length;
    return {
      threads,
      total,
      loadedEmailCount: flat.length,
    };
  }, [query.data]);

  return {
    data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isFetching: query.isFetching,
    refetch: query.refetch,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
  } as const;
}
