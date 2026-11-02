import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router";
import { api, setSessionExpiredHandler, tokens, unwrap, type Me, type TokenOut } from "@/api/client";

export type Role = "platform_admin" | "org_admin" | "teacher" | "student" | "parent";

interface AuthValue {
  me: Me | null;
  loading: boolean;
  login: (t: TokenOut) => void;
  logout: () => void;
  hasRole: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  // 必须订阅令牌变化：直接在渲染时读 localStorage，退出后这里不会重新渲染，
  // me 会停留在旧账号，登录页又把人送回首页，形成跳转死循环
  const hasToken = useSyncExternalStore(tokens.subscribe, () => Boolean(tokens.access()));

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => unwrap(await api.GET("/api/me")),
    enabled: hasToken,
    retry: false,
    staleTime: 5 * 60_000,
  });

  useEffect(() => {
    setSessionExpiredHandler(() => {
      qc.clear();
      navigate("/login", { replace: true });
    });
  }, [qc, navigate]);

  const login = useCallback(
    (t: TokenOut) => {
      tokens.save(t);
      qc.setQueryData(["me"], t.user);
    },
    [qc],
  );

  const logout = useCallback(() => {
    tokens.clear();
    qc.clear();
    navigate("/login", { replace: true });
  }, [qc, navigate]);

  const me = hasToken ? (meQuery.data ?? null) : null;
  const value = useMemo<AuthValue>(
    () => ({
      me,
      loading: hasToken && meQuery.isPending,
      login,
      logout,
      hasRole: (...roles) => Boolean(me && roles.some((r) => me.roles.includes(r))),
    }),
    [me, hasToken, meQuery.isPending, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}

/** 登录后默认进入的页面，按角色优先级。 */
export function homePath(me: Pick<Me, "roles">): string {
  if (me.roles.includes("platform_admin")) return "/ops/tenants";
  if (me.roles.includes("org_admin")) return "/org/classes";
  if (me.roles.includes("teacher")) return "/teacher";
  if (me.roles.includes("student")) return "/student";
  return "/login";
}
