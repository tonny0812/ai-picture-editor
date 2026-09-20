import { Navigate, Outlet } from 'react-router-dom'

import { useCurrentUser } from '@/hooks/useAuth'

/** 管理页守卫：后端 403 才是真闸门，这里只做体验层拦截。 */
export default function RequireAdmin() {
  const { user, isLoading } = useCurrentUser()

  if (isLoading) {
    return <div className="text-muted flex h-screen items-center justify-center text-sm">加载中…</div>
  }
  if (!user) return <Navigate to="/auth" replace />
  return user.role === 'admin' ? <Outlet /> : <Navigate to="/create" replace />
}
