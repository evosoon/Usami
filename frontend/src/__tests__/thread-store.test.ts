import { describe, it, expect, beforeEach } from "vitest";
import { useThreadStore } from "@/stores/thread-store";
import type { SseEvent } from "@/types/sse";

function resetStore() {
  useThreadStore.setState({
    threads: new Map(),
    activeThreadId: null,
  });
}

describe("useThreadStore", () => {
  beforeEach(resetStore);

  it("creates a thread", () => {
    useThreadStore.getState().createThread("t1", "hello");
    const thread = useThreadStore.getState().threads.get("t1");
    expect(thread).toBeDefined();
    expect(thread!.intent).toBe("hello");
    expect(thread!.phase).toBe("created");
    expect(useThreadStore.getState().activeThreadId).toBe("t1");
  });

  it("appendEvent auto-creates thread on task.created", () => {
    const event: SseEvent = {
      type: "task.created",
      thread_id: "t2",
      seq: 1,
      intent: "test intent",
    };
    useThreadStore.getState().appendEvent("t2", event);
    const thread = useThreadStore.getState().threads.get("t2");
    expect(thread).toBeDefined();
    expect(thread!.intent).toBe("test intent");
    expect(thread!.events).toHaveLength(1);
  });

  it("appendEvent deduplicates by seq", () => {
    const event: SseEvent = {
      type: "task.created",
      thread_id: "t3",
      seq: 1,
      intent: "dup test",
    };
    useThreadStore.getState().appendEvent("t3", event);
    useThreadStore.getState().appendEvent("t3", event); // duplicate
    const thread = useThreadStore.getState().threads.get("t3");
    expect(thread!.events).toHaveLength(1);
    expect(thread!.lastSeq).toBe(1);
  });

  it("appendEvent allows transient events without seq", () => {
    useThreadStore.getState().createThread("t4", "test");
    const token: SseEvent = {
      type: "llm.token",
      thread_id: "t4",
      content: "hello ",
      node: "plan",
    };
    useThreadStore.getState().appendEvent("t4", token);
    useThreadStore.getState().appendEvent("t4", token);
    const thread = useThreadStore.getState().threads.get("t4");
    expect(thread!.streamingPlan).toBe("hello hello ");
  });

  it("transitions phase on phase.change event", () => {
    useThreadStore.getState().createThread("t5", "test");
    const event: SseEvent = {
      type: "phase.change",
      thread_id: "t5",
      seq: 1,
      phase: "planning",
    };
    useThreadStore.getState().appendEvent("t5", event);
    expect(useThreadStore.getState().threads.get("t5")!.phase).toBe("planning");
  });

  it("sets result on task.completed", () => {
    useThreadStore.getState().createThread("t6", "test");
    const event: SseEvent = {
      type: "task.completed",
      thread_id: "t6",
      seq: 1,
      result: "done!",
    };
    useThreadStore.getState().appendEvent("t6", event);
    const thread = useThreadStore.getState().threads.get("t6")!;
    expect(thread.phase).toBe("completed");
    expect(thread.result).toBe("done!");
  });

  it("sets error on task.failed", () => {
    useThreadStore.getState().createThread("t7", "test");
    const event: SseEvent = {
      type: "task.failed",
      thread_id: "t7",
      seq: 1,
      error: "boom",
    };
    useThreadStore.getState().appendEvent("t7", event);
    const thread = useThreadStore.getState().threads.get("t7")!;
    expect(thread.phase).toBe("failed");
    expect(thread.error).toBe("boom");
  });

  it("removeThread returns the removed thread", () => {
    useThreadStore.getState().createThread("t8", "bye");
    const removed = useThreadStore.getState().removeThread("t8");
    expect(removed).toBeDefined();
    expect(removed!.intent).toBe("bye");
    expect(useThreadStore.getState().threads.has("t8")).toBe(false);
  });

  it("restoreThread brings back a removed thread", () => {
    useThreadStore.getState().createThread("t9", "restore me");
    const removed = useThreadStore.getState().removeThread("t9")!;
    useThreadStore.getState().restoreThread(removed);
    expect(useThreadStore.getState().threads.has("t9")).toBe(true);
  });

  it("prepareFollowUp resets streaming state", () => {
    useThreadStore.getState().createThread("t10", "first");
    useThreadStore.getState().appendEvent("t10", {
      type: "task.completed",
      thread_id: "t10",
      seq: 1,
      result: "first result",
    });
    useThreadStore.getState().prepareFollowUp("t10", "second");
    const thread = useThreadStore.getState().threads.get("t10")!;
    expect(thread.phase).toBe("created");
    expect(thread.pendingIntent).toBe("second");
    expect(thread.streamingResult).toBe("");
  });

  it("sets pendingInterrupt on interrupt event", () => {
    useThreadStore.getState().createThread("t11", "test");
    const event: SseEvent = {
      type: "interrupt",
      thread_id: "t11",
      seq: 1,
      value: { type: "approval", message: "approve?", options: ["yes", "no"] },
    };
    useThreadStore.getState().appendEvent("t11", event);
    const thread = useThreadStore.getState().threads.get("t11")!;
    expect(thread.phase).toBe("hitl_waiting");
    expect(thread.pendingInterrupt).toEqual({
      type: "approval",
      message: "approve?",
      options: ["yes", "no"],
    });
  });
});
