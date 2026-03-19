import { describe, it, expect, beforeEach } from "vitest";
import { useNotificationStore } from "@/stores/notification-store";

function resetStore() {
  useNotificationStore.setState({
    notifications: [],
    unreadCount: 0,
    seenEventKeys: [],
  });
}

describe("useNotificationStore", () => {
  beforeEach(resetStore);

  it("adds a notification", () => {
    useNotificationStore.getState().addNotification({
      type: "task_completed",
      title: "taskCompleted",
      body: "done",
      threadId: "t1",
    });
    const { notifications, unreadCount } = useNotificationStore.getState();
    expect(notifications).toHaveLength(1);
    expect(notifications[0].read).toBe(false);
    expect(unreadCount).toBe(1);
  });

  it("deduplicates by eventKey", () => {
    const payload = {
      type: "task_completed" as const,
      title: "taskCompleted",
      body: "done",
      threadId: "t1",
    };
    useNotificationStore.getState().addNotification(payload, "t1:42");
    useNotificationStore.getState().addNotification(payload, "t1:42");
    expect(useNotificationStore.getState().notifications).toHaveLength(1);
    expect(useNotificationStore.getState().seenEventKeys).toContain("t1:42");
  });

  it("limits to 100 notifications", () => {
    for (let i = 0; i < 110; i++) {
      useNotificationStore.getState().addNotification({
        type: "system",
        title: "test",
        body: `n${i}`,
      });
    }
    expect(useNotificationStore.getState().notifications).toHaveLength(100);
  });

  it("marks a notification as read", () => {
    useNotificationStore.getState().addNotification({
      type: "hitl_request",
      title: "hitlRequest",
      body: "approve",
    });
    const id = useNotificationStore.getState().notifications[0].id;
    useNotificationStore.getState().markRead(id);
    expect(useNotificationStore.getState().notifications[0].read).toBe(true);
    expect(useNotificationStore.getState().unreadCount).toBe(0);
  });

  it("marks all as read", () => {
    useNotificationStore.getState().addNotification({ type: "system", title: "a", body: "a" });
    useNotificationStore.getState().addNotification({ type: "system", title: "b", body: "b" });
    useNotificationStore.getState().markAllRead();
    expect(useNotificationStore.getState().unreadCount).toBe(0);
  });

  it("clears all notifications", () => {
    useNotificationStore.getState().addNotification({ type: "system", title: "a", body: "a" });
    useNotificationStore.getState().clearAll();
    expect(useNotificationStore.getState().notifications).toHaveLength(0);
    expect(useNotificationStore.getState().unreadCount).toBe(0);
  });
});
