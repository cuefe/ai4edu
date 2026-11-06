import "katex/dist/katex.min.css";
import katex from "katex";
import { Markmap } from "markmap-view";
import { useEffect, useRef } from "react";
import type { Schemas } from "@/api/client";

type MindNode = Schemas["MindNode"];
type PureNode = { content: string; children: PureNode[]; payload?: { fold?: number } };

const INITIAL_DEPTH = 3; // 默认展开的层数，更深的点开看

function escapeHtml(text: string) {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

/** markmap 的节点内容是 HTML：普通文字转义，$...$ 用 KaTeX 渲染。 */
function nodeHtml(text: string) {
  return text
    .split(/(\$[^$]+\$)/)
    .map((part) =>
      part.length > 2 && part.startsWith("$") && part.endsWith("$")
        ? katex.renderToString(part.slice(1, -1), { throwOnError: false })
        : escapeHtml(part),
    )
    .join("");
}

function toPureNode(node: MindNode, depth = 1): PureNode {
  return {
    content: nodeHtml(node.text),
    children: (node.children ?? []).map((c) => toPureNode(c, depth + 1)),
    payload: depth >= INITIAL_DEPTH && node.children?.length ? { fold: 1 } : undefined,
  };
}

/** 思维导图：可拖动、缩放，点圆点折叠或展开。 */
export function MindMap({ data }: { data: MindNode }) {
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => {
    if (!svg.current) return;
    const map = Markmap.create(svg.current, { duration: 200, maxWidth: 280, paddingX: 12 }, toPureNode(data));
    return () => map.destroy();
  }, [data]);
  return <svg ref={svg} className="mind-map" />;
}
