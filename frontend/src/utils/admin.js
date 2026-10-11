export const SUPER_ADMIN_EMAIL = (import.meta.env.VITE_SUPER_ADMIN_EMAIL || 'minitchitroda@gmail.com').trim().toLowerCase()

export function isSuperAdmin(user) {
  return Boolean(user?.email) && user.email.trim().toLowerCase() === SUPER_ADMIN_EMAIL
}
