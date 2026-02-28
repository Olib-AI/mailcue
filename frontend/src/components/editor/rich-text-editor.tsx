import { useState, useRef, useEffect, useCallback } from "react";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Link from "@tiptap/extension-link";
import { TextStyle } from "@tiptap/extension-text-style";
import Color from "@tiptap/extension-color";
import Placeholder from "@tiptap/extension-placeholder";
import DOMPurify from "dompurify";
import { cn } from "@/lib/utils";
import { Textarea } from "@/components/ui/textarea";
import { EditorToolbar } from "./editor-toolbar";
import "./editor-styles.css";

interface RichTextEditorProps {
  value: string;
  onChange: (html: string) => void;
  mode: "html" | "plain";
  onModeChange?: (mode: "html" | "plain") => void;
  placeholder?: string;
  className?: string;
  disabled?: boolean;
}

function RichTextEditor({
  value,
  onChange,
  mode,
  onModeChange,
  placeholder = "Type your message...",
  className,
  disabled = false,
}: RichTextEditorProps) {
  const [sourceMode, setSourceMode] = useState(false);
  const isExternalUpdate = useRef(false);

  const handleUpdate = useCallback(
    ({ editor }: { editor: import("@tiptap/core").Editor }) => {
      if (isExternalUpdate.current) return;
      const html = editor.isEmpty
        ? ""
        : DOMPurify.sanitize(editor.getHTML());
      onChange(html);
    },
    [onChange]
  );

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
      Underline,
      Link.configure({
        openOnClick: false,
        HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
      }),
      TextStyle,
      Color,
      Placeholder.configure({ placeholder }),
    ],
    content: value || "<p></p>",
    editable: !disabled,
    onUpdate: handleUpdate,
  });

  // Sync external value changes into TipTap
  useEffect(() => {
    if (!editor) return;
    const current = editor.getHTML();
    // Normalize both to compare: empty editor produces <p></p>
    const normalizedCurrent = current === "<p></p>" ? "" : current;
    const normalizedValue = value || "";
    if (normalizedValue !== normalizedCurrent) {
      isExternalUpdate.current = true;
      editor.commands.setContent(value || "<p></p>", { emitUpdate: false });
      isExternalUpdate.current = false;
    }
  }, [value, editor]);

  // Sync disabled state
  useEffect(() => {
    if (editor) {
      editor.setEditable(!disabled);
    }
  }, [disabled, editor]);

  const handleToggleSource = () => {
    if (sourceMode && editor) {
      // Switching from source back to WYSIWYG — push textarea value into TipTap
      isExternalUpdate.current = true;
      editor.commands.setContent(value || "<p></p>", { emitUpdate: false });
      isExternalUpdate.current = false;
    }
    setSourceMode(!sourceMode);
  };

  // Plain text mode — simple textarea, no TipTap
  if (mode === "plain") {
    return (
      <div className={cn("space-y-1.5", className)}>
        {onModeChange && (
          <div className="flex justify-end">
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              onClick={() => onModeChange("html")}
            >
              Switch to Rich Text
            </button>
          </div>
        )}
        <Textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="font-mono text-sm"
          rows={10}
          disabled={disabled}
        />
      </div>
    );
  }

  return (
    <div
      className={cn(
        "tiptap-editor overflow-hidden rounded-md border border-input bg-transparent shadow-sm",
        disabled && "cursor-not-allowed opacity-50",
        className
      )}
    >
      {editor && (
        <EditorToolbar
          editor={editor}
          sourceMode={sourceMode}
          onToggleSource={handleToggleSource}
          onSwitchToPlain={
            onModeChange ? () => onModeChange("plain") : undefined
          }
        />
      )}

      {sourceMode ? (
        <textarea
          value={value}
          onChange={(e) => onChange(DOMPurify.sanitize(e.target.value))}
          placeholder={placeholder}
          className="block w-full resize-none bg-transparent px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
          style={{ minHeight: 200, maxHeight: 350 }}
          disabled={disabled}
        />
      ) : (
        <EditorContent editor={editor} />
      )}
    </div>
  );
}

export { RichTextEditor };
