import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type TokenOut = Schemas["TokenOut"];

const ACCESS_KEY = "ai4edu.access";
const REFRESH_KEY = "ai4edu.refresh";

// localStorage 在隐私模式等情况下可能不可用，全部包一层
function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* 忽略 */
  }
}

export const tokens = {
  access: () => read(ACCESS_KEY),
  refresh: () => read(REFRESH_KEY),
  save(t: Pick<TokenOut, "access_token" | "refresh_token">) {
    write(ACCESS_KEY, t.access_token);
    write(REFRESH_KEY, t.refresh_token);
  },
  clear() {
    write(ACCESS_KEY, null);
    write(REFRESH_KEY, null);
  },
};

/** 登录失效时调用（由 AuthProvider 注册），用于跳回登录页。 */
let onSessionExpired: () => void = () => {};
export function setSessionExpiredHandler(fn: () => void) {
  onSessionExpired = fn;
}

function withToken(req: Request): Request {
  const access = tokens.access();
  if (!access) return req;
  const next = new Request(req);
  next.headers.set("Authorization", `Bearer ${access}`);
  return next;
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const refresh = tokens.refresh();
  if (!refresh) return false;
  refreshing ??= fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  })
    .then(async (resp) => {
      if (!resp.ok) return false;
      tokens.save(await resp.json());
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/** 带令牌的 fetch：访问令牌过期时自动刷新一次再重试。 */
export async function authFetch(input: Request): Promise<Response> {
  const retry = input.clone();
  const resp = await fetch(withToken(input));
  if (resp.status !== 401 || new URL(input.url).pathname.startsWith("/api/auth/")) return resp;
  if (await refreshTokens()) return fetch(withToken(retry));
  tokens.clear();
  onSessionExpired();
  return resp;
}

export const api = createClient<paths>({ baseUrl: "", fetch: authFetch });

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

function errorMessage(error: unknown, status: number): { message: string; code?: string } {
  if (error && typeof error === "object") {
    const e = error as { message?: unknown; code?: unknown; detail?: unknown };
    if (typeof e.message === "string") return { message: e.message, code: typeof e.code === "string" ? e.code : undefined };
    if (Array.isArray(e.detail)) return { message: "填写的内容格式不正确，请检查后重试", code: "validation" };
  }
  if (status >= 500) return { message: "服务器出错了，请稍后再试" };
  return { message: `请求失败（${status}）` };
}

/** 把 openapi-fetch 的返回值转成 数据 / 抛出 ApiError，方便配合 react-query 使用。 */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const { message, code } = errorMessage(result.error, result.response.status);
    throw new ApiError(message, result.response.status, code);
  }
  return result.data as T;
}

/** 下载需要登录的文件（例如导入模板）。 */
export async function downloadFile(path: string, filename: string) {
  const resp = await authFetch(new Request(path));
  if (!resp.ok) throw new ApiError("下载失败", resp.status);
  saveBlob(await resp.blob(), filename);
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
