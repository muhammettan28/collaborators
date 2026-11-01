import { SignJWT, createLocalJWKSet, exportJWK, generateKeyPair } from 'jose';
import { beforeAll, describe, expect, it } from 'vitest';

import { AUDIENCE, isBackend, useKeys } from '../src/auth.js';

const { privateKey, publicKey } = await generateKeyPair('RS256');
const other = await generateKeyPair('RS256');

const token = (claims: Record<string, unknown>, key = privateKey) =>
  new SignJWT(claims)
    .setProtectedHeader({ alg: 'RS256', kid: 'backend' })
    .setExpirationTime('5m')
    .sign(key);

describe('isBackend', () => {
  beforeAll(async () => {
    useKeys(
      createLocalJWKSet({
        keys: [{ ...(await exportJWK(publicKey)), kid: 'backend', alg: 'RS256' }],
      }),
    );
  });

  it("takes the backend's tokens for this service", async () => {
    const valid = await token({ aud: AUDIENCE, admin: true });
    expect(await isBackend(`Bearer ${valid}`, 'unused')).toBe(true);
  });

  it('refuses tokens for another service, not admin, or signed by others', async () => {
    expect(
      await isBackend(`Bearer ${await token({ aud: 'y-converter', admin: true })}`, ''),
    ).toBe(false);
    expect(await isBackend(`Bearer ${await token({ aud: AUDIENCE })}`, '')).toBe(false);
    expect(
      await isBackend(
        `Bearer ${await token({ aud: AUDIENCE, admin: true }, other.privateKey)}`,
        '',
      ),
    ).toBe(false);
    expect(await isBackend(undefined, '')).toBe(false);
    expect(await isBackend('Basic abc', '')).toBe(false);
  });
});
