"use client";

import { create } from "zustand";

interface User {
  id: string;
  email: string;
  display_name: string;
  role: string;
}

interface AuthStore {
  user: User | null;
  isAuthenticated: boolean;
  setUser: (user: User) => void;
  clearAuth: () => void;
  logout: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  isAuthenticated: false,

  setUser: (user) =>
    set({ user, isAuthenticated: true }),

  clearAuth: () =>
    set({ user: null, isAuthenticated: false }),

  logout: () => {
    set({ user: null, isAuthenticated: false });
    // Clear cookies by calling backend logout endpoint
    fetch("/api/v1/auth/logout", { method: "POST", credentials: "include" }).catch(() => {});
    window.location.href = "/login";
  },
}));
