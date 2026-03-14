import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export const metadata: Metadata = {
  title: "关于 Usami",
  description: "Usami 架构设计和技术栈介绍",
};

const PERSONAS = [
  { name: "Boss", role: "Orchestrator", desc: "任务分解和全局协调，管理执行计划的生成和验证" },
  { name: "Researcher", role: "Specialist", desc: "网络搜索和信息采集，提供技术调研的原始数据" },
  { name: "Writer", role: "Specialist", desc: "内容撰写和报告生成，将研究成果转化为结构化文档" },
  { name: "Analyst", role: "Specialist", desc: "数据分析和知识提炼，从原始信息中提取关键洞察" },
];

const TECH_STACK = [
  { name: "LangGraph", desc: "状态机驱动的多 Agent 编排框架" },
  { name: "FastAPI", desc: "高性能异步 API 服务" },
  { name: "Next.js 15", desc: "SSR/SSG + 客户端交互" },
  { name: "PostgreSQL + pgvector", desc: "持久化存储 + 向量搜索" },
  { name: "Redis", desc: "工作记忆和事件总线" },
  { name: "LiteLLM", desc: "多模型统一路由代理" },
];

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-16 space-y-16">
      {/* Header */}
      <section className="text-center space-y-4">
        <h1 className="text-4xl font-bold">关于 Usami</h1>
        <p className="text-lg text-muted-foreground">
          Boss-Worker 多 Agent 架构，专为技术调研和知识凝练设计
        </p>
      </section>

      {/* Architecture */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">架构设计</h2>
        <div className="rounded-lg border p-6 bg-muted/30">
          <pre className="text-sm text-muted-foreground whitespace-pre-wrap">
{`用户意图
  ↓
Boss (规划)
  ↓
计划验证 → HiTL 审批 (可选)
  ↓
并行执行 ─┬─ Researcher → 搜索采集
          ├─ Writer     → 内容撰写
          └─ Analyst    → 数据分析
  ↓
Boss (聚合) → 最终报告`}
          </pre>
        </div>
      </section>

      {/* Personas */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">Agent Personas</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          {PERSONAS.map((p) => (
            <Card key={p.name}>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">
                  {p.name}
                  <span className="ml-2 text-xs text-muted-foreground font-normal">
                    {p.role}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{p.desc}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* Tech Stack */}
      <section className="space-y-4">
        <h2 className="text-2xl font-semibold">技术栈</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {TECH_STACK.map((t) => (
            <div key={t.name} className="rounded-lg border p-4">
              <h3 className="font-medium">{t.name}</h3>
              <p className="text-sm text-muted-foreground">{t.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="text-center">
        <Button size="lg" render={<Link href="/chat" />}>
          开始使用 Usami
        </Button>
      </section>
    </div>
  );
}
