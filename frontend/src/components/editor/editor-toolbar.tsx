import { useState, useRef, useEffect } from "react";
import type { Editor } from "@tiptap/react";
import {
  Bold,
  Italic,
  Underline,
  Strikethrough,
  Heading1,
  Heading2,
  Heading3,
  List,
  ListOrdered,
  Quote,
  Code2,
  Minus,
  Link,
  Palette,
  Undo2,
  Redo2,
  Eye,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";

interface EditorToolbarProps {
  editor: Editor;
  sourceMode: boolean;
  onToggleSource: () => void;
  onSwitchToPlain?: () => void;
}

const PRESET_COLORS = [
  "#000000", "#434343", "#666666", "#999999",
  "#b7b7b7", "#dc3545", "#fd7e14", "#ffc107",
  "#28a745", "#20c997", "#0d6efd", "#6f42c1",
];

function ToolbarButton({
  active,
  disabled,
  onClick,
  title,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50",
        active && "bg-accent text-accent-foreground"
      )}
      onClick={onClick}
      disabled={disabled}
      title={title}
    >
      {children}
    </button>
  );
}

function ToolbarSeparator() {
  return <div className="mx-0.5 h-5 w-px bg-border" />;
}

function EditorToolbar({
  editor,
  sourceMode,
  onToggleSource,
  onSwitchToPlain,
}: EditorToolbarProps) {
  const [showLinkInput, setShowLinkInput] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [showColorPicker, setShowColorPicker] = useState(false);
  const linkRef = useRef<HTMLDivElement>(null);
  const colorRef = useRef<HTMLDivElement>(null);

  // Close popovers on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (linkRef.current && !linkRef.current.contains(e.target as Node)) {
        setShowLinkInput(false);
      }
      if (colorRef.current && !colorRef.current.contains(e.target as Node)) {
        setShowColorPicker(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const openLinkInput = () => {
    const existing = editor.getAttributes("link").href || "";
    setLinkUrl(existing);
    setShowLinkInput(true);
    setShowColorPicker(false);
  };

  const applyLink = () => {
    if (linkUrl.trim()) {
      editor
        .chain()
        .focus()
        .extendMarkRange("link")
        .setLink({ href: linkUrl.trim() })
        .run();
    }
    setShowLinkInput(false);
    setLinkUrl("");
  };

  const removeLink = () => {
    editor.chain().focus().extendMarkRange("link").unsetLink().run();
    setShowLinkInput(false);
    setLinkUrl("");
  };

  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b px-2 py-1.5">
      {/* Text styles */}
      <ToolbarButton
        active={editor.isActive("bold")}
        onClick={() => editor.chain().focus().toggleBold().run()}
        disabled={sourceMode}
        title="Bold"
      >
        <Bold className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        active={editor.isActive("italic")}
        onClick={() => editor.chain().focus().toggleItalic().run()}
        disabled={sourceMode}
        title="Italic"
      >
        <Italic className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        active={editor.isActive("underline")}
        onClick={() => editor.chain().focus().toggleUnderline().run()}
        disabled={sourceMode}
        title="Underline"
      >
        <Underline className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        active={editor.isActive("strike")}
        onClick={() => editor.chain().focus().toggleStrike().run()}
        disabled={sourceMode}
        title="Strikethrough"
      >
        <Strikethrough className="h-3.5 w-3.5" />
      </ToolbarButton>

      <ToolbarSeparator />

      {/* Headings */}
      <ToolbarButton
        active={editor.isActive("heading", { level: 1 })}
        onClick={() =>
          editor.chain().focus().toggleHeading({ level: 1 }).run()
        }
        disabled={sourceMode}
        title="Heading 1"
      >
        <Heading1 className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        active={editor.isActive("heading", { level: 2 })}
        onClick={() =>
          editor.chain().focus().toggleHeading({ level: 2 }).run()
        }
        disabled={sourceMode}
        title="Heading 2"
      >
        <Heading2 className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        active={editor.isActive("heading", { level: 3 })}
        onClick={() =>
          editor.chain().focus().toggleHeading({ level: 3 }).run()
        }
        disabled={sourceMode}
        title="Heading 3"
      >
        <Heading3 className="h-3.5 w-3.5" />
      </ToolbarButton>

      <ToolbarSeparator />

      {/* Lists */}
      <ToolbarButton
        active={editor.isActive("bulletList")}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
        disabled={sourceMode}
        title="Bullet List"
      >
        <List className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        active={editor.isActive("orderedList")}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
        disabled={sourceMode}
        title="Ordered List"
      >
        <ListOrdered className="h-3.5 w-3.5" />
      </ToolbarButton>

      <ToolbarSeparator />

      {/* Blocks */}
      <ToolbarButton
        active={editor.isActive("blockquote")}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
        disabled={sourceMode}
        title="Blockquote"
      >
        <Quote className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        active={editor.isActive("codeBlock")}
        onClick={() => editor.chain().focus().toggleCodeBlock().run()}
        disabled={sourceMode}
        title="Code Block"
      >
        <Code2 className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        onClick={() => editor.chain().focus().setHorizontalRule().run()}
        disabled={sourceMode}
        title="Horizontal Rule"
      >
        <Minus className="h-3.5 w-3.5" />
      </ToolbarButton>

      <ToolbarSeparator />

      {/* Link */}
      <div className="relative" ref={linkRef}>
        <ToolbarButton
          active={editor.isActive("link")}
          onClick={openLinkInput}
          disabled={sourceMode}
          title="Link"
        >
          <Link className="h-3.5 w-3.5" />
        </ToolbarButton>
        {showLinkInput && (
          <div className="absolute left-0 top-full z-50 mt-1 flex items-center gap-1 rounded-md border bg-popover p-2 shadow-md">
            <Input
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
              placeholder="https://..."
              className="h-7 w-48 text-xs"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  applyLink();
                }
              }}
              autoFocus
            />
            <button
              type="button"
              className="h-7 rounded bg-primary px-2 text-xs text-primary-foreground hover:bg-primary/90"
              onClick={applyLink}
            >
              Apply
            </button>
            {editor.isActive("link") && (
              <button
                type="button"
                className="h-7 rounded bg-destructive px-2 text-xs text-destructive-foreground hover:bg-destructive/90"
                onClick={removeLink}
              >
                Remove
              </button>
            )}
          </div>
        )}
      </div>

      {/* Color */}
      <div className="relative" ref={colorRef}>
        <ToolbarButton
          onClick={() => {
            setShowColorPicker(!showColorPicker);
            setShowLinkInput(false);
          }}
          disabled={sourceMode}
          title="Text Color"
        >
          <Palette className="h-3.5 w-3.5" />
        </ToolbarButton>
        {showColorPicker && (
          <div className="absolute left-0 top-full z-50 mt-1 grid grid-cols-4 gap-1 rounded-md border bg-popover p-2 shadow-md">
            {PRESET_COLORS.map((color) => (
              <button
                key={color}
                type="button"
                className="h-6 w-6 rounded border border-border transition-transform hover:scale-110"
                style={{ background: color }}
                onClick={() => {
                  editor.chain().focus().setColor(color).run();
                  setShowColorPicker(false);
                }}
                title={color}
              />
            ))}
            <button
              type="button"
              className="col-span-4 mt-1 h-6 rounded border border-border text-xs text-muted-foreground hover:bg-accent"
              onClick={() => {
                editor.chain().focus().unsetColor().run();
                setShowColorPicker(false);
              }}
            >
              Remove color
            </button>
          </div>
        )}
      </div>

      <ToolbarSeparator />

      {/* History */}
      <ToolbarButton
        onClick={() => editor.chain().focus().undo().run()}
        disabled={sourceMode || !editor.can().undo()}
        title="Undo"
      >
        <Undo2 className="h-3.5 w-3.5" />
      </ToolbarButton>
      <ToolbarButton
        onClick={() => editor.chain().focus().redo().run()}
        disabled={sourceMode || !editor.can().redo()}
        title="Redo"
      >
        <Redo2 className="h-3.5 w-3.5" />
      </ToolbarButton>

      {/* Spacer + mode toggle */}
      <div className="ml-auto flex items-center gap-1">
        {onSwitchToPlain && (
          <>
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              onClick={onSwitchToPlain}
            >
              Plain Text
            </button>
            <ToolbarSeparator />
          </>
        )}
        <ToolbarButton
          active={!sourceMode}
          onClick={() => sourceMode && onToggleSource()}
          title="Visual Editor"
        >
          <Eye className="h-3.5 w-3.5" />
        </ToolbarButton>
        <ToolbarButton
          active={sourceMode}
          onClick={() => !sourceMode && onToggleSource()}
          title="Source Code"
        >
          <Code2 className="h-3.5 w-3.5" />
        </ToolbarButton>
      </div>
    </div>
  );
}

export { EditorToolbar };
