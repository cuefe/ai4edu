// 后端技能名、审计操作名对应的中文，运营后台和机构概况共用

export const SKILL_LABEL: Record<string, string> = {
  ping: "连通测试",
  lesson_plan: "教案",
  handout: "讲义",
  recite_cards: "背诵卡片",
  question_gen: "出题",
  answer_check: "答案校验（解题）",
  answer_judge: "答案校验（比对）",
  grade_subjective: "主观题批改",
  correction_guide: "错题订正引导",
  tutor: "问一问",
  tutor_vision: "问一问（拍照）",
  safety_classify: "内容安全",
  ocr: "资料识别",
  embed: "资料检索",
};

export const AUDIT_LABEL: Record<string, string> = {
  login: "登录",
  login_failed: "登录失败",
  create_tenant: "开通机构",
  update_tenant: "修改机构",
  create_plan: "新建套餐",
  update_plan: "修改套餐",
  create_teacher: "添加老师",
  import_students: "导入学生",
  reset_password: "重置密码",
  enable_user: "启用账号",
  disable_user: "停用账号",
  change_score: "改分",
  export_document: "导出文档",
  delete_document: "删除文档",
  delete_assignment: "删除作业",
  delete_question: "删除题目",
  delete_recite_deck: "删除卡片组",
  delete_resource: "删除资料",
};

// 审计详情里的字段名
export const AUDIT_FIELD_LABEL: Record<string, string> = {
  method: "方式",
  ip: "IP",
  locked: "已锁定",
  code: "机构代码",
  plan_id: "套餐",
  expires_at: "到期",
  student_quota: "学生名额",
  teacher_quota: "老师名额",
  ai_budget_yuan: "AI 月额度",
  note: "备注",
  name: "名称",
  active: "启用",
  before: "原分",
  after: "新分",
  created: "新建",
  skipped: "跳过",
  errors: "出错",
  is_org_admin: "管理员",
};

export const yuan = (v: string | number | null | undefined) => `¥${Number(v ?? 0).toFixed(2)}`;
