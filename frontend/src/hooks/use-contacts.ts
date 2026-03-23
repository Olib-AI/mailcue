import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { extractEmailAddress, extractDisplayName } from "@/lib/utils";
import type { EmailListResponse } from "@/types/api";

interface Contact {
  email: string;
  name: string;
  count: number;
}

export function useContacts(mailbox: string | null) {
  const { data } = useQuery({
    queryKey: ["contacts", mailbox ?? ""],
    queryFn: () => {
      const params = new URLSearchParams({
        folder: "INBOX",
        page: "1",
        page_size: "100",
      });
      return api.get<EmailListResponse>(
        `/mailboxes/${encodeURIComponent(mailbox ?? "")}/emails?${params.toString()}`
      );
    },
    enabled: !!mailbox,
    staleTime: 5 * 60 * 1000,
  });

  const contacts = useMemo(() => {
    if (!data) return [];

    const frequencyMap = new Map<string, { name: string; count: number }>();

    for (const email of data.emails) {
      // from_address
      const fromRaw = extractEmailAddress(email.from_address).toLowerCase();
      const fromName = email.from_name || extractDisplayName(email.from_address);
      const existing = frequencyMap.get(fromRaw);
      if (existing) {
        existing.count += 1;
        // Prefer a non-email name
        if (existing.name === existing.name.toLowerCase() && fromName !== fromRaw) {
          existing.name = fromName;
        }
      } else {
        frequencyMap.set(fromRaw, { name: fromName !== fromRaw ? fromName : "", count: 1 });
      }

      // to_addresses
      for (const addr of email.to_addresses) {
        const toRaw = extractEmailAddress(addr).toLowerCase();
        const toName = extractDisplayName(addr);
        const ex = frequencyMap.get(toRaw);
        if (ex) {
          ex.count += 1;
          if (!ex.name && toName !== toRaw) {
            ex.name = toName;
          }
        } else {
          frequencyMap.set(toRaw, { name: toName !== toRaw ? toName : "", count: 1 });
        }
      }
    }

    const result: Contact[] = [];
    for (const [email, { name, count }] of frequencyMap) {
      result.push({ email, name, count });
    }

    result.sort((a, b) => b.count - a.count);
    return result;
  }, [data]);

  return contacts;
}
