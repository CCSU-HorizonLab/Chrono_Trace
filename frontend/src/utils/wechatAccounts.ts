import { api, bridgeReady } from '@/api/bridge'

type AccountLike = {
  wxid: string
  label?: string
  avatar?: string
  profile_name?: string
}

type CachedProfile = {
  name: string
  avatar: string
}

const profileCache = new Map<string, CachedProfile>()

function isMeaningfulLabel(label?: string, wxid?: string) {
  const normalized = String(label || '').trim()
  if (!normalized) return false
  return normalized !== String(wxid || '').trim()
}

export function getWechatAccountDisplayName(account?: AccountLike | null) {
  if (!account) return '未命名账号'
  if (account.profile_name?.trim()) return account.profile_name.trim()
  if (isMeaningfulLabel(account.label, account.wxid)) return String(account.label).trim()
  return account.wxid || '未命名账号'
}

export async function enrichWechatAccountsWithProfiles<T extends AccountLike>(accounts: T[]) {
  if (!Array.isArray(accounts) || accounts.length === 0) return []

  await bridgeReady()

  return Promise.all(
    accounts.map(async (account) => {
      const wxid = String(account.wxid || '').trim()
      if (!wxid) return account

      const cached = profileCache.get(wxid)
      if (cached) {
        return {
          ...account,
          profile_name: account.profile_name || cached.name || '',
          avatar: account.avatar || cached.avatar || '',
        }
      }

      try {
        const result = await api.get_current_user_profile(wxid)
        const profile = result?.profile || {}
        const name = String(profile.name || '').trim()
        const avatar = String(profile.avatar || '').trim()

        profileCache.set(wxid, { name, avatar })

        return {
          ...account,
          profile_name: account.profile_name || name || '',
          avatar: account.avatar || avatar || '',
        }
      } catch (error) {
        console.error('[wechatAccounts] 加载账号身份失败:', wxid, error)
        return account
      }
    }),
  ) as Promise<T[]>
}
