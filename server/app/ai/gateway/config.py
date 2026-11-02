import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml
from dotenv import dotenv_values


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    base_url: str = ""
    api_key: str = ""
    price_in: Decimal | None = None  # 元 / 百万 token
    price_out: Decimal | None = None

    def cost(self, prompt_tokens: int, completion_tokens: int) -> Decimal | None:
        if self.price_in is None or self.price_out is None:
            return None
        return (self.price_in * prompt_tokens + self.price_out * completion_tokens) / Decimal(1_000_000)


MOCK = Candidate(provider="mock", model="mock-echo")


@dataclass
class TierEntry:
    provider: str
    model: str | None
    model_env: str | None
    price: dict[str, float] | None


@dataclass
class GatewayConfig:
    providers: dict[str, dict[str, str]]
    tiers: dict[str, list[TierEntry]]
    skills: dict[str, str]
    env: Mapping[str, str | None]

    @classmethod
    def load(cls, path: Path, env_file: Path | None = None) -> "GatewayConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        # .env 里的值不会进入 os.environ，这里合并读取；真实环境变量优先
        env: dict[str, str | None] = {}
        if env_file and env_file.exists():
            env.update(dotenv_values(env_file))
        env.update(os.environ)
        tiers = {
            name: [
                TierEntry(e["provider"], e.get("model"), e.get("model_env"), e.get("price")) for e in entries
            ]
            for name, entries in raw["tiers"].items()
        }
        config = cls(providers=raw["providers"], tiers=tiers, skills=raw["skills"], env=env)
        config.validate()
        return config

    def validate(self) -> None:
        for skill, tier in self.skills.items():
            if tier not in self.tiers:
                raise ValueError(f"技能 {skill} 引用了不存在的档位 {tier}")
        for tier, entries in self.tiers.items():
            for e in entries:
                if e.provider not in self.providers:
                    raise ValueError(f"档位 {tier} 引用了不存在的供应商 {e.provider}")
                if not (e.model or e.model_env):
                    raise ValueError(f"档位 {tier} 的 {e.provider} 候选缺少 model 或 model_env")

    def tier_of(self, skill: str) -> str:
        if skill not in self.skills:
            raise KeyError(f"未登记的技能：{skill}，请在 models.yaml 的 skills 里添加")
        return self.skills[skill]

    def candidates(self, skill: str) -> list[Candidate]:
        """按顺序返回可用候选：供应商配了 Key、模型名能解析出来。"""
        result = []
        for e in self.tiers[self.tier_of(skill)]:
            provider = self.providers[e.provider]
            api_key = self.env.get(provider["api_key_env"])
            model = e.model or (self.env.get(e.model_env) if e.model_env else None)
            if not api_key or not model:
                continue
            price = e.price or {}
            result.append(
                Candidate(
                    provider=e.provider,
                    model=model,
                    base_url=provider["base_url"],
                    api_key=api_key,
                    price_in=Decimal(str(price["input"])) if "input" in price else None,
                    price_out=Decimal(str(price["output"])) if "output" in price else None,
                )
            )
        return result
