import { ScrollArea } from "@/components/ui/scroll-area";

interface EmailHeadersProps {
  headers: Record<string, string>;
}

function EmailHeaders({ headers }: EmailHeadersProps) {
  const entries = Object.entries(headers);

  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground p-4">
        No headers available
      </p>
    );
  }

  return (
    <ScrollArea className="max-h-[500px]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-left font-medium p-2 w-48 text-muted-foreground">
              Header
            </th>
            <th className="text-left font-medium p-2 text-muted-foreground">
              Value
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key} className="border-b last:border-0">
              <td className="p-2 align-top font-mono text-xs font-medium text-primary">
                {key}
              </td>
              <td className="p-2 align-top font-mono text-xs break-all whitespace-pre-wrap">
                {value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollArea>
  );
}

export { EmailHeaders };
