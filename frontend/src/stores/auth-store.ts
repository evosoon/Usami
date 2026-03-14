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
  accessToken: string | null;
  isAuthenticated: boolean;
  setAuth: (user: User, accessToken: string) => void;
  clearAuth: () => void;
  logout: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  accessToken: null,
  isAuthenticated: false,

  setAuth: (user, accessToken) =>
    set({ user, accessToken, isAuthenticated: true }),

  clearAuth: () =>
    set({ user: null, accessToken: null, isAuthenticated: false }),

  logout: () => {
    set({ user: null, accessToken: null, isAuthenticated: false });
    // Clear cookies by calling backend logout endpoint
    fetch("/api/v1/auth/logout", { method: "POST" }).catch(() => {});
    window.location.href = "/login";
  },
}));
