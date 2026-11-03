import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Button, Popconfirm } from "antd";
import { api, unwrap, type Schemas } from "@/api/client";

/** 停用、启用账号。停用的不能登录、不占名额；再启用要有空名额。 */
export function ToggleActive({ user }: { user: Schemas["UserOut"] }) {
  const qc = useQueryClient();
  const { message } = App.useApp();
  const toggle = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/org/users/{user_id}", {
          params: { path: { user_id: user.id } },
          body: { active: !user.active },
        }),
      ),
    onSuccess: (u) => {
      message.success(u.active ? "已启用" : "已停用");
      qc.invalidateQueries({ queryKey: ["org"] });
    },
    onError: (e) => message.error(e.message),
  });
  return (
    <Popconfirm
      title={user.active ? `停用 ${user.name}？` : `启用 ${user.name}？`}
      description={user.active ? "停用后不能登录，也不占名额；已登录的设备会马上退出" : undefined}
      onConfirm={() => toggle.mutate()}
    >
      <Button type="link" size="small" danger={user.active} loading={toggle.isPending}>
        {user.active ? "停用" : "启用"}
      </Button>
    </Popconfirm>
  );
}
