import { Image, Spin } from "antd";
import { useEffect, useState } from "react";
import { authFetch } from "@/api/client";

/** 需要登录才能看的图片（拍照作答等）：用 authFetch 取回来转成本地地址，可点开大图。 */
export function AuthImage({ src, alt, width = 160 }: { src: string; alt: string; width?: number }) {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | undefined;
    authFetch(new Request(src))
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))))
      .then((b) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(b);
        setUrl(objectUrl);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src]);
  return url ? <Image src={url} alt={alt} width={width} /> : <Spin size="small" />;
}
