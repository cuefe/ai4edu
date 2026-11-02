import { ApiError, authFetch } from "./client";

/**
 * POST 一个 JSON 请求并按 Server-Sent Events 读取响应。
 * 浏览器自带的 EventSource 只支持 GET、不能带 Authorization 头，所以自己解析。
 */
export async function postSSE(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await authFetch(
    new Request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    }),
  );
  if (!resp.ok || !resp.body) {
    const data = await resp.json().catch(() => ({}));
    throw new ApiError(data.message ?? `请求失败（${resp.status}）`, resp.status, data.code);
  }

  const reader = resp.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (data.length) onEvent(event, JSON.parse(data.join("\n")));
    }
  }
}
