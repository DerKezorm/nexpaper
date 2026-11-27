/**
 * The addresses of the settings (plan "Einstellungen", E8): every area under `/settings/<slug>`, and every address of
 * before leads on for good: the slugs of before (`reminders` is `notifications`, E1; `ai-setup` is `ai-provider`, E10;
 * the area `api` went apart, its address leads to Server › Connections since E67) and the pages of before (`/konto?tab=…`,
 * `/einstellungen?tab=…`, `/ueber`), which the server's notices and mails, the providers' answers and saved links
 * still name.
 */
import { AREAS, areasFor, formerAddress, resolveArea } from './areas'

describe('the slugs of the settings', () => {
  it('are the plan\'s, in its order, with nexpaper\'s own at their places', () => {
    expect(areasFor('operator').map((area) => area.slug)).toEqual([
      'profile', 'security', 'appearance', 'upload', 'ai', 'notifications', 'connections',
      'general', 'server-connections', 'sign-in', 'mail', 'storage', 'ocr', 'ai-provider', 'filing', 'inputs', 'import', 'accounts', 'log',
    ])
    expect(areasFor('member').map((area) => area.slug)).toEqual(['profile', 'security', 'appearance', 'upload', 'ai', 'notifications', 'connections'])
    expect(AREAS.some((area) => (area.slug as string) === 'api' || (area.slug as string) === 'reminders' || (area.slug as string) === 'ai-setup')).toBe(false)
  })

  it('open themselves and "about" for everybody', () => {
    expect(resolveArea('notifications', 'member', '')).toEqual({ area: 'notifications' })
    expect(resolveArea('ai-provider', 'operator', '')).toEqual({ area: 'ai-provider' })
    expect(resolveArea('about', 'member', '')).toEqual({ area: 'about' })
    expect(resolveArea(undefined, 'member', '')).toEqual({ area: 'profile' })
  })
})

describe('the slugs of before', () => {
  it('lead to the area that took their place, with what the address carried', () => {
    expect(resolveArea('reminders', 'member', '')).toEqual({ redirect: '/settings/notifications' })
    expect(resolveArea('reminders', 'operator', '?x=1')).toEqual({ redirect: '/settings/notifications?x=1' })
    expect(resolveArea('ai-setup', 'operator', '')).toEqual({ redirect: '/settings/ai-provider' })
    expect(resolveArea('api', 'operator', '')).toEqual({ redirect: '/settings/server-connections' })
  })

  it('lead a member to the settings\' start where the new area is the operator\'s', () => {
    expect(resolveArea('ai-setup', 'member', '')).toEqual({ redirect: '/settings' })
    expect(resolveArea('api', 'member', '')).toEqual({ redirect: '/settings' })
    expect(resolveArea('nowhere', 'operator', '')).toEqual({ redirect: '/settings' })
  })

  it('E67: the anchors of the cards that left General lead to Server › Connections, for the operator only', () => {
    expect(resolveArea('general', 'operator', '', '#nex-apps')).toEqual({ redirect: '/settings/server-connections#nex-apps' })
    expect(resolveArea('general', 'operator', '?x=1', '#interfaces')).toEqual({ redirect: '/settings/server-connections?x=1#interfaces' })
    expect(resolveArea('general', 'operator', '', '#limits')).toEqual({ area: 'general' })
    expect(resolveArea('general', 'operator', '')).toEqual({ area: 'general' })
    expect(resolveArea('general', 'member', '', '#nex-apps')).toEqual({ redirect: '/settings' })
    expect(resolveArea('server-connections', 'member', '')).toEqual({ redirect: '/settings' })
    expect(resolveArea('api', 'operator', '', '#interfaces')).toEqual({ redirect: '/settings/server-connections#interfaces' })
  })

  it('a provider\'s answer at /settings belongs to Security', () => {
    expect(resolveArea(undefined, 'member', '?linked=authentik')).toEqual({ redirect: '/settings/security?linked=authentik' })
    expect(resolveArea(undefined, 'member', '?error=oidc_failed')).toEqual({ redirect: '/settings/security?error=oidc_failed' })
  })
})

describe('the pages of before', () => {
  it('/konto?tab=… leads to the areas of "Mein Konto", Erinnerungen to Benachrichtigungen', () => {
    expect(formerAddress('konto', '?tab=erinnerungen')).toBe('/settings/notifications')
    expect(formerAddress('konto', '?tab=devices')).toBe('/settings/connections')
    expect(formerAddress('konto', '?tab=looks')).toBe('/settings/appearance')
    expect(formerAddress('konto', '?tab=sicherheit')).toBe('/settings/security')
    expect(formerAddress('konto', '?tab=upload')).toBe('/settings/upload')
    expect(formerAddress('konto', '?tab=ai')).toBe('/settings/ai')
    expect(formerAddress('konto', '')).toBe('/settings/profile')
    expect(formerAddress('konto', '?tab=nonsense')).toBe('/settings/profile')
    expect(formerAddress('konto', '?linked=authentik')).toBe('/settings/security?linked=authentik')
  })

  it('/einstellungen?tab=… leads to the areas of "Server", the AI to KI-Anbieter and the API to Connections', () => {
    expect(formerAddress('einstellungen', '?tab=ai')).toBe('/settings/ai-provider')
    expect(formerAddress('einstellungen', '?tab=api')).toBe('/settings/server-connections')
    expect(formerAddress('einstellungen', '?tab=backups')).toBe('/settings/storage')
    expect(formerAddress('einstellungen', '?tab=storage')).toBe('/settings/filing')
    expect(formerAddress('einstellungen', '?tab=push')).toBe('/settings/general')
    expect(formerAddress('einstellungen', '?tab=signin')).toBe('/settings/sign-in')
    expect(formerAddress('einstellungen', '?tab=accounts&x=1')).toBe('/settings/accounts?x=1')
    expect(formerAddress('einstellungen', '')).toBe('/settings/general')
  })

  it('/ueber leads to "Über nexpaper"', () => {
    expect(formerAddress('ueber', '')).toBe('/settings/about')
  })
})
