// A stand-in sign-in provider for the end-to-end tests of nexpaper's nexoidc.spec.ts, never anything real: an OpenID Connect
// provider under /oidc that a browser really goes through. /oidc/auth answers at once with a code for whoever
// POST /oidc/next named (sub, email, preferred_username); the token is signed with a key made here at the start.
import crypto from 'node:crypto'
import http from 'node:http'

const PORT = Number(process.env.FAKE_PROVIDER_PORT ?? 18567)
const ISSUER = `http://127.0.0.1:${PORT}/oidc`
const KID = 'e2e-key'

const { privateKey, publicKey } = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 })
let next = { sub: 'person-1', email: 'person@example.com', preferred_username: 'person' }
const codes = new Map()

const b64url = (value) => Buffer.from(value).toString('base64url')

function idToken(claims) {
  const head = b64url(JSON.stringify({ alg: 'RS256', typ: 'JWT', kid: KID }))
  const body = b64url(JSON.stringify(claims))
  const signature = crypto.sign('RSA-SHA256', Buffer.from(`${head}.${body}`), privateKey).toString('base64url')
  return `${head}.${body}.${signature}`
}

http
  .createServer((request, response) => {
    let raw = ''
    request.on('data', (chunk) => (raw += chunk))
    request.on('end', () => {
      const url = new URL(request.url, `http://127.0.0.1:${PORT}`)
      const send = (status, value) => {
        response.writeHead(status, { 'Content-Type': 'application/json' })
        response.end(JSON.stringify(value))
      }
      if (url.pathname === '/health') return send(200, { ok: true })
      if (url.pathname === '/oidc/next' && request.method === 'POST') {
        next = JSON.parse(raw || '{}')
        return send(200, next)
      }
      if (url.pathname === '/oidc/.well-known/openid-configuration') {
        return send(200, {
          issuer: ISSUER,
          authorization_endpoint: `${ISSUER}/auth`,
          token_endpoint: `${ISSUER}/token`,
          jwks_uri: `${ISSUER}/jwks`,
          userinfo_endpoint: `${ISSUER}/userinfo`,
        })
      }
      if (url.pathname === '/oidc/jwks') {
        return send(200, { keys: [{ ...publicKey.export({ format: 'jwk' }), kid: KID, use: 'sig', alg: 'RS256' }] })
      }
      if (url.pathname === '/oidc/auth') {
        // Whoever was named last signs in, at once: the browser goes straight back to nexpaper with a code.
        const code = crypto.randomBytes(12).toString('hex')
        codes.set(code, {
          claims: next,
          nonce: url.searchParams.get('nonce'),
          challenge: url.searchParams.get('code_challenge'),
          client: url.searchParams.get('client_id'),
        })
        const back = new URL(url.searchParams.get('redirect_uri'))
        back.searchParams.set('code', code)
        back.searchParams.set('state', url.searchParams.get('state') ?? '')
        response.writeHead(302, { Location: back.toString() })
        return response.end()
      }
      if (url.pathname === '/oidc/token' && request.method === 'POST') {
        const form = new URLSearchParams(raw)
        const kept = codes.get(form.get('code') ?? '')
        codes.delete(form.get('code') ?? '')
        const verifier = form.get('code_verifier') ?? ''
        const challenge = crypto.createHash('sha256').update(verifier).digest('base64url')
        if (!kept || challenge !== kept.challenge) return send(400, { error: 'invalid_grant' })
        const now = Math.floor(Date.now() / 1000)
        const claims = { iss: ISSUER, aud: kept.client, exp: now + 300, iat: now, nonce: kept.nonce, ...kept.claims }
        return send(200, { id_token: idToken(claims), access_token: `access-${kept.claims.sub}`, token_type: 'Bearer' })
      }
      if (url.pathname === '/oidc/userinfo') return send(404, { error: 'not here' })
      send(404, { error: 'not found' })
    })
  })
  .listen(PORT, '127.0.0.1')
