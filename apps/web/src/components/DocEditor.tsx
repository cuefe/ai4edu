import "katex/dist/katex.min.css";
import {
  BoldOutlined,
  FunctionOutlined,
  ItalicOutlined,
  OrderedListOutlined,
  RedoOutlined,
  StrikethroughOutlined,
  TableOutlined,
  UnderlineOutlined,
  UndoOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import { Mathematics } from "@tiptap/extension-mathematics";
import { TableKit } from "@tiptap/extension-table";
import { EditorContent, useEditor, useEditorState, type Editor, type JSONContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Button, Divider, Dropdown, Input, Modal, Select, Tooltip, Typography, type MenuProps } from "antd";
import katex from "katex";
import { useEffect, useState, type ReactNode, type RefObject } from "react";

type MathTarget = { kind: "inline" | "block"; pos?: number; latex: string };

const BLOCK_TYPES = [
  { value: "p", label: "正文" },
  { value: "h1", label: "标题 1" },
  { value: "h2", label: "标题 2" },
  { value: "h3", label: "标题 3" },
  { value: "h4", label: "标题 4" },
];

/**
 * 文档编辑器（TipTap）。节点类型和后端 markdown.py、docx_export.py 一一对应，新增扩展时三处一起改。
 * 父组件通过 editorRef 在保存时取 JSON；onChange 只通知"有改动"，不传内容，避免每次按键都序列化整篇文档。
 */
export function DocEditor({
  initialContent,
  onChange,
  editorRef,
}: {
  initialContent: JSONContent;
  onChange: () => void;
  editorRef: RefObject<Editor | null>;
}) {
  const [math, setMath] = useState<MathTarget | null>(null);
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3, 4] }, link: { openOnClick: false } }),
      TableKit.configure({ table: { resizable: true } }),
      Mathematics.configure({
        katexOptions: { throwOnError: false },
        inlineOptions: { onClick: (node, pos) => setMath({ kind: "inline", pos, latex: node.attrs.latex }) },
        blockOptions: { onClick: (node, pos) => setMath({ kind: "block", pos, latex: node.attrs.latex }) },
      }),
    ],
    content: initialContent,
    onUpdate: onChange,
  });

  // 卸载时不清空：父组件离开页面时还要用它保存最后的改动（TipTap 会延后销毁编辑器）
  useEffect(() => {
    editorRef.current = editor;
  }, [editor, editorRef]);

  return (
    <div className="doc-paper">
      <Toolbar editor={editor} onMath={(kind) => setMath({ kind, latex: "" })} />
      <EditorContent editor={editor} className="doc-body" />
      <MathModal editor={editor} target={math} onClose={() => setMath(null)} />
    </div>
  );
}

function ToolButton({
  title,
  icon,
  active,
  disabled,
  onClick,
}: {
  title: string;
  icon: ReactNode;
  active?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Tooltip title={title} mouseEnterDelay={0.5}>
      <Button
        type="text"
        size="small"
        icon={icon}
        aria-label={title}
        aria-pressed={active}
        disabled={disabled}
        className={active ? "doc-tool-active" : undefined}
        onClick={onClick}
      />
    </Tooltip>
  );
}

