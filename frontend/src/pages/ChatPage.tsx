import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Bot, RotateCcw, Send, Sparkles, User } from "lucide-react";

import { Card } from "@/components/Card";
import { chat, resetChat } from "@/api/endpoints";
import { useDateRange } from "@/hooks/useDateRange";

interface Msg {
  role: "user" | "assistant";
  content: string;
}

const QUICK_PROMPTS = [
  "How much did I spend on Dining last month?",
  "What is my average monthly savings?",
  "Show my top 5 merchants by spend.",
  "What are my recurring payments?",
  "Find any transactions related to travel.",
  "Which month had the highest spending?",
];

export function ChatPage() {
  const { start, end } = useDateRange();
  const [history, setHistory] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  const send = useMutation({
    mutationFn: (message: string) => chat(message, start, end),
    onSuccess: (data) =>
      setHistory((h) => [...h, { role: "assistant", content: data.answer }]),
    onError: (err) =>
      setHistory((h) => [
        ...h,
        { role: "assistant", content: `Sorry — ${(err as any).message ?? "error"}` },
      ]),
  });

  const reset = useMutation({
    mutationFn: () => resetChat(),
    onSuccess: () => setHistory([]),
  });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history.length, send.isPending]);

  const submit = (text: string) => {
    if (!text.trim()) return;
    setHistory((h) => [...h, { role: "user", content: text }]);
    setInput("");
    send.mutate(text);
  };

  return (
    <div className="grid grid-rows-[1fr_auto] gap-6 h-[calc(100vh-7rem)]">
      <Card
        title={
          <span className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-brand-400" />
            FinSight Chat
          </span>
        }
        subtitle={`Hybrid RAG over your data · Range: ${start} → ${end}`}
        actions={
          <button
            onClick={() => reset.mutate()}
            className="btn-ghost !px-2 !py-1 text-xs"
            disabled={reset.isPending}
          >
            <RotateCcw className="h-3 w-3" />
            Reset
          </button>
        }
        bodyClassName="flex h-full min-h-0 flex-col p-0"
        className="flex h-full min-h-0 flex-col"
      >
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {history.length === 0 && (
            <div className="mx-auto max-w-xl py-6 text-center">
              <Sparkles className="mx-auto h-8 w-8 text-brand-400" />
              <p className="mt-3 text-sm text-slate-300">
                Ask anything — totals, categories, recurring payments, or fuzzy
                lookups like "transactions related to travel".
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Numbers come straight from your bank statement. The agent never
                makes them up.
              </p>
            </div>
          )}
          {history.map((m, i) => (
            <div key={i} className="mb-3 flex gap-3">
              <div
                className={
                  m.role === "user"
                    ? "flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-brand-300"
                    : "flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gain-500/15 text-gain-400"
                }
              >
                {m.role === "user" ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
              </div>
              <div
                className={
                  m.role === "user"
                    ? "rounded-2xl rounded-tl-sm bg-brand-500/10 px-3.5 py-2 text-sm text-slate-100"
                    : "rounded-2xl rounded-tl-sm bg-surface-strong px-3.5 py-2 text-sm text-slate-100 whitespace-pre-wrap"
                }
              >
                {m.content}
              </div>
            </div>
          ))}
          {send.isPending && (
            <div className="flex gap-3 text-xs text-slate-500">
              <div className="h-7 w-7 rounded-full bg-gain-500/15 animate-pulse" />
              Thinking…
            </div>
          )}
          <div ref={endRef} />
        </div>

        <div className="border-t border-line px-5 py-4">
          <div className="flex gap-2">
            <input
              className="input"
              placeholder="Ask FinSight…"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submit(input);
              }}
            />
            <button
              className="btn-primary"
              onClick={() => submit(input)}
              disabled={send.isPending || !input.trim()}
            >
              <Send className="h-4 w-4" />
              Send
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {QUICK_PROMPTS.map((q) => (
              <button
                key={q}
                onClick={() => submit(q)}
                className="rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] text-slate-300 hover:bg-surface-strong"
                disabled={send.isPending}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </Card>
    </div>
  );
}
