// 认证态与账号操作。同时注册 401 的集中出口：任一受保护请求登录态失效时，
// 清空身份、切回认证界面并给出中文提示（见 design.md 决策 8）。

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { ApiError, request, setUnauthorizedHandler } from '../api/client';
import type { AuthMessage, Identity } from '../types';

const UNAUTHORIZED_TIP = '登录状态已失效，请重新登录。';

interface AuthContextValue {
  /** 登录态是否已确认（/api/auth/me 已返回）。 */
  ready: boolean;
  identity: Identity | null;
  /** 认证界面顶部的提示文案。 */
  notice: string;
  setNotice: (text: string) => void;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<string>;
  logout: () => Promise<void>;
  changePassword: (oldPassword: string, newPassword: string) => Promise<string>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [notice, setNotice] = useState('');

  // 页面加载门控：先确认登录态，成功才进入对话界面
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const current = await request<Identity>('GET', '/api/auth/me', undefined, {
          skipAuthHandler: true,
        });
        if (active) setIdentity(current);
      } catch (err) {
        if (!active) return;
        const status = err instanceof ApiError ? err.status : 0;
        // 401 是「未登录」的正常情形，不提示；其余情况说明无法确认登录态
        setNotice(status === 401 ? '' : `无法确认登录状态（HTTP ${status}），请重新登录。`);
        setIdentity(null);
      } finally {
        if (active) setReady(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setIdentity(null);
      setNotice(UNAUTHORIZED_TIP);
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const current = await request<Identity>(
      'POST',
      '/api/auth/login',
      { username, password },
      { skipAuthHandler: true },
    );
    setNotice('');
    setIdentity(current);
  }, []);

  const register = useCallback(async (username: string, password: string) => {
    const result = await request<AuthMessage>(
      'POST',
      '/api/auth/register',
      { username, password },
      { skipAuthHandler: true },
    );
    return result.message || '注册成功，请登录。';
  }, []);

  const logout = useCallback(async () => {
    try {
      await request<AuthMessage>('POST', '/api/auth/logout', {});
    } finally {
      setIdentity(null);
      setNotice('已退出登录。');
    }
  }, []);

  const changePassword = useCallback(async (oldPassword: string, newPassword: string) => {
    const result = await request<AuthMessage>('POST', '/api/auth/password', {
      old_password: oldPassword,
      new_password: newPassword,
    });
    return result.message || '密码已修改，其他登录态已失效。';
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ready, identity, notice, setNotice, login, register, logout, changePassword }),
    [ready, identity, notice, login, register, logout, changePassword],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用');
  return ctx;
}