function Toolbar({ editor, onMath }: { editor: Editor; onMath: (kind: "inline" | "block") => void }) {
  const s = useEditorState({
    editor,
    selector: ({ editor: e }) => ({
      block: ([1, 2, 3, 4] as const).map((l) => (e.isActive("heading", { level: l }) ? `h${l}` : "")).find(Boolean) || "p",
      bold: e.isActive("bold"),
      italic: e.isActive("italic"),
      underline: e.isActive("underline"),
      strike: e.isActive("strike"),
      bullet: e.isActive("bulletList"),
      ordered: e.isActive("orderedList"),
      inTable: e.isActive("table"),
      canUndo: e.can().undo(),
      canRedo: e.can().redo(),
    }),
  });
  const chain = () => editor.chain().focus();

  const tableItems: MenuProps["items"] = [
    { key: "insert", label: "插入表格（3×3）", disabled: s.inTable },
    { type: "divider" },
    { key: "rowBefore", label: "在上方插入行", disabled: !s.inTable },
    { key: "rowAfter", label: "在下方插入行", disabled: !s.inTable },
    { key: "colBefore", label: "在左侧插入列", disabled: !s.inTable },
    { key: "colAfter", label: "在右侧插入列", disabled: !s.inTable },
    { type: "divider" },
    { key: "merge", label: "合并单元格", disabled: !s.inTable },
    { key: "split", label: "拆分单元格", disabled: !s.inTable },
    { type: "divider" },
    { key: "delRow", label: "删除行", disabled: !s.inTable, danger: true },
    { key: "delCol", label: "删除列", disabled: !s.inTable, danger: true },
    { key: "delTable", label: "删除表格", disabled: !s.inTable, danger: true },
  ];
  const tableActions: Record<string, () => boolean> = {
    insert: () => chain().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
    rowBefore: () => chain().addRowBefore().run(),
    rowAfter: () => chain().addRowAfter().run(),
    colBefore: () => chain().addColumnBefore().run(),
    colAfter: () => chain().addColumnAfter().run(),
    merge: () => chain().mergeCells().run(),
    split: () => chain().splitCell().run(),
    delRow: () => chain().deleteRow().run(),
    delCol: () => chain().deleteColumn().run(),
    delTable: () => chain().deleteTable().run(),
  };

  return (
    <div className="doc-toolbar">
      <ToolButton title="撤销（Ctrl+Z）" icon={<UndoOutlined />} disabled={!s.canUndo} onClick={() => chain().undo().run()} />
      <ToolButton title="重做（Ctrl+Y）" icon={<RedoOutlined />} disabled={!s.canRedo} onClick={() => chain().redo().run()} />
      <Divider orientation="vertical" />
      <Select
        size="small"
        variant="borderless"
        value={s.block}
        options={BLOCK_TYPES}
        style={{ width: 84 }}
        onChange={(v) => {
          if (v === "p") chain().setParagraph().run();
          else chain().setHeading({ level: Number(v[1]) as 1 | 2 | 3 | 4 }).run();
        }}
      />
      <Divider orientation="vertical" />
      <ToolButton title="加粗（Ctrl+B）" icon={<BoldOutlined />} active={s.bold} onClick={() => chain().toggleBold().run()} />
      <ToolButton title="斜体（Ctrl+I）" icon={<ItalicOutlined />} active={s.italic} onClick={() => chain().toggleItalic().run()} />
      <ToolButton
        title="下划线（Ctrl+U）"
        icon={<UnderlineOutlined />}
        active={s.underline}
        onClick={() => chain().toggleUnderline().run()}
      />
      <ToolButton title="删除线" icon={<StrikethroughOutlined />} active={s.strike} onClick={() => chain().toggleStrike().run()} />
      <Divider orientation="vertical" />
      <ToolButton
        title="项目符号列表"
        icon={<UnorderedListOutlined />}
        active={s.bullet}
        onClick={() => chain().toggleBulletList().run()}
      />
      <ToolButton
        title="编号列表"
        icon={<OrderedListOutlined />}
        active={s.ordered}
        onClick={() => chain().toggleOrderedList().run()}
      />
      <Dropdown menu={{ items: tableItems, onClick: ({ key }) => tableActions[key]?.() }} trigger={["click"]}>
        <Button type="text" size="small" icon={<TableOutlined />} aria-label="表格" className={s.inTable ? "doc-tool-active" : undefined} />
      </Dropdown>
      <Dropdown
        menu={{
          items: [
            { key: "inline", label: "行内公式" },
            { key: "block", label: "独立公式（单独一行）" },
          ],
          onClick: ({ key }) => onMath(key as "inline" | "block"),
        }}
        trigger={["click"]}
      >
        <Button type="text" size="small" icon={<FunctionOutlined />} aria-label="公式" />
      </Dropdown>
    </div>
  );
}

function MathModal({ editor, target, onClose }: { editor: Editor; target: MathTarget | null; onClose: () => void }) {
  const [latex, setLatex] = useState("");
  useEffect(() => setLatex(target?.latex ?? ""), [target]);
  if (!target) return null;

  const editing = target.pos !== undefined;
  const preview = katex.renderToString(latex || "\\text{在上方输入 LaTeX}", {
    throwOnError: false,
    displayMode: target.kind === "block",
  });

  function save() {
    const value = latex.trim();
    if (!target) return;
    const chain = editor.chain().focus();
    if (!value) {
      if (editing) (target.kind === "inline" ? chain.deleteInlineMath({ pos: target.pos }) : chain.deleteBlockMath({ pos: target.pos })).run();
    } else if (editing) {
      (target.kind === "inline"
        ? chain.updateInlineMath({ latex: value, pos: target.pos })
        : chain.updateBlockMath({ latex: value, pos: target.pos })
      ).run();
    } else {
      (target.kind === "inline" ? chain.insertInlineMath({ latex: value }) : chain.insertBlockMath({ latex: value })).run();
    }
    onClose();
  }

  return (
    <Modal
      title={editing ? "编辑公式" : target.kind === "inline" ? "插入行内公式" : "插入独立公式"}
      open
      onCancel={onClose}
      onOk={save}
      okText={editing && !latex.trim() ? "删除公式" : "确定"}
      okButtonProps={{ danger: editing && !latex.trim() }}
      destroyOnHidden
    >
      <Input.TextArea
        autoFocus
        rows={3}
        value={latex}
        placeholder="例如：\frac{1}{2}、x^2、\sqrt{3}"
        onChange={(e) => setLatex(e.target.value)}
        onPressEnter={(e) => {
          if (!e.shiftKey) {
            e.preventDefault();
            save();
          }
        }}
        style={{ fontFamily: "Consolas, monospace" }}
      />
      <div className="math-preview" dangerouslySetInnerHTML={{ __html: preview }} />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        使用 LaTeX 语法；清空后确定即删除公式。Shift+Enter 换行。
      </Typography.Text>
    </Modal>
  );
}
