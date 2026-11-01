import { createRemoteJWKSet, jwtVerify, type JWTVerifyGetKey } from 'jose';

// Only the backend asks for PDFs: with a short-lived token it signs for this
// service (audience "presentation-renderer", admin), checked against the
// public keys it publishes. A token for another service is refused.

export const AUDIENCE = 'presentation-renderer';

let keys: JWTVerifyGetKey | null = null;

export const useKeys = (given: JWTVerifyGetKey | null) => {
  keys = given;
};

export const isBackend = async (
  header: string | undefined,
  jwksUrl: string,
): Promise<boolean> => {
  if (!header?.startsWith('Bearer ')) {
    return false;
  }
  keys ??= createRemoteJWKSet(new URL(jwksUrl));
  try {
    const { payload } = await jwtVerify(header.slice('Bearer '.length), keys, {
      algorithms: ['RS256'],
      audience: AUDIENCE,
    });
    return payload.admin === true;
  } catch {
    return false;
  }
};
