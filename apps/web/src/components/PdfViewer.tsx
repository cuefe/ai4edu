import { LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined } from "@ant-design/icons";
import { Alert, Button, InputNumber, Space, Spin, Typography } from "antd";
// 用 legacy 版：学校的平板浏览器可能比较旧，标准版要求很新的浏览器
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from "pdfjs-dist/legacy/build/pdf.mjs";
import workerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";
import { authFetch, tokens } from "@/api/client";

GlobalWorkerOptions.workerSrc = workerUrl;

/** 需要登录才能看的 PDF：一页一页显示，大文件分段下载，不用等整本下载完。 */
export function PdfViewer({ url }: { url: string }) {
  const [doc, setDoc] = useState<PDFDocumentProxy>();
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState<string>();
  const [rendering, setRendering] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof getDocument> | undefined;
    setDoc(undefined);
    setError(undefined);
    setPage(1);
    (async () => {
      // 先发一个小请求：令牌过期时 authFetch 会刷新，后面分段下载用的是刷新后的令牌
      const probe = await authFetch(new Request(url, { headers: { Range: "bytes=0-0" } }));
      if (!probe.ok) throw new Error(String(probe.status));
      await probe.body?.cancel();
      task = getDocument({
        url,
        httpHeaders: { Authorization: `Bearer ${tokens.access()}` },
        // 只下载正在看的页。默认设置下 pdf.js 会在后台把整本下完，扫描版课本有 100MB，手机流量扛不住
        disableStream: true,
        disableAutoFetch: true,
        cMapUrl: "/pdfjs/cmaps/",
        cMapPacked: true,
        standardFontDataUrl: "/pdfjs/standard_fonts/",
      });
      const loaded = await task.promise;
      if (!cancelled) setDoc(loaded);
    })().catch(() => {
      if (!cancelled) setError("文件打不开，请刷新页面重试");
    });
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [url]);

  useEffect(() => {
    if (!doc || !canvas.current || !box.current) return;
    let cancelled = false;
    let render: { cancel: () => void; promise: Promise<unknown> } | undefined;
    const target = canvas.current;
    const width = box.current.clientWidth - 2;
    setRendering(true);
    (async () => {
      const pdfPage = await doc.getPage(page);
      if (cancelled) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const scale = (Math.max(width, 280) / base.width) * zoom;
      const ratio = window.devicePixelRatio || 1;
      const viewport = pdfPage.getViewport({ scale: scale * ratio });
      target.width = viewport.width;
      target.height = viewport.height;
      target.style.width = `${viewport.width / ratio}px`;
      target.style.height = `${viewport.height / ratio}px`;
      render = pdfPage.render({ canvas: target, viewport });
      await render.promise;
    })()
      .catch((e: { name?: string }) => {
        if (e?.name !== "RenderingCancelledException" && !cancelled) setError("这一页显示不出来");
      })
      .finally(() => {
        if (!cancelled) setRendering(false);
      });
    return () => {
      cancelled = true;
      render?.cancel();
    };
  }, [doc, page, zoom]);

  if (error) return <Alert type="error" showIcon title={error} />;
  const pages = doc?.numPages ?? 0;
  return (
    <div className="pdf-viewer">
      <Space wrap className="pdf-toolbar">
        <Button icon={<LeftOutlined />} aria-label="上一页" disabled={!doc || page <= 1} onClick={() => setPage(page - 1)} />
        <InputNumber
          min={1}
          max={pages || 1}
          value={page}
          disabled={!doc}
          style={{ width: 72 }}
          aria-label="页码"
          onChange={(v) => v && setPage(v)}
        />
        <Typography.Text type="secondary">/ {pages || "…"} 页</Typography.Text>
        <Button icon={<RightOutlined />} aria-label="下一页" disabled={!doc || page >= pages} onClick={() => setPage(page + 1)} />
        <Button icon={<ZoomOutOutlined />} aria-label="缩小" disabled={zoom <= 0.5} onClick={() => setZoom(zoom - 0.25)} />
        <Button icon={<ZoomInOutlined />} aria-label="放大" disabled={zoom >= 3} onClick={() => setZoom(zoom + 0.25)} />
      </Space>
      <div ref={box} className="pdf-page">
        <Spin spinning={!doc || rendering}>
          <canvas ref={canvas} />
        </Spin>
      </div>
    </div>
  );
}
