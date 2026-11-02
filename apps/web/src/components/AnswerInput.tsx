import { Checkbox, Input, Radio, Space } from "antd";
import { MarkdownView } from "./MarkdownView";

const LETTERS = "ABCDEF";
const BLANK = /_{3,}|＿{2,}|[（(]\s{2,}[)）]/g;

/** 题干里有几个空（至少 1 个）。 */
export function blankCount(stem: string) {
  return Math.max(1, (stem.match(BLANK) ?? []).length);
}

/**
 * 按题型作答：单选、多选、判断用选项，填空每个空一个输入框（答案用“；”拼起来），解答题用多行文本。
 * value / onChange 都是提交给后端的字符串。
 */
export function AnswerInput({
  qtype,
  stem,
  options,
  value,
  onChange,
  disabled,
}: {
  qtype: string;
  stem: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  if (qtype === "单选题") {
    return (
      <Radio.Group value={value || undefined} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
        <Space orientation="vertical">
          {options.map((o, i) => (
            <Radio key={i} value={LETTERS[i]}>
              {LETTERS[i]}. <MarkdownView text={o} inline />
            </Radio>
          ))}
        </Space>
      </Radio.Group>
    );
  }
  if (qtype === "多选题") {
    return (
      <Checkbox.Group
        value={value ? value.split("") : []}
        onChange={(v) => onChange([...v].sort().join(""))}
        disabled={disabled}
      >
        <Space orientation="vertical">
          {options.map((o, i) => (
            <Checkbox key={i} value={LETTERS[i]}>
              {LETTERS[i]}. <MarkdownView text={o} inline />
            </Checkbox>
          ))}
        </Space>
      </Checkbox.Group>
    );
  }
  if (qtype === "判断题") {
    return (
      <Radio.Group
        optionType="button"
        value={value || undefined}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        options={[
          { value: "对", label: "对" },
          { value: "错", label: "错" },
        ]}
      />
    );
  }
  if (qtype === "填空题") {
    const n = blankCount(stem);
    const parts = value.split("；");
    return (
      <Space wrap>
        {Array.from({ length: n }, (_, i) => (
          <Input
            key={i}
            value={parts[i] ?? ""}
            disabled={disabled}
            placeholder={n > 1 ? `第 ${i + 1} 空` : "填写答案"}
            style={{ width: 180 }}
            onChange={(e) => {
              const next = Array.from({ length: n }, (_, j) => (j === i ? e.target.value.replace(/[；;]/g, "") : (parts[j] ?? "")));
              onChange(next.join("；"));
            }}
          />
        ))}
      </Space>
    );
  }
  return (
    <Input.TextArea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      rows={4}
      maxLength={5000}
      placeholder="写出解答过程；也可以拍照上传"
    />
  );
}
