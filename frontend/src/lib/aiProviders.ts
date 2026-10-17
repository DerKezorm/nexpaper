/**
 * The kinds of AI service the operator can choose (Settings, AI). The names of
 * providers stand here and nowhere else: the server knows only the kind of interface (`openai`, `messages`, `local`)
 * and an address. For the Messages API the address is the provider's own; the field is not shown for it.
 */
import type { AiProvider } from '../api/client'

export const AI_PROVIDERS: AiProvider[] = ['none', 'local', 'messages', 'openai']

/** The name a provider goes by, where it is a product name (the others are words of the interface). */
export const PROVIDER_NAME: Partial<Record<AiProvider, string>> = { messages: 'Anthropic' }

/** The address filled in for the Messages API. */
export const MESSAGES_URL = 'https://api.anthropic.com/v1/'

/** Where to fill in a local model's address to begin with: Ollama in the same compose file. */
export const LOCAL_URL = 'http://ollama:11434/v1'

/** The name of a kind of service as the settings show it. */
export function providerName(provider: AiProvider, t: (key: string) => string): string {
  return PROVIDER_NAME[provider] ?? t(`server.ai.${provider}`)
}
