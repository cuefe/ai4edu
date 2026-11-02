import "katex/dist/katex.min.css";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

// remark-breaks：单个换行也换行，和后端转成编辑器文档时的处理一致
const remarkPlugins = [remarkGfm, remarkMath, remarkBreaks];
const rehypePlugins = [rehypeKatex];

const inlineComponents = { p: ({ children }: { children?: ReactNode }) => <>{children}</> };

/** 只读的 Markdown 渲染（含表格、公式），用于生成过程中的实时预览、题目和卡片的展示。inline：不分段，嵌在一行里显示。 */
export function MarkdownView({ text, inline }: { text: string; inline?: boolean }) {
  if (inline) {
    return (
      <span className="md-inline">
        <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={inlineComponents}>
          {text}
        </ReactMarkdown>
      </span>
    );
  }
  return (
    <div className="doc-body">
      <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
